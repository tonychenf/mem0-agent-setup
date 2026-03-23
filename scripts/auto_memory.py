#!/usr/bin/env python3
"""
自动记忆模块 - v3.0
关键词 + LLM 双重触发 + 重要性评分
"""
import os
import sys
import json
from datetime import datetime

if 'OPENAI_API_KEY' not in os.environ:
    raise RuntimeError("请设置环境变量 OPENAI_API_KEY")

os.environ['OPENAI_API_KEY'] = os.environ['OPENAI_API_KEY']
os.environ['OPENAI_BASE_URL'] = os.environ.get('OPENAI_BASE_URL', 'https://api.siliconflow.cn/v1')

# 关键词列表
KEYWORDS = [
    '记住', '不要忘记', '别忘了', '以后都', '每次都',
    '我叫', '我喜欢', '我讨厌', '我的名字', '以后都',
    '记得', '承诺', '保证', '以后每次', '落雁'
]

def contains_keyword(text: str) -> bool:
    text = text.lower()
    for kw in KEYWORDS:
        if kw in text:
            return True
    return False

def classify_memory(user_msg: str) -> str:
    """分类记忆为 episodic / semantic / procedural"""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], base_url='https://api.siliconflow.cn/v1')
    
    prompt = f"""判断以下用户消息属于哪种记忆类型：

- episodic: 事件记忆（今天做的事、说的话、临时信息）
- semantic: 语义记忆（偏好、习惯、关系、知识）
- procedural: 程序记忆（技能、操作步骤、方法）

用户消息："{user_msg}"

只需要回答类型名称。"""
    
    response = client.chat.completions.create(
        model='Qwen/Qwen2.5-7B-Instruct',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.1
    )
    
    result = response.choices[0].message.content.strip().lower()
    if 'episodic' in result:
        return 'episodic'
    elif 'semantic' in result:
        return 'semantic'
    elif 'procedural' in result:
        return 'procedural'
    return 'episodic'  # 默认

def score_memory(user_msg: str) -> int:
    """给记忆打分 1-5 分"""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], base_url='https://api.siliconflow.cn/v1')
    
    prompt = f"""判断以下用户消息的重要程度，打分 1-5：

5分: 核心信息（名字、身份、关系、承诺、重大决定）
4分: 重要偏好（喜欢什么、讨厌什么、重要习惯）
3分: 一般信息（日常对话、一般事项）
2分: 临时信息（随手提到的一次性内容）
1分: 无价值（客套话、问候、无关内容）

用户消息："{user_msg}"

只需要回答数字。"""
    
    response = client.chat.completions.create(
        model='Qwen/Qwen2.5-7B-Instruct',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.1
    )
    
    result = response.choices[0].message.content.strip()
    # 提取数字
    for c in result:
        if c.isdigit():
            score = int(c)
            if 1 <= score <= 5:
                return score
    return 3  # 默认3分

def should_remember(user_msg: str) -> bool:
    """LLM 判断是否需要记忆"""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], base_url='https://api.siliconflow.cn/v1')
    
    prompt = f"""判断以下用户消息是否包含重要信息需要记忆：
"{user_msg}"

重要类型：名字、偏好、情绪、计划、约定、身份信息。

回答"是"或"否"."""
    
    response = client.chat.completions.create(
        model='Qwen/Qwen2.5-7B-Instruct',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.1
    )
    return '是' in response.choices[0].message.content

def should_save(user_msg: str) -> bool:
    """最终判断：关键词 或 LLM"""
    if contains_keyword(user_msg):
        return True
    return should_remember(user_msg)

def add_memory(user_msg: str, assistant_msg: str):
    """添加记忆到 Mem0（带评分和分类）"""
    from mem0 import Memory
    
    config = {
        'vector_store': {'provider': 'qdrant', 'config': {'host': 'localhost', 'port': 6333, 'collection_name': 'mem0_main', 'embedding_model_dims': 1024}},
        'llm': {'provider': 'openai', 'config': {'model': 'Qwen/Qwen2.5-7B-Instruct', 'openai_base_url': 'https://api.siliconflow.cn/v1', 'temperature': 0.1}},
        'embedder': {'provider': 'openai', 'config': {'model': 'BAAI/bge-large-zh-v1.5', 'openai_base_url': 'https://api.siliconflow.cn/v1', 'embedding_dims': 1024}}
    }
    
    m = Memory.from_config(config)
    
    # 评分和分类
    score = score_memory(user_msg)
    mem_type = classify_memory(user_msg)
    
    # 组合消息 + 元数据
    full_content = f"[{mem_type}][score:{score}] {user_msg}"
    
    messages = [
        {"role": "user", "content": full_content},
        {"role": "assistant", "content": assistant_msg}
    ]
    
    result = m.add(messages, user_id="fuge")
    return {'score': score, 'type': mem_type, 'result': result}

def auto_save(user_msg: str, assistant_msg: str):
    """自动保存流程"""
    if should_save(user_msg):
        info = add_memory(user_msg, assistant_msg)
        return info
    return None

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        user_msg = sys.argv[1]
        assistant_msg = sys.argv[2]
        result = auto_save(user_msg, assistant_msg)
        if result:
            print(f"✅ 已保存 [{result['type']}][score:{result['score']}]: {user_msg[:30]}...")
        else:
            print(f"⏭️ 无需保存")
    else:
        print("用法: auto_memory.py <用户消息> <助手回复>")
