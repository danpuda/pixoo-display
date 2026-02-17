#!/usr/bin/env python3
"""
Pixoo agent state controller v2.
Manages /tmp/pixoo-agents.json for the display script.
Supports multiple agents with the same character.

Usage:
  python3 pixoo-agent-ctl.py add <char> "<task>"        # register (returns ID)
  python3 pixoo-agent-ctl.py remove <id_or_char>         # remove by ID or first matching char
  python3 pixoo-agent-ctl.py remove-all <char>            # remove ALL entries for a char
  python3 pixoo-agent-ctl.py clear                        # remove all
  python3 pixoo-agent-ctl.py list                         # show current state

Characters: opus, sonnet, haiku, gemini, kusomegane, codex, grok
"""

import json
import sys
import time
import uuid
from pathlib import Path

STATE_FILE = Path("/tmp/pixoo-agents.json")
VALID_CHARS = {"opus", "sonnet", "haiku", "gemini", "kusomegane", "codex", "grok"}


def validate_char(char: str) -> str:
    """Validate character name, reject flags like --char."""
    if char.startswith("-"):
        print(f"[!] ERROR: '{char}' looks like a flag, not a character name!")
        print(f"    Valid characters: {', '.join(sorted(VALID_CHARS))}")
        print(f"    Usage: pixoo-agent-ctl.py add <char> \"<task>\"")
        sys.exit(1)
    if char not in VALID_CHARS:
        print(f"[!] WARNING: '{char}' is not a known character ({', '.join(sorted(VALID_CHARS))})")
    return char


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"agents": []}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def cmd_add(char: str, task: str) -> None:
    char = validate_char(char)
    state = load_state()
    agent_id = uuid.uuid4().hex[:8]
    now = time.time()
    state["agents"].append({
        "id": agent_id,
        "char": char,
        "task": task,
        "started": now,
        "last_seen": now,
        "source": "manual",
    })
    save_state(state)
    count_same = sum(1 for a in state["agents"] if a["char"] == char)
    print(f"[+] Added {char}#{agent_id}: {task} (total: {len(state['agents'])}, {char}x{count_same})")


def cmd_remove(id_or_char: str) -> None:
    state = load_state()
    before = len(state["agents"])

    # Try by ID first
    new_agents = [a for a in state["agents"] if a.get("id") != id_or_char]
    if len(new_agents) < before:
        state["agents"] = new_agents
        save_state(state)
        print(f"[-] Removed by id={id_or_char} (remaining: {len(state['agents'])})")
        return

    # Fallback: remove FIRST matching char
    found = False
    result = []
    for a in state["agents"]:
        if a["char"] == id_or_char and not found:
            found = True
            continue
        result.append(a)
    if found:
        state["agents"] = result
        save_state(state)
        print(f"[-] Removed first {id_or_char} (remaining: {len(state['agents'])})")
    else:
        print(f"[!] {id_or_char} not found")


def cmd_remove_all(char: str) -> None:
    state = load_state()
    before = len(state["agents"])
    state["agents"] = [a for a in state["agents"] if a["char"] != char]
    after = len(state["agents"])
    save_state(state)
    removed = before - after
    print(f"[-] Removed all {char} ({removed} removed, remaining: {after})")


def cmd_clear() -> None:
    save_state({"agents": []})
    print("[x] Cleared all agents")


def cmd_list() -> None:
    state = load_state()
    if not state["agents"]:
        print("No active subagents")
        return
    now = time.time()
    # Count by character
    from collections import Counter
    char_counts = Counter(a["char"] for a in state["agents"])
    print(f"Total: {len(state['agents'])} agents ({', '.join(f'{c}x{n}' for c, n in char_counts.items())})")
    for a in state["agents"]:
        elapsed = now - a["started"]
        m, s = divmod(int(elapsed), 60)
        agent_id = a.get("id", "?")
        print(f"  [{agent_id}] {a['char']}: {a['task']} ({m}:{s:02d} elapsed)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]
    if action == "add" and len(sys.argv) >= 4:
        cmd_add(sys.argv[2], sys.argv[3])
    elif action == "remove" and len(sys.argv) >= 3:
        cmd_remove(sys.argv[2])
    elif action == "remove-all" and len(sys.argv) >= 3:
        cmd_remove_all(sys.argv[2])
    elif action == "clear":
        cmd_clear()
    elif action == "list":
        cmd_list()
    else:
        print(__doc__)
        sys.exit(1)
