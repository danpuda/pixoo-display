#!/usr/bin/env python3
"""
Pixoo tmux Sync — tmux shared セッション → /tmp/pixoo-agents.json

tmux の shared セッションを監視し、window 一覧を解析して
Pixoo-64 ディスプレイ用の JSON ファイルに書き出す。

既存の pixoo-display-test.py との互換性を維持するため、
必須キー (id, char, task, started, last_seen, main_active) を出力する。
追加キー (role, status) は display 側では無視される。

Phase 1: capture-pane は行わない（scroll_text なし）。

Usage: python3 pixoo_tmux_sync.py  (runs as daemon)
"""

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

# --- Config ---
TMUX_SESSION = "shared"
STATE_FILE = Path("/tmp/pixoo-agents.json")
CONFIG_FILE = Path("/tmp/pixoo-tmux-config.json")
POLL_SEC = 3.0

# Role → char mapping (for Pixoo display sprite selection)
# Available sprites: opus, sonnet, haiku, gemini, kusomegane, codex, grok
ROLE_TO_CHAR: dict[str, str] = {
    "DIR": "opus",
    "PL": "codex",
    "DEV": "codex",
    "QA": "codex",
    "SEC": "codex",
    "RES": "sonnet",
}

# Window name pattern for idle slots (not displayed)
IDLE_PATTERN = re.compile(r"^worker-\d+$")


def load_config() -> dict:
    """Load optional PL config from /tmp/pixoo-tmux-config.json.

    Supports:
        {"pl_window": "ebay-ph4-lead"}  — force a specific window as PL
    """
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text())
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def classify_window(window_name: str) -> tuple[str, bool]:
    """Classify a tmux window name into a team role.

    Returns:
        (role, is_idle) — is_idle=True means the window should be skipped.

    Priority order (from design doc section 3):
        1. "monitor"              → DIR
        2. *-lead                 → PL  (1 person only; resolved in build_agents)
        3. *-review / *-qa / *-fl3 → QA
        4. *-sec                  → SEC
        5. *-impl / *-dev         → DEV
        6. *-research             → RES
        7. worker-N               → idle (skip)
        8. anything else          → DEV
    """
    name_lower = window_name.lower()

    # 1. monitor → DIR
    if name_lower == "monitor":
        return "DIR", False

    # 7. worker-N → idle (early exit)
    if IDLE_PATTERN.match(window_name):
        return "---", True

    # 2. *-lead → PL
    if "-lead" in name_lower:
        return "PL", False

    # 3. *-review / *-qa / *-fl3 → QA
    if "-review" in name_lower or "-qa" in name_lower or "-fl3" in name_lower:
        return "QA", False

    # 4. *-sec → SEC
    if "-sec" in name_lower:
        return "SEC", False

    # 5. *-impl / *-dev → DEV
    if "-impl" in name_lower or "-dev" in name_lower:
        return "DEV", False

    # 6. *-research → RES
    if "-research" in name_lower:
        return "RES", False

    # 8. fallback → DEV
    return "DEV", False


def get_tmux_windows() -> list[dict] | None:
    """Get tmux window list from the shared session.

    Returns:
        List of dicts with keys: window_index, window_name, pane_pid.
        None if tmux or the session is unavailable.
    """
    try:
        result = subprocess.run(
            [
                "tmux", "list-windows", "-t", TMUX_SESSION,
                "-F", "#{window_index}\t#{window_name}\t#{pane_pid}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        windows: list[dict] = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            try:
                idx = int(parts[0])
                pid = int(parts[2])
            except ValueError:
                continue
            windows.append({
                "window_index": idx,
                "window_name": parts[1],
                "pane_pid": pid,
            })
        return windows
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def build_agents(
    windows: list[dict],
    config: dict,
    first_seen: dict[str, float],
) -> tuple[list[dict], bool]:
    """Convert tmux windows into a Pixoo-compatible agent list.

    Returns:
        (agents, main_active).
        - agents: list of dicts for /tmp/pixoo-agents.json
        - main_active: True if DIR (monitor) window exists
    """
    now = time.time()
    main_active = False
    pl_candidates: list[dict] = []
    classified: list[tuple[dict, str]] = []

    # --- First pass: classify every window ---
    for w in windows:
        role, is_idle = classify_window(w["window_name"])
        if is_idle:
            continue
        if role == "DIR":
            main_active = True
            continue  # DIR is tracked via main_active, not in agents list
        if role == "PL":
            pl_candidates.append(w)
        classified.append((w, role))

    # --- PL selection: config-fixed > lowest window_index ---
    # Use window_index (unique) instead of window_name to avoid same-name bugs.
    selected_pl_idx: int | None = None
    if pl_candidates:
        pl_window_cfg = config.get("pl_window")
        if pl_window_cfg:
            for w in pl_candidates:
                if w["window_name"] == pl_window_cfg:
                    selected_pl_idx = w["window_index"]
                    break
        if selected_pl_idx is None:
            pl_candidates.sort(key=lambda w: w["window_index"])
            selected_pl_idx = pl_candidates[0]["window_index"]

    # --- Second pass: build agent entries ---
    agents: list[dict] = []
    for w, role in classified:
        name = w["window_name"]

        # Demote extra PLs to DEV (compare by unique window_index)
        if role == "PL" and w["window_index"] != selected_pl_idx:
            role = "DEV"

        char = ROLE_TO_CHAR.get(role, "codex")

        # Track first-seen time per window name
        if name not in first_seen:
            first_seen[name] = now

        agents.append({
            # --- 互換必須キー ---
            "id": name,
            "char": char,
            "task": name,
            "started": first_seen[name],
            "last_seen": now,
            # --- 追加キー (display側は無視) ---
            "role": role,
            "status": "active",
        })

    # Prune stale entries from first_seen
    current_names = {w["window_name"] for w in windows}
    for stale_key in [k for k in first_seen if k not in current_names]:
        del first_seen[stale_key]

    return agents, main_active


def write_state(agents: list[dict], main_active: bool) -> None:
    """Atomically write agent state to /tmp/pixoo-agents.json.

    Uses tempfile + os.replace to prevent half-written reads by the display daemon.
    """
    payload = json.dumps(
        {"agents": agents, "main_active": main_active},
        ensure_ascii=False,
        indent=2,
    )

    fd, tmp_path = tempfile.mkstemp(
        dir=str(STATE_FILE.parent),
        suffix=".tmp",
        prefix=".pixoo-agents-",
    )
    closed = False
    try:
        os.write(fd, payload.encode("utf-8"))
        os.close(fd)
        closed = True
        os.replace(tmp_path, str(STATE_FILE))
    except BaseException:
        if not closed:
            os.close(fd)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def main() -> None:
    """Main polling loop — tmux → JSON every POLL_SEC seconds."""
    print("[pixoo-tmux-sync] Started")
    print(f"[i] tmux session: {TMUX_SESSION}")
    print(f"[i] Poll interval: {POLL_SEC}s")
    print(f"[i] Output: {STATE_FILE}")

    first_seen: dict[str, float] = {}
    last_agent_ids: set[str] | None = None
    last_main_active: bool | None = None

    while True:
        try:
            config = load_config()
            windows = get_tmux_windows()

            if windows is None:
                # tmux unavailable — write empty state so display shows fallback
                agents: list[dict] = []
                main_active = False
                if last_agent_ids is not None:
                    print("[!] tmux session unavailable — writing empty state")
            else:
                agents, main_active = build_agents(windows, config, first_seen)

            write_state(agents, main_active)

            # Log only on change
            agent_ids = {a["id"] for a in agents}
            if agent_ids != last_agent_ids or main_active != last_main_active:
                dir_status = "active" if main_active else "idle"
                if agents:
                    roles = [f"{a['id']}({a['role']})" for a in agents]
                    print(f"[i] Agents: {len(agents)} — {', '.join(roles)} (DIR: {dir_status})")
                else:
                    print(f"[i] No agents (DIR: {dir_status})")
                last_agent_ids = agent_ids
                last_main_active = main_active

            time.sleep(POLL_SEC)

        except KeyboardInterrupt:
            print("\n[i] Stopped")
            break
        except Exception as e:
            print(f"[!] Error: {e}")
            time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
