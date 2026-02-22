#!/bin/bash
# Auto-restart wrapper for pixoo-display-test.py v6
SCRIPT="/home/yama/pixoo-display/pixoo-display-test.py"
LOG="/tmp/pixoo-display-v6.log"

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting pixoo-display-test.py" >> "$LOG"
    python3 -u "$SCRIPT" 2>&1 | tee -a "$LOG"
    EXIT_CODE=${PIPESTATUS[0]}
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Exited with code $EXIT_CODE. Restarting in 5s..." >> "$LOG"
    sleep 5
done
