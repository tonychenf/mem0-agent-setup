# Mem0 Agent Setup

为 AI Agent 配置向量记忆系统，让 AI 拥有"长期记忆"能力。

## 😰 痛点

你是否遇到过这些问题？

| 场景 | 问题 |
|------|------|
| **每次重启都是新人** | AI 客服每次都要用户重复介绍自己的情况 |
| **上下文越来越长** | 对话历史越来越长，API 成本暴增 |
| **重要信息被遗忘** | 用户说过偏好/需求，转头就忘了 |
| **多 Agent 记忆混乱** | 多个 AI Agent 之间记忆互相串门 |

**本质问题**：大语言模型没有长期记忆能力！

## 💡 解决方案

Mem0 Agent Setup = **Mem0 + Qdrant + 自动化部署**

> 本项目基于 [Mem0](https://github.com/mem0ai/mem0) 开发，采用**本地部署**方案，所有数据存储在你的 Qdrant 向量数据库中，**隐私安全可控**。

## ⚠️ 前置要求

使用本项目前，你需要准备：

| 资源 | 说明 | 获取方式 |
|------|------|---------|
| **LLM API** | 用于语义理解和生成 | [SiliconFlow](https://siliconflow.cn) / [OpenAI](https://platform.openai.com) |
| **Embedding API** | 用于将文本转为向量 | 同上（可用同一服务商） |
| **Qdrant** | 向量数据库 | 本地 Docker 部署（install.sh 自动完成） |

> 💡 **API 费用**：LLM + Embedding 组合使用，成本约 ¥1/天（1000条记忆）

```
用户说"我最喜欢蓝色" → 自动存储到向量数据库
用户下次问"有什么推荐" → 自动检索"蓝色偏好" → 个性化推荐
```

**核心能力**：
- 🧠 **语义记忆**：不是关键词匹配，而是理解含义
- 📝 **自动同步**：对话自动写入，无需人工介入
- 🔍 **智能检索**：每次回复前自动读取相关记忆
- 🔒 **隐私隔离**：不同用户/Agent 记忆完全隔离

## ✨ 功能

- ✅ **一键安装**：bash install.sh 搞定全部
- ✅ **智能检测**：自动识别已安装组件，不重复安装
- ✅ **重复检测**：安装前自动检测重复配置，询问用户处理方式
- ✅ **多 Agent 自动配置**：自动检测 OpenClaw 中的所有 Agent 并批量配置
- ✅ **自动记忆**：对话同时自动写入向量库
- ✅ **智能检索**：每次回复前自动检索相关记忆
- ✅ **多 Agent 支持**：main / capital / dev 等独立记忆
- ✅ **systemd 自启**：开机自动运行，永不丢失
- ✅ **命令行工具**：status / stats / search 随时查看

### 🆕 v3.1 新功能

| 功能 | 说明 |
|------|------|
| **重要性评分** | 1-5分自动评分，核心信息(5分)永不过期 |
| **记忆分类** | 自动分类为 episodic/semantic/procedural |
| **Rerank排序** | LLM 二次排序，提升相关性 |
| **自动清理** | 定时删除过期记忆（cron 可选） |

### 评分规则

```
5分: 核心信息（名字、身份、关系、承诺）
4分: 重要偏好（喜欢、讨厌、重要习惯）
3分: 一般信息（日常对话）
2分: 临时信息（随手提到）
1分: 无价值（客套话）
```

### 过期清理

```bash
# 手动清理（删除30天前的低分记忆）
python3 scripts/memory_cleanup.py

# 可设置 cron 每天自动执行
0 3 * * * python3 /root/.openclaw/workspace/memory_cleanup.py
```

## 📋 适用场景

| 场景 | 说明 |
|------|------|
| **AI 客服** | 记住用户历史问题和偏好 |
| **个人 AI 助手** | 记住主人的喜好、习惯、目标 |
| **多 Agent 系统** | 每个 Agent 独立记忆，不串台 |
| **知识助手** | 记住用户的专业背景和查询习惯 |

## 🚀 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/tonychenf/mem0-agent-setup.git
cd mem0-agent-setup
```

### 2. 配置环境变量

```bash
# 复制配置模板
cp scripts/config.env.example .env

# 编辑 .env 文件，填入你的 API Key
vim .env

# 或者直接设置环境变量（推荐）
export OPENAI_API_KEY="your-api-key-here"
export OPENAI_BASE_URL="https://api.siliconflow.cn/v1"
```

> ⚠️ **必须设置 `OPENAI_API_KEY`** 环境变量，否则脚本无法运行

### 3. 一键安装

```bash
# 安装单个 Agent（默认 main）
bash install.sh

# 自动检测并配置所有 Agent（推荐！）
bash install.sh --auto

# 指定 Agent
bash install.sh --agent-id capital

# 卸载
bash install.sh --uninstall
bash install.sh --uninstall-all
```

> 💡 `--auto` 会自动检测 OpenClaw 中的所有 Agent（main、capital、dev 等），并为每个 Agent 配置独立的记忆系统

### 4. 测试一下

```bash
# 查看状态
mem0-agent status

# 查看记忆数量
mem0-agent stats

# 搜索记忆
mem0-agent search "我的偏好"
```

## 📖 配置说明

### 环境变量配置（必需）

```bash
# 必需：LLM API Key
export OPENAI_API_KEY="your-siliconflow-or-openai-api-key"

# 可选：API Base URL（默认使用 SiliconFlow）
export OPENAI_BASE_URL="https://api.siliconflow.cn/v1"

# 可选：Qdrant 地址（默认 localhost:6333）
export QDRANT_HOST="localhost"
export QDRANT_PORT="6333"
```

### 多 Agent 配置

每个 Agent 有独立的 systemd 服务和 collection，通过 agent_id 区分：

| Agent | Collection | 说明 |
|-------|------------|------|
| main | mem0_main | 主 Agent |
| capital | mem0_capital | 量化 Agent |
| dev | mem0_dev | 开发 Agent |
| ... | ... | 可扩展 |

Agent 识别优先级：
1. 环境变量 `AGENT_NAME`
2. 工作目录路径（如 `/root/.openclaw/agents/capital/` → `capital`）
3. 默认 `main`

## 🔍 配置重复检测

安装时会自动检测重复配置，检测项目包括：

| 检测项 | 说明 |
|--------|------|
| Qdrant | 容器或服务是否已存在 |
| systemd 服务 | 服务是否已部署 |
| 监听脚本 | watch_sessions.js 是否已部署 |
| 同步脚本 | sync_to_mem0.py 是否已部署 |
| Mem0 包 | Python 包是否已安装 |

### 检测行为

**非自动模式（默认）**：
- 安装前弹出提示，列出重复项
- 用户选择：`[o]覆盖` / `[s]跳过` / `[c]取消`

**自动模式（--auto）**：
- 自动跳过已存在的配置项
- 仅安装缺失的组件

### 输出示例

```
⚠️  检测到以下重复配置:
   1. Qdrant 服务已在运行 (localhost:6333)
   2. systemd 服务已存在: openclaw-session-watch
   3. 监听脚本 watch_sessions.js 已部署

请选择操作:
  [o] 覆盖现有配置
  [s] 跳过重复项，仅安装缺失的
  [c] 取消安装

> s
✅ 跳过重复项，仅安装缺失的
```

## 🛠 命令行工具

```bash
mem0-agent status    # 查看服务状态
mem0-agent start     # 启动服务
mem0-agent stop      # 停止服务
mem0-agent restart   # 重启服务
mem0-agent logs      # 查看日志
mem0-agent stats     # 查看记忆数量
mem0-agent search "关键词"  # 搜索记忆
```

## 📂 脚本说明

| 脚本 | 功能 |
|------|------|
| `scripts/auto_memory.py` | 保存记忆（含评分、分类） |
| `scripts/auto_recall.py` | 读取记忆（含 rerank 排序） |
| `scripts/memory_sync.py` | 批量同步历史记忆 |
| `scripts/memory_cleanup.py` | 清理过期记忆 |

## 🧠 工作原理

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  用户对话   │───▶│ sessions目录  │───▶│ 监听脚本    │
└─────────────┘    └──────────────┘    └──────┬──────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │  Mem0 SDK   │
                                        └──────┬──────┘
                                               │
                    ┌──────────────────────────┘
                    ▼
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  用户回复   │◀───│ 语义检索     │◀───│ Qdrant向量库│
└─────────────┘    └──────────────┘    └─────────────┘
```

**读取流程**：
1. 用户发来消息
2. 自动检索向量库中相关记忆
3. 将记忆融入上下文
4. 生成回复

## 🔧 系统要求

- Linux (Ubuntu 20.04+)
- Python 3.8+
- Docker（用于 Qdrant 向量数据库）

## 📚 文档

- [客户端配置指南（飞书文档）](https://www.feishu.cn/docx/Pj1EdcEYyo92wfx1XoTcCiq5nPg)

## 🤝 贡献

欢迎提交 Issue 和 PR！

## 📄 License

MIT
