[![GitHub stars](https://img.shields.io/github/stars/tonychenf/openclaw-memory-enhance)](https://github.com/tonychenf/openclaw-memory-enhance)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

[[🌐 中文版](#chinese)] &nbsp;|&nbsp; [[🌐 English](#english)]

---

# <a id="chinese">🧠</a> openclaw-memory-enhance

> **让 AI Agent 拥有真正的长期记忆** —— 基于 Mem0 + Qdrant 的本地化向量记忆系统，专为 [OpenClaw](https://github.com/openclaw/openclaw) 多 Agent 环境设计。

---

## 🌟 一句话概括

**每一次对话都被记住，下一次会话无需重复。**

---

## 🤯 痛点

你是否遇到过这样的烦恼？

| 场景 | 崩溃程度 |
|------|---------|
| 🤕 **每次重启都是陌生人** — AI 不记得你是谁、你的偏好、你的项目背景 | 💔💔💔💔💔 |
| 📄 **对话历史越来越长** — 3个月的聊天记录塞进 context，API 费用爆炸 | 💰💰💰💰 |
| 😤 **重要信息转头就忘** — 用户说过"我叫孚哥，是公司老板"，转头就问"你叫什么？" | 😠😠😠 |
| 🔀 **多 Agent 记忆串台** — capital agent 以为自己是 legal agent | 🤯🤯🤯 |

**根本原因**：大语言模型没有持久化记忆能力，每一次会话都是从零开始。

---

## 💡 解决方案

本项目为 OpenClaw 的每一个 Agent 搭建**私有向量记忆系统**：

```
用户说"我最喜欢蓝色" 
       ↓
  自动存储到本地 Qdrant 向量数据库
       ↓
用户下次问"有什么推荐？" 
       ↓
  自动检索"蓝色偏好" 
       ↓
  给出了解用户的个性化推荐 ✨
```

### 核心技术栈

| 技术 | 作用 |
|------|------|
| **[Mem0](https://github.com/mem0ai/mem0)** | 记忆管理框架（Python SDK） |
| **[Qdrant](https://github.com/qdrant/qdrant)** | 本地向量数据库（Docker，一行命令启动） |
| **OpenClaw Sessions** | 对话历史来源（JSONL 文件） |
| **watch_sessions.js** | 实时监控对话变化，自动触发记忆写入 |

**100% 本地部署，数据完全自主可控。**

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户对话                                  │
│  （飞书 / WhatsApp / Discord / 终端 ...）                         │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   OpenClaw Agent Session                         │
│            /root/.openclaw/agents/{agent}/sessions/             │
│                      *.jsonl 文件                                │
└────────────────────────┬────────────────────────────────────────┘
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
┌───────────────────────┐   ┌───────────────────────────────────┐
│  watch_sessions.js    │   │    memory_distill_daily.py        │
│  （实时监听，Node进程）   │   │    （每日蒸馏，cron 04:00-04:25）  │
│  每5秒轮询一次          │   │    将对话蒸馏为精华记忆块           │
└───────────┬───────────┘   └──────────────┬────────────────────┘
            │                              │
            ▼                              ▼
┌───────────────────────────────────────────────────────────────┐
│                    sync_to_mem0.py                             │
│  实时写入：对话 → Qdrant（realtime layer，score=3）              │
│  每日蒸馏：精华块 → Qdrant（distilled layer，score=3-5）        │
└────────────────────────────┬──────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Qdrant 向量数据库                           │
│              localhost:6333（Docker 运行）                        │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ mem0_main   │  │ mem0_dev    │  │ mem0_capital│  ...        │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│                                                                  │
│  每条记录 metadata 包含：layer / score / agent_id / created_at   │
└────────────────────────────┬──────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    auto_recall.py                               │
│  每次回复前自动检索：                                             │
│  ① Qdrant 语义搜索（蒸馏记忆，按分数过滤）                          │
│  ② 追加最近20条 realtime（按时序，不过滤）                          │
│  ③ 补全 session 上下文（来源文件 + 原始对话片段）                    │
└────────────────────────────┬──────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AI Agent 回复                                 │
│  "根据你之前说的，你最喜欢蓝色，我推荐这个..."                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 项目结构

```
openclaw-memory-enhance/
│
├── README.md                     # 本文件，项目总体介绍
├── AGENT_GUIDE.md               # AI Agent 配置指引（面向 AI 的手册）
├── install.sh                   # 一键安装脚本
│
├── scripts/                     # ⭐ 核心脚本目录（所有 agent 共用）
│   │
│   │  ── 实时监控 ──
│   ├── watch_sessions.js        # Node.js 进程，监控 session 文件变化
│   │                            # 每5秒轮询，发现新对话自动触发 sync
│   │
│   │  ── 记忆写入 ──
│   ├── sync_to_mem0.py          # 实时写入：对话 → Qdrant（realtime layer）
│   │                            # 每次写入带 metadata: layer=realtime, score=3
│   │                            # 支持 Feishu 格式解析，自动提取真正用户消息
│   │
│   │  ── 记忆检索 ──
│   ├── auto_recall.py           # v11：每次回复前调用，返回格式化记忆
│   │                            # 语义搜索（排除realtime） + realtime追加（服务端filter） + 去重
│   │
│   │  ── 每日蒸馏 ──
│   ├── memory_distill_daily.py  # v5：每日 cron 任务（蒸馏前先清理噪音）
│   │                            # 将原始对话蒸馏为精华 block（LLM 评分 1-5）
│   │                            # 支持 per-session 断点续传 + 蒸馏记录表
│   │
│   │  ── 清理维护 ──
│   ├── memory_cleanup.py        # 每日 03:00 执行，清理低分记忆
│   ├── is_noise.py             # 公共噪音判断函数（两处共用）
│   └── cleanup_noise_realtime.py # 一次性清理噪音记录脚本
│   │
│   │  ── 辅助工具 ──
│   ├── auto_memory.py           # 手动保存单条记忆
│   ├── mem0-agent.py            # CLI 工具：stats / status / search
│   ├── parse_sync_memory.py     # 解析 sync 写入的记忆
│   ├── sync_all_to_mem0.py      # 全量同步（手动触发）
│   ├── test_recall.py           # 检索测试脚本
│   ├── config.env.example       # 环境变量示例
│   │
│   └── backup/                   # 备份脚本
│
├── crontab                       # 系统 crontab 配置
│
└── docs/                         # 补充文档（可选）
```

**关键设计原则**：所有 agent **共用同一套脚本**，通过 `--agent-id` 或环境变量指定操作哪个 agent 的数据。

---

## 🧠 记忆分层体系

系统采用**四层记忆架构**，每层有不同的用途和生命周期：

```
┌──────────────────────────────────────────────────────────────┐
│  🍯 Semantic（语义层）                                        │
│  用途：用户偏好、沟通风格、语言习惯                               │
│  示例："用户喜欢简洁的回复"、"用户使用中文"、"用户叫孚哥"          │
│  触发：用户明确表达喜好、习惯、身份                              │
├──────────────────────────────────────────────────────────────┤
│  📅 Episodic（事件层）                                        │
│  用途：历史决策、重大事件、项目进展                               │
│  示例："用户决定用 Qdrant"、"项目选型已完成"                    │
│  触发：用户做出决定、描述事件、评价结果                           │
├──────────────────────────────────────────────────────────────┤
│  ⚙️ Procedural（程序层）                                      │
│  用途：工作流程、操作步骤、规则约定                               │
│  示例："每周一需要汇报进度"、"部署用 docker-compose"             │
│  触发：用户制定规则、说明流程、提出要求                           │
├──────────────────────────────────────────────────────────────┤
│  ⚡ Realtime（实时层）                                        │
│  用途：当前对话的原始记录                                       │
│  示例："用户刚问了什么问题"、"助手刚回答了什么"                  │
│  触发：每次对话实时写入（realtime layer，score=3，不过滤）        │
└──────────────────────────────────────────────────────────────┘
```

### 评分规则

| 评分 | 类型 | 说明 | 存入主库 |
|------|------|------|---------|
| ⭐⭐⭐⭐⭐ 5分 | 核心信息 | 名字、身份、关系、重大承诺 | ✅ |
| ⭐⭐⭐⭐ 4分 | 重要偏好 | 喜欢/讨厌、重要习惯 | ✅ |
| ⭐⭐⭐ 3分 | 一般信息 | 日常对话、有用但非关键 | ✅ |
| ⭐ 1-2分 | 无价值 | 客套话、问候 | ❌ 清理掉 |

---

## 🔄 两种记忆写入模式

### 模式一：实时写入（sync_to_mem0.py）

**目标**：一个都不能漏

```
用户 ←→ AI 对话 
         ↓
    每条消息（user + assistant 对）自动写入 Qdrant
         ↓
    metadata: layer=realtime, score=3
```

**特点**：
- 100% 覆盖，不丢失任何对话
- 不过滤长度（最低5字符）
- 自动解析 Feishu System 包装消息
- 支持 content 为 list 的 JSONL 格式
- 默认 score=3

### 模式二：每日蒸馏（memory_distill_daily.py）

**目标**：提炼精华，去芜存菁

```
session JSONL 文件（大量原始对话）
         ↓
    LLM 评分 + 提炼精华
         ↓
    精华 block 写入 Qdrant
         ↓
    metadata: layer=semantic/episodic/procedural, score=3-5
```

**特点**：
- per-session 断点续传（不重复处理）
- 蒸馏记录表（Qdrant collection）追踪每个 session 状态
- 支持 `.reset.TIMESTAMP` 重命名文件的 UUID 追溯
- 自动清理 30 天前低分记忆

---

## 📊 Cron 定时任务

所有任务记录在 `crontab`，每日自动执行：

| 时间 | 任务 | 说明 |
|------|------|------|
| `03:00` | memory_cleanup.py | 清理 30 天前低分记忆 |
| `04:00` | memory_distill (main, capital, dev) | 第一批蒸馏 |
| `04:05` | memory_distill (......) | 第二批 |
| `04:10` | memory_distill (......) | 第三批 |
| `04:15` | memory_distill (......) | 第四批 |
| `04:20` | memory_distill (......) | 第五批 |
| `04:25` | memory_distill (......) | 第六批 |
| `23:59` | sync_sessions_to_memory.js | 每日全量同步 |

---

## 🚀 快速开始

### 前置要求

- Linux (Ubuntu 20.04+)
- Python 3.8+
- Docker（Qdrant 向量数据库）
- OpenClaw 已安装并运行

### 第一步：启动 Qdrant

```bash
docker run -d --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

### 第二步：配置环境变量

```bash
cp scripts/config.env.example /root/.openclaw/mem0-agent-setup/.env
vim /root/.openclaw/mem0-agent-setup/.env
```

必须设置：
```bash
OPENAI_API_KEY=sk-xxxxxxxx          # 你的 SiliconFlow API Key
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
MEM0_USER_ID=fuge                   # 固定用户 ID
```

### 第三步：一键安装

```bash
cd /root/.openclaw/project/mem0-agent-setup
bash install.sh --auto
```

这会自动：
- 检测已安装组件（不重复安装）
- 为所有 17 个 agent 配置 watch 进程
- 设置 cron 定时任务

### 第四步：测试

```bash
# 加载环境变量
source /root/.openclaw/mem0-agent-setup/.env

# 搜索记忆
python3 scripts/auto_recall.py "孚哥"

# 手动触发每日蒸馏（dry run）
python3 scripts/memory_distill_daily.py --agent main --dry-run --yes

# 查看 agent 状态
python3 scripts/mem0-agent.py status --agent main
```

---

## 📚 核心文件详解

### watch_sessions.js

> 挂在后台的 Node.js 进程，监控 session 文件变化。

**工作原理**：
```
每 5 秒轮询 session 目录
       ↓
比对文件修改时间（mtime）
       ↓
发现新内容 → 读取 JSONL 中未处理的消息对
       ↓
调用 sync_to_mem0.py 写入 Qdrant
```

**进程管理**：
```bash
# 查看运行中的 watch 进程
ps aux | grep watch_sessions

# 重启某个 agent 的 watch
systemctl restart openclaw-session-watch@{agent}

# 查看日志
journalctl -u openclaw-session-watch@main -f
```

### sync_to_mem0.py

> 将对话实时写入 Qdrant 的 Python 脚本。

**处理逻辑**：
```python
# 1. 读取 session JSONL 文件
# 2. 提取 user + assistant 消息对
# 3. 解析 Feishu System 包装，提取真正用户消息
# 4. 过滤：len < 5 或 System 包装残留 → 跳过
# 5. 格式化为 [realtime][score:3] 用户消息
# 6. m.add() 写入 Qdrant，metadata={'layer': 'realtime'}
```

**支持的 session 格式**：
```jsonl
{"type":"message","message":{"role":"user","content":"[{\"type\":\"text\",\"text\":\"用户消息\"}]"}}
{"type":"message","message":{"role":"assistant","content":"[{\"type\":\"text\",\"text\":\"助手回复\"}]"}}
```

### auto_recall.py

> v11 版本：每次回复前调用的记忆检索脚本。

**检索流程（v11）**：
```
用户查询："天王盖地虎是什么意思？"
       ↓
① 生成 query embedding（bge-large-zh-v1.5）
       ↓
② Qdrant 语义搜索（top 8，按相关性）
       ↓
③ 解析结果：
   - 蒸馏记忆 → 按 score 过滤（< min_score 丢弃）
       ↓
④ 追加最近 20 条 realtime（服务端 filter：layer=realtime + 24h 时间范围）
       ↓
⑤ 去重（id + data 内容双重去重）
       ↓
⑤ 按 layer 分组（semantic / episodic / procedural / realtime）
       ↓
⑥ 格式化输出：
   
   ## 📚 相关记忆
   
   语义记忆（用户偏好、沟通习惯）：
     [语义]用户叫孚哥，是公司老板 [score=4]
   
   实时捕获的原始记忆片段：
     [实时]什么是天王盖地虎？ [score=3]
     [实时]两只小老鼠。这是一个中国传统的口令游戏。 [score=3]
```

### memory_distill_daily.py

> v5 版本：每日对话蒸馏脚本。

**核心功能**：
- 读取 session JSONL 文件
- LLM 评分 + 内容提炼
- 生成精华 block
- 写入 Qdrant（layer = semantic/episodic/procedural）

**Per-session 断点续传**：
```json
// Qdrant: distill_session_records collection
{
  "session_id": "7c86da32-ea18-4a3a-90b7-5d65bb1c2f53",
  "agent_id": "main",
  "remark_1": "2026-03-29T04:30:19",
  "remark_2": "142 lines processed",
  "remark_3": ""
}
```

---

## 🛠️ 运维管理

### 查看所有 watch 进程

```bash
ps aux | grep watch_sessions | grep -v grep
```

### 查看 cron 任务

```bash
openclaw cron list
openclaw cron runs <task-id>
```

### 查看 Qdrant 数据统计

```bash
python3 scripts/mem0-agent.py stats --agent main
```

### 手动触发记忆蒸馏

```bash
# dry run（不写入，看会处理多少）
python3 scripts/memory_distill_daily.py --agent main --dry-run --yes

# 强制处理最近 N 天（兜底漏跑）
python3 scripts/memory_distill_daily.py --agent main --days 3 --yes
```

### 清理记忆

```bash
# 清理 30 天前低分记忆
python3 scripts/memory_cleanup.py 30
```

---

## 📖 文档

| 文档 | 内容 |
|------|------|
| **README.md** | 项目总体介绍（本文） |
| **[AGENT_GUIDE.md](AGENT_GUIDE.md)** | AI Agent 配置指引（面向 AI Agent 的手册） |
| **[飞书文档](https://www.feishu.cn/docx/L0HldmlNSobggfxAohFcRL2nnSh)** | 在线文档，图文并茂 |

---

## 📝 更新日志

### v11 (2026-04-17)

**auto_recall.py**：
- `qdrant_search`：排除 realtime 层（must_not realtime），避免与 realtime 追加重复
- `fetch_recent_realtime`：scroll 改用服务端 filter（layer=realtime + 时间范围），避免全量扫描漏数据；新增 id+data 双重去重
- `get_realtime_context`：零向量搜索改为 scroll + 时间排序（零向量无排序意义）
- 移除 `search_raw_reset_files` 死代码（-136行）
- 版本号统一为 v11

**sync_to_mem0.py**：
- 引用 `is_noise.py`，源头过滤 Cron 任务输出、Agent 指令、HEARTBEAT、OpenClaw 内部上下文等噪音

**memory_distill_daily.py**：
- 新增 `_cleanup_realtime_noise()`，每次蒸馏前自动清理当前 agent collection 中的噪音 realtime 记录

**新增文件**：
- `is_noise.py`：公共噪音判断函数，两处共用，避免重复维护
- `cleanup_noise_realtime.py`：一次性清理噪音脚本，支持指定 collection

### v8 (2026-03-29)

**auto_recall.py**：
- `qdrant_search` 移除 layer 过滤，支持所有层级
- 新增 `fetch_recent_realtime()` 函数，追加最近 20 条 realtime
- `parse_memory` 支持 realtime 格式 `[realtime][score:3]` 解析
- realtime 数据不按分数过滤，全量追加
- `layer_order` 加入 "realtime"，确保 realtime 结果输出
- `lookup_session_snippets` 过滤 System 包装和 toolResult 消息

**sync_to_mem0.py**：
- 移除 LLM 评估，改为直接写入所有对话
- 修复 Feishu 格式 content 解析（list → string）
- 降低最短长度阈值 10→5
- 添加 System 包装解析，提取真正用户消息
- metadata={'layer': 'realtime'} 写入 Qdrant

### v7 (2026-03-28)

**auto_recall.py**：
- Qdrant REST API 替换 mem0.search()
- layer 过滤：只搜 Semantic/Episodic/Procedural
- Realtime sync 数据被过滤，不再干扰结果

### v5 (2026-03-28)

**memory_distill_daily.py**：
- Session 蒸馏记录表（Qdrant）替代本地状态文件
- Per-session 断点续传 + UUID 追踪
- 支持 `.reset.TIMESTAMP` 重命名文件

### v4 (2026-03-28)

- Per-session 断点续传
- Cron 分批时间表（多 agent 分 6 批）

---

## 🤝 License

MIT License

---

**🦋 让每一个 AI Agent 都不再是陌生人。**

---

# <a id="english">🧠</a> openclaw-memory-enhance (English)

> **Give Your AI Agent True Long-Term Memory** — A local vector memory system based on Mem0 + Qdrant, designed for the [OpenClaw](https://github.com/openclaw/openclaw) multi-Agent environment.

---

## 🌟 Elevator Pitch

**Every conversation is remembered. No repetition needed.**

---

## 🤯 The Problem

Ever run into these frustrations?

| Scenario | Pain Level |
|----------|------------|
| 🤕 **Every restart feels like meeting a stranger** — AI doesn't remember who you are, your preferences, your project context | 💔💔💔💔💔 |
| 📄 **Chat history keeps growing** — 3 months of logs stuffed into context, API costs explode | 💰💰💰💰 |
| 😤 **Important info vanishes** — User said "I'm the boss" then AI asks "What's your name?" | 😠😠😠 |
| 🔀 **Memory bleeds across Agents** — capital agent thinks it's the legal agent | 🤯🤯🤯 |

**Root cause**: LLMs have no persistent memory. Every session starts from scratch.

---

## 💡 The Solution

This project builds a **private vector memory system** for every OpenClaw Agent:

```
User says "I love blue best"
       ↓
  Auto-stored to local Qdrant vector database
       ↓
User asks "Any recommendations?"
       ↓
  Auto-retrieve "blue preference"
       ↓
  Personalized recommendation ✨
```

### Core Stack

| Tech | Role |
|------|------|
| **[Mem0](https://github.com/mem0ai/mem0)** | Memory management framework (Python SDK) |
| **[Qdrant](https://github.com/qdrant/qdrant)** | Local vector database (Docker, one-command startup) |
| **OpenClaw Sessions** | Source of conversation history (JSONL files) |
| **watch_sessions.js** | Real-time session monitoring, auto-triggers memory writes |

**100% local deployment. Your data, your control.**

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Conversation                         │
│          (Feishu / WhatsApp / Discord / Terminal ...)           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    OpenClaw Agent Session                        │
│             /root/.openclaw/agents/{agent}/sessions/            │
│                         *.jsonl files                           │
└────────────────────────┬────────────────────────────────────────┘
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
┌───────────────────────┐   ┌───────────────────────────────────┐
│  watch_sessions.js    │   │     memory_distill_daily.py       │
│  (Real-time Monitor,  │   │     (Daily Distillation,          │
│   Node.js process)    │   │      cron 04:00-04:25)            │
│  Polls every 5 secs   │   │     Distills convos into         │
│                       │   │     distilled memory blocks        │
└───────────┬───────────┘   └──────────────┬────────────────────┘
            │                              │
            ▼                              ▼
┌───────────────────────────────────────────────────────────────┐
│                      sync_to_mem0.py                          │
│  Real-time: conversation → Qdrant (realtime layer, score=3)   │
│  Daily: distilled blocks → Qdrant (distilled layer, score=3-5) │
└────────────────────────────┬──────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Qdrant Vector Database                      │
│                  localhost:6333 (Docker)                        │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ mem0_main   │  │ mem0_dev    │  │ mem0_capital│  ...      │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│                                                                  │
│  Each record metadata: layer / score / agent_id / created_at    │
└────────────────────────────┬──────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      auto_recall.py                            │
│  Auto-retrieves before every reply:                            │
│  ① Qdrant semantic search (distilled memory, filtered by score) │
│  ② Append recent 20 realtime entries (by time order)            │
│  ③ Fill in session context (source file + raw conversation)    │
└────────────────────────────┬──────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AI Agent Reply                             │
│  "Based on what you said earlier, you prefer blue, so I'd       │
│   recommend this..."                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
openclaw-memory-enhance/
│
├── README.md                    # This file, project overview
├── AGENT_GUIDE.md              # AI Agent configuration guide (for AI agents)
├── install.sh                   # One-command install script
│
├── scripts/                     # ⭐ Core scripts (shared by all agents)
│   │
│   │  ── Real-time Monitor ──
│   ├── watch_sessions.js        # Node.js process, monitors session file changes
│   │                            # Polls every 5 seconds, auto-triggers sync on new content
│   │
│   │  ── Memory Write ──
│   ├── sync_to_mem0.py          # Real-time write: conversation → Qdrant (realtime layer)
│   │                            # Writes with metadata: layer=realtime, score=3
│   │                            # Parses Feishu format, extracts real user messages
│   │
│   │  ── Memory Retrieval ──
│   ├── auto_recall.py           # v11: Called before every reply, returns formatted memory
│   │                            # Semantic search (excludes realtime) + realtime append (server-side filter) + dedup
│   │
│   │  ── Daily Distillation ──
│   ├── memory_distill_daily.py  # v5: Daily cron job (cleans noise before distilling)
│   │                            # Distills raw conversations into refined memory blocks
│   │                            # (LLM scored 1-5)
│   │                            # Supports per-session checkpoint/resume + distillation log
│   │
│   │  ── Cleanup ──
│   ├── memory_cleanup.py        # Runs at 03:00 daily, cleans low-score memories
│   ├── is_noise.py             # Shared noise detection function
│   └── cleanup_noise_realtime.py # One-time noise cleanup utility
│   │
│   │  ── Utilities ──
│   ├── auto_memory.py           # Manually save a single memory
│   ├── mem0-agent.py            # CLI tool: stats / status / search
│   ├── parse_sync_memory.py     # Parse sync-written memories
│   ├── sync_all_to_mem0.py      # Full sync (manual trigger)
│   ├── test_recall.py           # Retrieval test script
│   ├── config.env.example       # Environment variable template
│   │
│   └── backup/                   # Backup scripts
│
├── crontab                       # System crontab configuration
│
└── docs/                         # Supplementary documents (optional)
```

**Key Design Principle**: All agents **share the same scripts**, using `--agent-id` or environment variables to specify which agent's data to operate on.

---

## 🧠 Four-Layer Memory Architecture

The system uses a **four-layer memory architecture**, each layer serving different purposes and lifecycles:

```
┌──────────────────────────────────────────────────────────────┐
│  🍯 Semantic Layer                                           │
│  Purpose: User preferences, communication style, language     │
│  Examples: "User prefers concise replies", "User speaks      │
│             Chinese", "User is called Fuge"                  │
│  Trigger: User expresses preferences, habits, identity      │
├──────────────────────────────────────────────────────────────┤
│  📅 Episodic Layer                                           │
│  Purpose: Historical decisions, major events, project status │
│  Examples: "User chose Qdrant", "Project selection done"      │
│  Trigger: User makes decisions, describes events, evaluates  │
├──────────────────────────────────────────────────────────────┤
│  ⚙️ Procedural Layer                                         │
│  Purpose: Workflows, operational steps, agreed rules         │
│  Examples: "Need weekly progress report on Mondays",        │
│             "Deployment uses docker-compose"                 │
│  Trigger: User sets rules, describes processes, makes reqs    │
├──────────────────────────────────────────────────────────────┤
│  ⚡ Realtime Layer                                           │
│  Purpose: Raw records of the current conversation           │
│  Examples: "What did the user just ask?", "What did the     │
│             assistant just reply?"                           │
│  Trigger: Written in real-time for every conversation        │
│           (realtime layer, score=3, no filtering)            │
└──────────────────────────────────────────────────────────────┘
```

### Scoring Rules

| Score | Type | Description | Store in Main DB |
|-------|------|-------------|-----------------|
| ⭐⭐⭐⭐⭐ 5 | Core Info | Name, identity, relationships, major commitments | ✅ |
| ⭐⭐⭐⭐ 4 | Important Preference | Likes/dislikes, significant habits | ✅ |
| ⭐⭐⭐ 3 | General Info | Daily conversation, useful but not critical | ✅ |
| ⭐ 1-2 | Low Value | Small talk, greetings | ❌ Clean up |

---

## 🔄 Two Memory Write Modes

### Mode 1: Real-time Write (sync_to_mem0.py)

**Goal**: Not a single message missed.

```
User ←→ AI conversation
         ↓
    Every message pair (user + assistant) auto-written to Qdrant
         ↓
    metadata: layer=realtime, score=3
```

**Characteristics**:
- 100% coverage, no conversation lost
- No length filtering (minimum 5 characters)
- Auto-parses Feishu System wrapping
- Supports content-as-list JSONL format
- Default score=3

### Mode 2: Daily Distillation (memory_distill_daily.py)

**Goal**: Refine essence, remove noise.

```
session JSONL files (large volume of raw conversations)
         ↓
    LLM scoring + content distillation
         ↓
    Refined blocks written to Qdrant
         ↓
    metadata: layer=semantic/episodic/procedural, score=3-5
```

**Characteristics**:
- Per-session checkpoint/resume (no duplicate processing)
- Distillation log table (Qdrant collection) tracks each session's state
- Supports `.reset.TIMESTAMP` renamed file UUID tracing
- Auto-cleanup of low-score memories older than 30 days

---

## 📊 Cron Scheduled Tasks

All tasks recorded in `crontab`, executed daily:

| Time | Task | Description |
|------|------|-------------|
| `03:00` | memory_cleanup.py | Clean low-score memories older than 30 days |
| `04:00` | memory_distill (batch 1) | Batch 1 |
| `04:05` | memory_distill (batch 2) | Batch 2 |
| `04:10` | memory_distill (batch 3) | Batch 3 |
| `04:15` | memory_distill (batch 4) | Batch 4 |
| `04:20` | memory_distill (batch 5) | Batch 5 |
| `04:25` | memory_distill (batch 6) | Batch 6 |
| `23:59` | sync_sessions_to_memory.js | Daily full sync |

---

## 🚀 Quick Start

### Prerequisites

- Linux (Ubuntu 20.04+)
- Python 3.8+
- Docker (for Qdrant vector database)
- OpenClaw installed and running

### Step 1: Start Qdrant

```bash
docker run -d --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

### Step 2: Configure Environment Variables

```bash
cp scripts/config.env.example /root/.openclaw/mem0-agent-setup/.env
vim /root/.openclaw/mem0-agent-setup/.env
```

Must set:
```bash
OPENAI_API_KEY=sk-xxxxxxxx          # Your SiliconFlow API Key
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
MEM0_USER_ID=fuge                   # Fixed user ID
```

### Step 3: One-Command Install

```bash
cd /root/.openclaw/project/mem0-agent-setup
bash install.sh --auto
```

This automatically:
- Detects already-installed components (no duplicate installs)
- Configures watch processes for all 17 agents
- Sets up cron scheduled tasks

### Step 4: Test

```bash
# Load environment variables
source /root/.openclaw/mem0-agent-setup/.env

# Search memories
python3 scripts/auto_recall.py "Fuge"

# Manually trigger daily distillation (dry run)
python3 scripts/memory_distill_daily.py --agent main --dry-run --yes

# Check agent status
python3 scripts/mem0-agent.py status --agent main
```

---

## 📚 Core Scripts Explained

### watch_sessions.js

> Node.js background process that monitors session file changes.

**How it works**:
```
Poll session directory every 5 seconds
       ↓
Compare file modification times (mtime)
       ↓
New content detected → Read unprocessed message pairs from JSONL
       ↓
Call sync_to_mem0.py to write to Qdrant
```

**Process management**:
```bash
# Check running watch processes
ps aux | grep watch_sessions

# Restart watch for a specific agent
systemctl restart openclaw-session-watch@{agent}

# View logs
journalctl -u openclaw-session-watch@main -f
```

### sync_to_mem0.py

> Python script that writes conversations to Qdrant in real-time.

**Processing logic**:
```python
# 1. Read session JSONL file
# 2. Extract user + assistant message pairs
# 3. Parse Feishu System wrapping, extract real user messages
# 4. Filter: len < 5 or System wrapper residue → skip
# 5. Format as [realtime][score:3] user message
# 6. m.add() write to Qdrant, metadata={'layer': 'realtime'}
```

**Supported session format**:
```jsonl
{"type":"message","message":{"role":"user","content":"[{\"type\":\"text\",\"text\":\"User message\"}]"}}
{"type":"message","message":{"role":"assistant","content":"[{\"type\":\"text\",\"text\":\"Assistant reply\"}]"}}
```

### auto_recall.py

> v11: Memory retrieval script called before every reply.

**Retrieval flow (v11)**:
```
User asks: "What does 天王盖地虎 mean?"
       ↓
① Generate query embedding (bge-large-zh-v1.5)
       ↓
② Qdrant semantic search (top 8, by relevance)
       ↓
③ Parse results:
   - Distilled memories → filter by score (< min_score discard)
   - Realtime memories → no filtering, append all
       ↓
④ Append recent 20 realtime entries④ Append recent 20 realtime entries (by time order, not relevance)
       ↓
⑤ Group by layer (semantic / episodic / procedural / realtime)
       ↓
⑥ Format output:
   
   ## 📚 Related Memories
   
   Semantic memories (user preferences, communication habits):
     [Semantic] User is called Fuge, is the company boss [score=4]
   
   Real-time captured raw memory fragments:
     [Realtime] What does 天王盖地虎 mean? [score=3]
     [Realtime] Two little mice. This is a traditional Chinese password game. [score=3]
```

### memory_distill_daily.py

> v5: Daily conversation distillation script.

**Core functionality**:
- Read session JSONL files
- LLM scoring + content distillation
- Generate refined blocks
- Write to Qdrant (layer = semantic/episodic/procedural)

**Per-session checkpoint/resume**:
```json
// Qdrant: distill_session_records collection
{
  "session_id": "7c86da32-ea18-4a3a-90b7-5d65bb1c2f53",
  "agent_id": "main",
  "remark_1": "2026-03-29T04:30:19",
  "remark_2": "142 lines processed",
  "remark_3": ""
}
```

---

## 🛠️ Operations & Maintenance

### Check all watch processes

```bash
ps aux | grep watch_sessions | grep -v grep
```

### Check cron tasks

```bash
openclaw cron list
openclaw cron runs <task-id>
```

### View Qdrant data statistics

```bash
python3 scripts/mem0-agent.py stats --agent main
```

### Manually trigger memory distillation

```bash
# dry run (don't write, just see how much would be processed)
python3 scripts/memory_distill_daily.py --agent main --dry-run --yes

# force process last N days (fallback for missed runs)
python3 scripts/memory_distill_daily.py --agent main --days 3 --yes
```

### Memory cleanup

```bash
# Clean low-score memories older than 30 days
python3 scripts/memory_cleanup.py 30
```

---

## 📖 Documentation

| Document | Content |
|----------|---------|
| **README.md** | Project overview (this file) |
| **[AGENT_GUIDE.md](AGENT_GUIDE.md)** | AI Agent configuration guide (for AI agents) |
| **[Feishu Doc](https://www.feishu.cn/docx/L0HldmlNSobggfxAohFcRL2nnSh)** | Online documentation with screenshots |

---

## 📝 Changelog

### v11 (2026-04-17)

**auto_recall.py**:
- `qdrant_search`: excludes realtime layer (must_not realtime), avoids duplication with realtime append
- `fetch_recent_realtime`: scroll uses server-side filter (layer=realtime + time range), avoids full scan missing data; adds id+data dual dedup
- `get_realtime_context`: zero-vector search replaced with scroll + time sort (zero vector has no sorting meaning)
- Removed dead code `search_raw_reset_files` (-136 lines)
- Version unified as v11

**sync_to_mem0.py**:
- References `is_noise.py`, filters Cron task output, Agent instructions, HEARTBEAT, OpenClaw internal context at write time

**memory_distill_daily.py**:
- Added `_cleanup_realtime_noise()`, automatically cleans noisy realtime records before each distillation run

**New files**:
- `is_noise.py`: shared noise detection function, avoids duplicate maintenance
- `cleanup_noise_realtime.py`: one-time cleanup utility, supports specified collection

### v8 (2026-03-29)

**auto_recall.py**:
- `qdrant_search` removes layer filtering, supports all layers
- Added `fetch_recent_realtime()` function, appends recent 20 realtime entries
- `parse_memory` supports realtime format `[realtime][score:3]` parsing
- Realtime data not filtered by score, appended in full
- `layer_order` adds "realtime", ensures realtime results output
- `lookup_session_snippets` filters System wrapping and toolResult messages

**sync_to_mem0.py**:
- Removed LLM evaluation, directly writes all conversations
- Fixed Feishu format content parsing (list → string)
- Lowered minimum length threshold 10→5
- Added System wrapping parsing, extracts real user messages
- metadata={'layer': 'realtime'} write to Qdrant

### v7 (2026-03-28)

**auto_recall.py**:
- Qdrant REST API replaced mem0.search()
- Layer filtering: only search Semantic/Episodic/Procedural
- Realtime sync data filtered, no longer interferes with results

### v5 (2026-03-28)

**memory_distill_daily.py**:
- Session distillation log table (Qdrant) replaces local state file
- Per-session checkpoint/resume + UUID tracking
- Supports `.reset.TIMESTAMP` renamed file UUID tracing

### v4 (2026-03-28)

- Per-session checkpoint/resume
- Cron batch schedule (17 agents divided into 6 batches)

---

## 🤝 License

MIT License

---

**🦋 Let every AI Agent no longer be a stranger.**
