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

## 功能

- ✅ **一键安装** — `bash install.sh` 搞定全部
- ✅ **智能检测** — 自动识别已安装组件，不重复安装
- ✅ **多 Agent 自动配置** — 自动检测所有 Agent 并批量配置
- ✅ **自动记忆** — 对话同时自动写入向量库
- ✅ **智能检索（v6）** — 扁平分组输出 + session 上下文内联
- ✅ **多 Agent 支持** — 每个 Agent 独立 collection（`mem0_main` / `mem0_capital` 等）
- ✅ **systemd 自启** — 开机自动运行
- ✅ **每日蒸馏** — 凌晨 4 点自动将对话蒸馏为精华 block
- ✅ **自动清理** — 凌晨 3 点自动删除过期低分记忆

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
                          │ 每天 04:00 distill（memory_distill_daily.py）
                          │ 每天 03:00 cleanup（memory_cleanup.py）
```

**两种记忆写入模式**：
1. **实时写入** — `sync_to_mem0.py` 将对话实时写入向量库（全文）
2. **每日蒸馏** — `memory_distill_daily.py` 将对话蒸馏为精华 block（评分 3 分以上）

## 核心文件

| 脚本 | 功能 | 触发方式 |
|------|------|---------|
| `watch_sessions.js` | 监听 session 目录变化 | systemd 服务 |
| `sync_to_mem0.py` | 将对话实时写入 Qdrant | watch 调用 |
| `auto_recall.py` | 检索记忆 + session 上下文 | 每次回复前 |
| `memory_distill_daily.py` | 每日蒸馏精华 block | cron（每天 04:00） |
| `memory_cleanup.py` | 清理过期低分记忆 | cron（每天 03:00） |

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
# .env 文件位于：/root/.openclaw/mem0-agent-setup/.env（所有 Agent 共用）
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

# 查看记忆数量
python3 scripts/mem0-agent.py stats
```

## Agent ID 检测

auto_recall.py 自动检测当前 agent，优先级：

```
WORKSPACE_DIR 路径推导 > AGENT_NAME 环境变量 > fallback "main"
```

示例：
- `WORKSPACE_DIR=/root/.openclaw/workspace-capital` → agent = `capital`
- `WORKSPACE_DIR=/root/.openclaw/workspace` → agent = `main`
- `AGENT_NAME=capital`（systemd watchdog 设置）

## 多 Agent 配置

| Agent | Collection | 说明 |
|-------|------------|------|
| main | `mem0_main` | 主 Agent |
| capital | `mem0_capital` | 量化 Agent |
| dev | `mem0_dev` | 开发 Agent |

每个 Agent 的 systemd 服务：
- `openclaw-session-watch-main`
- `openclaw-session-watch-capital`
- `openclaw-session-watch-dev`

## 系统要求

- Linux (Ubuntu 20.04+)
- Python 3.8+
- Docker（Qdrant 向量数据库）

## 文档

- [AGENT_GUIDE.md](AGENT_GUIDE.md) — AI Agent 配置指引
- [飞书文档](https://www.feishu.cn/docx/L0HldmlNSobggfxAohFcRL2nnSh)

## 日志目录

每次 cron 执行自动记录到日志文件：

| 日志位置 | 内容 |
|---------|------|
| `/root/.openclaw/cron_log/cleanup_{agent}.log` | cleanup START/END 标记 + 脚本输出 |
| `/root/.openclaw/cron_log/distill_{agent}.log` | distill START/END 标记 + 脚本输出 |
| `/root/.openclaw/workspace/logs/distill_{agent}.log` | distill 详细输出（每批处理、blocks 生成情况） |

日志格式：
```
2026-03-26 03:00:12 CLEANUP main START
没有记忆需要清理
2026-03-26 03:00:15 CLEANUP main END
```

## License

MIT
