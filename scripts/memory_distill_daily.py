#!/usr/bin/env python3
"""
每日记忆精炼脚本 - v5 (session 蒸馏记录表)
将 session 文件中的对话蒸馏成结构化记忆 blocks，评分后写入 Qdrant

改进点 v5:
- 新增 distill_session_records 表（Qdrant），记录每个 session 的蒸馏状态
- 每次蒸馏前查表：已蒸馏则跳过，未蒸馏则处理
- session_id = UUID（从文件名提取，支持 .reset.TIMESTAMP 重命名）
- 替换 V4 的 per-session 状态文件为 Qdrant 记录表
"""
import os, sys, re, json, time, argparse, requests
from datetime import datetime, timedelta
from pathlib import Path

SESSIONS_DIR = "/root/.openclaw/agents/main/sessions"
STATE_FILE = "/root/.openclaw/workspace/.distill_state.json"
COLLECTION = "mem0_main"
RECORD_COLLECTION = "distill_session_records"

# ========== 公共变量 ==========
_API_KEY = None
_BASE_URL = "https://api.siliconflow.cn/v1"

# ========== .env 自动加载 ==========
_ENV_PATH = "/root/.openclaw/mem0-agent-setup/.env"
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

def _get_api_key():
    global _API_KEY
    if _API_KEY is None:
        os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "")
        if not os.environ.get("OPENAI_API_KEY"):
            print("ERROR: set OPENAI_API_KEY"); sys.exit(1)
        _API_KEY = os.environ["OPENAI_API_KEY"]
    return _API_KEY

# ========== 配置 ==========
def get_config():
    parser = argparse.ArgumentParser(description="每日记忆精炼")
    parser.add_argument("--agent", default=os.environ.get("AGENT_NAME", "main"), help="Agent ID")
    parser.add_argument("--days", type=int, default=1, help="处理最近多少天（默认1）")
    parser.add_argument("--dry-run", action="store_true", help="只蒸馏，不写入")
    parser.add_argument("--force", action="store_true", help="强制全量处理")
    parser.add_argument("--yes", action="store_true", help="跳过确认直接写入")
    parser.add_argument("--batch-size", type=int, default=80, help="每批处理多少条对话（默认80）")
    parser.add_argument("--cleanup", action="store_true", help="清理超过N天未活跃的session记录（需配合 --days 指定天数）")
    args = parser.parse_args()

    agent = args.agent

    if agent == "main":
        state_file = f"/root/.openclaw/workspace/.distill_state.json"
    else:
        state_file = f"/root/.openclaw/workspace-{agent}/.distill_state.json"

    return {
        "sessions_dir": f"/root/.openclaw/agents/{agent}/sessions",
        "collection": f"mem0_{agent}",
        "state_file": state_file,
        "agent": agent,
        "dry_run": args.dry_run,
        "force": args.force,
        "days": args.days,
        "batch_size": args.batch_size,
        "yes": args.yes,
        "cleanup": args.cleanup,
    }

def _cleanup_realtime_noise(collection):
    """
    清理指定 collection 的 realtime 层噪音记录
    在每天蒸馏前执行，防止噪音干扰蒸馏质量
    """
    scroll_url = f'http://localhost:6333/collections/{collection}/points/scroll'
    delete_url = f'http://localhost:6333/collections/{collection}/points/delete'
    
    def is_noise(d):
        t = d.strip()
        if '[cron:' in t: return True
        if len(t) < 400 and '你是' in t and 'agent' in t.lower() and '请执行' in t: return True
        if t in ('HEARTBEAT_OK', 'HEARTBEAT_TIMEOUT'): return True
        if '<<<BEGIN_OPENCLAW' in t: return True
        if t.startswith('[Internal') or t.startswith('Queued #'): return True
        if 'Conversation info' in t and 'message_id' in t: return True
        if 'Exec completed' in t and len(t) < 600: return True
        if '.jsonl.reset.' in t: return True
        return False
    
    all_pts = []
    offset = None
    while True:
        body = {'limit': 100, 'offset': offset, 'with_payload': True, 'with_vectors': False,
                'filter': {'must': [{'key': 'layer', 'match': {'value': 'realtime'}}]}}
        try:
            r = requests.post(scroll_url, headers={'Content-Type': 'application/json'}, json=body, timeout=10)
            result = r.json()
            if result.get('status') != 'ok': break
            pts = result.get('result', {}).get('points', [])
            if not pts: break
            all_pts.extend(pts)
            offset = result.get('result', {}).get('next_page_offset')
            if offset is None: break
        except: break
    
    noisy = [p['id'] for p in all_pts if is_noise(p['payload'].get('data', ''))]
    if not noisy:
        print(f'[Cleanup] {collection}: 无噪音需要清理')
        return
    
    deleted = 0
    for i in range(0, len(noisy), 50):
        batch = noisy[i:i+50]
        try:
            r = requests.post(delete_url, headers={'Content-Type': 'application/json'}, json={'points': batch}, timeout=10)
            if r.json().get('status') == 'ok':
                deleted += len(batch)
        except: pass
    print(f'[Cleanup] {collection}: 清理了 {deleted}/{len(noisy)} 条噪音')


def get_state_path(cfg):
    state_file = cfg["state_file"]
    state_dir = os.path.dirname(state_file)
    if state_dir and not os.path.exists(state_dir):
        os.makedirs(state_dir, exist_ok=True)
    return state_file

# ========== 状态管理 ==========
def load_state(state_file):
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
        if "last_distilled_at" in state and "sessions" not in state:
            print(f"[迁移] 检测到旧格式状态文件，自动迁移到新格式")
            old_ts = state["last_distilled_at"]
            state = {
                "sessions": {},
                "global_last_run": old_ts,
                "migrated_from_timestamp": True,
                "migrated_at": datetime.now().isoformat()
            }
            save_state(state, state_file)
            print(f"[迁移] 已迁移，last_distilled_at={old_ts}")
        return state
    return {"sessions": {}, "global_last_run": None}

def save_state(state, state_file):
    state_file = get_state_path({"state_file": state_file})
    with open(state_file, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ========== Session UUID 提取 ==========
def extract_session_uuid(filepath):
    """
    从 session 文件路径提取 UUID。
    处理两种情况：
    - 正常：/path/1589659c-8407-406a-a383-5dc74a7335c3.jsonl
    - 重命名：/path/20889554-a992-4a5c-8832-1ed138489174.jsonl.reset.2026-03-25T22-11-30.587Z
    返回：(uuid_str, is_renamed)
    """
    fname = Path(filepath).name
    # 去掉 .reset.TIMESTAMP 后缀
    if ".reset." in fname:
        base = fname.split(".reset.")[0]
        is_renamed = True
    else:
        base = fname
        is_renamed = False
    # 去掉 .jsonl 后缀
    uuid_str = base.replace(".jsonl", "").replace(".jsonl.reset", "")
    return uuid_str, is_renamed

# ========== 蒸馏记录表（Qdrant） ==========
def ensure_record_collection():
    """确保 distill_session_records collection 存在"""
    url = "http://localhost:6333/collections"
    resp = requests.get(f"{url}/{RECORD_COLLECTION}")
    if resp.status_code == 200:
        return
    # 不存在，创建
    create_payload = {
        "name": RECORD_COLLECTION,
        "vectors": {"size": 1024, "distance": "Cosine"}
    }
    r = requests.put(url, json=create_payload)
    if r.status_code not in (200, 201):
        print(f"[WARN] 无法创建 collection {RECORD_COLLECTION}: {r.text}")

def is_session_distilled(session_id):
    """检查某 session 是否已被蒸馏过"""
    url = f"http://localhost:6333/collections/{RECORD_COLLECTION}/points/search"
    body = {
        "vector": [0.0] * 1024,  # dummy vector, filter only
        "limit": 1,
        "with_payload": True,
        "filter": {
            "must": [
                {"key": "session_id", "match": {"value": session_id}}
            ]
        }
    }
    try:
        resp = requests.post(url, headers={"Content-Type": "application/json"}, json=body)
        result = resp.json()
        if result.get("result"):
            return True
        return False
    except:
        return False

def batch_check_sessions(session_ids):
    """
    批量检查多个 session 是否已被蒸馏。
    返回 set of already_distilled session_ids。
    """
    if not session_ids:
        return set()

    url = f"http://localhost:6333/collections/{RECORD_COLLECTION}/points/search"
    body = {
        "vector": [0.0] * 1024,
        "limit": len(session_ids),
        "with_payload": True,
        "filter": {
            "must": [
                {"key": "session_id", "match": {"any": list(session_ids)}}
            ]
        }
    }
    try:
        resp = requests.post(url, headers={"Content-Type": "application/json"}, json=body)
        result = resp.json()
        found = set()
        for p in result.get("result", []):
            sid = p.get("payload", {}).get("session_id", "")
            if sid:
                found.add(sid)
        return found
    except Exception as e:
        print(f"[WARN] 批量检查 session 失败: {e}")
        return set()

def add_distilled_record(session_id, agent_id):
    """
    将 session 标记为已蒸馏（写入 Qdrant 记录表）。
    使用 session_id 的 hash 作为 point ID（幂等）。
    """
    import hashlib
    point_id = hashlib.md5(f"{agent_id}:{session_id}".encode()).hexdigest()
    payload = {
        "session_id": session_id,
        "agent_id": agent_id,
        "remark_1": "",
        "remark_2": "",
        "remark_3": "",
        "distilled_at": datetime.now().isoformat()
    }
    url = f"http://localhost:6333/collections/{RECORD_COLLECTION}/points"
    body = {
        "points": [{"id": point_id, "vector": [0.0] * 1024, "payload": payload}]
    }
    try:
        requests.put(url, headers={"Content-Type": "application/json"}, json=body)
    except Exception as e:
        print(f"[WARN] 写入 session 记录失败: {e}")

# ========== Session 文件扫描 ==========
def get_session_files_with_uuid(sessions_dir):
    """
    扫描 sessions 目录，返回所有 session 文件的 UUID 信息。
    返回：list of (uuid_str, filepath, is_renamed)
    用 list 避免同一 UUID 多个文件时被 dict 覆盖（如 .reset 和新 .jsonl 共用 UUID）
    """
    p = Path(sessions_dir)
    if not p.exists():
        return []
    result = []
    # 同时扫描活跃文件(*.jsonl)和被rotate的文件(*.reset.*)
    for f in list(p.glob("*.jsonl")) + list(p.glob("*.reset.*")):
        uuid_str, is_renamed = extract_session_uuid(str(f))
        result.append((uuid_str, str(f), is_renamed))
    return result

def get_session_with_progress(sessions_dir, state, agent, force=False):
    """
    返回需要处理的 session 文件列表。

    v5 改进：
    - 先查 distill_session_records 表，过滤已蒸馏的 session
    - 再用 per-session 状态文件做行数断点续传

    Returns:
        list of (filepath, uuid_str, start_line)
    """
    # 1. 扫描所有 session 文件，提取 UUID（返回 list，每文件一条记录）
    all_sessions = get_session_files_with_uuid(sessions_dir)
    if not all_sessions:
        return []

    # 2. 批量查记录表，过滤已蒸馏的
    all_uuids = set(uuid_str for uuid_str, _, _ in all_sessions)
    already_distilled = batch_check_sessions(all_uuids)

    new_uuids = all_uuids - already_distilled
    if not new_uuids and not force:
        print(f"[记录表] 共 {len(all_uuids)} 个 session，其中 {len(already_distilled)} 个已蒸馏，{len(new_uuids)} 个待处理")
        print(f"[记录表] 所有 session 均已蒸馏，跳过全量检查")
        return []

    print(f"[记录表] 共 {len(all_uuids)} 个 session，其中 {len(already_distilled)} 个已蒸馏，{len(new_uuids)} 个待处理")

    # 3. 读取 per-session 状态文件（用于行数断点）
    sessions_state = state.get("sessions", {})
    global_last_run = state.get("global_last_run")
    if global_last_run:
        try:
            last_run_dt = datetime.fromisoformat(global_last_run)
        except:
            last_run_dt = None
    else:
        last_run_dt = None

    result = []
    for uuid_str, filepath, is_renamed in all_sessions:
        # .reset 文件：强制从 line 0 处理（不跳过），因为包含历史内容可能未被完整蒸馏
        is_reset_file = is_renamed or ".reset." in filepath

        if not is_reset_file and uuid_str in already_distilled and not force:
            # 非 reset 文件且已蒸馏 → 跳过
            continue

        current_lines = count_lines(filepath)

        # per-session 状态用 (uuid, filepath) 作为 key，独立跟踪每个文件
        state_key = f"{uuid_str}::{Path(filepath).name}"
        if state_key in sessions_state:
            # 断点续传
            processed_lines = sessions_state[state_key].get("processed_lines", 0)
            if current_lines > processed_lines:
                result.append((filepath, uuid_str, processed_lines))
        else:
            # 没有任何记录
            if force or is_reset_file:
                # .reset 文件强制处理（即使 force=False）
                result.append((filepath, uuid_str, 0))
            elif last_run_dt:
                # 只处理 last_run 之后修改的
                mtime = datetime.fromtimestamp(Path(filepath).stat().st_mtime)
                if mtime > last_run_dt:
                    result.append((filepath, uuid_str, 0))
            else:
                result.append((filepath, uuid_str, 0))

    return result

def count_lines(filepath):
    try:
        with open(filepath, 'rb') as f:
            return sum(1 for _ in f)
    except:
        return 0

def read_sessions_from_file(filepath, start_line=0):
    conversations = []
    with open(filepath) as fp:
        for i, line in enumerate(fp):
            if i < start_line:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") == "message":
                    msg = obj.get("message", {})
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
                    if role in ("user", "assistant") and content.strip():
                        clean = extract_user_content(content) if role == "user" else content.strip()
                        if clean and len(clean) > 5:
                            conversations.append({
                                "session": Path(filepath).name,
                                "role": role,
                                "content": clean[:500]
                            })
            except:
                pass
    return conversations

# ========== 原有函数（保持不变） ==========
def extract_user_content(text):
    if text.startswith("System:"):
        m = re.search(r'Sender \(untrusted metadata\):[\s\S]+?\n\n([\s\S]+)$', text)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return text.strip()

def distill_batch(conversations_batch, llm_client):
    if not conversations_batch:
        return []
    sessions = list(set(c["session"] for c in conversations_batch))
    lines = [f"[{i+1}] [{c['session']}] {'User' if c['role']=='user' else 'Assistant'}: {c['content']}" for i, c in enumerate(conversations_batch)]
    block_list = "\n".join(lines)
    prompt = f"""你是记忆整理助手。以下是一批对话记录，涉及 session 文件：{', '.join(sessions)}

{block_list}

请将以上对话提炼成若干独立的记忆块（block），每个 block 是完整的自然语言陈述。

要求：
- 每个 block 包含一个独立的事实/事件/方法
- 相同主题的内容合并为一个 block
- 不重要的闲聊忽略
- 每个 block 必须标注层级
- **重要：每个 block 的内容不超过200字，越精简越好**

格式（严格按此格式，每个 block 之间空一行）：
[层级:Semantic|层级:Episodic|层级:Procedural]
[{{block}}内容]

示例：
[层级:Episodic]
用户提到项目ABC需要在周五前完成测试报告

不要解释，只输出 block 列表。"""
    try:
        resp = llm_client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        text = resp.choices[0].message.content.strip()
        parsed = parse_distilled_blocks(text)
        return [(b.strip(), sessions, layer) for b, layer in parsed]
    except Exception as e:
        print(f"  LLM 错误: {e}")
        return []

def parse_distilled_blocks(text):
    pattern = re.compile(
        r'\[层级:(\w+)\]\s*\n*([\s\S]+?)(?=\[层级:|$)',
        re.MULTILINE | re.DOTALL
    )
    results = []
    for m in pattern.finditer(text):
        layer = m.group(1)
        content = m.group(2).strip()
        if content:
            results.append((content, layer))
    return results

def distill_conversations_batched(conversations, llm_client, batch_size=80):
    all_blocks = []
    total_batches = (len(conversations) + batch_size - 1) // batch_size
    print(f"  共 {len(conversations)} 条对话，分 {total_batches} 批处理（每批 {batch_size} 条）")
    for i in range(0, len(conversations), batch_size):
        batch = conversations[i:i+batch_size]
        batch_num = i // batch_size + 1
        print(f"  处理第 {batch_num}/{total_batches} 批（{len(batch)} 条）...")
        blocks = distill_batch(batch, llm_client)
        print(f"    -> 产出 {len(blocks)} 个 blocks")
        all_blocks.extend(blocks)
        if i + batch_size < len(conversations):
            time.sleep(1)
    print(f"  共生成 {len(all_blocks)} 个 blocks")
    return all_blocks

def score_blocks(blocks_with_layers, llm_client, batch_size=30):
    if not blocks_with_layers:
        return []

    scored = []
    total_batches = (len(blocks_with_layers) + batch_size - 1) // batch_size
    print(f"  分 {total_batches} 批评分（每批 {batch_size} 条）")

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(blocks_with_layers))
        batch = blocks_with_layers[start:end]

        texts = [b[0] for b in batch]
        sessions_all = [b[1] for b in batch]
        layers = [b[2] for b in batch]

        prompt = """以下是从对话中提炼的记忆 block，请对每个评分（1-5分，5分最重要）：
1分：闲聊、无关内容
2分：一般信息
3分：有价值的信息
4分：重要信息
5分：关键信息（如决策、承诺、偏好、重要事件）

评分格式（严格一行一个）：
[分数] block内容

block列表：
""" + "\n".join([f"[{i+1}] {t}" for i, t in enumerate(texts)])

        try:
            resp = llm_client.chat.completions.create(
                model="Qwen/Qwen2.5-7B-Instruct",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            text = resp.choices[0].message.content.strip()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            batch_scored = 0
            for line in lines:
                m = re.match(r'\[?(\d)\]?\s*(.+)', line)
                if m:
                    score = int(m.group(1))
                    block_text = m.group(2).strip()
                    for j, t in enumerate(texts):
                        if block_text == t or block_text in t:
                            scored.append((block_text, score, sessions_all[j], layers[j]))
                            batch_scored += 1
                            break
            print(f"    第{batch_idx+1}批：评分了 {batch_scored} 个")
        except Exception as e:
            print(f"    第{batch_idx+1}批 LLM 错误: {e}")

    print(f"  共评分了 {len(scored)} 个 blocks")
    return scored

def write_blocks(blocks_with_scores, qdrant_client, embed_api_key, agent, collection, min_score=3):
    import uuid, requests

    written = 0
    for item in blocks_with_scores:
        if len(item) != 4:
            continue
        block_text, score, sessions, layer = item[:4]
        if score < min_score:
            continue
        files = ",".join([f"/root/.openclaw/agents/{agent}/sessions/{s}" for s in sessions])
        record = f"[层级:{layer}][score:{score}][distilled][sessions:{len(sessions)}][files:{files}]\n{block_text}"

        try:
            # Truncate text if too long (SiliconFlow BGE has ~512 token limit ≈ 500 chars for Chinese)
            # Header is ~100 chars, so block text should be ≤ 300 chars for safety
            text_to_embed = record[:400] if len(record) > 400 else record
            resp = requests.post(
                "https://api.siliconflow.cn/v1/embeddings",
                headers={"Authorization": f"Bearer {embed_api_key}"},
                json={"model": "BAAI/bge-large-zh-v1.5", "input": text_to_embed}
            )
            if resp.status_code != 200:
                print(f"  Embedding 失败: HTTP {resp.status_code} - {resp.text[:100]}")
                continue
            data = resp.json()
            if not data.get("data"):
                print(f"  Embedding 失败: 空响应 (文本过长), status={resp.status_code}")
                # Retry with much shorter text
                text_to_embed = record[:200] if len(record) > 200 else record
                resp = requests.post(
                    "https://api.siliconflow.cn/v1/embeddings",
                    headers={"Authorization": f"Bearer {embed_api_key}"},
                    json={"model": "BAAI/bge-large-zh-v1.5", "input": text_to_embed}
                )
                if resp.status_code != 200 or not resp.json().get("data"):
                    print(f"  Embedding 重试也失败: HTTP {resp.status_code}")
                    continue
                data = resp.json()
            vec = data["data"][0]["embedding"]
        except Exception as e:
            print(f"  Embedding 失败: {e}")
            continue

        payload = {
            "user_id": os.environ.get("MEM0_USER_ID", "fuge"),
            "agent_id": agent,
            "role": "user",
            "data": record,
            "hash": str(uuid.uuid4()),
            "created_at": datetime.now().isoformat(),
            "layer": layer,
        }

        point = {
            "id": str(uuid.uuid4()),
            "vector": vec,
            "payload": payload,
        }
        try:
            qdrant_client.upsert(collection_name=collection, points=[point])
            print(f"  OK [层级:{layer}][score:{score}] {block_text[:60]}...")
            written += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  Qdrant 写入失败: {e}")
    return written

# ========== 主流程 ==========
def main():
    cfg = get_config()
    sessions_dir = cfg["sessions_dir"]
    collection = cfg["collection"]
    state_file = cfg["state_file"]
    agent = cfg["agent"]
    dry_run = cfg["dry_run"]
    force = cfg["force"]
    batch_size = cfg["batch_size"]

    os.environ["OPENAI_API_KEY"] = _get_api_key()
    from qdrant_client import QdrantClient
    from openai import OpenAI

    API_KEY = _get_api_key()
    BASE_URL = _BASE_URL
    client_llm = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    qdrant_client = QdrantClient(url="http://localhost:6333")

    print(f"[Agent: {agent}] Collection: {collection}  Sessions: {sessions_dir}")
    print(f"[State] {state_file}")

    # v5: 清理 realtime 层噪音（Cron任务、Agent指令等）
    try:
        _cleanup_realtime_noise(collection)
    except Exception as e:
        print(f'[Cleanup] 噪音清理失败: {e}')

    # v5: 确保记录表存在
    ensure_record_collection()

    state = load_state(state_file)

    # 获取需要处理的文件及起始行
    files_to_process = get_session_with_progress(sessions_dir, state, agent, force=force)

    if not files_to_process:
        print("没有需要处理的 session 文件")
        return

    print(f"发现 {len(files_to_process)} 个 session 需要处理")

    total_convs = 0
    for filepath, uuid_str, start_line in files_to_process:
        convs = read_sessions_from_file(filepath, start_line)
        total_convs += len(convs)
        print(f"  {Path(filepath).name} (uuid={uuid_str}): 从第{start_line}行开始，{len(convs)}条新对话")

    if total_convs == 0:
        print("没有新对话可处理")
        return

    all_convs = []
    for filepath, uuid_str, start_line in files_to_process:
        convs = read_sessions_from_file(filepath, start_line)
        all_convs.extend(convs)

    print(f"共 {len(all_convs)} 条对话片段")

    print("开始分批蒸馏...")
    blocks = distill_conversations_batched(all_convs, client_llm, batch_size=batch_size)
    if not blocks:
        return

    print("开始评分...")
    scored = score_blocks(blocks, client_llm)
    if not scored:
        return

    print(f"\n评分结果（共 {len(scored)} 个 blocks）：")
    for s in [5, 4, 3, 2, 1]:
        g = [item for item in scored if item[1] == s]
        if g:
            label = {5: "core", 4: "important", 3: "normal", 2: "temp", 1: "discard"}[s]
            layer_count = {}
            for item in g:
                layer = item[3] if len(item) > 3 else "?"
                layer_count[layer] = layer_count.get(layer, 0) + 1
            print(f"  score={s} ({label}): {len(g)} 条 {layer_count}")
            for item in g[:3]:
                print(f"    - [{item[3]}] {item[0][:80]}...")

    to_store = [item for item in scored if item[1] >= 3]
    print(f"\n将存入 {len(to_store)} 条（score>=3）")

    if dry_run:
        print("[dry-run，不写入]")
        return

    if not cfg.get("yes") and input("确认写入？（y/n）: ").strip().lower() != "y":
        print("已取消")
        return

    print("写入 mem0...")
    written = write_blocks(to_store, qdrant_client, API_KEY, agent, collection)

    # v5: 将每个处理的 session 写入蒸馏记录表
    now = datetime.now().isoformat()
    for filepath, uuid_str, start_line in files_to_process:
        add_distilled_record(uuid_str, agent)
        # 同时更新 per-session 状态（用 uuid::filename 作为 key，区分同一 UUID 下的不同文件）
        current_lines = count_lines(filepath)
        state_key = f"{uuid_str}::{Path(filepath).name}"
        if "sessions" not in state:
            state["sessions"] = {}
        state["sessions"][state_key] = {
            "processed_lines": current_lines,
            "distilled_at": now,
            "current_lines": current_lines
        }

    state["global_last_run"] = now
    save_state(state, state_file)

    print(f"\n完成！写入 {written} 条")
    print(f"状态已更新: {len(files_to_process)} 个 session")

if __name__ == "__main__":
    main()
