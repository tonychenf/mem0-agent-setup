#!/usr/bin/env python3
"""
auto_recall - 自动记忆读取（v7）
设计目标：
- 分组扁平输出：每层定义出现一次，block 用 | 分隔
- 严谨性：边界条件，空值、异常全面处理
- 可拓展性：层级定义外部化、输出格式可配置、session 上下文策略可扩展
- v7: 直接调 Qdrant REST API + layer 过滤，只搜 distilled block
"""
import os, sys, re, json, time
from pathlib import Path
from collections import defaultdict

# === Workspace 路径推导（唯一路径） ===
def detect_agent_id_from_workspace():
    workspace_dir = os.environ.get("WORKSPACE_DIR", "").rstrip("/")
    if not workspace_dir:
        return None
    basename = os.path.basename(workspace_dir)
    if basename.startswith("workspace-"):
        return basename[len("workspace-"):]
    elif basename == "workspace":
        return "main"
    return None

_detected_agent_id = None

def get_agent_id():
    global _detected_agent_id
    if _detected_agent_id is not None:
        return _detected_agent_id
    _detected_agent_id = detect_agent_id_from_workspace() or os.environ.get("AGENT_NAME", "main")
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

import requests

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
DEFAULT_MAX_FILES_PER_BLOCK = 2
DEFAULT_MAX_CONTEXTS_PER_FILE = 2
MAX_BLOCK_TEXT_LEN = 200
MAX_CTX_MSG_LEN = 150
BLOCK_SEPARATOR = " | "
CTX_SEPARATOR = " | "


# === v7: 直接调 Qdrant REST API + layer 过滤 ===

def embed_query(query_text):
    """
    用 SiliconFlow BAAI/bge-large-zh-v1.5 生成 query 向量
    返回 1024 维 float 列表
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/embeddings",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"model": "BAAI/bge-large-zh-v1.5", "input": query_text}
        )
        data = resp.json()
        return data["data"][0]["embedding"]
    except Exception as e:
        raise RuntimeError(f"Embedding 失败: {e}")


def qdrant_search(vec, agent, limit=8):
    """
    直接调 Qdrant REST API，只搜有 layer 字段的 distilled block

    过滤逻辑：layer IN ["Semantic", "Episodic", "Procedural"]
    Realtime sync 数据没有 layer 字段，会被过滤掉
    """
    collection = f"mem0_{agent}"
    url = f"http://localhost:6333/collections/{collection}/points/search"

    body = {
        "vector": vec,
        "limit": limit,
        "with_payload": True,
        "filter": {
            "must": [
                {
                    "key": "layer",
                    "match": {
                        "any": ["Semantic", "Episodic", "Procedural"]
                    }
                }
            ]
        }
    }

    try:
        resp = requests.post(url, headers={"Content-Type": "application/json"}, json=body)
        result = resp.json()
        if result.get("status") != "ok":
            raise RuntimeError(f"Qdrant search failed: {result}")
        return result.get("result", [])
    except Exception as e:
        raise RuntimeError(f"Qdrant search 失败: {e}")


def parse_memory(text):
    """
    解析记忆 block，提取层级、分数、文件路径、纯文本
    格式：[层级:Episodic][score:5][distilled][sessions:2][files:/path/a.jsonl,/path/b.jsonl]
          {block_text}
    """
    if not text or not isinstance(text, str):
        return None

    layer_m = re.search(r'\[层级:(\w+)\]', text)
    score_m = re.search(r'\[score:(\d+)\]', text)
    files_m = re.search(r'\[files:([^\]]+)\]', text)

    layer = layer_m.group(1).lower() if layer_m else "unknown"
    score = int(score_m.group(1)) if score_m else 0
    files = []
    if files_m and files_m.group(1).strip():
        files = [f.strip() for f in files_m.group(1).split(",") if f.strip()]

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

            content_arr = msg.get("content", [])
            if isinstance(content_arr, list) and content_arr:
                text = content_arr[0].get("text", "") if isinstance(content_arr[0], dict) else str(content_arr[0])
            else:
                text = str(content_arr)

            if text:
                relevant_messages.append({
                    "role": role,
                    "text": text[:MAX_CTX_MSG_LEN],
                    "icon": role_icon_map[role]
                })
        except Exception:
            continue

    if not relevant_messages:
        return []

    keyword_lower = keyword.lower() if keyword else ""
    matched_indices = []
    for i, msg in enumerate(relevant_messages):
        if keyword_lower and keyword_lower in msg["text"].lower():
            matched_indices.append(i)

    if not matched_indices:
        matched_indices = [len(relevant_messages) - 1]

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
    keyword = parsed.get("clean_text", "")[:20]

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

        output_parts.append(f"{layer_def}：\n")

        for item in items:
            clean_text = item.get("clean_text", "")
            if len(clean_text) > MAX_BLOCK_TEXT_LEN:
                clean_text = clean_text[:MAX_BLOCK_TEXT_LEN] + "..."

            score = item.get("score", 0)
            line = f"  [{layer_short}]{clean_text} [score={score}]"

            contexts = item.get("contexts", [])
            if contexts:
                ctx_parts = []
                for ctx in contexts[:DEFAULT_MAX_CONTEXTS_PER_FILE]:
                    ctx_lines = ctx.split("\n")
                    if len(ctx_lines) >= 2:
                        header = ctx_lines[0]
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

    v7: 直接调 Qdrant REST API + layer 过滤
    只返回有 layer 字段的 distilled block（realtime sync 数据被过滤）

    Args:
        query: 搜索关键词
        min_score: 最低分数阈值
        limit: 最多返回多少条 block

    Returns:
        格式化后的记忆文本
    """
    agent = get_agent_id()

    # v7: 生成 query embedding，然后调 Qdrant 过滤搜索
    try:
        vec = embed_query(query)
        points = qdrant_search(vec, agent, limit=limit)
    except Exception as e:
        return f"## 📚 记忆检索失败\n搜索失败: {e}"

    if not points:
        return ""

    # 解析 + 过滤
    parsed = []
    for p in points:
        payload = p.get("payload", {})
        text = payload.get("data", "")
        if not text:
            continue
        parsed_item = parse_memory(text)
        if not parsed_item:
            continue
        if parsed_item["score"] < min_score:
            continue
        parsed_item["_payload"] = payload
        parsed.append(parsed_item)

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
