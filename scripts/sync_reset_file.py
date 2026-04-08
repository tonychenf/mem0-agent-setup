#!/usr/bin/env python3
"""
sync_reset_file.py - 处理 .reset 文件的完整对话同步
直接重建 user→assistant 对话对，包含 toolResult 填充
"""
import os, sys, re, json, subprocess

SESSIONS_DIR = "/root/.openclaw/agents/main/sessions"
SYNC_SCRIPT = "/root/.openclaw/mem0-agent-setup/scripts/sync_to_mem0.py"


def extract_user_content(text):
    """从 System: 包装中提取真实用户消息"""
    if not text.startswith("System:"):
        return text.strip()
    m = re.search(r'Sender \(untrusted metadata\)[\s\S]+?\n\n([\s\S]+)$', text)
    if m and m.group(1) and m.group(1).strip():
        return m.group(1).strip()
    return text.strip()


def build_messages_from_reset(filepath):
    """
    从 .reset 文件重建完整对话对。
    处理模式: user → assistant(空) → toolResult → ... → assistant(有内容)
    """
    messages = []
    current_user = None
    pending_tool_results = []

    with open(filepath, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except:
                continue
            if obj.get("type") != "message":
                continue

            msg = obj.get("message", {})
            role = msg.get("role", "")
            content_arr = msg.get("content", [])

            text = ""
            if isinstance(content_arr, list):
                for c in content_arr:
                    if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip():
                        text = c.get("text", "").strip()
                        break

            if role == "user" and len(text) > 20:
                # 有前置 user 未完成，先 flush
                if current_user and pending_tool_results:
                    assistant_text = "\n".join(pending_tool_results)
                    if len(assistant_text) > 5:
                        messages.append({
                            "user": current_user[:500],
                            "assistant": assistant_text[:500]
                        })
                # 提取用户消息
                user_text = extract_user_content(text)
                if len(user_text) >= 5:
                    current_user = user_text
                pending_tool_results = []

            elif role == "assistant" and current_user:
                if len(text) > 0:
                    # 普通 assistant 回复
                    messages.append({
                        "user": current_user[:500],
                        "assistant": text[:500]
                    })
                    current_user = None
                    pending_tool_results = []
                # 空 assistant：等 toolResult

            elif role == "toolResult" and current_user and len(text) > 5:
                pending_tool_results.append(text[:500])

    # 最后一条
    if current_user and pending_tool_results:
        assistant_text = "\n".join(pending_tool_results)
        messages.append({
            "user": current_user[:500],
            "assistant": assistant_text[:500]
        })

    # 过滤
    valid = [m for m in messages if
             len(m["user"]) >= 5 and
             not m["user"].startswith("System:") and
             not m["user"].startswith("Read HEARTBEAT") and
             len(m["assistant"]) > 5]
    return valid


def sync_to_mem0(messages, agent="main"):
    """调用 sync_to_mem0.py 同步消息"""
    if not messages:
        return 0
    # 优先用 .env 里的 API key（如果 shell 环境是假的）
    env = os.environ.copy()
    env["AGENT_NAME"] = agent
    env_path = "/root/.openclaw/mem0-agent-setup/.env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    result = subprocess.run(
        ["python3", SYNC_SCRIPT],
        input=json.dumps(messages),
        capture_output=True,
        text=True,
        env=env,
        timeout=120
    )
    if result.stdout and "DONE:" in result.stdout:
        return int(result.stdout.split("DONE:")[1].strip())
    if result.stderr:
        print(f"sync stderr: {result.stderr[:200]}", file=sys.stderr)
    return 0


def main():
    agent = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AGENT_NAME", "main")
    sessions_dir = f"/root/.openclaw/agents/{agent}/sessions"

    # 找最近 7 天内修改的 .reset 文件
    import time
    from pathlib import Path
    cutoff = time.time() - 7 * 86400
    reset_files = []
    p = Path(sessions_dir)
    for f in p.glob("*.reset.*"):
        try:
            if f.stat().st_mtime >= cutoff:
                reset_files.append(str(f))
        except:
            pass

    total_synced = 0
    for filepath in sorted(reset_files, key=lambda f: -Path(f).stat().st_mtime):
        messages = build_messages_from_reset(filepath)
        if not messages:
            print(f"[{agent}] {os.path.basename(filepath)}: 0 pairs")
            continue
        count = sync_to_mem0(messages, agent)
        fname = os.path.basename(filepath)
        print(f"[{agent}] {fname}: {count} pairs synced")
        total_synced += count

    print(f"Total: {total_synced} pairs synced from {len(reset_files)} .reset files")


if __name__ == "__main__":
    main()
