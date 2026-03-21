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
- ✅ **自动记忆**：对话同时自动写入向量库
- ✅ **智能检索**：每次回复前自动检索相关记忆
- ✅ **多 Agent 支持**：main / capital / dev 等独立记忆
- ✅ **systemd 自启**：开机自动运行，永不丢失
- ✅ **命令行工具**：status / stats / search 随时查看

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

### 2. 填写配置

```bash
cp config/config.yaml.example config/config.yaml
# 编辑 config.yaml，填入你的配置
```

### 3. 一键安装

```bash
bash install.sh
```

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

### config.yaml 完整示例

```yaml
# ═══════════════════════════════════════════════════════
# 在这里修改 API 配置（config/config.yaml）
# ═══════════════════════════════════════════════════════

# 向量数据库（Qdrant）- 通常不需要改
qdrant:
  host: localhost
  port: 6333

# LLM API（⚠️ 在这里修改你的 API）
llm:
  api_base_url: "https://api.siliconflow.cn/v1"  # 或 OpenAI: https://api.openai.com/v1
  api_key: "sk-xxxxxxxxxxxxxxxx"                  # ⚠️ 填入你的 API Key
  model: "Qwen/Qwen2.5-7B-Instruct"               # 或其他模型

# Embedding 模型（⚠️ 在这里修改）
embedding:
  model: "BAAI/bge-large-zh-v1.5"   # ⚠️ 填入你的 Embedding 模型
  dimensions: 1024                    # 向量维度

# Agent 配置
agent:
  id: "main"           # Agent 标识
  user_id: "user1"     # 用户标识
  collection: "mem0_main"  # 记忆集合

# 监听配置
watch:
  interval: 5000        # 检查间隔（毫秒）
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
