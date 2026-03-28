# openclaw memory solution #
# 基于Mem0的openclaw长期记忆本地化解决方案 #

> 🦋 **Agent 必读**：[AGENT_GUIDE.md](AGENT_GUIDE.md) — 面向 AI Agent 的配置指引，帮助你理解系统架构、多 Agent 环境检查方法、以及如何接入新 Agent。

为 AI Agent 配置向量记忆系统，让 AI 拥有"长期记忆"能力。

## 痛点

| 场景 | 问题 |
|------|------|
| **每次重启都是新人** | AI 每次都要用户重复介绍自己的情况 |
| **上下文越来越长** | 对话历史越来越长，API 成本暴增 |
| **重要信息被遗忘** | 用户说过偏好/需求，转头就忘了 |
| **多 Agent 记忆混乱** | 多个 AI Agent 之间记忆互相串台 |

**本质问题**：大语言模型没有长期记忆能力！

## 解决方案

Mem0 Agent Setup = **Mem0 + Qdrant + 自动化部署**

> 基于 [Mem0](https://github.com/mem0ai/mem0) 开发，**本地部署**，所有数据存储在你自己的 Qdrant 向量数据库中，隐私安全可控。

```
用户说"我最喜欢蓝色" → 自动存储到向量数据库
用户下次问"有什么推荐" → 自动检索"蓝色偏好" → 个性化推荐
```

**核心能力**：
- 🧠 **语义记忆** — 理解含义，不是关键词匹配
- 📝 **自动同步** — 对话同时写入，无需人工介入
- 🔍 **智能检索** — 每次回复前自动读取相关记忆
- 🔒 **多 Agent 隔离** — 每个 Agent 记忆完全隔离
- 📎 **来源追溯** — 每条记忆记录来自哪个 session 文件
- ⚡ **断点续传** — Per-session 独立记录已处理行数，不重复处理

## 功能

- ✅ **一键安装** — `bash install.sh` 搞定全部
- ✅ **智能检测** — 自动识别已安装组件，不重复安装
- ✅ **多 Agent 自动配置** — 自动检测所有 Agent 并批量配置
- ✅ **自动记忆** — 对话同时自动写入向量库（watch_sessions.js）
- ✅ **智能检索（v6）** — 扁平分组输出 + session 上下文内联
- ✅ **多 Agent 支持** — 每个 Agent 独立 collection（`mem0_main` / `mem0_capital` 等）
- ✅ **Per-session 断点续传** — v5，每个 session 独立记录进度，不重复处理
- ✅ **Session 蒸馏记录表** — v5，Qdrant 表记录每个 session 蒸馏状态，支持 UUID 追踪（含 .reset 重命名文件）
- ✅ **每日分批蒸馏** — 17 个 agent 分批在 04:00-04:25 执行
- ✅ **自动清理** — 凌晨 03:00 清理过期低分记忆
- ✅ **状态文件隔离** — 各 agent 状态存在各自 workspace

## 系统架构

```
┌─────────────┐    ┌──────────────┐    ┌─────────────────┐
│  用户对话   │───▶│ sessions目录  │───▶│ watch_sessions  │
└─────────────┘    └──────────────┘    └────────┬────────┘
                                                  │
                                                  ▼
                                        ┌─────────────────┐
                                        │ sync_to_mem0.py  │
                                        └────────┬────────┘
                                                  │
                    ┌──────────────────────────────┘
                    ▼
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  用户回复   │◀───│ 智能检索     │◀───│ Qdrant 向量库│
└─────────────┘    │ auto_recall  │    └─────────────┘
                   └──────────────┘
                          ▲
                          │ 每天 04:00-04:25 分批 distill（memory_distill_daily.py v4）
                          │ 每天 03:00 cleanup（memory_cleanup.py）
```

**两种记忆写入模式**：
1. **实时写入** — `sync_to_mem0.py` 将对话实时写入向量库（全文）
2. **每日蒸馏** — `memory_distill_daily.py` 将对话蒸馏为精华 block（评分 3 分以上）

## 核心文件

| 脚本 | 功能 | 触发方式 |
|------|------|---------|
| `watch_sessions.js` | 监听 session 目录变化 | node 进程（自启动） |
| `sync_to_mem0.py` | 将对话实时写入 Qdrant | watch 调用 |
| `auto_recall.py` | 检索记忆 + session 上下文 | 每次回复前 |
| `memory_distill_daily.py` | 每日蒸馏精华 block（v4） | cron（每天 04:00-04:25） |
| `memory_cleanup.py` | 清理过期低分记忆 | cron（每天 03:00） |

## Per-Session 断点续传（v4）

`memory_distill_daily.py` v4 实现 Per-Session 独立进度：

```json
{
  "sessions": {
    "7c86da32-ea18-4a3a-90b7-5d65bb1c2f53.jsonl": {
      "processed_lines": 142,
      "distilled_at": "2026-03-28T04:30:19"
    }
  },
  "global_last_run": "2026-03-28T04:35:00"
}
```

**优势**：
- 同一 session 的新消息不会被重复蒸馏
- 每个 session 独立追踪进度
- 状态文件存在各 agent 自己的 workspace

## Cron 任务分批时间表

| 时间 | 任务 | Agent |
|------|------|-------|
| 03:00 | 记忆清理（main） | main |
| 04:00 | 记忆蒸馏 | main, capital, dev |
| 04:05 | 记忆蒸馏 | bingbu, gongbu |
| 04:10 | 记忆蒸馏 | legal, ops |
| 04:15 | 记忆蒸馏 | libu_hr, menxia, rich |
| 04:20 | 记忆蒸馏 | xingbu |
| 04:25 | 记忆蒸馏 | zaochao, zhongshu, shangshu, taizi, hubu, libu |

## 评分规则

| 评分 | 说明 | 存入主库 |
|------|------|---------|
| 5 分 | 核心信息（名字、身份、关系、承诺） | ✅ |
| 4 分 | 重要偏好（喜欢、讨厌、重要习惯） | ✅ |
| 3 分 | 一般信息（日常对话） | ✅ |
| 1-2 分 | 无价值（客套话） | ❌ |

## 快速开始

### 1. 配置环境变量

```bash
cp scripts/config.env.example /root/.openclaw/mem0-agent-setup/.env
vim /root/.openclaw/mem0-agent-setup/.env
# 必须设置：OPENAI_API_KEY
```

### 2. 一键安装

```bash
# 自动检测并配置所有 Agent（推荐）
bash install.sh --auto

# 安装单个 Agent
bash install.sh --agent-id capital

# 卸载
bash install.sh --uninstall
bash install.sh --uninstall-all
```

### 3. 测试

```bash
# 加载环境变量
. /root/.openclaw/mem0-agent-setup/.env

# 搜索记忆
python3 scripts/auto_recall.py "关键词"

# 手动触发 distill（dry run）
python3 scripts/memory_distill_daily.py --agent main --dry-run --yes

# 手动触发 cleanup
python3 scripts/memory_cleanup.py 30
```

## Agent ID 检测

auto_recall.py 自动检测当前 agent，优先级：

```
WORKSPACE_DIR 路径推导 > AGENT_NAME 环境变量 > fallback "main"
```

## 多 Agent 配置（17 个 Agent）

| Agent | Collection | 状态文件位置 |
|-------|------------|-------------|
| main | `mem0_main` | `/root/.openclaw/workspace/.distill_state.json` |
| capital | `mem0_capital` | `/root/.openclaw/workspace-capital/.distill_state.json` |
| dev | `mem0_dev` | `/root/.openclaw/workspace-dev/.distill_state.json` |
| legal | `mem0_legal` | `/root/.openclaw/workspace-legal/.distill_state.json` |
| ops | `mem0_ops` | `/root/.openclaw/workspace-ops/.distill_state.json` |
| bingbu | `mem0_bingbu` | 各 workspace |
| hubu | `mem0_hubu` | 各 workspace |
| gongbu | `mem0_gongbu` | 各 workspace |
| libu | `mem0_libu` | 各 workspace |
| libu_hr | `mem0_libu_hr` | 各 workspace |
| menxia | `mem0_menxia` | 各 workspace |
| rich | `mem0_rich` | 各 workspace |
| shangshu | `mem0_shangshu` | 各 workspace |
| taizi | `mem0_taizi` | 各 workspace |
| xingbu | `mem0_xingbu` | 各 workspace |
| zaochao | `mem0_zaochao` | 各 workspace |
| zhongshu | `mem0_zhongshu` | 各 workspace |

所有 17 个 agent 的 watch_sessions.js 进程均已启动并运行中。

## 系统要求

- Linux (Ubuntu 20.04+)
- Python 3.8+
- Docker（Qdrant 向量数据库，运行于 localhost:6333）

## 文档

- [AGENT_GUIDE.md](AGENT_GUIDE.md) — AI Agent 配置指引
- [飞书文档](https://www.feishu.cn/docx/L0HldmlNSobggfxAohFcRL2nnSh)

## 更新日志

### v8 (2026-03-28)
- `auto_recall.py`：Step 4 + Step 5 改进，实现 Active Recall
  - Step 4：**加载整个 session 文件**（移除 keyword 匹配，直接读取完整内容）
  - Step 5：**加载 24h 内 realtime 对话**（当前 session 文件 + Qdrant 实时数据）
  - 召回输出 = 历史蒸馏记忆 + 当前实时对话

### v7 (2026-03-28)
- `auto_recall.py`：Qdrant REST API + layer 过滤，只搜 distilled block
  - 替换 mem0.search() 为直接 Qdrant API
  - Realtime sync 数据（无 layer 字段）被过滤，不再干扰结果

### v5 (2026-03-28)
- **Session 蒸馏记录表**：新增 `distill_session_records` collection（Qdrant）
  - 字段：`session_id`（UUID）| `agent_id` | `remark_1` | `remark_2` | `remark_3`
  - 蒸馏前查表：已蒸馏则跳过，未蒸馏则处理
  - 支持 `.reset.TIMESTAMP` 重命名文件的 UUID 追溯
  - 替换 V4 的 per-session 状态文件为 Qdrant 统一记录表
- `memory_distill_daily.py` v5：整合蒸馏记录表 + 断点续传

### v4 (2026-03-28)
- Per-session 断点续传：每个 session 独立记录已处理行数
- 状态文件改为各 agent 自己的 workspace
- 新增 `--cleanup` 参数
- Cron 分批时间表（17 agent 分 6 批，04:00-04:25）

### v3 (2026-03-26)
- 支持 17 个 agent 同时蒸馏
- 批量处理优化
- 新增每日分批执行

## License

MIT
