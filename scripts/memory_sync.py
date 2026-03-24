#!/usr/bin/env python3
"""
每日记忆同步脚本 - 快速版
只用关键词判断，快速同步重要对话
"""
import os
import re
import glob
from datetime import datetime, timedelta

if 'OPENAI_API_KEY' not in os.environ:
    raise RuntimeError("请设置环境变量 OPENAI_API_KEY")

os.environ['OPENAI_API_KEY'] = os.environ['OPENAI_API_KEY']
os.environ['OPENAI_BASE_URL'] = os.environ.get('OPENAI_BASE_URL', 'https://api.siliconflow.cn/v1')

from mem0 import Memory

# 根据 AGENT_NAME 动态获取 workspace 路径
def get_workspace_dir():
    agent = os.environ.get('AGENT_NAME', 'main')
    if agent == 'main':
        return '/root/.openclaw/workspace'
    return f'/root/.openclaw/workspace-{agent}'

WORKSPACE_DIR = get_workspace_dir()
MEMORY_DIR = os.path.join(WORKSPACE_DIR, 'memory')

def get_memory():
    agent = os.environ.get('AGENT_NAME', 'main')
    collection = f'mem0_{agent}'
    config = {
        'vector_store': {'provider': 'qdrant', 'config': {'host': 'localhost', 'port': 6333, 'collection_name': collection, 'embedding_model_dims': 1024}},
        'llm': {'provider': 'openai', 'config': {'model': 'Qwen/Qwen2.5-7B-Instruct', 'openai_base_url': 'https://api.siliconflow.cn/v1', 'temperature': 0.1}},
        'embedder': {'provider': 'openai', 'config': {'model': 'BAAI/bge-large-zh-v1.5', 'openai_base_url': 'https://api.siliconflow.cn/v1', 'embedding_dims': 1024}}
    }
    return Memory.from_config(config)

def extract_conversations(filepath: str) -> list:
    """提取对话"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except:
        return []
    
    conversations = []
    
    # 格式1: **User**: xxx \n **Assistant**: xxx
    pattern1 = r'\*\*User\*\*:\s*(.+?)\n\*\*Assistant\*\*:\s*(.+?)(?=\n\*\*User\*\*|\Z)'
    matches1 = re.findall(pattern1, content, re.DOTALL)
    for user_msg, assistant_msg in matches1:
        user_msg = user_msg.strip()
        assistant_msg = assistant_msg.strip()
        if user_msg.startswith('System:'):
            continue
        if user_msg and assistant_msg:
            conversations.append((user_msg[:200], assistant_msg[:200]))
    
    return conversations

KEYWORDS = ['记住', '不要忘记', '我叫', '我喜欢', '我讨厌', '以后都', '记得', '承诺', '保证', '以后每次', '落雁']

def should_save(text: str) -> bool:
    """判断是否应该保存 - 只用关键词"""
    text_lower = text.lower()
    for kw in KEYWORDS:
        if kw in text_lower:
            return True
    return False

def sync_memories(days: int = 7):
    """同步最近N天的记忆"""
    m = get_memory()
    saved_count = 0
    
    all_files = glob.glob(os.path.join(MEMORY_DIR, "*.md"))
    
    md_files = []
    for f in all_files:
        basename = os.path.basename(f)
        if 'archive' in basename or 'MEMORY' in basename or 'USER' in basename or 'heartbeat' in basename:
            continue
        match = re.match(r'(\d{4}-\d{2}-\d{2})', basename)
        if match:
            date_str = match.group(1)
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
                md_files.append((date, f, date_str))
            except:
                pass
    
    md_files.sort(reverse=True)
    md_files = md_files[:days]
    
    for date, filepath, date_str in md_files:
        conversations = extract_conversations(filepath)
        print(f"📄 {date_str}: {len(conversations)} 条")
        
        for user_msg, assistant_msg in conversations:
            if should_save(user_msg):
                try:
                    m.add([{"role": "user", "content": user_msg}, {"role": "assistant", "content": assistant_msg}], user_id=os.environ.get("MEM0_USER_ID", "user"))
                    saved_count += 1
                    print(f"  ✅ {user_msg[:30]}...")
                except Exception as e:
                    print(f"  ❌ {e}")
    
    print(f"\n🎉 共保存 {saved_count} 条")

if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    print(f"🔄 同步最近 {days} 天...")
    sync_memories(days)
