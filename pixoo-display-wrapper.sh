#!/bin/bash
# Auto-restart wrapper for pixoo-display-test.py v6
# Phase 5.4: co-manages pixoo_tmux_sync.py as a child daemon
SCRIPT="/home/yama/pixoo-display/pixoo-display-test.py"
SYNC_SCRIPT="/home/yama/pixoo-display/pixoo_tmux_sync.py"
LOG="/tmp/pixoo-display-v6.log"
SYNC_LOG="/tmp/pixoo-tmux-sync.log"
SYNC_PID=""

# Ensure sprites exist in /tmp before starting
bash /home/yama/pixoo-display/ensure-sprites.sh >> "$LOG" 2>&1

start_sync() {
    python3 -u "$SYNC_SCRIPT" >> "$SYNC_LOG" 2>&1 &
    SYNC_PID=$!
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync daemon started (PID=$SYNC_PID)" >> "$LOG"
}

cleanup() {
    if [ -n "$SYNC_PID" ] && kill -0 "$SYNC_PID" 2>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Killing sync daemon (PID=$SYNC_PID)" >> "$LOG"
        kill "$SYNC_PID" 2>/dev/null
        wait "$SYNC_PID" 2>/dev/null
    fi
}
trap cleanup EXIT

# Start sync daemon before the display loop
start_sync

while true; do
    # Restart sync daemon if it died
    if ! kill -0 "$SYNC_PID" 2>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync daemon died, restarting..." >> "$LOG"
        start_sync
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting pixoo-display-test.py" >> "$LOG"
    python3 -u "$SCRIPT" 2>&1 | tee -a "$LOG"
    EXIT_CODE=${PIPESTATUS[0]}
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Exited with code $EXIT_CODE. Restarting in 5s..." >> "$LOG"
    sleep 5
done
