#!/usr/bin/env python3
"""
Mem0 Sync - Conversation Sync to Vector Store
Supports multi-agent auto-detection and LLM-based importance scoring
"""
import os
import sys
import json
import re

# 配置 API Key（必须设置环境变量）
# 优先从 .env 加载（解决 shell 环境有假 key 的问题）
for env_path in ["/root/.openclaw/mem0-agent-setup/.env"]:
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()
        break

if 'OPENAI_API_KEY' not in os.environ or not os.environ.get('OPENAI_API_KEY', '').strip():
    raise RuntimeError("请设置环境变量 OPENAI_API_KEY")

os.environ['OPENAI_BASE_URL'] = os.environ.get('OPENAI_BASE_URL', 'https://api.siliconflow.cn/v1')

try:
    from mem0 import Memory
except ImportError:
    print("ERROR: mem0 not installed")
    sys.exit(1)

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai not installed")
    sys.exit(1)

# 统一配置常量
MEMORY_CONFIG = {
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

# 已知的 Agent 列表
KNOWN_AGENTS = ['main', 'capital', 'legal', 'dev', 'ops', 'rich', 'hubu', 'zaochao', 
               'libu', 'libu_hr', 'taizi', 'zhongshu', 'menxia', 'bingbu', 'gongbu', 'xingbu', 'shangshu']

# LLM 客户端
llm_client = None

def get_llm_client():
    global llm_client
    if llm_client is None:
        llm_client = OpenAI(
            api_key=os.environ['OPENAI_API_KEY'],
            base_url='https://api.siliconflow.cn/v1'
        )
    return llm_client

def get_agent_name() -> str:
    """
    自动识别当前 agent 名称，优先级：
    1. 环境变量 AGENT_NAME
    2. 从工作目录路径推断
    3. 默认 'main'
    """
    agent_name = os.environ.get('AGENT_NAME')
    if agent_name:
        return agent_name
    
    cwd = os.getcwd()
    for agent in KNOWN_AGENTS:
        if f'/agents/{agent}/' in cwd or cwd.endswith(f'/agents/{agent}'):
            return agent
    
    return 'main'

def get_memory(collection_name: str = None):
    """获取记忆实例"""
    if collection_name is None:
        agent_name = get_agent_name()
        collection_name = f"mem0_{agent_name}"
    
    config = MEMORY_CONFIG.copy()
    config['vector_store'] = {
        'provider': 'qdrant',
        'config': {
            'host': 'localhost',
            'port': 6333,
            'collection_name': collection_name,
            'embedding_model_dims': 1024
        }
    }
    
    return Memory.from_config(config)

def should_remember_and_score(user_msg: str, assistant_msg: str) -> dict:
    """
    用 LLM 判断消息是否值得记忆，并进行评分和分类
    
    Returns:
        dict: {
            'should_remember': bool,
            'score': int (1-5),
            'type': str (episodic/semantic/procedural),
            'reason': str
        }
    """
    prompt = f"""分析以下对话，判断是否值得存储为长期记忆：

用户：{user_msg[:300]}
助手：{assistant_msg[:300]}

评分标准：
- 5分：核心信息（名字、身份、重要关系、承诺、决策）
- 4分：重要偏好（喜欢、讨厌、重要习惯）
- 3分：一般信息（日常对话、有价值的事实）
- 2分：临时信息（随口提到、可忽略）
- 1分：无价值（客套话、问候）

重要规则：score >= 3 时 should_remember 必须为 true，score < 3 时 should_remember 为 false。

分类：
- episodic: 事件记忆（做过的事、说过的话）
- semantic: 语义记忆（偏好、习惯、关系、事实）
- procedural: 程序记忆（步骤、流程、方法）

请用 JSON 格式回复：
{{"should_remember": true/false, "score": 1-5, "type": "episodic/semantic/procedural", "reason": "原因"}}

只回复 JSON，不要其他内容。"""
    
    try:
        client = get_llm_client()
        response = client.chat.completions.create(
            model='Qwen/Qwen2.5-7B-Instruct',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.1
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # 解析 JSON
        json_match = re.search(r'\{[^{}]*\}', result_text)
        if json_match:
            result = json.loads(json_match.group())
            return {
                'should_remember': result.get('should_remember', False),
                'score': result.get('score', 3),
                'type': result.get('type', 'semantic'),
                'reason': result.get('reason', '')
            }
    except Exception as e:
        print(f"LLM评估失败: {e}", file=sys.stderr)
    
    # 默认返回
    return {'should_remember': True, 'score': 3, 'type': 'semantic', 'reason': 'default'}

def sync_messages(messages, agent_name: str = None) -> int:
    """
    同步消息到向量库（带 LLM 筛选）
    
    Args:
        messages: 消息列表 [{user: str, assistant: str}, ...]
        agent_name: Agent 名称（可选，默认自动识别）
    
    Returns:
        成功同步的消息数量
    """
    if agent_name is None:
        agent_name = get_agent_name()
    
    m = get_memory()
    
    if not isinstance(messages, list):
        messages = [messages]
    
    imported = 0
    for msg in messages[:10]:  # 最多10条
        try:
            if isinstance(msg, str):
                continue
            user = msg.get('user', '')[:500]
            assistant = msg.get('assistant', '')[:500]
            
            # 从 System 包装里提取真正的用户消息内容
            # content 可能是字符串，也可能是列表（[{"type": "text", "text": "..."}]）
            # 先提取纯文本
            if isinstance(user, list):
                # content 是列表，从中提取 text
                for c in user:
                    if isinstance(c, dict) and c.get('type') == 'text' and c.get('text', '').strip():
                        user = c.get('text', '')
                        break
            
            if isinstance(user, str) and user.startswith('System:'):
                # 尝试提取消息正文（两个换行后的内容）
                parts = user.split('\n\n')
                if len(parts) >= 2:
                    user = parts[-1].strip()  # 取最后一段（实际消息内容）
                else:
                    # 没有双换行，跳过 System: 行，取剩余内容
                    lines = user.split('\n')
                    content_lines = [l for l in lines if not l.startswith('System:') and not l.startswith('Conversation')]
                    user = ' '.join(content_lines).strip()
            
            # 过滤：太短的不要（中文短语通常较短，5字符起步）
            if len(user) < 5:
                continue
            
            # 直接写入：不过滤，保留所有 user + assistant 对话
            # 格式：[realtime][score:3] 内容
            enhanced_content = f"[realtime][score:3] {user}"
            
            m.add(
                [{'role': 'user', 'content': enhanced_content}, {'role': 'assistant', 'content': assistant}],
                user_id=os.environ.get("MEM0_USER_ID", "user"),
                agent_id=agent_name,
                infer=False,
                metadata={'layer': 'realtime'}
            )
            imported += 1
            
        except Exception as e:
            print(f"Error syncing message: {e}", file=sys.stderr)
    
    return imported

def main():
    messages_json = sys.stdin.read().strip()
    
    if not messages_json:
        print("ERROR: No messages provided")
        return
    
    try:
        messages = json.loads(messages_json)
    except Exception as e:
        print(f"ERROR: Invalid JSON - {e}")
        return
    
    agent_name = get_agent_name()
    imported = sync_messages(messages, agent_name)
    
    print(f"DONE:{imported}")

if __name__ == '__main__':
    main()
