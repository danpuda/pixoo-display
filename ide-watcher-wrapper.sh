#!/usr/bin/env bash
# IDE Output Watcher デーモン化wrapper
# Usage: ./ide-watcher-wrapper.sh [start|stop|restart|status]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/ide-output-watcher.py"
PID_FILE="/tmp/ide-output-watcher.pid"
LOG_FILE="/tmp/ide-output-watcher.log"

start() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "[!] Already running (PID: $pid)"
            return 1
        else
            echo "[i] Stale PID file found, removing..."
            rm -f "$PID_FILE"
        fi
    fi
    
    echo "[i] Starting IDE Output Watcher..."
    nohup python3 "$PYTHON_SCRIPT" >> "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"
    echo "[✓] Started (PID: $pid)"
    echo "[i] Log: $LOG_FILE"
}

stop() {
    if [ ! -f "$PID_FILE" ]; then
        echo "[!] Not running (no PID file)"
        return 1
    fi
    
    local pid=$(cat "$PID_FILE")
    if ! ps -p "$pid" > /dev/null 2>&1; then
        echo "[!] Process not found (PID: $pid)"
        rm -f "$PID_FILE"
        return 1
    fi
    
    echo "[i] Stopping IDE Output Watcher (PID: $pid)..."
    kill "$pid"
    sleep 1
    
    # SIGTERM失敗時はSIGKILL
    if ps -p "$pid" > /dev/null 2>&1; then
        echo "[i] SIGTERM failed, sending SIGKILL..."
        kill -9 "$pid"
        sleep 1
    fi
    
    rm -f "$PID_FILE"
    echo "[✓] Stopped"
}

status() {
    if [ ! -f "$PID_FILE" ]; then
        echo "[i] Status: NOT RUNNING"
        return 1
    fi
    
    local pid=$(cat "$PID_FILE")
    if ps -p "$pid" > /dev/null 2>&1; then
        echo "[i] Status: RUNNING (PID: $pid)"
        return 0
    else
        echo "[i] Status: NOT RUNNING (stale PID file)"
        return 1
    fi
}

restart() {
    echo "[i] Restarting..."
    stop
    sleep 1
    start
}

case "${1:-start}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
