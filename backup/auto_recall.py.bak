#!/usr/bin/env python3
"""
自动记忆读取模块 - v3.1
支持 rerank 二次排序
"""
import os
import sys
import re

# 配置 API Key（必须设置环境变量）
if 'OPENAI_API_KEY' not in os.environ:
    raise RuntimeError("请设置环境变量 OPENAI_API_KEY")
os.environ['OPENAI_API_KEY'] = os.environ['OPENAI_API_KEY']

os.environ['OPENAI_BASE_URL'] = os.environ.get('OPENAI_BASE_URL', 'https://api.siliconflow.cn/v1')

from mem0 import Memory
from openai import OpenAI

def get_memory(collection_name: str = "mem0_main"):
    config = {
        'vector_store': {'provider': 'qdrant', 'config': {'host': 'localhost', 'port': 6333, 'collection_name': collection_name, 'embedding_model_dims': 1024}},
        'llm': {'provider': 'openai', 'config': {'model': 'Qwen/Qwen2.5-7B-Instruct', 'openai_base_url': 'https://api.siliconflow.cn/v1', 'temperature': 0.1}},
        'embedder': {'provider': 'openai', 'config': {'model': 'BAAI/bge-large-zh-v1.5', 'openai_base_url': 'https://api.siliconflow.cn/v1', 'embedding_dims': 1024}}
    }
    return Memory.from_config(config)

def parse_memory(text: str) -> dict:
    """解析记忆中的类型和分数"""
    match = re.search(r'\[(episodic|semantic|procedural)\]\[score:(\d+)\]', text)
    if match:
        return {'type': match.group(1), 'score': int(match.group(2)), 'clean_text': re.sub(r'\[.*?\]', '', text)}
    return {'type': 'unknown', 'score': 3, 'clean_text': text}

def rerank_memories(query: str, memories: list) -> list:
    """用 LLM 对记忆进行二次排序"""
    if not memories or len(memories) <= 1:
        return memories
    
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], base_url='https://api.siliconflow.cn/v1')
    
    # 构建选项
    options = []
    for i, mem in enumerate(memories):
        parsed = parse_memory(mem.get('memory', ''))
        options.append(f"{i+1}. {parsed['clean_text']}")
    
    options_text = "\n".join(options)
    
    prompt = f"""用户问题是："{query}"

以下是搜索到的相关记忆，请按与问题的相关性排序（最相关的放最前面）：

{options_text}

请按顺序输出编号，用逗号分隔。例如：1,3,2

只需要输出编号。"""
    
    try:
        response = client.chat.completions.create(
            model='Qwen/Qwen2.5-7B-Instruct',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.1
        )
        
        # 解析返回的排序
        result = response.choices[0].message.content.strip()
        # 提取数字
        order = [int(c) for c in result.split(',') if c.strip().isdigit()]
        
        if order and len(order) == len(memories):
            # 重新排序
            reranked = []
            for idx in order:
                if 1 <= idx <= len(memories):
                    reranked.append(memories[idx-1])
            return reranked
    except:
        pass
    
    return memories  # 如果失败，返回原顺序

def auto_recall(query: str, min_score: int = 2, mem_type: str = None, use_rerank: bool = True) -> str:
    """
    自动检索记忆（带 rerank）
    """
    agent = os.environ.get('AGENT_NAME', 'main')
    collection = f'mem0_{agent}'
    m = get_memory(collection)
    results = m.search(query=query, user_id="fuge", limit=5)
    
    memories = results.get("results", [])
    if not memories:
        return ""
    
    # 预处理：解析分数和类型
    parsed_memories = []
    for mem in memories:
        raw = mem.get("memory", "")
        parsed = parse_memory(raw)
        
        # 分数过滤
        if parsed['score'] < min_score:
            continue
        # 类型过滤
        if mem_type and parsed['type'] != mem_type:
            continue
        
        parsed_memories.append(mem)
    
    if not parsed_memories:
        return ""
    
    # Rerank 二次排序
    if use_rerank and len(parsed_memories) > 1:
        parsed_memories = rerank_memories(query, parsed_memories)
    
    # 格式化输出
    lines = ["\n## 📝 相关记忆:"]
    for mem in parsed_memories:
        raw = mem.get("memory", "")
        parsed = parse_memory(raw)
        lines.append(f"- [{parsed['type']}][score:{parsed['score']}] {parsed['clean_text']}")
    
    return '\n'.join(lines)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: auto_recall.py <用户消息>")
        sys.exit(1)
    
    query = sys.argv[1]
    context = auto_recall(query)
    if context:
        print(context)
    else:
        print("未找到相关记忆")
