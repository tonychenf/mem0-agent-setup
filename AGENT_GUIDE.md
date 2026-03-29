# Mem0 Agent Setup - Agent 配置指引

> 本文档面向 **AI Agent**（尤其是刚启动的新会话），帮助你快速理解 Mem0 向量记忆系统的架构、在多 Agent 环境中进行检查、以及最重要的是——**如何在每次回复中正确使用记忆系统**。

---

## 一、系统概述

Mem0 向量记忆系统让你的 AI Agent 拥有**跨会话记住用户偏好和重要信息**的能力。

```
用户对话
    ↓
session JSONL 文件
    ↓
watch_sessions.js（每5秒轮询）
    ↓
sync_to_mem0.py（实时写入 Qdrant，realtime layer，score=3）
    ↓
memory_distill_daily.py（每日蒸馏，精华 block → Qdrant，score=3-5）
    ↓
auto_recall.py（每次回复前检索）
    ↓
AI Agent 参考记忆回复用户
```

**核心能力**：
- 🧠 **语义记忆** — 理解含义，不是关键词匹配
- 📝 **自动同步** — 对话同时写入，无需人工介入
- ⚡ **两次写入** — 实时写入（不过滤）+ 每日蒸馏（精华提炼）
- 🔍 **智能检索** — 每次回复前自动搜索相关记忆
- 🔒 **多 Agent 隔离** — 每个 Agent 记忆完全隔离
- 📎 **来源追溯** — 每条记忆记录来自哪个 session 文件
- ⚡ **Per-session 断点续传**（v5，不重复处理同一 session）

---

## 二、记忆分层体系

系统采用**四层记忆架构**，每层有不同的用途：

| 层级 | 标签格式 | 用途 | 写入方式 |
|------|---------|------|---------|
| 🍯 **Semantic** | `[层级:Semantic]` | 用户偏好、沟通风格、语言习惯 | 每日蒸馏 |
| 📅 **Episodic** | `[层级:Episodic]` | 历史决策、重大事件 | 每日蒸馏 |
| ⚙️ **Procedural** | `[层级:Procedural]` | 工作流程、操作步骤 | 每日蒸馏 |
| ⚡ **Realtime** | `[realtime]` | 当前对话原始记录 | 实时写入（不过滤） |

### 评分规则

| 评分 | 类型 | 示例 | 存入主库 |
|------|------|------|---------|
| ⭐⭐⭐⭐⭐ 5分 | 核心信息 | 名字、身份、关系、重大承诺 | ✅ |
| ⭐⭐⭐⭐ 4分 | 重要偏好 | 喜欢/讨厌、重要习惯 | ✅ |
| ⭐⭐⭐ 3分 | 一般信息 | 日常对话 | ✅ |
| ⭐ 1-2分 | 无价值 | 客套话、问候 | ❌ 清理掉 |

---

## 三、核心脚本详解

### 3.1 auto_recall.py（⭐ 最重要的脚本）

> **每次回复前必须调用** — 这是你获取记忆的唯一入口。

**v8 检索流程**：
```
用户查询 → 生成 embedding → Qdrant 语义搜索
                         ↓
              ① 语义搜索结果（top 8）
                 - 蒸馏记忆：按 score 过滤（< min_score 丢弃）
                 - realtime 记忆：不过滤，全部追加
                         ↓
              ② 追加最近 20 条 realtime（按时序，不按相关度）
                         ↓
              ③ 按 layer 分组输出
```

**调用方式**：
```bash
python3 /root/.openclaw/project/mem0-agent-setup/scripts/auto_recall.py "搜索关键词" [min_score] [limit] [--agent <agent_id>]
```

**参数说明**：
- `搜索关键词` — 要搜索的记忆内容（必填）
- `min_score` — 最低分数（默认2，realtime 固定不过滤）
- `limit` — 最多返回条数（默认8）
- `--agent` — 指定 agent（默认从环境变量推导）

**示例输出**：
```
## 📚 相关记忆

回答请符合用户偏好、沟通习惯、语言风格：
  [语义]用户喜欢简洁的回复 [score=4] | [session文件]: 👤 用户说"尽量简短一点"

回答请参考用户的历史决策、重大事件：
  [事件]用户决定使用Qdrant作为向量数据库 [score=5] | [session文件]: 👤 我们用Qdrant吧

实时捕获的原始记忆片段：
  [实时]什么是天王盖地虎？ [score=3]
  [实时]两只小老鼠。这是一个中国传统的口令游戏。 [score=3]
```

---

### 3.2 sync_to_mem0.py

> **实时写入脚本** — 每当 watch_sessions.js 检测到新对话，自动调用。

**处理逻辑**：
```python
# 1. 读取 session JSONL 中的 user + assistant 消息对
# 2. 解析 Feishu System 包装，提取真正用户消息
# 3. content 可能是 list [{"type": "text", "text": "..."}]，需提取 text
# 4. 长度 < 5 的跳过
# 5. 格式化为 [realtime][score:3] 用户消息
# 6. m.add() 写入 Qdrant，metadata={'layer': 'realtime'}
```

**注意**：实时写入**不经过 LLM 评分**，所有对话都会写入（长度 >= 5 的），默认 score=3。

---

### 3.3 memory_distill_daily.py

> **每日蒸馏脚本** — 凌晨 04:00-04:25 分批执行。

**功能**：
- 读取 session JSONL 文件
- LLM 评分 + 内容提炼
- 生成精华 block
- 写入 Qdrant（layer = semantic/episodic/procedural，score = 3-5）

**Per-session 断点续传**：
```json
// Qdrant: distill_session_records collection
{
  "session_id": "7c86da32-ea18-4a3a-90b7-5d65bb1c2f53",
  "agent_id": "main",
  "remark_1": "2026-03-29T04:30:19",
  "remark_2": "142 lines processed"
}
```

---

### 3.4 watch_sessions.js

> **Node.js 守护进程** — 挂后台运行，每5秒轮询 session 目录。

**工作流程**：
```
每 5 秒：
  ↓
读取所有 .jsonl 文件
  ↓
比对文件的 mtime（修改时间）
  ↓
发现文件有更新 → 读取新增行
  ↓
提取 user + assistant 消息对
  ↓
调用 sync_to_mem0.py 写入 Qdrant
```

---

## 四、在每次回复中使用记忆

### 4.1 必须调用的时机

根据 [AGENTS.md](../workspace/AGENTS.md) 规定：

> **Mem0 Recall（每次回答前必须执行）**：
> 使用 `python3 /root/.openclaw/project/mem0-agent-setup/scripts/auto_recall.py "<当前对话关键词>"` 检索相关记忆

**触发条件**：当你需要回答用户问题时，都应该先检索记忆。

**关键词选择**：尽量具体，避免太泛（如"工作" → "孚哥的工作项目"）。

### 4.2 调用示例

```bash
# 用户问："我之前说的那个项目进展如何了？"
# 你应该先检索"项目进展"相关记忆：

python3 /root/.openclaw/project/mem0-agent-setup/scripts/auto_recall.py "孚哥 项目 进展" 2 8

# 返回结果会自动以 ## 📚 相关记忆 标题输出
# 你在回复中引用这些记忆即可
```

### 4.3 强制指定 agent

如果需要在非当前 agent 的上下文中检索其他 agent 的记忆，使用 `--agent` 参数：

```bash
# 在 main agent 中检索 capital agent 的记忆
python3 /root/.openclaw/project/mem0-agent-setup/scripts/auto_recall.py "量化交易" 2 8 --agent capital
```

---

## 五、环境检查清单

### 5.1 检查 watch 进程状态

```bash
ps aux | grep watch_sessions | grep -v grep

# 应该看到 17+ 个进程在运行
# 如果某个 agent 的 watch 进程消失了，对应 agent 的实时写入就会中断
```

### 5.2 检查 cron 任务

```bash
openclaw cron list | grep -E "记忆蒸馏|记忆清理"
```

**正常状态**：看到 1 个 cleanup + 多个 distill cron，状态为 idle/in progress

### 5.3 检查 .env 配置

```bash
cat /root/.openclaw/mem0-agent-setup/.env

# 必须包含：
# OPENAI_API_KEY=sk-xxx
# OPENAI_BASE_URL=https://api.siliconflow.cn/v1
# MEM0_USER_ID=fuge
```

### 5.4 测试记忆是否正常

```bash
# 加载 .env
. /root/.openclaw/mem0-agent-setup/.env

# 搜索记忆
python3 /root/.openclaw/project/mem0-agent-setup/scripts/auto_recall.py "测试"

# 查看记忆数量
python3 /root/.openclaw/project/mem0-agent-setup/scripts/mem0-agent.py stats
```

### 5.5 检查向量库状态

```bash
# 查看所有 collection 的 point 数量
curl -s http://localhost:6333/collections | python3 -c "
import sys,json
d=json.load(sys.stdin)
for c in d['result']['collections']:
    name=c['name']
    if name.startswith('mem0_'):
        import requests
        r=requests.get(f'http://localhost:6333/collections/{name}')
        cnt=r.json()['result']['points_count']
        print(f'{name}: {cnt} points')
"
```

---

## 六、Cron 定时任务

| 时间 | 任务 | Agent |
|------|------|-------|
| `03:00` | memory_cleanup.py | main |
| `04:00` | memory_distill (main, capital, dev) | 第一批 |
| `04:05` | memory_distill (bingbu, gongbu) | 第二批 |
| `04:10` | memory_distill (legal, ops) | 第三批 |
| `04:15` | memory_distill (libu_hr, menxia, rich) | 第四批 |
| `04:20` | memory_distill (xingbu) | 第五批 |
| `04:25` | memory_distill (zaochao, zhongshu, shangshu, taizi, hubu, libu) | 第六批 |
| `23:59` | sync_sessions_to_memory.js | 每日全量同步 |

---

## 七、记忆存储结构

### Qdrant Collection

每个 agent 独立的 collection：`mem0_{agent}`

```json
// 一条记录的结构
{
  "id": "uuid-xxxx",
  "vector": [0.123, -0.456, ...],  // 1024维 embedding
  "payload": {
    "data": "[层级:Episodic][score:5][distilled] 用户决定使用Qdrant",
    "layer": "episodic",
    "score": 5,
    "agent_id": "main",
    "user_id": "fuge",
    "created_at": "2026-03-29T07:00:00.000000-07:00"
  }
}
```

### Session 文件

```
/root/.openclaw/agents/{agent}/sessions/*.jsonl
```

每行一条 JSON：
```jsonl
{"type":"message","message":{"role":"user","content":"[{\"type\":\"text\",\"text\":\"用户消息\"}]","created_at":"..."}}
{"type":"message","message":{"role":"assistant","content":"[{\"type\":\"text\",\"text\":\"助手回复\"}]","created_at":"..."}}
```

---

## 八、快速命令参考

```bash
# ══ 记忆检索 ════════════════════════════════════════════════
# 搜索记忆（默认 min_score=2, limit=8）
python3 /root/.openclaw/project/mem0-agent-setup/scripts/auto_recall.py "关键词"

# 指定 agent 搜索
python3 /root/.openclaw/project/mem0-agent-setup/scripts/auto_recall.py "关键词" --agent capital

# 指定分数阈值
python3 /root/.openclaw/project/mem0-agent-setup/scripts/auto_recall.py "关键词" 3 10

# ══ 蒸馏操作 ════════════════════════════════════════════════
# dry run（不写入，看会处理多少）
python3 /root/.openclaw/project/mem0-agent-setup/scripts/memory_distill_daily.py \
  --agent main --dry-run --yes

# 强制全量处理（跳过断点续传）
python3 /root/.openclaw/project/mem0-agent-setup/scripts/memory_distill_daily.py \
  --agent main --force --yes

# 清理 30 天前未活跃的 session 记录
python3 /root/.openclaw/project/mem0-agent-setup/scripts/memory_distill_daily.py \
  --agent main --cleanup --days 30 --yes

# ══ 状态查看 ════════════════════════════════════════════════
# 查看所有 agent 的 watch 进程数量
ps aux | grep watch_sessions | grep -v grep | wc -l

# 查看某 agent 的 distill 状态
cat /root/.openclaw/workspace/.distill_state_main.json

# 查看 Qdrant collection 统计
python3 /root/.openclaw/project/mem0-agent-setup/scripts/mem0-agent.py stats --agent main
```

---

*最后更新：2026-03-29 by 落雁 🦋*
