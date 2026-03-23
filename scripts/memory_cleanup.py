#!/usr/bin/env python3
"""
记忆清理脚本 - 定时删除过期记忆
根据分数自动清理：
- score=1 → 30天后删除
- score=2 → 90天后删除
- score=3 → 180天后删除
- score>=4 → 永不过期
"""
import os
import re
from datetime import datetime, timedelta

if 'OPENAI_API_KEY' not in os.environ:
    raise RuntimeError("请设置环境变量 OPENAI_API_KEY")

os.environ['OPENAI_API_KEY'] = os.environ['OPENAI_API_KEY']
os.environ['OPENAI_BASE_URL'] = os.environ.get('OPENAI_BASE_URL', 'https://api.siliconflow.cn/v1')

from mem0 import Memory

def get_memory():
    config = {
        'vector_store': {'provider': 'qdrant', 'config': {'host': 'localhost', 'port': 6333, 'collection_name': 'mem0_main', 'embedding_model_dims': 1024}},
        'llm': {'provider': 'openai', 'config': {'model': 'Qwen/Qwen2.5-7B-Instruct', 'openai_base_url': 'https://api.siliconflow.cn/v1', 'temperature': 0.1}},
        'embedder': {'provider': 'openai', 'config': {'model': 'BAAI/bge-large-zh-v1.5', 'openai_base_url': 'https://api.siliconflow.cn/v1', 'embedding_dims': 1024}}
    }
    return Memory.from_config(config)

def parse_memory_info(text: str) -> dict:
    """解析记忆的分数和类型"""
    # 匹配 [type][score:n] 格式
    match = re.search(r'\[(episodic|semantic|procedural)\]\[score:(\d+)\]', text)
    if match:
        return {'type': match.group(1), 'score': int(match.group(2))}
    # 旧格式没有分数，默认3分
    return {'type': 'unknown', 'score': 3}

def get_score_days(score: int) -> int:
    """根据分数返回保留天数"""
    rules = {
        1: 30,   # 30天
        2: 90,   # 90天
        3: 180,  # 180天
        4: 99999, # 永不过期
        5: 99999,
    }
    return rules.get(score, 99999)

def cleanup_memories(days: int = 30):
    """清理过期记忆"""
    m = get_memory()
    
    # 获取所有记忆
    all_results = m.get_all(user_id="fuge")
    memories = all_results.get("results", [])
    
    if not memories:
        print("没有记忆需要清理")
        return
    
    now = datetime.now()
    delete_count = 0
    keep_count = 0
    
    print(f"🔍 检查 {len(memories)} 条记忆...")
    
    for mem in memories:
        mem_id = mem.get("id")
        text = mem.get("memory", "")
        parsed = parse_memory_info(text)
        score = parsed['score']
        
        # 获取创建时间（如果支持）
        created_at = mem.get("created_at", "")
        if created_at:
            try:
                # Mem0 返回的是 ISO 格式
                created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                age_days = (now - created_date.replace(tzinfo=None)).days
                
                keep_days = get_score_days(score)
                
                if age_days > keep_days:
                    # 删除
                    try:
                        m.delete(memory_id=mem_id, user_id="fuge")
                        delete_count += 1
                        print(f"  🗑️ 删除 [score:{score}] {text[:30]}... ({age_days}天)")
                    except Exception as e:
                        print(f"  ❌ 删除失败: {e}")
                else:
                    keep_count += 1
            except:
                keep_count += 1
        else:
            # 没有创建时间，默认保留
            keep_count += 1
    
    print(f"\n✅ 清理完成！")
    print(f"   保留: {keep_count} 条")
    print(f"   删除: {delete_count} 条")

if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    print(f"🔄 开始清理 {days} 天前的记忆...")
    cleanup_memories(days)
