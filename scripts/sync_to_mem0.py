#!/usr/bin/env python3
"""
同步对话到 Mem0 向量库
"""
import os
import sys
import json
import yaml

# 从配置文件读取配置
CONFIG_FILE = os.environ.get('MEM0_CONFIG_FILE', '/root/.openclaw/workspace/config.yaml')

def load_config():
    """从配置文件加载配置"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f)
    return {}

def get_config():
    """获取配置"""
    config = load_config()
    
    llm_config = config.get('llm', {})
    embedding_config = config.get('embedding', {})
    qdrant_config = config.get('qdrant', {})
    agent_config = config.get('agent', {})
    
    return {
        'api_key': llm_config.get('api_key', os.environ.get('OPENAI_API_KEY', '')),
        'api_base_url': llm_config.get('api_base_url', 'https://api.siliconflow.cn/v1'),
        'model': llm_config.get('model', 'Qwen/Qwen2.5-7B-Instruct'),
        'embedding_model': embedding_config.get('model', 'BAAI/bge-large-zh-v1.5'),
        'embedding_dims': embedding_config.get('dimensions', 1024),
        'qdrant_host': qdrant_config.get('host', 'localhost'),
        'qdrant_port': qdrant_config.get('port', 6333),
        'collection': agent_config.get('collection', 'mem0_main'),
        'user_id': agent_config.get('user_id', 'user'),
        'agent_id': agent_config.get('id', 'main'),
    }

cfg = get_config()
os.environ['OPENAI_API_KEY'] = cfg['api_key']

from mem0 import Memory

def main():
    # 从 stdin 读取消息列表
    messages_json = sys.stdin.read().strip()
    
    if not messages_json:
        print("ERROR: No messages provided")
        return
    
    try:
        messages = json.loads(messages_json)
    except Exception as e:
        print(f"ERROR: Invalid JSON - {e}")
        return
    
    config = {
        'vector_store': {
            'provider': 'qdrant', 
            'config': {'host': cfg['qdrant_host'], 'port': cfg['qdrant_port'], 'collection_name': cfg['collection']}
        },
        'llm': {
            'provider': 'openai', 
            'config': {'model': cfg['model'], 'openai_base_url': cfg['api_base_url'], 'temperature': 0.1}
        },
        'embedder': {
            'provider': 'openai', 
            'config': {'model': cfg['embedding_model'], 'openai_base_url': cfg['api_base_url'], 'embedding_dims': cfg['embedding_dims']}
        }
    }
    
    m = Memory.from_config(config)
    
    imported = 0
    for msg in messages[:10]:  # 最多10条
        try:
            user = msg.get('user', '')[:500]
            assistant = msg.get('assistant', '')[:500]
            
            # 过滤掉系统消息和太短的消息
            if len(user) >= 20 and not user.startswith('System:') and not user.startswith('Conversation info') and not user.startswith('Read HEARTBEAT'):
                m.add(
                    [{'role': 'user', 'content': user}, {'role': 'assistant', 'content': assistant}],
                    user_id=cfg['user_id'],
                    agent_id=cfg['agent_id'],
                    infer=False
                )
                imported += 1
        except Exception as e:
            pass
    
    print(f"DONE:{imported}")

if __name__ == '__main__':
    main()
