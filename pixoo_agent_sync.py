#!/usr/bin/env python3
"""
Pixoo Agent Auto-Sync — OpenClawセッション自動検知
手動 add/remove を不要にする。

セッションディレクトリを監視し、アクティブなサブエージェントを
自動的に /tmp/pixoo-agents.json に反映する。

Usage: python3 pixoo-agent-sync.py  (runs as daemon alongside pixoo-display-test.py)
"""

import json
import os
import tempfile
import time
from pathlib import Path

SESSIONS_DIR = Path("/home/yama/.openclaw/agents/main/sessions/")
SESSIONS_JSON_STORE = Path("/home/yama/.openclaw/agents/main/sessions/sessions.json")
STATE_FILE = Path("/tmp/pixoo-agents.json")
POLL_SEC = 3.0
# Sessions modified within this window are considered "active"
ACTIVE_WINDOW_SEC = 300  # 5 minutes (relaxed from 2 min for long-running tasks)
MAX_AGE_SEC = 1800       # 30 minutes — age cap for completed/stale sessions
MAX_AGE_RUNNING_SEC = 14400  # 4 hours — extended cap for sessions still running tools
AGENT_TTL_SEC = 600      # 10 minutes — manual entries expire after this

# Model → Character mapping
MODEL_TO_CHAR = {
    "claude-opus-4-6": "opus",
    "claude-sonnet-4-5": "sonnet",
    "claude-haiku-3-5": "haiku",
    "claude-haiku-4-5": "haiku",
    "gpt-5.2": "kusomegane",
    "gpt-5.1": "kusomegane",
    "gpt-5.3-codex": "codex",
    "gemini-3-pro-low": "gemini",
    "gemini-3-pro-high": "gemini",
    "gemini-3-flash": "gemini",
    "grok-4": "grok",
    "grok-3-mini-fast": "grok",
}

# The main session (largest file, opus model) — exclude from subagent list
MAIN_SESSION_MODEL = "claude-opus-4-6"

# Cache: filepath → model string.  Survives across poll cycles so that
# a large-file miss (progressive read still too small) doesn't lose the
# previously-detected model.
_model_cache: dict[str, str] = {}


def get_session_model(filepath: Path) -> str | None:
    """Caching wrapper around _get_session_model_uncached().

    * If the cache already holds a **non-opus** answer, return it
      immediately (the real model never changes mid-session).
    * Otherwise probe the file and update the cache.
    * On probe failure, return the previous cached value (stale but
      better than losing a known model).
    """
    key = str(filepath)
    cached = _model_cache.get(key)

    # Happy path: we already know it's a non-default model
    if cached and cached != MAIN_SESSION_MODEL:
        return cached

    fresh = _get_session_model_uncached(filepath)
    if fresh:
        _model_cache[key] = fresh
        return fresh

    # Probe failed — return stale cache (may be None on first call)
    return cached


def _get_session_model_uncached(filepath: Path) -> str | None:
    """Read model from session JSONL (uncached).
    
    Strategy: Check the LAST assistant message's 'model' field first
    (most accurate — reflects the actual API model used).
    Falls back to the first model_change header if no assistant message found.
    """
    # Strategy 1: Read from the tail of the file (last assistant response = actual model)
    actual_model = _get_model_from_tail(filepath)
    if actual_model:
        return actual_model
    
    # Strategy 2: Fall back to model_change header
    try:
        with open(filepath, 'r', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("type") == "model_change":
                    return data.get("modelId", "")
                # Stop after 5 lines to avoid reading huge files
                if data.get("type") not in ("session", "model_change", "thinking_level_change", "custom"):
                    break
    except (json.JSONDecodeError, OSError):
        pass
    return None


def get_session_started(filepath: Path) -> float | None:
    """Read actual session creation timestamp from JSONL header.
    
    The first line of every JSONL has type='session' with an ISO timestamp.
    This is MUCH more accurate than guessing from filesize.
    """
    try:
        with open(filepath, 'r', errors='ignore') as f:
            line = f.readline().strip()
            if line:
                data = json.loads(line)
                if data.get("type") == "session":
                    ts = data.get("timestamp", "")
                    if ts:
                        from datetime import datetime, timezone
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        return dt.timestamp()
    except (json.JSONDecodeError, OSError, ValueError):
        pass
    return None


def is_session_completed(filepath: Path) -> bool:
    """Check if the session has finished (last assistant has stopReason).
    
    Completed sessions should NOT be shown as active subagents.
    """
    try:
        fsize = filepath.stat().st_size
        # Progressively read more: try 50KB first, then 200KB if no assistant found
        for read_bytes in [50_000, 200_000, fsize]:
            read_bytes = min(read_bytes, fsize)
            with open(filepath, 'rb') as f:
                f.seek(max(0, fsize - read_bytes))
                tail = f.read().decode('utf-8', errors='ignore')
            
            lines = tail.strip().split('\n')
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("type") != "message":
                    continue
                msg = data.get("message", {})
                if isinstance(msg, str):
                    try:
                        msg = json.loads(msg)
                    except:
                        continue
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    stop = msg.get("stopReason", "")
                    # stop/error/cancelled = completed
                    if stop in ("stop", "error", "cancelled"):
                        return True
                    elif stop == "toolUse":
                        # toolUse = likely still running, BUT check file age
                        # If file hasn't been modified in 10+ min, it's stuck/done
                        try:
                            import time
                            file_age = time.time() - filepath.stat().st_mtime
                            if file_age > 600:  # 10 min stale threshold
                                return True
                        except OSError:
                            pass
                        return False
                    # No stopReason = might still be streaming
                    # Also check file age for safety
                    try:
                        import time
                        file_age = time.time() - filepath.stat().st_mtime
                        if file_age > 600:
                            return True
                    except OSError:
                        pass
                    return False
            # If we read the full file and found nothing, stop
            if read_bytes >= fsize:
                break
        return False
    except OSError:
        return False


def _get_model_from_tail(filepath: Path) -> str | None:
    """Read the actual model from the last assistant message in the JSONL.
    
    OpenClaw subagents bootstrap with opus but the actual API responses
    contain the real model (e.g. grok-4, gpt-5.2, gemini-3-pro-low).
    Progressive read: try 50KB → 200KB → full file (same pattern as
    is_session_completed).
    """
    try:
        fsize = filepath.stat().st_size
        for read_bytes in [50_000, 200_000, fsize]:
            read_bytes = min(read_bytes, fsize)
            with open(filepath, 'rb') as f:
                f.seek(max(0, fsize - read_bytes))
                tail = f.read().decode('utf-8', errors='ignore')
            
            # Parse lines in reverse to find last assistant message with model
            lines = tail.strip().split('\n')
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("type") != "message":
                    continue
                msg = data.get("message", {})
                if isinstance(msg, str):
                    try:
                        msg = json.loads(msg)
                    except:
                        continue
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    model = msg.get("model", "")
                    if model:
                        return model
            # Found nothing in this chunk — try bigger read
            if read_bytes >= fsize:
                break
    except OSError:
        pass
    return None


# Label suffix → intended character mapping (for fallback model detection)
# When OpenClaw falls back to opus due to missing API key or rate limit,
# we can still infer the intended model from the spawn label or task text.
# Includes both English labels, Japanese keywords, and emoji prefixes.
LABEL_SUFFIX_TO_CHAR = {
    # Emoji prefixes (used in label field of sessions.json)
    "🤓": "kusomegane",
    "😎": "codex",
    "🟠": "sonnet",
    "🌀": "gemini",
    "🦊": "grok",
    # English (from spawn labels)
    "grok": "grok",
    "gemini": "gemini",
    "kusomegane": "kusomegane",
    "sonnet": "sonnet",
    "codex": "codex",
    "haiku": "haiku",
    "opus": "opus",
    # Japanese (from task text body)
    "クソメガネ": "kusomegane",
    "ソネット": "sonnet",
    "ジェミニ": "gemini",
    "グロック": "grok",
}


def get_session_label(filepath: Path) -> str | None:
    """Try to extract task label from session metadata."""
    try:
        with open(filepath, 'r', errors='ignore') as f:
            lines_read = 0
            for line in f:
                line = line.strip()
                if not line:
                    continue
                lines_read += 1
                if lines_read > 10:
                    break
                data = json.loads(line)
                # Look for the first user message (task description)
                if data.get("type") == "message":
                    msg = data.get("message", "")
                    if isinstance(msg, str):
                        try:
                            msg = json.loads(msg)
                        except:
                            continue
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    text = c.get("text", "")
                                    # Extract first meaningful line as label
                                    for tline in text.split("\n"):
                                        tline = tline.strip().strip("#").strip()
                                        if tline and len(tline) > 5:
                                            return tline[:60]
    except:
        pass
    return None


def infer_char_from_label(label: str | None) -> str | None:
    """Infer the intended character from spawn label suffix.
    
    When model=grok but XAI_API_KEY is missing, OpenClaw falls back to opus.
    The spawn label (e.g. 'fx-spike-twitter-research-grok') still contains
    the intended model name. Use this as fallback for Pixoo character display.
    """
    if not label:
        return None
    label_lower = label.lower()
    for suffix, char in LABEL_SUFFIX_TO_CHAR.items():
        if suffix in label_lower:
            return char
    return None


def _load_session_store() -> dict:
    """Load sessions.json once and return a comprehensive metadata dict.

    Returns:
        {
            "main_session_id": str | None,         # sessionId for agent:main:main
            "excluded_ids": set[str],               # sessionIds that are NOT subagents
                                                    # (main, cron, openai, discord, etc.)
            "labels": dict[str, str],               # sessionId → label
            "models": dict[str, str],               # sessionId → model (from sessions.json)
        }
    """
    result = {
        "main_session_id": None,
        "excluded_ids": set(),
        "labels": {},
        "models": {},
    }
    try:
        with open(SESSIONS_JSON_STORE, 'r', errors='ignore') as fh:
            data = json.loads(fh.read())
        for key, val in data.items():
            if not isinstance(val, dict):
                continue
            session_id = val.get("sessionId", "")
            if not session_id:
                continue
            # OpenClaw stores model in 'model' or 'modelOverride' depending on version
            model = val.get("model", "") or val.get("modelOverride", "") or ""
            label = val.get("label", "") or ""

            # Derive label from key slug when not set explicitly
            if not label and ":subagent:" in key:
                suffix = key.split(":subagent:", 1)[-1]
                # Only use if it looks like a slug (not a bare UUID)
                if suffix and "-" in suffix and len(suffix) < 80 and not (
                    len(suffix) == 36 and suffix.count("-") == 4
                ):
                    label = suffix

            if model:
                result["models"][session_id] = model
            if label:
                result["labels"][session_id] = label

            # Identify main session (authoritative)
            if key == "agent:main:main":
                result["main_session_id"] = session_id

            # Anything that is NOT a subagent goes into excluded set
            is_subagent = ":subagent:" in key
            if not is_subagent:
                result["excluded_ids"].add(session_id)

    except (OSError, json.JSONDecodeError, Exception):
        pass
    return result


def _load_session_labels() -> dict[str, str]:
    """Compatibility shim — returns sessionId → label mapping."""
    return _load_session_store()["labels"]


def find_active_subagents() -> list[dict]:
    """Scan session files for active subagent sessions.
    
    Main session identification: The LARGEST opus session file is always the
    main session (it accumulates conversation history). This is more robust
    than using mtime, which can be confused by multiple opus sessions
    (e.g., when subagents fall back to opus due to API rate limits).
    """
    now = time.time()
    active = []
    
    if not SESSIONS_DIR.exists():
        return active
    
    # Load sessions.json once — authoritative source for main session + labels
    store = _load_session_store()
    session_labels = store["labels"]
    session_models = store["models"]
    excluded_ids   = store["excluded_ids"]   # non-subagent sessions (cron, openai, etc.)

    # Main session ID: prefer sessions.json (agent:main:main key), else largest opus fallback.
    main_session_id: str | None = store["main_session_id"]
    if not main_session_id:
        # Fallback heuristic: largest opus file (for very old sessions not in sessions.json)
        main_size = 0
        for f in SESSIONS_DIR.glob("*.jsonl"):
            model = get_session_model(f)
            fsize = f.stat().st_size
            if model == MAIN_SESSION_MODEL and fsize > main_size:
                main_session_id = f.stem
                main_size = fsize

    # Pass: Find active subagent sessions
    for f in SESSIONS_DIR.glob("*.jsonl"):
        mtime = f.stat().st_mtime
        age = now - mtime

        # Quick skip: extremely old files (beyond even running cap)
        if age > MAX_AGE_RUNNING_SEC:
            continue
        
        # Skip main session (by authoritative ID from sessions.json)
        if f.stem == main_session_id:
            continue
        
        # Skip non-subagent sessions (cron, openai relay, discord relay, etc.)
        if f.stem in excluded_ids:
            continue
        
        # Skip tiny files (< 1KB = probably just initialized, no real work)
        if f.stat().st_size < 1000:
            continue
        
        # Check completion
        completed = is_session_completed(f)
        if completed:
            continue
        
        # Stale detection: if file hasn't been modified in MAX_AGE_SEC,
        # the session is almost certainly done — OpenClaw just didn't write
        # a clean stopReason. Drop it to prevent zombie display.
        if age > MAX_AGE_SEC:
            continue

        # --- Character detection (priority order) ---
        # 1. Label from sessions.json (most reliable — set by OpenClaw at spawn time)
        sessions_label = session_labels.get(f.stem, "")
        char = infer_char_from_label(sessions_label) if sessions_label else None

        # 2. Model from sessions.json (accurate when non-opus)
        if not char:
            sj_model = session_models.get(f.stem, "")
            if sj_model and sj_model != MAIN_SESSION_MODEL:
                char = MODEL_TO_CHAR.get(sj_model, "")
                if not char:
                    for km, kc in MODEL_TO_CHAR.items():
                        if km in sj_model or sj_model in km:
                            char = kc
                            break

        # 3. Model from JSONL tail (actual API response model)
        model = get_session_model(f)
        if not char and model:
            char = MODEL_TO_CHAR.get(model, "")
            if not char:
                for km, kc in MODEL_TO_CHAR.items():
                    if km in model or model in km:
                        char = kc
                        break

        if not char:
            char = "opus"  # honest default fallback (not "sonnet")

        # 4. If still opus, try label from JSONL task text
        if char == "opus":
            jsonl_label = get_session_label(f)
            inferred = infer_char_from_label(jsonl_label)
            if inferred:
                char = inferred

        # Build display label: prefer sessions.json label, fall back to JSONL task text
        if not model:
            model = "(unknown)"
        label = sessions_label or get_session_label(f) or f"({model})"
        
        # Read actual session start time from JSONL header
        started = get_session_started(f) or (mtime - 30)  # fallback: 30s before mtime
        
        active.append({
            "id": f.stem[:8],
            "char": char,
            "task": label,
            "started": started,
            "session_file": f.name,
            "age_sec": int(age),
        })
    
    return active


def check_main_session_active() -> bool:
    """Check if the main session (ロブ🦞) has been active recently."""
    now = time.time()
    if not SESSIONS_DIR.exists():
        return False
    
    for f in SESSIONS_DIR.glob("*.jsonl"):
        mtime = f.stat().st_mtime
        age = now - mtime
        
        # Main session = opus model, recently modified
        if age > ACTIVE_WINDOW_SEC:
            continue
        
        model = get_session_model(f)
        if model == MAIN_SESSION_MODEL:
            return True
    
    return False


def sync_state(agents: list[dict], main_active: bool = False) -> bool:
    """Update pixoo-agents.json. Returns True if changed.
    
    Preserves manually-added agents (source='manual') from pixoo-agent-ctl.py.
    Auto-detected agents get source='auto'.
    """
    now = time.time()
    new_agents = []
    for a in agents:
        new_agents.append({
            "id": a["id"],
            "char": a["char"],
            "task": a["task"],
            "started": a["started"],
            "last_seen": now,
            "source": "auto",
        })
    
    # Read current state
    current = {"agents": [], "main_active": False}
    try:
        if STATE_FILE.exists():
            current = json.loads(STATE_FILE.read_text())
    except:
        pass
    
    # Preserve manual entries (added via pixoo-agent-ctl.py) that haven't expired
    auto_ids = {a["id"] for a in new_agents}
    for existing in current.get("agents", []):
        if existing.get("source") == "manual" and existing.get("id") not in auto_ids:
            # Keep manual entries alive if within TTL (10 min from last_seen)
            last_seen = existing.get("last_seen", existing.get("started", 0))
            if now - last_seen < AGENT_TTL_SEC:
                new_agents.append(existing)
    
    current_ids = {a.get("id") for a in current.get("agents", [])}
    new_ids = {a["id"] for a in new_agents}
    current_main = current.get("main_active", False)
    
    if current_ids == new_ids and current_main == main_active:
        return False
    
    # Atomic write: write to temp file then rename, so the display daemon
    # never reads a half-written JSON file.
    payload = json.dumps({
        "agents": new_agents,
        "main_active": main_active,
    }, ensure_ascii=False, indent=2)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(STATE_FILE.parent), suffix=".tmp", prefix=".pixoo-agents-"
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
    return True


def main():
    print("[pixoo-agent-sync] Started")
    print(f"[i] Watching: {SESSIONS_DIR}")
    print(f"[i] Active window: {ACTIVE_WINDOW_SEC}s")
    print(f"[i] Poll interval: {POLL_SEC}s")
    
    last_count = -1
    
    while True:
        try:
            agents = find_active_subagents()
            main_active = check_main_session_active()
            changed = sync_state(agents, main_active)
            
            if changed or len(agents) != last_count:
                chars = [a["char"] for a in agents]
                status = "🦞 active" if main_active else "💤 idle"
                if agents:
                    print(f"[i] Active: {len(agents)} — {', '.join(chars)} (main: {status})")
                else:
                    print(f"[i] No active subagents (main: {status})")
                last_count = len(agents)
            
            time.sleep(POLL_SEC)
        except KeyboardInterrupt:
            print("\n[i] Stopped")
            break
        except Exception as e:
            print(f"[!] Error: {e}")
            time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
