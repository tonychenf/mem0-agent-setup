#!/usr/bin/env python3
"""
auto_recall - 自动记忆读取（v6）
设计目标：
- 分组扁平输出：每层定义出现一次，block 用 | 分隔
- 严谨性：边界条件、空值、异常全面处理
- 可拓展性：层级定义外部化、输出格式可配置、session 上下文策略可扩展
"""
import os, sys, re, json
from pathlib import Path
from collections import defaultdict

# === Workspace 路径推导（唯一路径） ===
def detect_agent_id_from_workspace():
    """
    从 WORKSPACE_DIR 环境变量推导 agent ID。
    唯一路径：workspace-xxx → xxx，workspace → main
    """
    workspace_dir = os.environ.get("WORKSPACE_DIR", "").rstrip("/")
    if not workspace_dir:
        return "main"

    basename = os.path.basename(workspace_dir)
    if basename.startswith("workspace-"):
        return basename[len("workspace-"):]
    elif basename == "workspace":
        return "main"

    return "main"

_detected_agent_id = None

def get_agent_id():
    """获取当前 agent ID（惰性计算，只计算一次）"""
    global _detected_agent_id
    if _detected_agent_id is not None:
        return _detected_agent_id
    # 优先用 WORKSPACE_DIR 路径推导（gateway 场景）
    # 其次用 AGENT_NAME 环境变量（systemd watchdog 场景）
    _detected_agent_id = os.environ.get("AGENT_NAME", "") or detect_agent_id_from_workspace()
    return _detected_agent_id

# === 共享 .env 加载 ===
for env_path in ["/root/.openclaw/mem0-agent-setup/.env"]:
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
        break

API_KEY = os.environ.get("OPENAI_API_KEY", "")
if not API_KEY:
    raise RuntimeError("请设置 OPENAI_API_KEY 环境变量")

BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.siliconflow.cn/v1")
os.environ["OPENAI_BASE_URL"] = BASE_URL

from mem0 import Memory
from openai import OpenAI

# === 层级定义（可外部化，未来可从配置文件读取） ===
LAYER_DEFINITIONS = {
    "semantic": "回答请符合用户偏好、沟通习惯、语言风格",
    "episodic": "回答请参考用户的历史决策、重大事件",
    "procedural": "回答请遵循用户认可的工作流程和操作步骤"
}

LAYER_SHORT_NAMES = {
    "semantic": "语义",
    "episodic": "事件",
    "procedural": "程序",
    "unknown": "未知"
}

# === 可配置常量 ===
DEFAULT_MIN_SCORE = 2
DEFAULT_LIMIT = 8
DEFAULT_MAX_FILES_PER_BLOCK = 2          # 每条 block 最多补全几个 session 文件
DEFAULT_MAX_CONTEXTS_PER_FILE = 2       # 每个 session 文件最多取几个上下文片段
MAX_BLOCK_TEXT_LEN = 200                # block 纯文本最大长度（超出截断）
MAX_CTX_MSG_LEN = 150                   # 单条 context 消息最大长度
BLOCK_SEPARATOR = " | "                 # block 之间的分隔符
CTX_SEPARATOR = " | "                   # context 内部的分组分隔符


def get_mem0(collection="mem0_main"):
    """构建 Mem0 实例"""
    return Memory.from_config({
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": collection,
                "embedding_model_dims": 1024,
                "url": "http://localhost:6333"
            }
        },
        "llm": {
            "provider": "openai",
            "config": {
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "openai_base_url": BASE_URL,
                "temperature": 0.1
            }
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": "BAAI/bge-large-zh-v1.5",
                "openai_base_url": BASE_URL,
                "embedding_dims": 1024
            }
        }
    })


def parse_memory(text):
    """
    解析记忆 block，提取层级、分数、文件路径、纯文本
    格式：[层级:Episodic][score:5][distilled][sessions:2][files:/path/a.jsonl,/path/b.jsonl]
          {block_text}
    """
    if not text or not isinstance(text, str):
        return None

    # 正则提取各字段
    layer_m = re.search(r'\[层级:(\w+)\]', text)
    score_m = re.search(r'\[score:(\d+)\]', text)
    files_m = re.search(r'\[files:([^\]]+)\]', text)

    layer = layer_m.group(1).lower() if layer_m else "unknown"
    score = int(score_m.group(1)) if score_m else 0
    files = []
    if files_m and files_m.group(1).strip():
        files = [f.strip() for f in files_m.group(1).split(",") if f.strip()]

    # 去掉所有 [xxx] 前缀，得到纯文本
    clean = text
    for _ in range(10):
        stripped = re.sub(r'^\[[^\]]+\]\s*', '', clean)
        if stripped == clean:
            break
        clean = stripped

    clean = clean.strip()

    return {
        "layer": layer,
        "layer_def": LAYER_DEFINITIONS.get(layer, ""),
        "score": score,
        "clean_text": clean,
        "files": files
    }


def lookup_session_snippets(filepath, keyword, max_snippets=6):
    """
    在 session JSONL 文件中搜索相关片段
    返回格式：[filename]\nicon text\nicon text\n...
    """
    if not filepath or not os.path.exists(filepath):
        return []

    snippets = []
    role_icon_map = {
        "user": "👤",
        "assistant": "🤖",
        "toolResult": "🔧"
    }

    try:
        with open(filepath, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []

    # 解析所有有效消息（user / assistant / toolResult）
    relevant_messages = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") != "message":
                continue
            msg = obj.get("message", {})
            role = msg.get("role", "")
            if role not in role_icon_map:
                continue

            # 提取文本内容
            content_arr = msg.get("content", [])
            if isinstance(content_arr, list) and content_arr:
                text = content_arr[0].get("text", "") if isinstance(content_arr[0], dict) else str(content_arr[0])
            else:
                text = str(content_arr)

            if text:
                relevant_messages.append({
                    "role": role,
                    "text": text[:MAX_CTX_MSG_LEN],  # 截断超长消息
                    "icon": role_icon_map[role]
                })
        except Exception:
            continue

    if not relevant_messages:
        return []

    # 用 keyword 找匹配位置
    keyword_lower = keyword.lower() if keyword else ""
    matched_indices = []
    for i, msg in enumerate(relevant_messages):
        if keyword_lower and keyword_lower in msg["text"].lower():
            matched_indices.append(i)

    # 如果没匹配，取最近的消息位置
    if not matched_indices:
        matched_indices = [len(relevant_messages) - 1]

    # 收集上下文片段（最多 max_snippets 条）
    collected = set()
    for idx in matched_indices[-max_snippets:]:
        start = max(0, idx - 2)
        end = min(len(relevant_messages), idx + 3)
        for i in range(start, end):
            if i not in collected:
                msg = relevant_messages[i]
                collected.add(i)
                snippets.append(f"{msg['icon']} {msg['text']}")

    if not snippets:
        return []

    # 组装片段
    filename = os.path.basename(filepath)
    return [f"[{filename}]\n" + "\n".join(snippets[:6])]


def get_session_context(parsed, max_files=DEFAULT_MAX_FILES_PER_BLOCK, max_snippets_per_file=DEFAULT_MAX_CONTEXTS_PER_FILE):
    """
    根据 block 中的 files 路径，补全 session 上下文
    返回格式：[ctx1, ctx2, ...]
    """
    if not parsed or not parsed.get("files"):
        return []

    files = parsed.get("files", [])
    keyword = parsed.get("clean_text", "")[:20]  # 用前20字做匹配

    contexts = []
    for filepath in files[:max_files]:
        ctx_list = lookup_session_snippets(filepath, keyword, max_snippets=max_snippets_per_file)
        contexts.extend(ctx_list)

    return contexts


def format_recall_output(by_layer):
    """
    按层级分组，扁平输出
    每层定义出现一次，block 之间用 | 分隔

    返回格式：
    ## 📚 相关记忆

    回答请符合用户偏好、沟通习惯、语言风格：
      [语义] block1 | ctx1 | ctx2 | [语义] block2 | ctx3

    回答请参考用户的历史决策、重大事件：
      [事件] block3 | ctx4
    """
    output_parts = ["## 📚 相关记忆\n"]

    layer_order = ["semantic", "episodic", "procedural"]

    for layer in layer_order:
        items = by_layer.get(layer, [])
        if not items:
            continue

        layer_def = LAYER_DEFINITIONS.get(layer, "")
        layer_short = LAYER_SHORT_NAMES.get(layer, "未知")

        # 该层定义行（换行结束，不带额外缩进）
        output_parts.append(f"{layer_def}：\n")

        # 收集所有 block，逐行输出（每条 block 独立一行）
        for item in items:
            # 构建 block 文本
            clean_text = item.get("clean_text", "")
            if len(clean_text) > MAX_BLOCK_TEXT_LEN:
                clean_text = clean_text[:MAX_BLOCK_TEXT_LEN] + "..."

            score = item.get("score", 0)
            line = f"  [{layer_short}]{clean_text} [score={score}]"

            # 补全 session 上下文（内联在 block 后面）
            contexts = item.get("contexts", [])
            if contexts:
                ctx_parts = []
                for ctx in contexts[:DEFAULT_MAX_CONTEXTS_PER_FILE]:
                    # ctx 格式: "[filename]\nicon text\nicon text"
                    ctx_lines = ctx.split("\n")
                    if len(ctx_lines) >= 2:
                        header = ctx_lines[0]  # [filename]
                        body = CTX_SEPARATOR.join(l for l in ctx_lines[1:] if l.strip())
                        ctx_parts.append(f"{header}: {body}")
                if ctx_parts:
                    line += " | " + " | ".join(ctx_parts)

            output_parts.append(f"{line}\n")

        output_parts.append("\n")

    return "".join(output_parts).strip()


def auto_recall(query, min_score=DEFAULT_MIN_SCORE, limit=DEFAULT_LIMIT):
    """
    搜索记忆，按层级分组，扁平输出

    Args:
        query: 搜索关键词
        min_score: 最低分数阈值
        limit: 最多返回多少条 block

    Returns:
        格式化后的记忆文本
    """
    # 确定 collection
    agent = get_agent_id()
    collection = f"mem0_{agent}"

    # 向量检索
    try:
        m = get_mem0(collection)
        results = m.search(
            query=query,
            user_id=os.environ.get("MEM0_USER_ID", "fuge"),
            limit=limit
        )
        memories = results.get("results", []) or []
    except Exception as e:
        return f"## 📚 记忆检索失败\n搜索失败: {e}"

    if not memories:
        return ""

    # 解析 + 过滤
    parsed = []
    for mem in memories:
        text = mem.get("memory", "")
        if not text:
            continue
        p = parse_memory(text)
        if not p:
            continue
        if p["score"] < min_score:
            continue
        parsed.append(p)

    if not parsed:
        return ""

    # 按层级分组
    by_layer = defaultdict(list)
    for p in parsed:
        by_layer[p["layer"]].append(p)

    # 每条 block 补全 session 上下文
    for layer in by_layer:
        for item in by_layer[layer]:
            item["contexts"] = get_session_context(item)

    # 格式化输出
    return format_recall_output(by_layer)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: auto_recall.py <查询内容> [min_score] [limit]")
        sys.exit(1)

    query = sys.argv[1]
    min_score = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MIN_SCORE
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_LIMIT

    result = auto_recall(query, min_score=min_score, limit=limit)
    if result:
        print(result)
    else:
        print("未找到相关记忆")
