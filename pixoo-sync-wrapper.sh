#!/bin/bash
# Auto-restart wrapper for pixoo sync daemon
# syncデーモンが死んでも自動復旧する
#
# v7: pixoo_tmux_sync.py (tmux shared セッション監視)
# v6: pixoo_agent_sync.py (旧: OpenClaw JSONL 監視) — 温存

SCRIPT="/home/yama/pixoo-display/pixoo_tmux_sync.py"
LOG="/tmp/pixoo-tmux-sync.log"

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting pixoo_tmux_sync.py" >> "$LOG"
    python3 -u "$SCRIPT" 2>&1 | tee -a "$LOG"
    EXIT_CODE=${PIPESTATUS[0]}
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Exited with code $EXIT_CODE. Restarting in 5s..." >> "$LOG"
    sleep 5
done
