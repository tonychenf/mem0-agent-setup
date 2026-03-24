#!/usr/bin/env python3
"""
Mem0 Agent 命令行工具
"""
import argparse
import os
import sys
import yaml
import subprocess

CONFIG_FILE = "/root/.openclaw/workspace/config.yaml"

def load_config():
    """加载配置文件"""
    if not os.path.exists(CONFIG_FILE):
        print(f"配置文件不存在: {CONFIG_FILE}")
        print("请复制 config/config.yaml.example 为 config.yaml")
        sys.exit(1)
    
    with open(CONFIG_FILE, 'r') as f:
        return yaml.safe_load(f)

def cmd_status(args):
    """查看状态"""
    config = load_config()
    agent_id = config.get('agent', {}).get('id', 'main')
    
    # 检查 systemd 服务
    result = subprocess.run(
        ['systemctl', 'status', f'openclaw-session-watch'],
        capture_output=True
    )
    
    if result.returncode == 0:
        print(f"✅ 服务运行中 (Agent: {agent_id})")
        subprocess.run(['systemctl', 'status', f'openclaw-session-watch', '--no-pager'])
    else:
        print(f"❌ 服务未运行 (Agent: {agent_id})")

def cmd_start(args):
    """启动服务"""
    subprocess.run(['systemctl', 'start', 'openclaw-session-watch'])
    print("✅ 服务已启动")

def cmd_stop(args):
    """停止服务"""
    subprocess.run(['systemctl', 'stop', 'openclaw-session-watch'])
    print("✅ 服务已停止")

def cmd_restart(args):
    """重启服务"""
    subprocess.run(['systemctl', 'restart', 'openclaw-session-watch'])
    print("✅ 服务已重启")

def cmd_logs(args):
    """查看日志"""
    lines = args.lines if hasattr(args, 'lines') else 50
    subprocess.run(['journalctl', '-u', 'openclaw-session-watch', '-n', str(lines), '-f'])

def cmd_stats(args):
    """查看记忆统计"""
    config = load_config()
    qdrant = config.get('qdrant', {})
    collection = config.get('agent', {}).get('collection', 'mem0_main')
    host = qdrant.get('host', 'localhost')
    port = qdrant.get('port', 6333)
    
    import urllib.request
    import json
    
    try:
        url = f"http://{host}:{port}/collections/{collection}"
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read())
            count = data.get('result', {}).get('points_count', 0)
            print(f"📊 记忆数量: {count} 条")
    except Exception as e:
        print(f"❌ 查询失败: {e}")

def cmd_search(args):
    """搜索记忆"""
    config = load_config()
    
    # 优先使用环境变量，其次使用配置文件（支持 ${OPENAI_API_KEY} 占位符）
    cfg_key = config.get('llm', {}).get('api_key', '')
    if cfg_key and cfg_key.startswith('${') and cfg_key.endswith('}'):
        # 占位符格式 ${VAR}，从环境变量读取
        var_name = cfg_key[2:-1]
        os.environ['OPENAI_API_KEY'] = os.environ.get(var_name, '')
    else:
        os.environ['OPENAI_API_KEY'] = os.environ.get('OPENAI_API_KEY') or cfg_key
    
    from mem0 import Memory
    
    m = Memory.from_config({
        'vector_store': {
            'provider': 'qdrant',
            'config': {
                'host': config['qdrant']['host'],
                'port': config['qdrant']['port'],
                'collection_name': config['agent']['collection']
            }
        },
        'llm': {
            'provider': 'openai',
            'config': {
                'model': config['llm']['model'],
                'openai_base_url': config['llm']['api_base_url'],
                'temperature': 0.1
            }
        },
        'embedder': {
            'provider': 'openai',
            'config': {
                'model': config['embedding']['model'],
                'openai_base_url': config['llm']['api_base_url'],
                'embedding_dims': config['embedding']['dimensions']
            }
        }
    })
    
    results = m.search(
        query=args.query,
        user_id=config['agent']['user_id'],
        agent_id=config['agent']['id'],
        limit=args.limit
    )
    
    print(f"🔍 搜索: {args.query}")
    print(f"📊 结果: {len(results.get('results', []))} 条\n")
    
    for i, r in enumerate(results.get('results', []), 1):
        print(f"{i}. {r['memory'][:100]}...")
        print()

def main():
    parser = argparse.ArgumentParser(description='Mem0 Agent 命令行工具')
    subparsers = parser.add_subparsers(dest='command', help='命令')
    
    # status
    subparsers.add_parser('status', help='查看状态')
    
    # start
    subparsers.add_parser('start', help='启动服务')
    
    # stop
    subparsers.add_parser('stop', help='停止服务')
    
    # restart
    subparsers.add_parser('restart', help='重启服务')
    
    # logs
    logs_parser = subparsers.add_parser('logs', help='查看日志')
    logs_parser.add_argument('-n', '--lines', type=int, default=50, help='显示行数')
    
    # stats
    subparsers.add_parser('stats', help='查看记忆统计')
    
    # search
    search_parser = subparsers.add_parser('search', help='搜索记忆')
    search_parser.add_argument('query', help='搜索关键词')
    search_parser.add_argument('--limit', type=int, default=5, help='结果数量')

    # distill
    distill_parser = subparsers.add_parser('distill', help='精炼记忆（生成浓缩块）')

    args = parser.parse_args()

    if args.command == 'status':
        cmd_status(args)
    elif args.command == 'start':
        cmd_start(args)
    elif args.command == 'stop':
        cmd_stop(args)
    elif args.command == 'restart':
        cmd_restart(args)
    elif args.command == 'logs':
        cmd_logs(args)
    elif args.command == 'stats':
        cmd_stats(args)
    elif args.command == 'search':
        cmd_search(args)
    elif args.command == 'distill':
        cmd_distill(args)
    else:
        parser.print_help()



def cmd_distill(args):
    """精炼记忆 - 将碎片合并为浓缩的 [block]"""
    import os, sys, re, time
    os.environ['OPENAI_API_KEY'] = os.environ.get('OPENAI_API_KEY') or ''
    if not os.environ.get('OPENAI_API_KEY'):
        print("ERROR: set OPENAI_API_KEY env"); sys.exit(1)

    from qdrant_client import QdrantClient
    from openai import OpenAI
    from mem0 import Memory

    API_KEY = os.environ['OPENAI_API_KEY']
    BASE_URL = 'https://api.siliconflow.cn/v1'
    COLLECTION = 'mem0_main'
    client = QdrantClient(url='http://localhost:6333')

    print("Reading all records...")
    records = []
    offset = None
    while True:
        result = client.scroll(collection_name=COLLECTION, limit=200, offset=offset)
        if not result[0]: break
        for p in result[0]:
            records.append({'id': p.id, 'data': p.payload.get('data', '')})
        offset = result[1]
        if offset is None: break

    print(f"Total: {len(records)} records")

    groups = {'episodic': [], 'semantic': [], 'procedural': []}
    for r in records:
        m_type = re.search(r'\[(episodic|semantic|procedural)\]', r['data'])
        if '[distilled]' in r['data'] or not m_type:
            continue
        clean = re.sub(r'^\[[^\]]+\]\[score:\d+\]\s*', '', r['data']).strip()
        if clean:
            groups[m_type.group(1)].append({'id': r['id'], 'clean': clean})

    print(f"Groups: episodic={len(groups['episodic'])} semantic={len(groups['semantic'])} procedural={len(groups['procedural'])}")

    prompts = {
        'episodic': "以下是从对话中提取的事件记忆片段，请将相关的合并为1-3条独立的自然语言陈述，每条一个主题：\n{block_list}\n\n要求：格式：[block] 完整陈述，多个主题分开。不要解释，只输出block列表。",
        'semantic': "以下是从对话中提取的事实和偏好记忆片段，请将相关的合并为1-3条独立的自然语言陈述，每条一个主题：\n{block_list}\n\n要求：格式：[block] 完整陈述，多个主题分开。不要解释，只输出block列表。",
        'procedural': "以下是从对话中提取的流程和方法记忆片段，请将相关的合并为1-3条独立的自然语言陈述，每条一个主题：\n{block_list}\n\n要求：格式：[block] 完整陈述，多个主题分开。不要解释，只输出block列表。",
    }

    llm_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    new_blocks = []
    for mtype, grp in groups.items():
        if not grp:
            print(f"[{mtype}] no records, skip")
            continue
        sample = grp[:20]
        block_list = '\n'.join([f"{i+1}. {r['clean']}" for i, r in enumerate(sample)])
        prompt = prompts[mtype].format(block_list=block_list)
        try:
            resp = llm_client.chat.completions.create(
                model='Qwen/Qwen2.5-7B-Instruct',
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.3
            )
            text = resp.choices[0].message.content.strip()
            blocks = re.findall(r'\[block\]\s*(.+)', text)
            print(f"[{mtype}] generated {len(blocks)} blocks")
            for b in blocks:
                new_blocks.append(f"[{mtype}][distilled] {b.strip()}")
                print(f"  - {b.strip()[:80]}")
        except Exception as e:
            print(f"[{mtype}] LLM error: {e}")

    if not new_blocks:
        print("No blocks generated, aborting")
        return

    print(f"\nTotal: {len(new_blocks)} distill blocks")
    confirm = input("Write to mem0? (y/n): ")
    if confirm.strip().lower() != 'y':
        print("Cancelled")
        return

    m = Memory.from_config({
        'vector_store': {'provider': 'qdrant', 'config': {'host': 'localhost', 'port': 6333, 'collection_name': COLLECTION, 'embedding_model_dims': 1024}},
        'llm': {'provider': 'openai', 'config': {'model': 'Qwen/Qwen2.5-7B-Instruct', 'openai_base_url': BASE_URL, 'temperature': 0.1}},
        'embedder': {'provider': 'openai', 'config': {'model': 'BAAI/bge-large-zh-v1.5', 'openai_base_url': BASE_URL, 'embedding_dims': 1024}}
    })

    for b in new_blocks:
        try:
            m.add([{'role': 'user', 'content': b}], user_id='fuge', agent_id='main', infer=True)
            time.sleep(0.3)
        except Exception as e:
            print(f"Write error: {e}")
    print(f"Done! {len(new_blocks)} distill blocks written")

if __name__ == '__main__':
    main()
