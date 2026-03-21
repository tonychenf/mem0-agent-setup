# Mem0 Agent Setup

为 AI Agent 配置 Mem0 向量记忆系统的自动化安装工具。

## 功能

- ✅ 自动安装 Mem0 和依赖
- ✅ 自动配置 Qdrant 向量数据库
- ✅ 自动部署监听脚本
- ✅ 支持 systemd 开机自启
- ✅ 多 Agent 支持

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/your-repo/mem0-agent-setup.git
cd mem0-agent-setup
```

### 2. 填写配置

复制配置模板并填写：

```bash
cp config/config.yaml.example config/config.yaml
# 编辑 config.yaml，填入你的配置
```

### 3. 一键安装

```bash
bash install.sh
```

## 配置说明

### config.yaml

```yaml
# 向量数据库
qdrant:
  host: localhost
  port: 6333

# LLM API
llm:
  api_base_url: "https://api.siliconflow.cn/v1"
  api_key: "your-api-key"
  model: "Qwen/Qwen2.5-7B-Instruct"

# Embedding
embedding:
  model: "BAAI/bge-large-zh-v1.5"
  dimensions: 1024

# Agent 配置
agent:
  id: "main"
  user_id: "your-user-id"
  collection: "mem0_main"

# 监听配置
watch:
  interval: 5000  # 毫秒
  sessions_dir: "/root/.openclaw/agents/main/sessions"
```

## 命令行选项

```bash
./bin/mem0-agent-setup [选项]

选项:
  --agent-id <id>       Agent ID (默认: main)
  --config <path>       配置文件路径
  --no-systemd          跳过 systemd 安装
  --uninstall           卸载
  --help                显示帮助
```

## 系统要求

- Linux (Ubuntu 20.04+)
- Python 3.8+
- Docker (用于 Qdrant)

## 文档

- [客户端配置指南](https://your-docs-url)

## License

MIT
