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

# 根据 agent_id 获取 workspace 目录
get_workspace_dir() {
    local agent=$1
    if [ "$agent" = "main" ]; then
        echo "/root/.openclaw/workspace"
    else
        echo "/root/.openclaw/workspace-$agent"
    fi
}

# 获取 scripts 目录
get_scripts_dir() {
    local agent=$1
    echo "$(get_workspace_dir $agent)/scripts"
}

# 解析参数


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
    if [ -f "/etc/systemd/system/${SERVICE_NAME}-${AGENT_ID}.service" ]; then
        conflicts+=("systemd 服务已存在: ${SERVICE_NAME}-${AGENT_ID}")
    fi

    # 3. 检测脚本重复
    local SCRIPT_DIR=$(get_scripts_dir "$AGENT_ID")
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
    local SCRIPTS_DIR=$(get_scripts_dir "$AGENT_ID")

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
            if [ -f "$SCRIPTS_DIR/watch_sessions.js" ]; then
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

    local SCRIPT_DIR=$(get_scripts_dir "$AGENT_ID")
    local WORKSPACE_DIR=$(get_workspace_dir "$AGENT_ID")
    local ENV_FILE="${WORKSPACE_DIR}/.env"

    mkdir -p "$SCRIPT_DIR"

    # 复制配置模板（如果 .env 不存在）
    if [ ! -f "$ENV_FILE" ]; then
        if [ -f "scripts/config.env.example" ]; then
            log_info "创建配置文件 $ENV_FILE..."
            cp scripts/config.env.example "$ENV_FILE"
            log_warn "请编辑 $ENV_FILE 填入你的 API Key 和 MEM0_USER_ID！"
        fi
    fi

    # 确保必要变量存在（即使 .env 已存在也要检查）
    if [ -f "$ENV_FILE" ]; then
        # 设置 MEM0_USER_ID（如果缺失）
        if ! grep -q "^MEM0_USER_ID=" "$ENV_FILE"; then
            echo "MEM0_USER_ID=${AGENT_ID}" >> "$ENV_FILE"
            log_info "已添加 MEM0_USER_ID=${AGENT_ID} 到 $ENV_FILE"
        fi
        # 提示用户设置 API Key（如果为空）
        if grep -q "^OPENAI_API_KEY=$" "$ENV_FILE"; then
            log_warn "$ENV_FILE 中 OPENAI_API_KEY 未设置，请编辑填入！"
        fi
    fi

    # 需要部署的所有脚本
    local SCRIPTS=(
        "watch_sessions.js"
        "sync_to_mem0.py"
        "auto_recall.py"
        "auto_memory.py"
        "memory_cleanup.py"
        "memory_sync.py"
        "memory_distill_daily.py"
    )

    # 检查是否所有脚本都已部署
    local all_deployed=true
    for script in "${SCRIPTS[@]}"; do
        if [ ! -f "$SCRIPT_DIR/$script" ]; then
            all_deployed=false
            break
        fi
    done

    if [ "$all_deployed" = true ]; then
        log_skip "所有脚本已部署"
        return 0
    else
        log_info "部署脚本到 $SCRIPT_DIR..."
        for script in "${SCRIPTS[@]}"; do
            if [ -f "scripts/$script" ]; then
                cp scripts/"$script" "$SCRIPT_DIR/"/
            fi
        done
        # 部署 mem0-agent CLI
        if [ -f "bin/mem0-agent.py" ]; then
            cp bin/mem0-agent.py "$SCRIPT_DIR/"/
            chmod +x "$SCRIPT_DIR/mem0-agent.py"
        fi
        return 1
    fi
}

# 设置每日 distill cron（每天凌晨 4 点执行 memory_distill_daily.py）
# 注意：脚本统一在共享目录，多 agent 共用同一套脚本
setup_distill_cron() {
    local WORKSPACE_DIR=$(get_workspace_dir "$AGENT_ID")
    # 脚本统一在共享目录（mem0-agent-setup/scripts/），而非 per-agent 目录
    local SHARED_SCRIPTS="/root/.openclaw/mem0-agent-setup/scripts"
    local CRON_CMD='. '"${WORKSPACE_DIR}/.env"' 2>/dev/null; AGENT_NAME='"$AGENT_ID"' python3 '"$SHARED_SCRIPTS/memory_distill_daily.py"' --agent '"$AGENT_ID"' --force"
    local CRON_JOB="0 4 * * * $CRON_CMD"

    # 检查是否已有此类型的 distill cron（区分 agent）
    if crontab -l 2>/dev/null | grep -q "memory_distill_daily.py.*--agent.*$AGENT_ID"; then
        log_skip "Distill cron (${AGENT_ID}) 已存在"
        return 0
    else
        log_info "设置 Distill cron (每天 04:00, agent=${AGENT_ID})..."
        (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
        return 1
    fi
}

# 设置清理 cron（每天凌晨 3 点执行 memory_cleanup.py）
setup_cleanup_cron() {
    local WORKSPACE_DIR=$(get_workspace_dir "$AGENT_ID")
    local SHARED_SCRIPTS="/root/.openclaw/mem0-agent-setup/scripts"
    # cron 命令：从对应 agent 的 .env 读取 API key，脚本在共享目录
    local CRON_CMD='. '"${WORKSPACE_DIR}/.env"' 2>/dev/null; AGENT_NAME='"$AGENT_ID"' python3 '"$SHARED_SCRIPTS/memory_cleanup.py"
    local CRON_JOB="0 3 * * * $CRON_CMD"

    # 检查是否已有此类型的 cleanup cron（区分 agent）
    if crontab -l 2>/dev/null | grep -q "memory_cleanup.py.*--agent.*$AGENT_ID"; then
        log_skip "清理 cron (${AGENT_ID}) 已存在"
        return 0
    else
        log_info "设置清理 cron (每天 03:00, agent=${AGENT_ID})..."
        (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
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
    local SCRIPTS_DIR=$(get_scripts_dir "$agent_id")
    local WORKSPACE_DIR=$(get_workspace_dir "$agent_id")
    local ENV_FILE="${WORKSPACE_DIR}/.env"

    if systemctl is-active --quiet ${SERVICE_NAME}-${agent_id} 2>/dev/null; then
        log_skip "服务已运行: ${SERVICE_NAME}-${agent_id}"
        return 0
    fi

    log_info "安装 systemd 服务: ${SERVICE_NAME}-${agent_id} (Agent: ${agent_id})"

    cat > /etc/systemd/system/${SERVICE_NAME}-${agent_id}.service << EOF
[Unit]
Description=OpenClaw Session Watcher - ${agent_id}
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${WORKSPACE_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=/usr/bin/node ${SCRIPTS_DIR}/watch_sessions.js ${agent_id}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}-${agent_id}
    systemctl start ${SERVICE_NAME}-${agent_id}

    log_info "systemd 服务已启动: ${SERVICE_NAME}-${agent_id}"
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
    # 检查是否已有旧安装（auto 模式自动清理后重装）
    if ls /etc/systemd/system/openclaw-session-watch-*.service 1>/dev/null 2>&1 || \
       crontab -l 2>/dev/null | grep -q "memory_distill_daily.py\|memory_cleanup.py"; then
        log_warn "检测到旧安装，正在清除..."
        uninstall_all
        echo ""
    fi

    log_info "========== 自动检测 OpenClaw Agent =========="

    local agents=$(detect_agents)
    local agent_count=$(echo "$agents" | wc -w)

    log_info "检测到 $agent_count 个 Agent: $agents"
    echo ""

    for agent in $agents; do
        log_info "========== 配置 Agent: $agent =========="
        AGENT_ID=$agent install_single_agent
        # 设置 per-agent 的 cron
        AGENT_ID=$agent setup_cleanup_cron
        AGENT_ID=$agent setup_distill_cron
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
    
    local SERVICE_NAME="openclaw-session-watch"
    local SCRIPTS_DIR=$(get_scripts_dir "$AGENT_ID")
    local WORKSPACE_DIR=$(get_workspace_dir "$AGENT_ID")
    local ENV_FILE="${WORKSPACE_DIR}/.env"
    
    systemctl stop ${SERVICE_NAME}-${AGENT_ID} 2>/dev/null || true
    systemctl disable ${SERVICE_NAME}-${AGENT_ID} 2>/dev/null || true
    rm -f /etc/systemd/system/${SERVICE_NAME}-${AGENT_ID}.service

    # 删除脚本
    rm -f "$SCRIPTS_DIR/watch_sessions.js"
    rm -f "$SCRIPTS_DIR/sync_to_mem0.py"
    rm -f "$SCRIPTS_DIR/auto_recall.py"
    rm -f "$SCRIPTS_DIR/auto_memory.py"
    rm -f "$SCRIPTS_DIR/memory_cleanup.py"
    rm -f "$SCRIPTS_DIR/memory_sync.py"
    rm -f "$SCRIPTS_DIR/memory_distill_daily.py"
    rm -f "$SCRIPTS_DIR/mem0-agent.py"

    # 删除清理 cron 和 distill cron
    crontab -l 2>/dev/null | grep -v "memory_cleanup.py" | grep -v "memory_distill_daily.py" | crontab - 2>/dev/null || true

    # 删除配置文件（可选）
    # rm -f "$ENV_FILE"

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

    # 删除所有 agent 的脚本
    for dir in /root/.openclaw/workspace*; do
        if [ -d "$dir/scripts" ]; then
            rm -f "$dir/scripts/watch_sessions.js"
            rm -f "$dir/scripts/sync_to_mem0.py"
            rm -f "$dir/scripts/auto_recall.py"
            rm -f "$dir/scripts/auto_memory.py"
            rm -f "$dir/scripts/memory_cleanup.py"
            rm -f "$dir/scripts/memory_distill_daily.py"
            rm -f "$dir/scripts/memory_sync.py"
            rm -f "$dir/scripts/mem0-agent.py"
        fi
    done

    # 删除清理 cron 和 distill cron
    crontab -l 2>/dev/null | grep -v "memory_cleanup.py" | grep -v "memory_distill_daily.py" | crontab - 2>/dev/null || true

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
        # 设置清理 cron（独立于 SKIP_EXISTING）
        AGENT_ID=$AGENT_ID setup_cleanup_cron
        # 设置每日 distill cron
        AGENT_ID=$AGENT_ID setup_distill_cron
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
