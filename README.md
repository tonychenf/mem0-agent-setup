# 🧠 openclaw-memory-enhance

> **让 AI Agent 拥有真正的长期记忆** —— 基于 Mem0 + Qdrant 的本地化向量记忆系统，专为 [OpenClaw](https://github.com/openclaw/openclaw) 多 Agent 环境设计。

[![GitHub stars](https://img.shields.io/github/stars/tonychenf/openclaw-memory-enhance)](https://github.com/tonychenf/openclaw-memory-enhance)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

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
├──
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
│   ├── auto_recall.py           # v8：每次回复前调用，返回格式化记忆
│   │                            # 语义搜索 + realtime 追加 + session 上下文
│   │
│   │  ── 每日蒸馏 ──
│   ├── memory_distill_daily.py  # v5：每日 cron 任务
│   │                            # 将原始对话蒸馏为精华 block（LLM 评分 1-5）
│   │                            # 支持 per-session 断点续传 + 蒸馏记录表
│   │
│   │  ── 清理维护 ──
│   ├── memory_cleanup.py         # 每日 03:00 执行，清理低分记忆
│   │
│   │  ── 辅助工具 ──
│   ├── auto_memory.py            # 手动保存单条记忆
│   ├── mem0-agent.py             # CLI 工具：stats / status / search
│   ├── parse_sync_memory.py      # 解析 sync 写入的记忆
│   ├── sync_all_to_mem0.py       # 全量同步（手动触发）
│   ├── test_recall.py            # 检索测试脚本
│   ├── config.env.example         # 环境变量示例
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
| `04:05` | memory_distill (bingbu, gongbu) | 第二批 |
| `04:10` | memory_distill (legal, ops) | 第三批 |
| `04:15` | memory_distill (libu_hr, menxia, rich) | 第四批 |
| `04:20` | memory_distill (xingbu) | 第五批 |
| `04:25` | memory_distill (zaochao, zhongshu, shangshu, taizi, hubu, libu) | 第六批 |
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
MEM0_USER_ID=fuge                    # 固定用户 ID
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

> v8 版本：每次回复前调用的记忆检索脚本。

**检索流程**：
```
用户查询："天王盖地虎是什么意思？"
       ↓
① 生成 query embedding（bge-large-zh-v1.5）
       ↓
② Qdrant 语义搜索（top 8，按相关性）
       ↓
③ 解析结果：
   - 蒸馏记忆 → 按 score 过滤（< min_score 丢弃）
   - realtime 记忆 → 不过滤，全量追加
       ↓
④ 追加最近 20 条 realtime（按时序，不按相关度）
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

## 🐛 多 Agent 支持（17 个 Agent）

| Agent | Collection | 用途 | 状态 |
|-------|------------|------|------|
| main | mem0_main | 主对话 agent | ✅ 运行中 |
| capital | mem0_capital | 量化交易分析 | ✅ 运行中 |
| dev | mem0_dev | 开发助手 | ✅ 运行中 |
| legal | mem0_legal | 法律顾问 | ✅ 运行中 |
| ops | mem0_ops | 运维管理 | ✅ 运行中 |
| rich | mem0_rich | 理财顾问 | ✅ 运行中 |
| bingbu | mem0_bingbu | 兵部 agent | ✅ 运行中 |
| gongbu | mem0_gongbu | 工部 agent | ✅ 运行中 |
| hubu | mem0_hubu | 户部 agent | ✅ 运行中 |
| libu | mem0_libu | 礼部 agent | ✅ 运行中 |
| libu_hr | mem0_libu_hr | 人力资源 | ✅ 运行中 |
| menxia | mem0_menxia | 门下省 | ✅ 运行中 |
| shangshu | mem0_shangshu | 尚书省 | ✅ 运行中 |
| taizi | mem0_taizi | 太子agent | ✅ 运行中 |
| xingbu | mem0_xingbu | 刑部 agent | ✅ 运行中 |
| zaochao | mem0_zaochao | 早朝 agent | ✅ 运行中 |
| zhongshu | mem0_zhongshu | 中书省 | ✅ 运行中 |

**隔离机制**：每个 agent 的记忆存在独立的 Qdrant collection 中，命名格式 `mem0_{agent}`，完全隔离，互不干扰。

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
- Cron 分批时间表（17 agent 分 6 批）

---

## 🤝 License

MIT License

---

**🦋 让每一个 AI Agent 都不再是陌生人。**
