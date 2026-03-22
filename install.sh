#!/bin/bash
# Mem0 Agent Setup - 一键安装脚本
# 支持自动检测和批量配置多 Agent

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 默认配置
AGENT_ID="main"
CONFIG_FILE=""
INSTALL_SYSTEMD=true
AUTO_DETECT_ALL=false
SKIP_EXISTING=false

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
        --auto)
            AUTO_DETECT_ALL=true
            shift
            ;;
        --uninstall)
            uninstall
            ;;
        --uninstall-all)
            uninstall_all
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
    echo "  --config <path>      配置文件路径"
    echo "  --no-systemd         跳过 systemd 安装"
    echo "  --auto               自动检测并配置所有 Agent"
    echo "  --uninstall          卸载当前 Agent"
    echo "  --uninstall-all      卸载所有 Agent"
    echo "  --help               显示帮助"
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

log_skip() {
    echo -e "${BLUE}[SKIP]${NC} $1"
}

# ========== 重复检测函数 ==========

# 检测重复配置
check_existing_configs() {
    local conflicts=()
    
    # 1. 检测 Qdrant 重复
    if docker ps -a | grep -q qdrant; then
        conflicts+=("Qdrant 容器已存在")
    elif curl -s http://localhost:6333/ >/dev/null 2>&1; then
        conflicts+=("Qdrant 服务已在运行 (localhost:6333)")
    fi
    
    # 2. 检测 systemd 服务重复
    local SERVICE_NAME="openclaw-session-watch"
    if [ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]; then
        conflicts+=("systemd 服务已存在: ${SERVICE_NAME}")
    fi
    
    # 3. 检测脚本重复
    local SCRIPT_DIR="/root/.openclaw/workspace/scripts"
    if [ -f "$SCRIPT_DIR/watch_sessions.js" ]; then
        conflicts+=("监听脚本 watch_sessions.js 已部署")
    fi
    if [ -f "$SCRIPT_DIR/sync_to_mem0.py" ]; then
        conflicts+=("同步脚本 sync_to_mem0.py 已部署")
    fi
    
    # 4. 检测 Mem0 Python 包
    if python3 -c "import mem0" 2>/dev/null; then
        conflicts+=("Mem0 Python 包已安装")
    fi
    
    # 如果有冲突，询问用户
    if [ ${#conflicts[@]} -gt 0 ]; then
        echo ""
        echo -e "${YELLOW}⚠️  检测到以下重复配置:${NC}"
        for i in "${!conflicts[@]}"; do
            echo -e "   $((i+1)). ${conflicts[$i]}"
        done
        echo ""
        echo -e "${YELLOW}请选择操作:${NC}"
        echo "  [o] 覆盖现有配置"
        echo "  [s] 跳过重复项，仅安装缺失的"
        echo "  [c] 取消安装"
        echo ""
        
        read -p "> " choice
        case "$choice" in
            o|O)
                echo -e "${GREEN}✅ 将覆盖现有配置${NC}"
                return 0
                ;;
            s|S)
                echo -e "${GREEN}✅ 跳过重复项，仅安装缺失的${NC}"
                return 1  # 返回1表示跳过模式
                ;;
            c|C)
                echo -e "${RED}❌ 已取消安装${NC}"
                exit 0
                ;;
            *)
                echo -e "${YELLOW}无效选择，默认跳过重复项${NC}"
                return 1
                ;;
        esac
    fi
    
    return 0  # 无冲突
}

# 检测单个配置项（用于自动模式）
check_single_conflict() {
    local item=$1
    
    case "$item" in
        qdrant)
            if docker ps -a | grep -q qdrant || curl -s http://localhost:6333/ >/dev/null 2>&1; then
                return 1  # 已存在
            fi
            ;;
        systemd)
            if [ -f "/etc/systemd/system/openclaw-session-watch.service" ]; then
                return 1
            fi
            ;;
        scripts)
            if [ -f "/root/.openclaw/workspace/scripts/watch_sessions.js" ]; then
                return 1
            fi
            ;;
        mem0)
            if python3 -c "import mem0" 2>/dev/null; then
                return 1
            fi
            ;;
    esac
    return 0  # 不存在，可以安装
}

# ========== 检测函数 ==========

# 检查 Python
check_python() {
    # 跳过模式下不检查，直接返回
    if [ "$SKIP_EXISTING" = "true" ]; then
        return 0
    fi
    
    if command -v python3 &> /dev/null; then
        log_skip "Python3 已安装"
        return 0
    else
        log_info "安装 Python3..."
        apt-get update -qq && apt-get install -y -qq python3 python3-pip
        return 1
    fi
}

# 检查 Mem0
check_mem0() {
    # 跳过模式下不检查，直接返回
    if [ "$SKIP_EXISTING" = "true" ]; then
        return 0
    fi
    
    if python3 -c "import mem0" 2>/dev/null; then
        log_skip "Mem0 已安装"
        return 0
    else
        log_info "安装 Mem0..."
        pip3 install mem0ai pyyaml -q
        return 1
    fi
}

# 检查 Qdrant
check_qdrant() {
    # 跳过模式下不检查，直接返回
    if [ "$SKIP_EXISTING" = "true" ]; then
        return 0
    fi
    
    if docker ps | grep -q qdrant; then
        log_skip "Qdrant 已运行"
        return 0
    fi
    
    if curl -s http://localhost:6333/ >/dev/null 2>&1; then
        log_skip "Qdrant 已运行（外部）"
        return 0
    fi
    
    if command -v docker &> /dev/null; then
        log_info "部署 Qdrant..."
        docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
        log_info "Qdrant 部署完成 (localhost:6333)"
        return 1
    else
        log_warn "Docker 未安装，跳过 Qdrant"
        return 0
    fi
}

# 检查脚本
check_scripts() {
    # 跳过模式下不检查，直接返回
    if [ "$SKIP_EXISTING" = "true" ]; then
        return 0
    fi
    
    SCRIPT_DIR="/root/.openclaw/workspace/scripts"
    mkdir -p "$SCRIPT_DIR"
    
    if [ -f "$SCRIPT_DIR/watch_sessions.js" ] && [ -f "$SCRIPT_DIR/sync_to_mem0.py" ]; then
        log_skip "监听脚本已部署"
        return 0
    else
        log_info "部署监听脚本..."
        cp scripts/watch_sessions.js "$SCRIPT_DIR/"
        cp scripts/sync_to_mem0.py "$SCRIPT_DIR/"
        return 1
    fi
}

# 检查 systemd 服务
check_systemd() {
    # 跳过模式下不检查，直接返回
    if [ "$SKIP_EXISTING" = "true" ]; then
        return 0
    fi
    
    SERVICE_NAME="openclaw-session-watch"
    
    if systemctl is-active --quiet ${SERVICE_NAME} 2>/dev/null; then
        log_skip "systemd 服务已运行: ${SERVICE_NAME}"
        return 0
    fi
    return 1
}

# ========== 部署函数 ==========

# 部署 systemd 服务（单个 Agent）
deploy_systemd_service() {
    local agent_id=$1
    local SERVICE_NAME="openclaw-session-watch"
    
    if systemctl is-active --quiet ${SERVICE_NAME} 2>/dev/null; then
        log_skip "服务已运行: ${SERVICE_NAME}"
        return 0
    fi
    
    log_info "安装 systemd 服务: ${SERVICE_NAME} (Agent: ${agent_id})"
    
    cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=OpenClaw Session Watcher - ${agent_id}
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/.openclaw/workspace
ExecStart=/usr/bin/node /root/.openclaw/workspace/scripts/watch_sessions.js ${agent_id}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}
    systemctl start ${SERVICE_NAME}
    
    log_info "systemd 服务已启动: ${SERVICE_NAME}"
    return 1
}

# ========== 多 Agent 检测 ==========

# 检测 OpenClaw 中的 Agent
detect_agents() {
    local AGENTS_DIR="/root/.openclaw/agents"
    
    if [ ! -d "$AGENTS_DIR" ]; then
        echo "main"
        return
    fi
    
    # 查找所有 agent 目录
    local agents=$(ls -1 "$AGENTS_DIR" 2>/dev/null | grep -v "^_" | grep -v "workspace" | grep -v "scripts" || true)
    
    if [ -z "$agents" ]; then
        echo "main"
        return
    fi
    
    echo "$agents"
}

# 检测所有 Agent 并配置
auto_setup_all_agents() {
    log_info "========== 自动检测 OpenClaw Agent =========="
    
    local agents=$(detect_agents)
    local agent_count=$(echo "$agents" | wc -w)
    
    log_info "检测到 $agent_count 个 Agent: $agents"
    echo ""
    
    for agent in $agents; do
        log_info "========== 配置 Agent: $agent =========="
        AGENT_ID=$agent install_single_agent
        echo ""
    done
    
    log_info "========== 所有 Agent 配置完成！=========="
}

# 安装单个 Agent
install_single_agent() {
    log_info "配置 Agent: $AGENT_ID"
    
    # 1. 检查/安装 Python
    check_python
    
    # 2. 检查/安装 Mem0
    check_mem0
    
    # 3. 检查/部署 Qdrant
    check_qdrant
    
    # 4. 检查/部署脚本
    check_scripts
    
    # 5. 检查/启动 systemd
    if [ "$INSTALL_SYSTEMD" = true ]; then
        deploy_systemd_service "$AGENT_ID"
    fi
}

# ========== 卸载函数 ==========

# 卸载单个
uninstall() {
    log_info "卸载 Mem0 Agent Setup..."
    
    SERVICE_NAME="openclaw-session-watch"
    
    systemctl stop ${SERVICE_NAME} 2>/dev/null || true
    systemctl disable ${SERVICE_NAME} 2>/dev/null || true
    rm -f /etc/systemd/system/${SERVICE_NAME}.service
    
    log_info "卸载完成"
}

# 卸载所有
uninstall_all() {
    log_info "========== 卸载所有 Agent =========="
    
    # 停止所有服务
    for svc in $(ls /etc/systemd/system/openclaw-session-watch*.service 2>/dev/null | xargs -n1 basename 2>/dev/null || true); do
        log_info "停止服务: $svc"
        systemctl stop "$svc" 2>/dev/null || true
        systemctl disable "$svc" 2>/dev/null || true
    done
    
    rm -f /etc/systemd/system/openclaw-session-watch*.service
    
    # 删除脚本
    rm -f /root/.openclaw/workspace/scripts/watch_sessions.js
    rm -f /root/.openclaw/workspace/scripts/sync_to_mem0.py
    
    log_info "卸载完成"
}

# ========== 主函数 ==========

main() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║        Mem0 Agent Setup v1.1                     ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
    echo ""
    
    # 检测重复配置（非自动模式时）
    if [ "$AUTO_DETECT_ALL" = false ]; then
        SKIP_EXISTING=false
        check_existing_configs || SKIP_EXISTING=$?
    fi
    
    if [ "$AUTO_DETECT_ALL" = true ]; then
        # 自动检测并配置所有 Agent
        check_dependencies
        auto_setup_all_agents
    else
        # 单个 Agent 安装
        log_info "配置 Agent: $AGENT_ID"
        echo ""
        
        check_dependencies
        install_single_agent
    fi
    
    echo ""
    log_info "========== 安装完成！=========="
    log_info "查看状态: systemctl status openclaw-session-watch"
    log_info "查看日志: journalctl -u openclaw-session-watch -f"
    log_info "查看记忆: mem0-agent stats"
}

# 检查基础依赖
check_dependencies() {
    if ! command -v python3 &> /dev/null; then
        log_error "Python3 未安装"
        exit 1
    fi
}

main
