# Mem0 Memory Enhance 项目详解文档

> 项目路径：`/root/.openclaw/mem0-agent-setup/`
> GitHub：`tonychenf/openclaw-memory-enhance`
> 最新版本：v8（auto_recall）、v5（memory_distill_daily）

---

## 一、项目概述

### 1.1 解决什么问题

LLM 本身没有持久化记忆，每次会话都是从零开始。这个项目为 OpenClaw 的每个 Agent 搭建了**私有向量记忆系统**，实现：

- **记住你是谁**：名字、身份、偏好
- **记住做过什么**：历史决策、事件、项目进展
- **记住怎么做**：工作流程、操作步骤、规则约定
- **记住当下**：当前对话的原始记录

### 1.2 核心技术栈

| 技术 | 作用 |
|------|------|
| **Mem0** | 记忆管理框架（Python SDK），封装向量存储逻辑 |
| **Qdrant** | 本地向量数据库（Docker，port 6333），存储所有记忆向量 |
| **OpenClaw Sessions** | 对话历史来源（JSONL 文件），每个 agent 独立目录 |
| **watch_sessions.js** | Node.js 常驻进程，实时监控 session 变化并触发写入 |
| **SiliconFlow API** | 提供 LLM（Qwen2.5-7B）和 Embedding（BGE）能力 |

### 1.3 记忆分层体系

系统采用**四层记忆架构**：

```
┌──────────────────────────────────────────────────────────────┐
│  🍯 Semantic（语义层）                                        │
│  内容：用户偏好、沟通风格、语言习惯、身份关系                       │
│  示例："用户叫孚哥"、"用户喜欢简洁回复"、"用户用中文交流"         │
│  触发：用户明确表达喜好、习惯、身份时                             │
├──────────────────────────────────────────────────────────────┤
│  📅 Episodic（事件层）                                        │
│  内容：历史决策、重大事件、项目进展                               │
│  示例："用户决定用 Qdrant"、"项目已完成选型"                     │
│  触发：用户做出决定、描述事件、评价结果时                         │
├──────────────────────────────────────────────────────────────┤
│  ⚙️ Procedural（程序层）                                      │
│  内容：工作流程、操作步骤、规则约定                               │
│  示例："每周一汇报进度"、"部署用 docker-compose"               │
│  触发：用户制定规则、说明流程、提出要求时                         │
├──────────────────────────────────────────────────────────────┤
│  ⚡ Realtime（实时层）                                        │
│  内容：当前对话的原始记录                                       │
│  示例："用户问了什么"、"助手答了什么"                           │
│  触发：每次对话实时写入（不过滤，score=3）                       │
└──────────────────────────────────────────────────────────────┘
```

### 1.4 评分规则

| 评分 | 类型 | 说明 | 保留策略 |
|------|------|------|---------|
| ⭐⭐⭐⭐⭐ 5分 | 核心信息 | 名字、身份、重要关系、重大承诺 | 永不过期 |
| ⭐⭐⭐⭐ 4分 | 重要偏好 | 喜欢/讨厌、重要习惯 | 永不过期 |
| ⭐⭐⭐ 3分 | 一般信息 | 日常对话、有价值的事实 | 180天后清理 |
| ⭐⭐ 2分 | 临时信息 | 随口提到、可忽略 | 90天后清理 |
| ⭐ 1分 | 无价值 | 客套话、问候 | 30天后清理 |

---

## 二、文件清单与详解

### 2.1 项目根目录文件

```
mem0-agent-setup/
├── README.md                    # 中英双语项目介绍（使用说明、快速开始）
├── AGENT_GUIDE.md               # 面向 AI Agent 的配置指引手册
├── memory_design.md             # 设计方案文档（v4 per-session断点续传）
├── install.sh                   # 一键安装脚本
├── setup.py                     # Python 包安装配置
├── .env                         # 环境变量配置文件（API密钥等）
└── scripts/                     # 核心脚本目录
```

---

### 2.2 scripts/ 目录详解

```
scripts/
├── watch_sessions.js           # 【实时监控】Node.js 常驻进程
├── sync_to_mem0.py             # 【实时写入】对话 → Qdrant（realtime层）
├── auto_recall.py              # 【记忆检索】每次回复前调用
├── memory_distill_daily.py     # 【每日蒸馏】对话 → 精华block（v5）
├── memory_cleanup.py           # 【清理维护】删除过期记忆
├── memory_sync.py              # 【批量同步】手动全量同步
├── auto_memory.py              # 【手动保存】单条记忆写入
├── mem0-agent.py               # 【CLI工具】stats/status/search
├── session_pre_reset_sync.sh   # 【安全阀】session reset前紧急同步
├── rebuild_vectors.py          # 【重建索引】重新构建向量索引
├── memory_reclassify.py        # 【重新分类】批量修改记忆层级
├── distill_legal_*.py          # 【专项蒸馏】法律agent专项
├── gen_crons.py                # 【cron生成】自动生成crontab配置
├── sync_reset_file.py          # 【reset同步】处理.reset文件
└── config.env.example          # 环境变量模板
```

#### 2.2.1 watch_sessions.js（实时监控）

**作用**：Node.js 常驻进程，监控 session 文件变化，检测到新对话时自动触发 sync。

**工作原理**：
```
每 5 秒轮询 session 目录
         ↓
比对文件修改时间（mtime）和大小（size）
         ↓
发现变化 → 读取新增的 user+assistant 消息对
         ↓
调用 sync_to_mem0.py 写入 Qdrant
```

**增强功能（v2）**：
- **文件删除检测**：session reset 时文件消失，检测到后立即尝试同步剩余内容
- **Pre-reset 触发器**：检测到 `/tmp/.pre_reset_sync.{agent}` 文件时，执行全量同步
- **加速轮询**：发现变化后自动切换到 500ms 快速轮询，10秒后恢复 5s 基础轮询

**进程管理**：
```bash
# 查看运行状态
ps aux | grep watch_sessions

# 重启某个 agent 的 watch
systemctl restart openclaw-session-watch@{agent}

# 查看日志
journalctl -u openclaw-session-watch@main -f
```

**同步策略**：
- 普通文件：只同步**最后 10 条**消息对
- `.reset` 文件：**全量同步**所有消息（因为包含历史内容）

---

#### 2.2.2 sync_to_mem0.py（实时写入）

**作用**：将对话实时写入 Qdrant，写入格式为 `[realtime][score:3]`。

**处理逻辑**：
```python
# 1. 从 stdin 读取 JSON 格式的消息列表
# 2. 遍历消息，提取 user + assistant 消息对
# 3. 解析 Feishu System 包装，提取真正用户消息
#    （飞书消息外层包裹了 System: header，需要提取内部真正内容）
# 4. 过滤：长度 < 5 字符的跳过
# 5. 格式化为 [realtime][score:3] 用户消息
# 6. 调用 m.add() 写入 Qdrant，metadata={'layer': 'realtime'}
```

**支持的 session JSONL 格式**：
```jsonl
{"type":"message","message":{"role":"user","content":"[{\"type\":\"text\",\"text\":\"用户消息\"}]"}}
{"type":"message","message":{"role":"assistant","content":"[{\"type\":\"text\",\"text\":\"助手回复\"}]"}}
```

**注意**：此脚本**不做 LLM 筛选**，所有对话都直接写入（保证不漏），但统一为 score=3 的 realtime 层。

---

#### 2.2.3 auto_recall.py（记忆检索）

**作用**：每次回复前调用的记忆检索脚本，返回格式化的相关记忆。

**当前版本**：v8

**检索流程**：
```
用户查询（query）
       ↓
① 生成 query embedding（BGE/bge-large-zh-v1.5，1024维）
       ↓
② Qdrant 语义搜索（top 8，按相关性）
       ↓
③ 解析结果：
   - 蒸馏记忆（semantic/episodic/procedural）→ 按 score ≥ min_score 过滤
   - realtime 记忆 → 不过滤，全部追加
       ↓
④ 追加最近 20 条 realtime（按时序排序，不按相关度）
       ↓
⑤ 后备：搜索 .reset 文件中的原始对话（补充向量搜不到的情况）
       ↓
⑥ 按 layer 分组（semantic → episodic → procedural → realtime）
       ↓
⑦ 每条 block 补全 session 上下文（来源文件 + 原始对话片段）
       ↓
⑧ 格式化输出
```

**输出格式示例**：
```
## 📚 相关记忆

回答请符合用户偏好、沟通习惯、语言风格：
  [语义]用户叫孚哥，是公司老板 [score=4] | [当前Session]: User: 你好

回答请参考用户的历史决策、重大事件：
  [事件]用户决定用 Qdrant 作为向量数据库 [score=5]

实时捕获的原始记忆片段：
  [实时]用户问：什么是天王盖地虎？ [score=3]
  [实时]助手答：两只小老鼠... [score=3]
```

**关键函数**：
- `embed_query()`：生成 query 向量
- `qdrant_search()`：Qdrant REST API 语义搜索
- `fetch_recent_realtime()`：获取最近 N 条 realtime（无时间过滤，只按时间排序）
- `parse_memory()`：解析 `[层级:Semantic][score:5][distilled]...` 格式
- `lookup_session_snippets()`：补全 session 原始对话上下文
- `get_current_session_path()`：找到当前活跃的 session 文件

**设计缺陷（已识别未修复）**：
- `fetch_recent_realtime()` 的 docstring 说"24小时"，但代码里**没有时间过滤**，是全量扫描后按时间排序取 top 20

---

#### 2.2.4 memory_distill_daily.py（每日蒸馏）

**作用**：每日 cron 任务，将原始对话蒸馏为精华记忆块，评分后写入 Qdrant。

**当前版本**：v5

**核心功能**：
1. 扫描 session JSONL 文件
2. LLM 批量评分 + 内容提炼
3. 生成精华 block（layer = semantic/episodic/procedural，score = 1-5）
4. 写入 Qdrant

**Per-Session 断点续传机制（v5 改进）**：
```
蒸馏记录表（Qdrant collection: distill_session_records）
    ↓
记录每个 session_id 的蒸馏状态
    ↓
蒸馏前查表：已蒸馏 → 跳过；未蒸馏 → 处理
    ↓
每个 session 独立记录 processed_lines（行数断点）
```

**状态文件**（各 agent 独立）：
```json
{
  "sessions": {
    "1589659c-8407-406a-a383-5dc74a7335c3.jsonl": {
      "processed_lines": 142,
      "distilled_at": "2026-03-29T04:30:19",
      "current_lines": 142
    }
  },
  "global_last_run": "2026-03-29T04:35:00"
}
```

**处理流程**：
```
get_session_with_progress()
    ├── 扫描所有 session 文件（*.jsonl + *.reset.*）
    ├── 提取 UUID（支持 .reset.TIMESTAMP 重命名格式）
    ├── 批量查蒸馏记录表（batch_check_sessions）
    ├── 过滤已蒸馏的 session
    └── 返回：[(filepath, uuid_str, start_line), ...]

read_sessions_from_file()
    └── 从 start_line 开始读取所有对话

distill_conversations_batched()
    └── 分批（默认80条/批）送 LLM 提炼精华 block

score_blocks()
    └── 分批（默认30条/批）送 LLM 评分（1-5分）

write_blocks()
    └── embedding → Qdrant upsert（每条间隔 0.3s）
```

**支持的文件格式**：
- 正常：`1589659c-8407-406a-a383-5dc74a7335c3.jsonl`
- 重命名：`.reset.TIMESTAMP` 后缀，如 `20889554-a992-4a5c-8832-1ed138489174.jsonl.reset.2026-03-25T22-11-30`

---

#### 2.2.5 memory_cleanup.py（清理维护）

**作用**：定时删除过期记忆，根据分数决定保留天数。

**清理规则**：
```
score=1 → 30天后删除
score=2 → 90天后删除
score=3 → 180天后删除
score>=4 → 永不过期
```

**执行时间**：每日 03:00（cron）

---

#### 2.2.6 其他辅助脚本

| 脚本 | 作用 |
|------|------|
| `auto_memory.py` | 手动保存单条记忆（LLM 评分 + 分类） |
| `mem0-agent.py` | CLI 工具：`stats`（统计）、`status`（状态）、`search`（搜索） |
| `session_pre_reset_sync.sh` | session reset 前的手动安全阀脚本 |
| `rebuild_vectors.py` | 重建向量索引 |
| `memory_reclassify.py` | 批量修改记忆的层级分类 |
| `gen_crons.py` | 自动生成 crontab 配置 |
| `distill_legal_*.py` | 法律 agent 专项蒸馏 |

---

## 三、Qdrant 数据结构

### 3.1 Collection 命名

每个 agent 有独立的 collection：
```
mem0_main       # main agent
mem0_capital    # capital agent
mem0_dev        # dev agent
mem0_legal      # legal agent
...             # 其他 agent 同理
```

额外系统 collection：
```
distill_session_records  # 蒸馏记录表（所有 agent 共用）
```

### 3.2 每条记录的结构

**蒸馏记忆（semantic/episodic/procedural）**：
```json
{
  "id": "uuid字符串",
  "vector": [1024维float数组],
  "payload": {
    "user_id": "fuge",
    "agent_id": "main",
    "role": "user",
    "data": "[层级:Semantic][score:4][distilled][sessions:1][files:/path/to/session.jsonl]\n用户叫孚哥，是公司老板",
    "hash": "uuid",
    "created_at": "2026-03-29T04:30:19",
    "layer": "semantic"
  }
}
```

**实时记忆（realtime）**：
```json
{
  "id": "uuid字符串",
  "vector": [1024维float数组],
  "payload": {
    "user_id": "fuge",
    "agent_id": "main",
    "role": "user",
    "data": "[realtime][score:3] 用户问：什么是天王盖地虎？",
    "hash": "uuid",
    "created_at": "2026-03-29T10:00:00",
    "layer": "realtime"
  }
}
```

---

## 四、系统运行流程

### 4.1 完整数据流

```
┌─────────────────────────────────────────────────────────┐
│                     用户对话                              │
│         （飞书 / WhatsApp / Discord / 终端）               │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              OpenClaw Agent Session                      │
│   /root/.openclaw/agents/{agent}/sessions/               │
│   ├── 7c86da32-...jsonl     （活跃 session）              │
│   └── *.reset.TIMESTAMP      （历史 session）             │
└──────────────────────────┬──────────────────────────────┘
                           │
          ┌────────────────┴────────────────┐
          ▼                                 ▼
┌─────────────────────────┐   ┌──────────────────────────────────┐
│  watch_sessions.js      │   │     memory_distill_daily.py       │
│  （Node.js 常驻进程）     │   │     （每日 cron 04:00-04:25）     │
│  每5秒轮询一次            │   │                                  │
│  检测文件变化 → 触发 sync │   │  对话 → LLM提炼 → 精华block      │
└────────────┬────────────┘   │  → 评分(1-5) → Qdrant写入         │
             │                └──────────────┬───────────────────┘
             ▼                                  │
             │    ┌─────────────────────────────┘
             ▼    ▼
┌─────────────────────────────────────────────┐
│              sync_to_mem0.py                │
│                                             │
│  格式：[realtime][score:3] 用户消息          │
│  metadata: {'layer': 'realtime'}           │
│  写入 Qdrant realtime 层                    │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│           Qdrant 向量数据库                   │
│        localhost:6333（Docker）              │
│                                             │
│  Collection per agent:                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│  │mem0_main│ │mem0_dev │ │mem0_capit│ ... │
│  └──────────┘ └──────────┘ └──────────┘     │
│                                             │
│  + distill_session_records（蒸馏记录表）      │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│              auto_recall.py                 │
│         （每次回复前调用）                    │
│                                             │
│  ① Qdrant 语义搜索（top 8）                  │
│  ② 追加最近20条 realtime                     │
│  ③ 补全 session 上下文                       │
│  ④ 格式化输出                               │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│              AI Agent 回复                   │
│   "根据你之前说的，你最喜欢蓝色..."            │
└─────────────────────────────────────────────┘
```

### 4.2 两种写入模式的区别

| 模式 | 脚本 | 触发 | 覆盖 | 层级 | score | 是否过滤 |
|------|------|------|------|------|-------|---------|
| **实时写入** | sync_to_mem0.py | watch_sessions 检测到变化 | 所有对话 | realtime | 3 | 不过滤 |
| **每日蒸馏** | memory_distill_daily.py | cron（每日04:00） | 未蒸馏的 session | semantic/episodic/procedural | 1-5 | 按分数 |

**为什么需要两种模式？**
- **实时写入**：保证不漏，但质量参差（全是 score=3）
- **每日蒸馏**：LLM 精炼，提炼精华、评分、分层，淘汰无价值内容

### 4.3 Cron 时间表

| 时间 | 任务 | Agent |
|------|------|-------|
| `03:00` | memory_cleanup.py | main |
| `04:00` | memory_distill（第一批） | main, capital, dev |
| `04:05` | memory_distill（第二批） | bingbu, gongbu |
| `04:10` | memory_distill（第三批） | legal, ops |
| `04:15` | memory_distill（第四批） | libu_hr, menxia, rich |
| `04:20` | memory_distill（第五批） | xingbu |
| `04:25` | memory_distill（第六批） | zaochao, zhongshu, shangshu, taizi, hubu, libu |

17 个 agent 分 6 批错峰执行，避免同时调用 LLM 超出速率限制。

---

## 五、auto_recall.py 已知问题

### 5.1 Realtime 时间过滤缺失

**问题**：`get_realtime_context()` 和 `fetch_recent_realtime()` 的 docstring 写的是"最近24小时"，但代码里**完全没有时间过滤逻辑**。

**现状**：
- `fetch_recent_realtime()`：扫描最多 500 条记录，按 `created_at` 倒序取 top 20
- Qdrant 查询：无 `range` 过滤条件

**影响**：会将所有历史的 realtime 记录都拉出来，不是真的只展示24小时内的。

**修复方案**：在 Qdrant 查询的 `filter` 里加 `range` 条件：
```python
{
    "must": [
        {"key": "agent_id", "match": {"any": [agent]}},
        {"key": "role", "match": {"any": ["user", "assistant"]}},
        {"key": "created_at", "range": {"gte": "2026-04-15T00:00:00+08:00"}})
    ]
}
```

### 5.2 Realtime 与蒸馏记忆混杂

**问题**：当前 session 刚结束时的 realtime 记忆，会和蒸馏后的记忆**同时出现在检索结果里**，造成重复。

**例如**：同一个问题"用户叫什么"，可能同时出现：
- `[realtime] 用户问：我叫什么？` (score=3)
- `[语义] 用户叫孚哥` (score=4)

**改进方向**：realtime 结果只展示**当前 session 内的**，历史的 realtime 应该已被蒸馏替代。

---

## 六、运维常用命令

```bash
# 查看所有 watch 进程
ps aux | grep watch_sessions | grep -v grep

# 重启某个 agent 的 watch
systemctl restart openclaw-session-watch@{agent}

# 查看 cron 任务
openclaw cron list

# 手动触发蒸馏（dry run）
python3 /root/.openclaw/mem0-agent-setup/scripts/memory_distill_daily.py \
  --agent main --dry-run --yes

# 强制处理最近3天
python3 /root/.openclaw/mem0-agent-setup/scripts/memory_distill_daily.py \
  --agent main --days 3 --force --yes

# 查看 agent 记忆统计
python3 /root/.openclaw/mem0-agent-setup/scripts/mem0-agent.py stats --agent main

# 搜索记忆
python3 /root/.openclaw/mem0-agent-setup/scripts/auto_recall.py "孚哥"

# 清理30天前低分记忆
python3 /root/.openclaw/mem0-agent-setup/scripts/memory_cleanup.py 30

# Session reset 前手动触发全量同步
bash /root/.openclaw/mem0-agent-setup/scripts/session_pre_reset_sync.sh main
```

---

## 七、文件映射关系

```
Agent workspace                    Memory Collection
/root/.openclaw/agents/main/sessions/   →  mem0_main
/root/.openclaw/agents/capital/sessions/ →  mem0_capital
/root/.openclaw/agents/legal/sessions/  →  mem0_legal
...

Agent workspace                    状态文件
/root/.openclaw/workspace/              →  /root/.openclaw/workspace/.distill_state.json
/root/.openclaw/workspace-capital/      →  /root/.openclaw/workspace-capital/.distill_state.json
...

Systemd service                    进程
openclaw-session-watch@main        →  watch_sessions.js main
openclaw-session-watch@capital     →  watch_sessions.js capital
...
```
