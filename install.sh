#!/bin/bash
# Mem0 Agent Setup - 一键安装脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 默认配置
AGENT_ID="main"
CONFIG_FILE=""
INSTALL_SYSTEMD=true

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --agent-id)
            AGENT_ID="$2"
            shift 2
            ;;
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --no-systemd)
            INSTALL_SYSTEMD=false
            shift
            ;;
        --uninstall)
            uninstall
            ;;
        --help)
            show_help
            ;;
        *)
            echo "未知参数: $1"
            show_help
            ;;
    esac
done

show_help() {
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  --agent-id <id>       Agent ID (默认: main)"
    echo "  --config <path>       配置文件路径"
    echo "  --no-systemd          跳过 systemd 安装"
    echo "  --uninstall           卸载"
    echo "  --help                显示帮助"
    exit 0
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查依赖
check_dependencies() {
    log_info "检查依赖..."
    
    if ! command -v python3 &> /dev/null; then
        log_error "Python3 未安装"
        exit 1
    fi
    
    if ! command -v docker &> /dev/null; then
        log_warn "Docker 未安装，将跳过 Qdrant 部署"
    fi
}

# 安装 Mem0
install_mem0() {
    log_info "安装 Mem0..."
    pip install mem0ai -q
}

# 部署 Qdrant
deploy_qdrant() {
    if docker ps | grep -q qdrant; then
        log_info "Qdrant 已运行"
        return
    fi
    
    log_info "部署 Qdrant..."
    docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
    log_info "Qdrant 部署完成 (localhost:6333)"
}

# 部署监听脚本
deploy_scripts() {
    log_info "部署监听脚本..."
    
    SCRIPT_DIR="/root/.openclaw/workspace/scripts"
    mkdir -p "$SCRIPT_DIR"
    
    # 复制脚本
    cp scripts/watch_sessions.js "$SCRIPT_DIR/"
    cp scripts/sync_to_mem0.py "$SCRIPT_DIR/"
    
    # 替换配置
    if [ -n "$CONFIG_FILE" ]; then
        # 从配置文件读取并替换
        log_info "使用配置文件: $CONFIG_FILE"
    fi
    
    log_info "脚本部署完成"
}

# 安装 systemd 服务
install_systemd() {
    if [ "$INSTALL_SYSTEMD" = false ]; then
        log_info "跳过 systemd 安装"
        return
    fi
    
    log_info "安装 systemd 服务..."
    
    SERVICE_NAME="openclaw-session-watch"
    
    cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=OpenClaw Session Watcher - ${AGENT_ID}
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/.openclaw/workspace
ExecStart=/usr/bin/node /root/.openclaw/workspace/scripts/watch_sessions.js ${AGENT_ID}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}
    systemctl start ${SERVICE_NAME}
    
    log_info "systemd 服务已启动"
}

# 卸载
uninstall() {
    log_info "卸载 Mem0 Agent Setup..."
    
    # 停止服务
    systemctl stop openclaw-session-watch 2>/dev/null || true
    systemctl disable openclaw-session-watch 2>/dev/null || true
    rm -f /etc/systemd/system/openclaw-session-watch.service
    
    # 删除脚本
    rm -f /root/.openclaw/workspace/scripts/watch_sessions.js
    rm -f /root/.openclaw/workspace/scripts/sync_to_mem0.py
    
    log_info "卸载完成"
}

# 主函数
main() {
    log_info "Mem0 Agent Setup 安装程序"
    log_info "Agent ID: $AGENT_ID"
    echo ""
    
    check_dependencies
    install_mem0
    
    if command -v docker &> /dev/null; then
        deploy_qdrant
    fi
    
    deploy_scripts
    
    if [ "$INSTALL_SYSTEMD" = true ]; then
        install_systemd
    fi
    
    echo ""
    log_info "安装完成!"
    log_info "查看状态: systemctl status openclaw-session-watch"
    log_info "查看日志: journalctl -u openclaw-session-watch -f"
}

main
