#!/bin/bash
# Auto-restart wrapper for pixoo_agent_sync.py
# syncデーモンが死んでも自動復旧する
SCRIPT="/home/yama/pixoo-display/pixoo_agent_sync.py"
LOG="/tmp/pixoo-agent-sync.log"

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting pixoo_agent_sync.py" >> "$LOG"
    python3 -u "$SCRIPT" 2>&1 | tee -a "$LOG"
    EXIT_CODE=${PIPESTATUS[0]}
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Exited with code $EXIT_CODE. Restarting in 5s..." >> "$LOG"
    sleep 5
done
