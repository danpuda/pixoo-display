#!/usr/bin/env python3
"""
IDE Output Watcher — ファイル変更検知デーモン
Phase 1: watchdogでワークスペースを監視し、ファイル変更をJSON出力

Usage:
  python3 ide-output-watcher.py [--watch-dir DIR] [--event-file FILE]

デーモン化:
  nohup python3 ide-output-watcher.py &
  または ./ide-watcher-wrapper.sh
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

# --- 設定 ---
DEFAULT_WATCH_DIR = "/home/yama/pixoo-display/"
DEFAULT_EVENT_FILE = "/tmp/ide-output-events.json"
DEFAULT_PIXOO_STATE = "/tmp/pixoo-agents.json"
DEFAULT_LOG_FILE = "/tmp/ide-output-watcher.log"

# 監視パターン（拡張子）
WATCH_PATTERNS = {".md", ".py", ".json", ".toml", ".txt", ".sh"}

# 除外パターン（ディレクトリ名、ファイル名部分一致）
IGNORE_PATTERNS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".ruff_cache",
    ".DS_Store",
    # イベントファイル自身は除外（無限ループ防止）
    "ide-output-events.json",
    "pixoo-agents.json",
    "ide-output-watcher.log",
}

# Pixooエージェント表示時間（秒）
PIXOO_DISPLAY_SEC = 10


class IDEOutputHandler(FileSystemEventHandler):
    """ファイル変更イベントハンドラ"""

    def __init__(self, event_file: Path, pixoo_state: Path, log_file: Path):
        self.event_file = event_file
        self.pixoo_state = pixoo_state
        self.log_file = log_file
        self._last_event_time = {}  # path → timestamp (debounce用)
        self._debounce_sec = 0.5  # 同じファイルの連続イベントを0.5秒以内なら無視

    def should_process(self, path: str) -> bool:
        """このファイルを処理すべきか判定"""
        p = Path(path)
        
        # ディレクトリは無視
        if p.is_dir():
            return False
        
        # 拡張子チェック
        if p.suffix not in WATCH_PATTERNS:
            return False
        
        # 除外パターンチェック
        path_parts = p.parts
        for part in path_parts:
            if part in IGNORE_PATTERNS:
                return False
        
        # ファイル名に除外パターンが含まれているか
        if any(pattern in p.name for pattern in IGNORE_PATTERNS):
            return False
        
        # debounce: 同じファイルの連続イベントを抑制
        now = time.time()
        last_time = self._last_event_time.get(path, 0)
        if now - last_time < self._debounce_sec:
            return False
        self._last_event_time[path] = now
        
        return True

    def on_created(self, event):
        if isinstance(event, FileCreatedEvent) and self.should_process(event.src_path):
            self.log_event("file_created", event.src_path)

    def on_modified(self, event):
        if isinstance(event, FileModifiedEvent) and self.should_process(event.src_path):
            self.log_event("file_modified", event.src_path)

    def log_event(self, event_type: str, path: str):
        """イベントをJSONログに記録 + Pixoo連動"""
        try:
            p = Path(path)
            size_bytes = p.stat().st_size if p.exists() else 0
            timestamp = int(time.time())
            
            event_data = {
                "event": event_type,
                "path": str(p.absolute()),
                "timestamp": timestamp,
                "size_bytes": size_bytes,
                "ai_source": "unknown",
                "task_id": None,
                "action": "notify",
            }
            
            # 1. ide-output-events.json に追記
            self._append_json(self.event_file, event_data)
            
            # 2. Pixoo連動: pixoo-agents.json に追記
            self._update_pixoo_state(event_data)
            
            # 3. ログ出力
            log_msg = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {event_type}: {p.name} ({size_bytes} bytes)"
            self._log(log_msg)
            print(log_msg)  # 標準出力にも
            
        except Exception as e:
            err_msg = f"[ERROR] log_event failed: {e}"
            self._log(err_msg)
            print(err_msg, file=sys.stderr)

    def _append_json(self, file_path: Path, data: dict):
        """JSON配列に要素を追記（atomic write）"""
        try:
            # 既存データ読み込み
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        events = json.load(f)
                    if not isinstance(events, list):
                        events = []
                except (json.JSONDecodeError, OSError):
                    events = []
            else:
                events = []
            
            # 新しいイベントを追加
            events.append(data)
            
            # atomic write: tempfile → rename
            fd, tmp_path = tempfile.mkstemp(
                dir=str(file_path.parent),
                suffix=".tmp",
                prefix=f".{file_path.name}-"
            )
            closed = False
            try:
                payload = json.dumps(events, ensure_ascii=False, indent=2)
                os.write(fd, payload.encode('utf-8'))
                os.close(fd)
                closed = True
                os.replace(tmp_path, str(file_path))
            except BaseException:
                if not closed:
                    os.close(fd)
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
                
        except Exception as e:
            raise RuntimeError(f"Failed to append JSON: {e}") from e

    def _update_pixoo_state(self, event_data: dict):
        """Pixoo表示用のpixoo-agents.jsonを更新"""
        try:
            now = time.time()
            
            # pixoo-agents.json 形式:
            # {
            #   "agents": [
            #     {"id": "...", "char": "...", "task": "...", "started": ..., "last_seen": ..., "source": "..."}
            #   ],
            #   "main_active": bool
            # }
            
            # 既存データ読み込み
            if self.pixoo_state.exists():
                try:
                    with open(self.pixoo_state, 'r', encoding='utf-8') as f:
                        state = json.load(f)
                except (json.JSONDecodeError, OSError):
                    state = {"agents": [], "main_active": False}
            else:
                state = {"agents": [], "main_active": False}
            
            if "agents" not in state:
                state["agents"] = []
            
            # IDE Watcherエントリを作成/更新
            # source="ide-watcher"で識別
            # 一時的にPixooに表示（PIXOO_DISPLAY_SEC秒後に自動削除される想定）
            
            # 既存のide-watcherエントリを削除（古いものは消す）
            state["agents"] = [
                a for a in state["agents"]
                if a.get("source") != "ide-watcher"
            ]
            
            # 新規エントリ追加
            path = Path(event_data["path"])
            state["agents"].append({
                "id": f"ide-{int(now)}",
                "char": "codex",  # IDE出力はCodexアイコンで表示
                "task": f"📝 {path.name}",
                "started": now,
                "last_seen": now,
                "source": "ide-watcher",
            })
            
            # atomic write
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.pixoo_state.parent),
                suffix=".tmp",
                prefix=f".{self.pixoo_state.name}-"
            )
            closed = False
            try:
                payload = json.dumps(state, ensure_ascii=False, indent=2)
                os.write(fd, payload.encode('utf-8'))
                os.close(fd)
                closed = True
                os.replace(tmp_path, str(self.pixoo_state))
            except BaseException:
                if not closed:
                    os.close(fd)
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
                
        except Exception as e:
            err_msg = f"[ERROR] Pixoo state update failed: {e}"
            self._log(err_msg)
            print(err_msg, file=sys.stderr)

    def _log(self, message: str):
        """ログファイルに出力"""
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f"{message}\n")
        except Exception:
            pass  # ログ書き込み失敗は無視


def main():
    parser = argparse.ArgumentParser(description="IDE Output Watcher — ファイル変更検知デーモン")
    parser.add_argument(
        "--watch-dir",
        type=str,
        default=DEFAULT_WATCH_DIR,
        help=f"監視対象ディレクトリ（デフォルト: {DEFAULT_WATCH_DIR}）"
    )
    parser.add_argument(
        "--event-file",
        type=str,
        default=DEFAULT_EVENT_FILE,
        help=f"イベントログファイル（デフォルト: {DEFAULT_EVENT_FILE}）"
    )
    parser.add_argument(
        "--pixoo-state",
        type=str,
        default=DEFAULT_PIXOO_STATE,
        help=f"Pixoo状態ファイル（デフォルト: {DEFAULT_PIXOO_STATE}）"
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=DEFAULT_LOG_FILE,
        help=f"ログファイル（デフォルト: {DEFAULT_LOG_FILE}）"
    )
    args = parser.parse_args()
    
    watch_dir = Path(args.watch_dir).resolve()
    event_file = Path(args.event_file)
    pixoo_state = Path(args.pixoo_state)
    log_file = Path(args.log_file)
    
    # 監視対象ディレクトリが存在するか確認
    if not watch_dir.exists():
        print(f"[ERROR] Watch directory not found: {watch_dir}", file=sys.stderr)
        sys.exit(1)
    
    print(f"[ide-output-watcher] Started")
    print(f"[i] Watch dir: {watch_dir}")
    print(f"[i] Event file: {event_file}")
    print(f"[i] Pixoo state: {pixoo_state}")
    print(f"[i] Log file: {log_file}")
    print(f"[i] Patterns: {', '.join(WATCH_PATTERNS)}")
    print(f"[i] Ignore: {', '.join(sorted(IGNORE_PATTERNS))}")
    print("[i] Press Ctrl+C to stop")
    
    # イベントハンドラ作成
    handler = IDEOutputHandler(event_file, pixoo_state, log_file)
    
    # オブザーバー作成
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=True)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[i] Stopping...")
        observer.stop()
    
    observer.join()
    print("[i] Stopped")


if __name__ == "__main__":
    main()
