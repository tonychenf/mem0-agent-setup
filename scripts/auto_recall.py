#!/usr/bin/env python3
"""
Mem0 Auto-Recall - 自动记忆读取脚本
在每次回复前自动检索相关记忆

使用方法（在 SOUL.md/AGENTS.md 中引用）:
    # 在回复前运行此脚本
    python3 /root/.openclaw/project/mem0-agent-setup/scripts/auto_recall.py "用户消息"
"""

import os
import sys
import json

# 配置 API Key
os.environ['OPENAI_API_KEY'] = 'REMOVED_API_KEY'

try:
    from mem0 import Memory
except ImportError:
    print("ERROR: mem0 未安装")
    sys.exit(1)

def get_memory(collection_name: str = "mem0_main"):
    """获取指定 Agent 的记忆实例"""
    config = {
        'vector_store': {
            'config': {
                'collection_name': collection_name,
                'embedding_model_dims': 1024
            }
        },
        'llm': {
            'provider': 'openai',
            'config': {
                'model': 'Qwen/Qwen2.5-7B-Instruct',
                'openai_base_url': 'https://api.siliconflow.cn/v1',
                'temperature': 0.1
            }
        },
        'embedder': {
            'provider': 'openai',
            'config': {
                'model': 'BAAI/bge-large-zh-v1.5',
                'openai_base_url': 'https://api.siliconflow.cn/v1',
                'embedding_dims': 1024
            }
        }
    }
    return Memory.from_config(config)

def auto_recall(query: str, collection: str = "mem0_main", agent_id: str = "main") -> list:
    """
    自动检索记忆
    
    Args:
        query: 用户消息（用于搜索相关记忆）
        collection: 记忆集合名（默认 mem0_main）
        agent_id: Agent ID（用于隔离记忆）
    
    Returns:
        记忆列表，每条包含 memory 和 score
    """
    m = get_memory(collection)
    results = m.search(
        query=query,
        user_id="fuge",  # 固定用户
        agent_id=agent_id,
        limit=3  # 最多返回3条最相关的
    )
    return results.get("results", [])

def format_memories_for_context(memories: list) -> str:
    """把记忆格式化为上下文提示"""
    if not memories:
        return ""
    
    lines = ["\n## 📝 相关记忆:"]
    for i, mem in enumerate(memories, 1):
        score = mem.get("score", 0)
        memory = mem.get("memory", "")
        lines.append(f"{i}. {memory} (相关度: {score:.2f})")
    
    return '\n'.join(lines)

def main():
    if len(sys.argv) < 2:
        print("用法: auto_recall.py <用户消息> [agent_id]")
        print("示例: auto_recall.py '我今天心情不好' main")
        sys.exit(1)
    
    query = sys.argv[1]
    agent_id = sys.argv[2] if len(sys.argv) > 2 else "main"
    
    # 根据 agent_id 确定 collection
    collection = f"mem0_{agent_id}"
    
    memories = auto_recall(query, collection, agent_id)
    
    if memories:
        context = format_memories_for_context(memories)
        print(context)
    else:
        print("未找到相关记忆")

if __name__ == "__main__":
    main()
