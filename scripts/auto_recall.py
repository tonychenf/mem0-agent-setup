#!/usr/bin/env python3
"""
auto_recall - 自动记忆读取（v8）
设计目标：
- 分组扁平输出：每层定义出现一次，block 用 | 分隔
- 严谨性：边界条件，空值、异常全面处理
- 可拓展性：层级定义外部化、输出格式可配置、session 上下文策略可扩展
- v8: Step 4完整session + Step 5 realtime
  - Step 4: 加载整个 session 文件（无 keyword 匹配）
  - Step 5: 加载当前 session + 24h 内 realtime 对话
"""
import os, sys, re, json, time
from datetime import datetime, timedelta, timezone
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
    "procedural": "回答请遵循用户认可的工作流程和操作步骤",
    "realtime": "实时捕获的原始记忆片段"
}

LAYER_SHORT_NAMES = {
    "semantic": "语义",
    "episodic": "事件",
    "procedural": "程序",
    "realtime": "实时",
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
    直接调 Qdrant REST API 语义搜索
    搜索所有层级的记录：Semantic, Episodic, Procedural, Realtime
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
                        "any": ["Semantic", "semantic", "Episodic", "Procedural"]
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


def fetch_recent_realtime(agent, limit=20):
    """
    获取最近 N 条 realtime 记录（按时序，不走向量搜索）
    """
    collection = f"mem0_{agent}"
    url = f"http://localhost:6333/collections/{collection}/points/scroll"

    all_points = []
    offset = None
    
    while len(all_points) < 500:  # 最多扫500条
        body = {"limit": 100, "offset": offset, "with_payload": True, "with_vectors": False}
        try:
            resp = requests.post(url, headers={"Content-Type": "application/json"}, json=body)
            result = resp.json()
            if result.get("status") != "ok":
                break
            points = result.get("result", {}).get("points", [])
            if not points:
                break
            all_points.extend(points)
            offset = result.get("result", {}).get("next_page_offset")
            if offset is None:
                break
        except:
            break

    # 过滤 realtime（没有 [层级: 和 [distilled] 标签的）
    # realtime 格式：[realtime][score:N] 内容
    realtime_points = []
    for p in all_points:
        data = p.get("payload", {}).get("data", "")
        if "[层级:" in data or "[distilled]" in data:
            continue  # 跳过蒸馏数据
        if re.search(r"\[(semantic|episodic|procedural)\]", data, re.IGNORECASE):
            continue  # 跳过带层级标签的同步数据
        realtime_points.append(p)

    # 按 created_at 倒序，取最近 limit 条
    realtime_points.sort(key=lambda p: p.get("payload", {}).get("created_at", ""), reverse=True)
    
    return [{
        "id": p.get("id"),
        "payload": p.get("payload", {})
    } for p in realtime_points[:limit]]


def parse_memory(text):
    """
    解析记忆 block，提取层级、分数、文件路径、纯文本
    支持两种格式：
    - 蒸馏格式：[层级:Episodic][score:5][distilled][sessions:2][files:/path/a.jsonl]\n{block}
    - 实时格式：[realtime][score:3] {content}
    """
    if not text or not isinstance(text, str):
        return None

    # 判断格式：蒸馏有 [层级: 或 [distilled]，其他是 realtime
    is_distill = "[层级:" in text or "[distilled]" in text

    if is_distill:
        # 蒸馏格式解析
        layer_m = re.search(r'\[层级:(\w+)\]', text)
        score_m = re.search(r'\[score:(\d+)\]', text)
        files_m = re.search(r'\[files:([^\]]+)\]', text)

        layer = layer_m.group(1).lower() if layer_m else "unknown"
        score = int(score_m.group(1)) if score_m else 0
        files = []
        if files_m and files_m.group(1).strip():
            files = [f.strip() for f in files_m.group(1).split(",") if f.strip()]
    else:
        # 实时格式解析
        score_m = re.search(r'\[score:(\d+)\]', text)
        layer = "realtime"
        score = int(score_m.group(1)) if score_m else 3
        files = []

    # 去掉所有 [标签] 前缀，得到纯文本
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


def extract_tool_result_text(text):
    """
    从 toolResult JSON 中智能提取关键内容。
    支持：browser、exec、file listing、API response 等多种工具输出。
    返回提取后的短文本，失败时返回原始 text。
    """
    if not text or len(text) > 50000:
        return text[:MAX_CTX_MSG_LEN] if text else ""

    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        # 不是 JSON，直接返回原始文本
        return text[:MAX_CTX_MSG_LEN] if text else ""

    if not isinstance(obj, dict):
        return text[:MAX_CTX_MSG_LEN] if text else ""

    # 检测工具类型
    url = obj.get("finalUrl") or obj.get("url", "")
    stdout = obj.get("stdout") or obj.get("output") or ""
    status = obj.get("status", "")
    error = obj.get("error") or ""
    content = obj.get("content", "")
    command = obj.get("command", "")
    exit_code = obj.get("exit_code", "")

    parts = []

    # browser 工具
    if url:
        parts.append(f"→ {url[:100]}")

    # exec 工具
    if command:
        parts.append(f"$ {command[:120]}")
    if stdout:
        # 过滤掉二进制或超长输出
        try:
            stdout_str = str(stdout)
            if len(stdout_str) > 2000:
                stdout_str = stdout_str[:2000] + " ..."
            parts.append(stdout_str)
        except Exception:
            pass

    # 简短响应
    if status and not stdout and not content:
        parts.append(f"[{status}]")

    # error
    if error:
        err_str = str(error)[:200]
        if err_str not in "".join(parts):
            parts.append(f"✗ {err_str}")

    # browser 结果的页面内容（content 通常是 HTML/text，简短取前 500 字）
    if content and url:
        try:
            content_str = str(content)
            if len(content_str) > 500:
                content_str = content_str[:500] + " ..."
            parts.append(content_str)
        except Exception:
            pass

    # API / file listing / 其他纯 content（无 url）
    if content and not url:
        try:
            content_str = str(content)
            if len(content_str) > 3000:
                content_str = content_str[:3000] + " ..."
            parts.append(content_str)
        except Exception:
            pass

    result = " ".join(parts)
    return result[:MAX_CTX_MSG_LEN] if result else text[:MAX_CTX_MSG_LEN]


def lookup_session_snippets(filepath, keyword=None, max_snippets=6):
    """
    读取 session JSONL 文件的完整内容（Step 4 改进）
    不再依赖 keyword 匹配，直接返回整个 session 的消息（限最新 N 条）

    返回格式：[filename]\nicon text\nicon text\n...
    """
    if not filepath or not os.path.exists(filepath):
        return []

    role_icon_map = {
        "user": "👤",
        "assistant": "🤖"
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
                first = content_arr[0]
                if isinstance(first, dict):
                    text = first.get("text", "")
                else:
                    text = str(first)
            else:
                text = str(content_arr)

            # 跳过 System: 包装的消息
            if text.startswith("System:"):
                continue
            # toolResult 走智能提取
            if role == "toolResult":
                text = extract_tool_result_text(text)
            else:
                text = text[:MAX_CTX_MSG_LEN]

            if text:
                relevant_messages.append({
                    "role": role,
                    "text": text,
                    "icon": role_icon_map[role]
                })
        except Exception:
            continue

    if not relevant_messages:
        return []

    # Step 4: 返回完整 session（不限 keyword），取最新消息
    MAX_SESSION_MSGS = 50
    session_msgs = relevant_messages[-MAX_SESSION_MSGS:]

    snippets = []
    for msg in session_msgs:
        snippets.append(f"{msg['icon']} {msg['text']}")

    filename = os.path.basename(filepath)
    return [f"[{filename}]\n" + "\n".join(snippets[:max_snippets])]


def get_session_context(parsed, max_files=DEFAULT_MAX_FILES_PER_BLOCK, max_snippets_per_file=DEFAULT_MAX_CONTEXTS_PER_FILE):
    """
    根据 block 中的 files 路径，补全 session 上下文
    返回格式：[ctx1, ctx2, ...]
    """
    if not parsed or not parsed.get("files"):
        return []

    files = parsed.get("files", [])
    # Step 4: 不再依赖 keyword，直接加载完整 session
    contexts = []
    for filepath in files[:max_files]:
        ctx_list = lookup_session_snippets(filepath, max_snippets=max_snippets_per_file)
        contexts.extend(ctx_list)

    return contexts


def get_current_session_path(agent=None):
    """
    找到当前活跃的 session 文件路径
    通过 sessions.json 找到最近更新的 session（按 updatedAt）
    """
    agent = agent or get_agent_id()
    sessions_json = f"/root/.openclaw/agents/{agent}/sessions/sessions.json"
    if not os.path.exists(sessions_json):
        return None
    try:
        with open(sessions_json) as f:
            data = json.load(f)
        # sessions.json 结构：{"agent:main:feishu:...": {"sessionId": "...", "updatedAt": ...}}
        # 找 updatedAt 最大（最近更新）的 session
        latest_key = None
        latest_time = 0
        for k, v in data.items():
            if isinstance(v, dict) and v.get("updatedAt", 0) > latest_time:
                latest_time = v["updatedAt"]
                latest_key = k
        if latest_key:
            session_file = data[latest_key].get("sessionFile")
            if session_file and os.path.exists(session_file):
                return session_file
    except Exception:
        pass
    return None


def get_realtime_context(agent, max_msgs=30):
    """
    Step 5: 加载向量库中最近 24 小时的 realtime 对话
    + 当前活跃 session 文件

    Realtime 数据特征：
    - role = 'user' 或 'assistant'（来自 sync_to_mem0）
    - data 不含 [层级:] 蒸馏标记（排除旧版 distillation blocks）
    - 来自当前 session 文件（未写入 Qdrant）

    返回格式：[realtime session file]\nicon text\nicon text\n...
           [Qdrant realtime]\nicon text\nicon text\n...
    """
    contexts = []
    now = datetime.now(timezone.utc)
    delta = now - timedelta(hours=24)

    # 1. 当前活跃 session 文件（未写入 Qdrant）
    current_session = get_current_session_path(agent)
    if current_session:
        msgs = _load_session_messages(current_session, max_msgs)
        if msgs:
            ctx_lines = [f"[当前 Session]\n"]
            for msg in msgs[-max_msgs:]:
                ctx_lines.append(f"{msg['icon']} {msg['text']}")
            contexts.append("\n".join(ctx_lines[:max_msgs + 1]))

    # 2. Qdrant 中最近 24h 的 realtime 数据（排除蒸馏 blocks）
    collection = f"mem0_{agent}"
    zero_vec = [0.0] * 1024
    url = f"http://localhost:6333/collections/{collection}/points/search"

    body = {
        "vector": zero_vec,
        "limit": 20,
        "filter": {
            "must": [
                {"key": "agent_id", "match": {"any": [agent]}},
                {"key": "role", "match": {"any": ["user", "assistant"]}}
            ]
        },
        "with_payload": True
    }

    try:
        resp = requests.post(url, headers={"Content-Type": "application/json"}, json=body)
        result = resp.json()
        if result.get("status") == "ok":
            pts = result.get("result", [])
            # 过滤：排除含 [层级:] 的蒸馏 blocks
            realtime_msgs = []
            for p in pts:
                pl = p.get("payload", {})
                data = pl.get("data", "")
                # 排除蒸馏 blocks（含有 [层级: 或 [semantic] 等标记）
                if "[层级:" in data or "[semantic]" in data.lower() or "[episodic]" in data.lower() or "[procedural]" in data.lower():
                    continue
                role = pl.get("role", "")
                icon = {"user": "👤", "assistant": "🤖"}.get(role, "📄")
                realtime_msgs.append(f"{icon} {data[:MAX_CTX_MSG_LEN]}")

            if realtime_msgs:
                contexts.append("[Qdrant 24h]\n" + "\n".join(realtime_msgs[:max_msgs]))
    except Exception:
        pass

    return contexts


def _load_session_messages(filepath, max_msgs=50):
    """读取 session 文件，返回消息列表"""
    role_icon_map = {"user": "👤", "assistant": "🤖", "toolResult": "🔧"}
    messages = []
    try:
        with open(filepath, encoding="utf-8") as f:
            lines = f.readlines()
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
                    messages.append({"role": role, "text": text[:MAX_CTX_MSG_LEN], "icon": role_icon_map[role]})
            except Exception:
                continue
    except Exception:
        pass
    return messages


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

    layer_order = ["semantic", "episodic", "procedural", "realtime"]

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


def auto_recall(query, min_score=DEFAULT_MIN_SCORE, limit=DEFAULT_LIMIT, agent=None):
    """
    搜索记忆，按层级分组，扁平输出

    v8: Qdrant 语义搜索 + 最近20条 realtime 追加
    - 语义搜索：返回相关度最高的记录（蒸馏+realtime混合）
    - 追加最近20条 realtime：按时序无条件追加
    - 蒸馏按分数过滤，realtime 不过滤

    Args:
        query: 搜索关键词
        min_score: 最低分数阈值
        limit: 最多返回多少条 block

    Returns:
        格式化后的记忆文本
    """
    agent = agent or get_agent_id()

    # v7: 生成 query embedding，然后调 Qdrant 过滤搜索
    try:
        vec = embed_query(query)
        points = qdrant_search(vec, agent, limit=limit)
    except Exception as e:
        return f"## 📚 记忆检索失败\n搜索失败: {e}"

    if not points:
        return ""

    # 解析 + 过滤
    # 语义搜索结果：蒸馏按分数过滤，realtime 不过滤
    parsed = []
    for p in points:
        payload = p.get("payload", {})
        text = payload.get("data", "")
        if not text:
            continue
        parsed_item = parse_memory(text)
        if not parsed_item:
            continue
        # 蒸馏按分数过滤，realtime 不过滤
        if parsed_item["layer"] != "realtime" and parsed_item["score"] < min_score:
            continue
        parsed_item["_payload"] = payload
        parsed.append(parsed_item)

    # 追加最近20条 realtime（按时序，不过滤）
    try:
        recent_realtime = fetch_recent_realtime(agent, limit=20)
        for rp in recent_realtime:
            payload = rp.get("payload", {})
            text = payload.get("data", "")
            if not text:
                continue
            # 去重：跳过已在语义搜索结果中的
            if any(p.get("_payload", {}).get("id") == rp.get("id") for p in parsed):
                continue
            parsed_item = parse_memory(text)
            if parsed_item:
                parsed_item["_payload"] = payload
                parsed.append(parsed_item)
    except:
        pass  # 出错不影响主流程

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
    output = format_recall_output(by_layer)

    return output


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="auto_recall - 记忆检索")
    parser.add_argument("query", help="搜索关键词")
    parser.add_argument("min_score", nargs="?", type=int, default=DEFAULT_MIN_SCORE, help=f"最低分数阈值（默认 {DEFAULT_MIN_SCORE}）")
    parser.add_argument("limit", nargs="?", type=int, default=DEFAULT_LIMIT, help=f"最多返回条数（默认 {DEFAULT_LIMIT}）")
    parser.add_argument("--agent", dest="agent", default=None, help="指定 agent（默认从环境变量推导）")
    args = parser.parse_args()

    result = auto_recall(args.query, min_score=args.min_score, limit=args.limit, agent=args.agent)
    if result:
        print(result)
    else:
        print("未找到相关记忆")
