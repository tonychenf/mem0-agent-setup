#!/usr/bin/env python3
"""
auto_recall - 自动记忆读取（v4）
搜索记忆 + 自动加载 session 上下文
"""
import os, sys, re, json
from pathlib import Path

API_KEY = os.environ.get("OPENAI_API_KEY", "")
if not API_KEY:
    raise RuntimeError("请设置 OPENAI_API_KEY 环境变量")

BASE_URL = "https://api.siliconflow.cn/v1"
os.environ["OPENAI_BASE_URL"] = BASE_URL

from mem0 import Memory
from openai import OpenAI

def get_mem0(collection="mem0_main"):
    return Memory.from_config({
        "vector_store": {"provider": "qdrant", "config": {
            "host": "localhost", "port": 6333,
            "collection_name": collection,
            "embedding_model_dims": 1024}},
        "llm": {"provider": "openai", "config": {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "openai_base_url": BASE_URL, "temperature": 0.1}},
        "embedder": {"provider": "openai", "config": {
            "model": "BAAI/bge-large-zh-v1.5",
            "openai_base_url": BASE_URL, "embedding_dims": 1024}}
    })

def parse_memory(text):
    """解析记忆：提取类型、分数、文件路径、纯文本"""
    type_m = re.search(r'\[(episodic|semantic|procedural)\]', text)
    score_m = re.search(r'\[score:(\d+)\]', text)
    files_m = re.search(r'\[files:([^\]]+)\]', text)

    type_ = type_m.group(1) if type_m else "unknown"
    score = int(score_m.group(1)) if score_m else 3
    files = [f.strip() for f in files_m.group(1).split(",")] if files_m else []

    # 循环去掉所有 [xxx] 前缀
    clean = text
    while True:
        stripped = re.sub(r'^\[[^\]]+\]\s*', '', clean)
        if stripped == clean:
            break
        clean = stripped

    return {
        "type": type_,
        "score": score,
        "clean_text": clean.strip(),
        "files": files
    }

def extract_user_content(text):
    if text.startswith("System:"):
        m = re.search(r'Sender \(untrusted metadata\):[\s\S]+?\n\n([\s\S]+)$', text)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return text.strip()

def lookup_session(filepath, keyword, max_snippets=4):
    """在 session 文件中搜索相关片段"""
    snippets = []
    if not os.path.exists(filepath):
        return snippets

    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") != "message":
                        continue
                    msg = obj.get("message", {})
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(c.get("text", "") for c in content if c.get("type") == "text")

                    if role in ("user", "assistant") and content.strip():
                        clean = extract_user_content(content) if role == "user" else content.strip()
                        if keyword.lower() in clean.lower():
                            prefix = "🧑" if role == "user" else "🤖"
                            snippets.append(f"{prefix} {clean[:300]}")
                            if len(snippets) >= max_snippets:
                                return snippets
                except:
                    pass
    except:
        pass
    return snippets

def get_session_context(parsed):
    """为记忆块加载 session 上下文"""
    if not parsed["files"]:
        return ""

    parts = []
    for filepath in parsed["files"][:2]:  # 最多2个文件
        fname = os.path.basename(filepath)
        snippets = lookup_session(filepath, parsed["clean_text"][:20], max_snippets=3)
        if snippets:
            parts.append(f"📄 {fname}:")
            for s in snippets:
                parts.append(f"   {s}")
    return "\n".join(parts) if parts else ""

def rerank(query, memories):
    if len(memories) <= 1:
        return memories
    options = "\n".join([f"{i+1}. {parse_memory(m.get('memory',''))['clean_text']}" for i, m in enumerate(memories)])
    prompt = f'用户问题："{query}"\n\n以下是相关记忆，按相关性排序（最相关的在前）：\n{options}\n\n只输出编号，用逗号分隔，如：1,3,2'
    try:
        client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        resp = client.chat.completions.create(model="Qwen/Qwen2.5-7B-Instruct", messages=[{"role": "user", "content": prompt}], temperature=0.1)
        result = resp.choices[0].message.content.strip()
        order = [int(x) for x in result.split(",") if x.strip().isdigit()]
        if order and len(order) == len(memories):
            reranked = []
            for idx in order:
                if 1 <= idx <= len(memories):
                    reranked.append(memories[idx-1])
            return reranked
    except:
        pass
    return memories

def auto_recall(query, min_score=2):
    """主函数：搜索记忆，自动加载 session 上下文"""
    agent = os.environ.get("AGENT_NAME", "main")
    m = get_mem0(f"mem0_{agent}")
    results = m.search(query=query, user_id=os.environ.get("MEM0_USER_ID", "user"), limit=5)
    memories = results.get("results", [])
    if not memories:
        return ""

    # 过滤 + 解析
    parsed = []
    for mem in memories:
        p = parse_memory(mem.get("memory", ""))
        if p["score"] >= min_score:
            parsed.append({"raw": mem.get("memory", ""), "parsed": p})

    if not parsed:
        return ""

    # Rerank
    if len(parsed) > 1:
        raw_memories = [{"memory": p["raw"]} for p in parsed]
        reranked_raw = rerank(query, raw_memories)
        reranked = []
        for rm in reranked_raw:
            for p in parsed:
                if p["raw"] == rm["memory"]:
                    reranked.append(p)
                    break
        parsed = reranked

    # 格式化输出
    type_icon = {"episodic": "📅", "semantic": "🧠", "procedural": "⚙️", "unknown": "❓"}
    lines = ["\n## 📝 相关记忆:"]
    for p in parsed:
        icon = type_icon.get(p["parsed"]["type"], "❓")
        text = p["parsed"]["clean_text"]
        score = p["parsed"]["score"]
        lines.append(f"- {icon}[score={score}] {text}")

        # 自动加载 session 上下文
        ctx = get_session_context(p["parsed"])
        if ctx:
            # 只显示文件信息，不重复内容
            files_info = ", ".join([os.path.basename(f) for f in p["parsed"]["files"][:2]])
            lines.append(f"  └ 📁 {files_info}")
            lines.append(f"     {ctx.split(chr(10))[0]}")
            lines.append(f"     {' | '.join(ctx.split(chr(10))[1:4])}")

    return "\n".join(lines)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: auto_recall.py <查询内容>")
        sys.exit(1)
    result = auto_recall(sys.argv[1])
    if result:
        print(result)
    else:
        print("未找到相关记忆")
