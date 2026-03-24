#!/usr/bin/env python3
"""
每日记忆精炼脚本 - v3 (batched)
将 session 文件中的对话蒸馏成结构化记忆 blocks，评分后写入 Qdrant
"""
import os, sys, re, json, time, argparse, requests
from datetime import datetime, timedelta
from pathlib import Path

SESSIONS_DIR = "/root/.openclaw/agents/main/sessions"
STATE_FILE = "/root/.openclaw/workspace/.distill_state.json"
COLLECTION = "mem0_main"

# ========== 配置 ==========
def get_config():
    parser = argparse.ArgumentParser(description="每日记忆精炼")
    parser.add_argument("--agent", default=os.environ.get("AGENT_NAME", "main"), help="Agent ID")
    parser.add_argument("--days", type=int, default=1, help="处理最近多少天（默认1）")
    parser.add_argument("--dry-run", action="store_true", help="只蒸馏，不写入")
    parser.add_argument("--force", action="store_true", help="强制全量处理")
    parser.add_argument("--yes", action="store_true", help="跳过确认直接写入")
    parser.add_argument("--batch-size", type=int, default=80, help="每批处理多少条对话（默认80）")
    args = parser.parse_args()

    agent = args.agent
    return {
        "sessions_dir": f"/root/.openclaw/agents/{agent}/sessions",
        "collection": f"mem0_{agent}",
        "state_file": f"/root/.openclaw/workspace/.distill_state_{agent}.json",
        "agent": agent,
        "dry_run": args.dry_run,
        "force": args.force,
        "days": args.days,
        "batch_size": args.batch_size,
        "yes": args.yes,
    }
# ==========================

def load_state(state_file):
    if os.path.exists(state_file):
        with open(state_file) as f:
            return json.load(f)
    return {"last_distilled_at": None}

def save_state(state, state_file):
    with open(state_file, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def get_session_files(sessions_dir, since_dt):
    files = []
    p = Path(sessions_dir)
    if not p.exists():
        return files
    for f in p.glob("*.jsonl"):
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime > since_dt:
            files.append(f)
    return files

def extract_user_content(text):
    if text.startswith("System:"):
        m = re.search(r'Sender \(untrusted metadata\):[\s\S]+?\n\n([\s\S]+)$', text)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return text.strip()

def read_sessions(files):
    conversations = []
    for f in files:
        with open(f) as fp:
            for line in fp:
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
                                conversations.append({"session": f.name, "role": role, "content": clean[:500]})
                except:
                    pass
    return conversations

def distill_batch(conversations_batch, llm_client):
    """蒸馏一批对话，返回 block 列表"""
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
- 用 [block] 开头，格式：[block] 陈述内容

不要解释，只输出 block 列表，每个一行。"""
    try:
        resp = llm_client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        text = resp.choices[0].message.content.strip()
        blocks = re.findall(r"\[block\]\s*(.+)", text)
        return [(b.strip(), sessions) for b in blocks]
    except Exception as e:
        print(f"  LLM 错误: {e}")
        return []

def distill_conversations_batched(conversations, llm_client, batch_size=80):
    """分批蒸馏，合并结果"""
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

def score_blocks(blocks_with_sessions, llm_client):
    """对所有 blocks 评分"""
    if not blocks_with_sessions:
        return []
    block_text = "\n".join([f"{i+1}. {b}" for i, (b, _) in enumerate(blocks_with_sessions)])
    prompt = f"""以下是从对话中提炼的记忆 block，请对每个评分：

{block_text}

评分标准：
- 5分：核心事实，必须记住
- 4分：重要信息，值得保留
- 3分：一般信息，可以保留
- 2分：临时信息，不值得单独保留
- 1分：无价值信息

格式（每行）：
评分 | block内容

只输出评分行，不要其他内容。"""
    try:
        resp = llm_client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        text = resp.choices[0].message.content.strip()
        scored = []
        for line in text.split("\n"):
            line = line.strip()
            if "|" in line:
                parts = line.split("|", 1)
                try:
                    score = int(parts[0].strip())
                    idx = len(scored)
                    sessions = blocks_with_sessions[idx][1] if idx < len(blocks_with_sessions) else []
                    scored.append((parts[1].strip(), score, sessions))
                except:
                    pass
        print(f"  评分了 {len(scored)} 个 blocks")
        return scored
    except Exception as e:
        print(f"  评分 LLM 错误: {e}")
        return []

def write_blocks(blocks_with_scores, qdrant_client, embed_api_key, agent, collection, min_score=3):
    """手动生成向量并直接写入 Qdrant"""
    import uuid, requests

    written = 0
    for block_text, score, sessions in blocks_with_scores:
        if score < min_score:
            continue
        c = block_text.lower()
        if any(k in c for k in ["流程", "步骤", "方法", "如何", "先", "然后"]):
            mtype = "procedural"
        elif any(k in c for k in ["今天", "昨天", "讨论", "开会", "做了", "完成"]):
            mtype = "episodic"
        else:
            mtype = "semantic"
        files = ", ".join([f"/root/.openclaw/agents/{agent}/sessions/{s}" for s in sessions])
        record = f"[{mtype}][score:{score}][distilled][sessions:{len(sessions)}][files:{files}]\n{block_text}"

        # Generate embedding via REST API
        try:
            resp = requests.post(
                "https://api.siliconflow.cn/v1/embeddings",
                headers={"Authorization": f"Bearer {embed_api_key}"},
                json={"model": "BAAI/bge-large-zh-v1.5", "input": record}
            )
            data = resp.json()
            vec = data["data"][0]["embedding"]
        except Exception as e:
            print(f"  Embedding 失败: {e}")
            continue

        payload = {
            "user_id": os.environ.get("MEM0_USER_ID", "user"),
            "agent_id": agent,
            "role": "user",
            "data": record,
            "hash": str(uuid.uuid4()),
            "created_at": datetime.now().isoformat(),
        }

        point = {
            "id": str(uuid.uuid4()),
            "vector": vec,
            "payload": payload,
        }
        try:
            qdrant_client.upsert(collection_name=collection, points=[point])
            print(f"  OK [{mtype}][score:{score}] {block_text[:60]}...")
            written += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  Qdrant 写入失败: {e}")
    return written


def main():
    cfg = get_config()
    sessions_dir = cfg["sessions_dir"]
    collection = cfg["collection"]
    state_file = cfg["state_file"]
    agent = cfg["agent"]
    dry_run = cfg["dry_run"]
    force = cfg["force"]
    days = cfg["days"]
    batch_size = cfg["batch_size"]

    os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "")
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: set OPENAI_API_KEY"); sys.exit(1)

    from qdrant_client import QdrantClient
    from openai import OpenAI
    from mem0 import Memory

    API_KEY = os.environ["OPENAI_API_KEY"]
    BASE_URL = "https://api.siliconflow.cn/v1"
    client_llm = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    qdrant_client = QdrantClient(url="http://localhost:6333")


    # Note: m (Memory) still used for scoring only in this version
    m = Memory.from_config({
        "vector_store": {"provider": "qdrant", "config": {"host": "localhost", "port": 6333, "collection_name": collection, "embedding_model_dims": 1024}},
        "llm": {"provider": "openai", "config": {"model": "Qwen/Qwen2.5-7B-Instruct", "openai_base_url": BASE_URL, "temperature": 0.1}},
        "embedder": {"provider": "openai", "config": {"model": "BAAI/bge-large-zh-v1.5", "openai_base_url": BASE_URL, "embedding_dims": 1024}}
    })

    print(f"[Agent: {agent}] Collection: {collection}  Sessions: {sessions_dir}")

    state = load_state(state_file)
    since_dt = datetime.now() - timedelta(days=days) if force or not state.get("last_distilled_at") else datetime.fromisoformat(state["last_distilled_at"])
    mode_str = "强制" if force else "增量"
    print(f"{mode_str}模式，处理最近 {days} 天（{since_dt.strftime('%Y-%m-%d')} 起）")

    files = get_session_files(sessions_dir, since_dt)
    print(f"找到 {len(files)} 个 session 文件")
    if not files:
        return

    convs = read_sessions(files)
    print(f"提取了 {len(convs)} 条对话片段")
    if not convs:
        return

    print("开始分批蒸馏...")
    blocks = distill_conversations_batched(convs, client_llm, batch_size=batch_size)
    if not blocks:
        return

    print("开始评分...")
    scored = score_blocks(blocks, client_llm)
    if not scored:
        return

    print(f"\n评分结果（共 {len(scored)} 个 blocks）：")
    for s in [5, 4, 3, 2, 1]:
        g = [(b, ss) for b, sc, ss in scored if sc == s]
        if g:
            label = {5: "core", 4: "important", 3: "normal", 2: "temp", 1: "discard"}[s]
            print(f"  score={s} ({label}): {len(g)} 条")
            for b, ss in g[:3]:
                print(f"    - {b[:80]}")

    to_store = [(b, sc, ss) for b, sc, ss in scored if sc >= 3]
    print(f"\n将存入 {len(to_store)} 条（score>=3）")

    if dry_run:
        print("[dry-run，不写入]")
        return

    if not cfg.get("yes") and input("确认写入？（y/n）: ").strip().lower() != "y":
        print("已取消")
        return

    print("写入 mem0...")
    written = write_blocks(to_store, qdrant_client, API_KEY, agent, collection)
    save_state({"last_distilled_at": datetime.now().isoformat()}, state_file)
    print(f"\n完成！写入 {written} 条")

if __name__ == "__main__":
    main()
