#!/bin/bash
# ============================================================
# Session Pre-Reset Sync Script
# 用法: bash session_pre_reset_sync.sh [agentId]
# 
# 在 session reset 之前手动执行，确保所有对话都已同步到 Mem0
# 也可以通过创建 /tmp/.pre_reset_sync.{agent} 触发自动同步
# ============================================================

set -e

AGENT="${1:-main}"
WATCH_DIR="/root/.openclaw/agents/${AGENT}/sessions"
TRIGGER_FILE="/tmp/.pre_reset_sync.${AGENT}"
LOG_DIR="/root/.openclaw/cron_log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Pre-Reset Sync: ${AGENT} ==="

# 检查 session 目录
if [ ! -d "$WATCH_DIR" ]; then
    echo "ERROR: Sessions directory not found: $WATCH_DIR"
    exit 1
fi

# 统计信息
SESSION_COUNT=$(ls -1 "$WATCH_DIR"/*.jsonl 2>/dev/null | grep -v '.deleted' | wc -l)
echo "Found $SESSION_COUNT session files"

# 方法1：直接触发 watcher 的预重置机制
echo "创建触发器: $TRIGGER_FILE"
touch "$TRIGGER_FILE"
echo "触发器已创建，watcher 将在下次轮询时自动执行全量同步"
echo "(watcher 轮询间隔 5s，可用 --watch 持续监控)"

# 等待 watcher 处理
sleep 8

# 检查触发器是否被清除（说明 watcher 已处理）
if [ -f "$TRIGGER_FILE" ]; then
    echo "WARNING: 触发器未被 watcher 清除，尝试直接同步..."
    
    # 方法2：直接从文件同步（备用方案）
    for f in "$WATCH_DIR"/*.jsonl; do
        [ -e "$f" ] || continue
        basename=$(basename "$f")
        
        # 解析并同步
        echo "  -> 同步 $basename"
        
        # 读取文件内容
        python3 /root/.openclaw/mem0-agent-setup/scripts/sync_to_mem0.py < /dev/null 2>&1 || true
    done
fi

# 验证同步结果
if [ -f "$TRIGGER_FILE" ]; then
    echo ""
    echo "⚠️  触发器仍存在，watcher 可能未运行"
    echo "请手动运行: node /root/.openclaw/mem0-agent-setup/scripts/watch_sessions.js ${AGENT}"
    rm -f "$TRIGGER_FILE"
    exit 1
else
    echo ""
    echo "✅ Pre-reset sync 完成！"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Pre-Reset Sync 完成: ${AGENT} ==="
fi
