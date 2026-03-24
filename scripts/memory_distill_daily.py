#!/usr/bin/env python3
"""
每日精炼脚本
读取 session 文件 → LLM 蒸馏 → 评分 → 存入 mem0_main（仅 score >= 3）

用法：
    python3 memory_distill_daily.py [--days N] [--dry-run] [--force]
"""
import os, sys, re, time, json, argparse
from datetime import datetime, timedelta
from pathlib import Path

# ========== 配置 ==========
SESSIONS_DIR = "/root/.openclaw/agents/main/sessions"
COLLECTION = "mem0_main"
STATE_FILE = "/root/.openclaw/workspace/.distill_state.json"
STAGING_FILE = "/root/.openclaw/workspace/.pending_conversations.jsonl"
# =========================

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_distilled_at": None}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def get_session_files(since_dt: datetime):
    """获取指定时间之后修改过的 session 文件"""
    files = []
    sessions_path = Path(SESSIONS_DIR)
    if not sessions_path.exists():
        return files
    for f in sessions_path.glob("*.jsonl"):
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime > since_dt:
            files.append(f)
    return files

def read_sessions(files):
    """读取所有 session 文件，返回原始对话文本列表"""
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
                            content = " ".join(
                                c.get("text", "") for c in content if c.get("type") == "text"
                            )
                        if role in ("user", "assistant") and content.strip():
                            # 提纯：去掉 System: / Conversation info 等元数据
                            clean = extract_user_content(content) if role == "user" else content.strip()
                            if clean and len(clean) > 5:
                                conversations.append({
                                    "session": f.name,
                                    "role": role,
                                    "content": clean[:500]
                                })
                except:
                    pass
    return conversations

def extract_user_content(text: str) -> str:
    """从 Feishu 格式的 user 消息中提取真实内容"""
    if text.startswith("System:"):
        m = re.search(r"Sender \(untrusted metadata\):[\s\S]+?\n\n([\s\S]+)$", text)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return text.strip()

def distill_conversations(conversations, llm_client) -> list:
    """调用 LLM 将对话蒸馏成独立的记忆 block，返回 (block_text, session_info) 列表"""
    if not conversations:
        return []

    # 收集所有 session 文件
    unique_sessions = list(set(c["session"] for c in conversations))
    session_list = ", ".join(unique_sessions)

    # 构造输入文本
    lines = []
    for i, c in enumerate(conversations):
        prefix = "User" if c["role"] == "user" else "Assistant"
        lines.append(f"[{i+1}] [{c['session']}] {prefix}: {c['content']}")

    block_list = "\n".join(lines)
    prompt = f"""你是记忆整理助手。以下是一段时间内的对话记录，涉及 session 文件：{session_list}

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
        print(f"  LLM 生成了 {len(blocks)} 个 blocks")
        # 所有 block 都关联所有 session 文件（简化处理）
        return [(b.strip(), unique_sessions) for b in blocks]
    except Exception as e:
        print(f"  LLM 错误: {e}")
        return []

def score_blocks(blocks_with_sessions, llm_client) -> list:
    """对每个 block 评分，返回 (block_text, score, sessions) 列表"""
    if not blocks_with_sessions:
        return []

    block_text = "\n".join([f"{i+1}. {b}" for i, (b, sess) in enumerate(blocks_with_sessions)])

    prompt = f"""以下是从对话中提炼的记忆 block，请对每个评分：

{block_text}

评分标准：
- 5分：核心事实，必须记住（重要决策、承诺、名字、身份）
- 4分：重要信息，值得保留（偏好、习惯、重要事件）
- 3分：一般信息，可以保留（日常讨论、有参考价值的内容）
- 2分：临时信息，不值得单独保留
- 1分：无价值信息

格式（每行一个block）：
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
                score_str = parts[0].strip()
                block_text = parts[1].strip()
                try:
                    score = int(score_str)
                    # 匹配回 sessions（用索引）
                    idx = len(scored)
                    sessions = blocks_with_sessions[idx][1] if idx < len(blocks_with_sessions) else []
                    scored.append((block_text, score, sessions))
                except:
                    pass
        print(f"  评分了 {len(scored)} 个 blocks")
        return scored
    except Exception as e:
        print(f"  评分 LLM 错误: {e}")
        return []

def determine_type(block_text: str, llm_client) -> str:
    """判断 block 类型"""
    prompt = f"""判断以下记忆属于哪种类型：

{block_text}

类型：
- episodic：事件、做过的事、发生过的事
- semantic：事实、偏好、习惯、关系、身份
- procedural：步骤、流程、方法、教程

只回复一个词：episodic、semantic 或 procedural。"""

    try:
        resp = llm_client.chat.completions.create(
            model="Qwen/Qwen2.5-7B-Instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        text = resp.choices[0].message.content.strip().lower()
        if "episodic" in text:
            return "episodic"
        elif "procedural" in text:
            return "procedural"
        else:
            return "semantic"
    except:
        return "semantic"

def write_to_mem0(blocks_with_scores, m, min_score=3):
    """将评分合格的 blocks 写入 mem0"""
    written = 0
    for block_text, score, sessions in blocks_with_scores:
        if score < min_score:
            print(f"  跳过(score={score}): {block_text[:50]}...")
            continue

        # 判断类型
        mem_type = determine_type(content, llm_client=None)  # 暂不调LLM，用默认值
        # 用简单的关键词判断
        content_lower = content.lower()
        if any(k in content_lower for k in ["流程", "步骤", "方法", "如何", "先", "然后"]):
            mem_type = "procedural"
        elif any(k in content_lower for k in ["今天", "昨天", "讨论", "开会", "做了", "完成"]):
            mem_type = "episodic"
        else:
            mem_type = "semantic"

        # session 文件路径
        session_files = ", ".join([f"/root/.openclaw/agents/main/sessions/{s}" for s in sessions])
        record = f"[{mem_type}][score:{score}][distilled][sessions:{len(sessions)}][files:{session_files}]\n{block_text}"
        try:
            m.add([{"role": "user", "content": record}], user_id="fuge", agent_id="main", infer=True)
            print(f"  ✅ [{mem_type}][score:{score}] {block_text[:60]}...")
            written += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ 写入失败: {e}")

    return written

def main():
    parser = argparse.ArgumentParser(description="每日记忆精炼")
    parser.add_argument("--days", type=int, default=1, help="处理最近多少天的 session（默认1）")
    parser.add_argument("--dry-run", action="store_true", help="只蒸馏，不写入")
    parser.add_argument("--force", action="store_true", help="不管上次蒸馏时间，强制全量处理")
    args = parser.parse_args()

    # 初始化
    os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "")
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: 请设置 OPENAI_API_KEY 环境变量")
        print('ERROR'); sys.exit(1)

    from qdrant_client import QdrantClient
    from openai import OpenAI
    from mem0 import Memory

    API_KEY = os.environ["OPENAI_API_KEY"]
    BASE_URL = "https://api.siliconflow.cn/v1"

    client_llm = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    m = Memory.from_config({
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "host": "localhost", "port": 6333,
                "collection_name": COLLECTION,
                "embedding_model_dims": 1024
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

    # 确定处理范围
    state = load_state()
    if args.force or not state["last_distilled_at"]:
        since_dt = datetime.now() - timedelta(days=args.days)
        print(f"强制模式 / 首次运行，处理最近 {args.days} 天")
    else:
        last = datetime.fromisoformat(state["last_distilled_at"])
        since_dt = last
        print(f"上次蒸馏: {last.strftime('%Y-%m-%d %H:%M')}，处理此后新增的 session")

    # 从 session 文件读取（根据上次蒸馏时间过滤）
    print("📖 读取 session 文件...")
    files = get_session_files(since_dt)
    print(f"  找到 {len(files)} 个 session 文件")

    if not files:
        print("  没有新的 session 文件，退出")
        return

    # 读取对话
    print("📝 提取对话内容...")
    conversations = read_sessions(files)
    print(f"  提取了 {len(conversations)} 条对话片段")

    if not conversations:
        print("没有对话内容，退出")
        return

    # 蒸馏
    print("🔮 开始蒸馏...")
    blocks_with_sessions = distill_conversations(conversations, client_llm)

    if not blocks_with_sessions:
        print("蒸馏失败或无输出")
        return

    # 评分
    print("📊 开始评分...")
    scored = score_blocks(blocks_with_sessions, client_llm)

    if not scored:
        print("评分失败或无输出")
        return

    # 预览
    print(f"\n📋 评分结果（共 {len(scored)} 个 blocks）：")
    score_groups = {5: [], 4: [], 3: [], 2: [], 1: []}
    for block_text, score, sessions in scored:
        score_groups[score].append((block_text, sessions))

    for s in [5, 4, 3, 2, 1]:
        if score_groups[s]:
            label = {5: "🔴核心", 4: "🟠重要", 3: "🟡一般", 2: "🟢临时", 1: "⚪无价值"}[s]
            print(f"\n  {label} (score={s})，共 {len(score_groups[s])} 条：")
            for c in score_groups[s][:5]:
                block_text, sessions = c
                print(f"    - {block_text[:80]}...")
                print(f"      📁 {len(sessions)} session(s): {", ".join(sessions[:2])}{" ..." if len(sessions)>2 else ""}")
            if len(score_groups[s]) > 5:
                print(f"    ... 还有 {len(score_groups[s])-5} 条")

    to_store = [(b, s, sess) for b, s, sess in scored if s >= 3]
    print(f"\n将存入 {len(to_store)} 条（score >= 3）")

    if args.dry_run:
        print("\n[dry-run 模式，不写入]")
        return

    # 确认写入
    confirm = input("\n确认写入 mem0？（y/n）: ").strip().lower()
    if confirm != "y":
        print("已取消")
        return

    # 写入
    print("\n💾 写入 mem0...")
    written = write_to_mem0(to_store, m, min_score=3)

    # 更新状态
    save_state({"last_distilled_at": datetime.now().isoformat()})

    # 清空暂存文件
    import subprocess
    try:
        result = subprocess.run(
            ["python3", "/root/.openclaw/workspace/scripts/sync_to_mem0.py", "--flush"],
            capture_output=True, text=True
        )
        print(f"  暂存文件已清空")
    except:
        pass

    print(f"\n🎉 完成！写入 {written} 条记忆")

if __name__ == "__main__":
    main()
