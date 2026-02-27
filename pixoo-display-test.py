#!/usr/bin/env python3
"""
Pixoo-64 status display v6
- Normal digits (no emoji keycap) + rainbow color cycling timer
- Sleep mode after 10min idle (uses sleep frames with Z animation)
- Dynamic scroll text from latest subagent task
- All 7 character variants loaded
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import types
from pathlib import Path
from typing import List, Tuple

import re

from PIL import Image, ImageDraw, ImageFont


def _ensure_pixoo_import_works_without_tk() -> None:
    try:
        import tkinter  # noqa: F401
        return
    except Exception:
        pass
    tk_stub = types.ModuleType("tkinter")

    class _Dummy:
        def __init__(self, *a, **kw): pass
        def __getattr__(self, _): return lambda *a, **k: None
        def pack(self, *a, **kw): pass
        def create_image(self, *a, **kw): return None
        def itemconfig(self, *a, **kw): pass
        def update(self, *a, **kw): pass
        def title(self, *a, **kw): pass
        def geometry(self, *a, **kw): pass
        def attributes(self, *a, **kw): pass

    tk_stub.Tk = _Dummy
    tk_stub.Canvas = _Dummy
    sys.modules.setdefault("tkinter", tk_stub)
    imgtk_stub = types.ModuleType("PIL.ImageTk")

    class PhotoImage:
        def __init__(self, *a, **kw): pass

    imgtk_stub.PhotoImage = PhotoImage
    sys.modules.setdefault("PIL.ImageTk", imgtk_stub)


_ensure_pixoo_import_works_without_tk()
from pixoo import Pixoo  # noqa: E402
from pilmoji import Pilmoji  # noqa: E402

# --- Config ---
PIXOO_IP = "192.168.86.42"
DISPLAY_SIZE = 64
FRAME_INTERVAL_MS = 250
SCROLL_SPEED_MS = 150  # ~6.7 FPS scroll (Phase 5-C: reduced from 100ms to save CPU)
TEXT_STEP_PX = 1
CHARACTER_SWAP_SEC = 5.0
STATE_FILE = Path("/tmp/pixoo-agents.json")
STATE_POLL_SEC = 3.0  # Phase 5-C: sync daemon polls every 3s, no need to check faster
SLEEP_AFTER_SEC = 1200  # 20 minutes idle — 10分だとロブ🦞が思考中に寝てしまう問題の修正
AGENT_TTL_SEC = 600    # auto-expire agents after 10 minutes (safety net)

SCROLL_FONT_SIZE = 10
UI_FONT_SIZE = 8

FALLBACK_TICKER = "ロブ稼働中！サブエージェント待機中..."
SLEEP_TICKER = "ロブ就寝中...zzZ"
TODO_FILE = Path("/mnt/c/Users/danpu/OneDrive/Desktop/obsidianVault/openclaw/memory/tasks/todo-priority.md")
TODO_POLL_SEC = 60  # re-read todo file every 60s

# Git repos to scan for latest commits (ticker display)
GIT_REPOS = [
    Path("/mnt/c/Users/danpu/OneDrive/Desktop/obsidianVault/openclaw"),
    Path("/mnt/c/Users/danpu/OneDrive/Desktop/fx-backtest-system"),
    Path("/mnt/c/Users/danpu/OneDrive/Desktop/pixoo-display"),
    Path("/home/yama/lobster-desktop-widget"),
    Path("/home/yama/pico-pedal-bridge"),
    Path("/home/yama/smart-home-dashboard"),
    Path("/home/yama/kyousei-kun"),
    Path("/home/yama/typeless-text-relay"),
    Path("/home/yama/switchbot-home-integration"),
    Path("/home/yama/nest-home-proxy"),
    Path("/home/yama/tuya-home-proxy"),
    Path("/home/yama/pixoo-notify-proxy"),
]
GIT_POLL_SEC = 30  # re-scan git repos every 30s

CHARACTER_FRAMES = {
    "opus":       [f"/tmp/lob64-opus-frame{i}.png" for i in range(1, 5)],
    "sonnet":     [f"/tmp/lob64-sonnet-frame{i}.png" for i in range(1, 5)],
    "haiku":      [f"/tmp/lob64-haiku-frame{i}.png" for i in range(1, 5)],
    "gemini":     [f"/tmp/lob64-gemini-frame{i}.png" for i in range(1, 5)],
    "kusomegane": [f"/tmp/lob64-kusomegane-frame{i}.png" for i in range(1, 5)],
    "codex":      [f"/tmp/lob64-codex-frame{i}.png" for i in range(1, 5)],
    "grok":       [f"/tmp/lob64-grok-frame{i}.png" for i in range(1, 5)],
}
SLEEP_FRAMES = [f"/tmp/lob64-opus-sleep-frame{i}.png" for i in range(1, 5)]

TIMER_COLORS = [
    (255, 50, 50),
    (255, 160, 0),
    (255, 255, 0),
    (0, 255, 80),
    (0, 220, 255),
    (80, 120, 255),
    (180, 60, 255),
    (255, 60, 200),
]

# --- Icon bar (Phase 2) ---
ROLE_COLORS: dict[str, Tuple[int, int, int]] = {
    "DIR": (180, 0, 255),    # purple
    "PL":  (0, 120, 255),    # blue
    "DEV": (0, 200, 80),     # green
    "QA":  (255, 200, 0),    # yellow
    "SEC": (255, 60, 60),    # red
    "RES": (255, 140, 0),    # orange
}
ROLE_DISPLAY_ORDER = {"DIR": 0, "PL": 1, "QA": 2, "SEC": 3, "DEV": 4, "RES": 5}
ICON_BAR_H = 21  # Issue #2: 2-row layout (row1: worker name 11px, row2: role label 9px)
ICON_BAR_ROW1_FONT_SIZE = 11  # worker name (Issue #2: was 8, now 11 for readability)
ICON_BAR_ROW2_FONT_SIZE = 9   # role label (large, readable on 64px LED)
ICON_LABEL_GAP = 1

ROLE_LABELS: dict[str, str] = {
    "DIR": "DIR",
    "PL":  "PL",
    "DEV": "DEV",
    "QA":  "QA",
    "SEC": "SEC",
    "RES": "RES",
}

FONT_CANDIDATES = [
    "/home/yama/.fonts/meiryo.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001F9FF\U0001FA00-\U0001FEFF\u2600-\u26FF\u2700-\u27BF]+"
)


def strip_emoji(text: str) -> str:
    """Remove emoji characters so PIL bitmap fonts can render the text."""
    return _EMOJI_RE.sub("", text).strip()


def load_font(size: int = 8) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for fp in FONT_CANDIDATES:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def text_bbox_size(font: ImageFont.ImageFont, text: str) -> Tuple[int, int]:
    probe = Image.new("RGB", (1, 1), (0, 0, 0))
    d = ImageDraw.Draw(probe)
    b = d.textbbox((0, 0), text, font=font)
    return b[2] - b[0], b[3] - b[1]


def measure_pilmoji_width(text: str, font: ImageFont.ImageFont) -> int:
    probe = Image.new("RGB", (800, 40), (0, 0, 0))
    with Pilmoji(probe) as pm:
        try:
            size = pm.getsize(text, font)
            return size[0] if isinstance(size, tuple) else size
        except Exception:
            w, _ = text_bbox_size(font, text)
            return w


def load_frames(paths: list) -> List[Image.Image] | None:
    frames = []
    for path in paths:
        if not Path(path).exists():
            return None
        img = Image.open(path).convert("RGB")
        if img.size != (DISPLAY_SIZE, DISPLAY_SIZE):
            img = img.resize((DISPLAY_SIZE, DISPLAY_SIZE), Image.NEAREST)
        frames.append(img)
    return frames if frames else None


def read_agent_state() -> tuple[list, bool]:
    """Returns (agents_list, main_active_flag)."""
    if not STATE_FILE.exists():
        return [], False
    try:
        data = json.loads(STATE_FILE.read_text())
        agents = data.get("agents", [])
        main_active = data.get("main_active", False)
        # TTL: auto-expire stale agents (safety net for missed removes)
        # Use last_seen (when sync daemon last wrote) instead of started (session creation)
        now = time.time()
        def _safe_ts(a: dict) -> float:
            """Safely extract timestamp, defaulting to now for invalid values."""
            try:
                return float(a.get("last_seen", a.get("started", now)))
            except (TypeError, ValueError):
                return now
        live = [a for a in agents if now - _safe_ts(a) < AGENT_TTL_SEC]
        if len(live) < len(agents):
            expired = len(agents) - len(live)
            print(f"[i] TTL expired {expired} agent(s)")
            # Note: do NOT write back to STATE_FILE here.
            # Only sync daemon should write (atomic via tempfile+os.replace).
            # Display side is read-only to avoid race conditions.
        return live, main_active
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, TypeError, ValueError):
        return [], False


def draw_outlined_text(draw, xy, text, font, fill):
    x, y = xy
    for ox in [-1, 0, 1]:
        for oy in [-1, 0, 1]:
            if ox == 0 and oy == 0:
                continue
            draw.text((x + ox, y + oy), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=fill)


def pilmoji_outlined(pm, xy, text, font, fill):
    x, y = xy
    for ox in [-1, 0, 1]:
        for oy in [-1, 0, 1]:
            if ox == 0 and oy == 0:
                continue
            pm.text((x + ox, y + oy), text, font=font, fill=(0, 0, 0))
    pm.text((x, y), text, font=font, fill=fill)


def get_count_color(count: int) -> Tuple[int, int, int]:
    """Dramatic gradient: 1=bright green → 4=yellow → 7=deep red.

    Uses a hand-tuned 7-stop palette so every count is visually distinct,
    even on the tiny Pixoo-64 display.
    """
    PALETTE = {
        1: (0, 255, 80),    # bright green
        2: (100, 255, 0),   # lime
        3: (200, 230, 0),   # yellow-green
        4: (255, 200, 0),   # yellow-orange
        5: (255, 120, 0),   # orange
        6: (255, 50, 0),    # red-orange
        7: (255, 0, 0),     # pure red
    }
    c = max(1, min(count, 7))
    return PALETTE[c]


def get_latest_task_text(agents: list) -> str | None:
    """Get scroll text from agents — prefer capture-pane scroll_text (Phase 3).

    Priority: active agent with scroll_text > any agent with scroll_text > task name.
    """
    if not agents:
        return None

    MAX_TICKER_LEN = 150  # Phase 5: cap ticker length to prevent OOM from huge strings

    # Prefer active agents with scroll_text
    active_with_text = [
        a for a in agents
        if a.get("scroll_text") and a.get("status") == "active"
    ]
    if active_with_text:
        latest = max(active_with_text, key=lambda a: a.get("last_seen", 0))
        role = latest.get("role", "?")
        text = strip_emoji(latest["scroll_text"][:MAX_TICKER_LEN])
        return f"[{role}] {text}"

    # Any agent with scroll_text
    with_text = [a for a in agents if a.get("scroll_text")]
    if with_text:
        latest = max(with_text, key=lambda a: a.get("last_seen", 0))
        role = latest.get("role", "?")
        text = strip_emoji(latest["scroll_text"][:MAX_TICKER_LEN])
        return f"[{role}] {text}"

    # Fallback to task name
    sorted_agents = sorted(agents, key=lambda a: a.get("started", 0), reverse=True)
    latest = sorted_agents[0]
    task = strip_emoji(str(latest.get("task", ""))[:MAX_TICKER_LEN])
    char = latest.get("char", "?")
    if task:
        return f"[{char}] {task}"
    return None


def get_top_priority_task() -> str:
    """Read todo-priority.md and return the first priority section title."""
    try:
        if not TODO_FILE.exists():
            return FALLBACK_TICKER
        text = TODO_FILE.read_text(encoding="utf-8")
        # Find first "### " line under "## 🔥" section
        in_priority = False
        for line in text.splitlines():
            if line.startswith("## 🔥"):
                in_priority = True
                continue
            if in_priority and line.startswith("### "):
                # Extract task name, strip markdown
                task = strip_emoji(line.lstrip("#").strip())
                return f"TOP: {task}"
            if in_priority and line.startswith("## ") and not line.startswith("## 🔥"):
                break  # next section
        return FALLBACK_TICKER
    except Exception:
        return FALLBACK_TICKER


def get_latest_git_commits() -> str:
    """Scan all repos and return the most recent commit as ticker text.

    Returns a string like: "🔧 [openclaw] 3a57c3a 記憶弱化修正 (2m ago)"
    Scans all GIT_REPOS sorted by commit time, picks the freshest.
    """
    import subprocess
    now = time.time()
    best = None  # (timestamp, repo_name, hash, message)

    for repo in GIT_REPOS:
        if not (repo / ".git").exists():
            continue
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "log", "-1",
                 "--format=%ct\t%h\t%s"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                continue
            line = result.stdout.strip()
            if not line:
                continue
            parts = line.split("\t", 2)
            if len(parts) < 3:
                continue
            ts = int(parts[0])
            commit_hash = parts[1]
            message = strip_emoji(parts[2])
            repo_name = repo.name
            if best is None or ts > best[0]:
                best = (ts, repo_name, commit_hash, message)
        except Exception:
            continue

    if not best:
        return FALLBACK_TICKER

    ts, repo_name, commit_hash, message = best
    age = now - ts

    # Human-readable age
    if age < 60:
        age_str = f"{int(age)}s"
    elif age < 3600:
        age_str = f"{int(age // 60)}m"
    elif age < 86400:
        age_str = f"{int(age // 3600)}h"
    else:
        age_str = f"{int(age // 86400)}d"

    # Truncate long messages for readability on 64px display
    if len(message) > 60:
        message = message[:57] + "..."

    return f"🔧 [{repo_name}] {commit_hash} {message} ({age_str}前)"


class ScrollTextCache:
    """Pre-render scroll text as a horizontal strip to avoid Pilmoji per-frame."""

    def __init__(self):
        self._text: str = ""
        self._strip: Image.Image | None = None
        self._strip_w: int = 0
        self._strip_h: int = 0

    def get_strip(self, text: str, font: ImageFont.ImageFont) -> Image.Image:
        if text == self._text and self._strip is not None:
            return self._strip
        # Measure width
        w = measure_pilmoji_width(text, font)
        # Use descender-heavy chars to get true max height
        probe = Image.new("RGB", (1, 1))
        d = ImageDraw.Draw(probe)
        b = d.textbbox((0, 0), "あgyj漢", font=font)
        h = b[3] - b[1]
        h += 6  # padding for outline + descender safety
        w += 4
        # Render once onto a transparent strip
        strip = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        with Pilmoji(strip) as pm:
            # Black outline (8 directions)
            for ox in [-1, 0, 1]:
                for oy in [-1, 0, 1]:
                    if ox == 0 and oy == 0:
                        continue
                    pm.text((2 + ox, 2 + oy), text, font=font, fill=(0, 0, 0, 255))
            pm.text((2, 2), text, font=font, fill=(255, 255, 255, 255))
        self._text = text
        self._strip = strip
        self._strip_w = w
        self._strip_h = h
        return strip

    @property
    def width(self) -> int:
        return self._strip_w

    @property
    def height(self) -> int:
        return self._strip_h


_scroll_cache = ScrollTextCache()


def compose_frame(
    bg_frame: Image.Image,
    scroll_font: ImageFont.ImageFont,
    ui_font: ImageFont.ImageFont,
    scroll_text: str,
    scroll_x: int,
    agents: list,
    main_active: bool,
    elapsed_sec: float | None,
    color_tick: int,
    is_main: bool,
    scroll_text_h: int,
    current_agent: dict | None = None,
) -> Image.Image:
    """Compose a single display frame with icon bar, character, and scroll text.

    Phase 5.3: Sprite is drawn full-size. Icon bar text is rendered on a
    transparent RGBA overlay with draw_outlined_text for contrast, then
    composited on top of the sprite via alpha mask (same technique as
    the scroll text strip).
    """
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), (0, 0, 0))

    # --- Character: full-size sprite (only 4px top margin crop) ---
    img.paste(bg_frame.crop((0, 4, DISPLAY_SIZE, DISPLAY_SIZE)), (0, 0))

    # --- Scroll text position ---
    marquee_y = DISPLAY_SIZE - scroll_text_h - 5

    # --- Transparent overlay for icon bar + xN count ---
    overlay = Image.new("RGBA", (DISPLAY_SIZE, DISPLAY_SIZE), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    # Lazy-init fonts for both rows
    if not hasattr(compose_frame, "_row1_font"):
        compose_frame._row1_font = load_font(size=ICON_BAR_ROW1_FONT_SIZE)
    if not hasattr(compose_frame, "_row2_font"):
        compose_frame._row2_font = load_font(size=ICON_BAR_ROW2_FONT_SIZE)
    if not hasattr(compose_frame, "_timer_font"):
        compose_frame._timer_font = load_font(size=7)
    row1_font = compose_frame._row1_font
    row2_font = compose_frame._row2_font
    timer_font = compose_frame._timer_font

    # Timer string (subagents only, rendered in row 2 right side)
    timer_str = None
    timer_w = 0
    if not is_main and elapsed_sec is not None:
        minutes = int(elapsed_sec) // 60
        seconds = int(elapsed_sec) % 60
        timer_str = f"{minutes}:{seconds:02d}"
        tw, _ = text_bbox_size(timer_font, timer_str)
        timer_w = tw + 4  # reserve space with gap

    ix = 1
    row1_y = 0   # worker name row
    row2_y = 12  # role label row (Issue #2: shifted down from 9 to match 11px row1 font)

    if current_agent is not None:
        role = current_agent.get("role", "DEV")
        status = current_agent.get("status", "active")
        label = ROLE_LABELS.get(role, role)

        # Row 1: Worker name (task name from agent) — Issue #2: strip emoji, bigger font
        worker_name = strip_emoji(current_agent.get("task", current_agent.get("id", "")))
        if worker_name:
            max_w = DISPLAY_SIZE - 2
            wn_w, _ = text_bbox_size(row1_font, worker_name)
            if wn_w > max_w:
                while len(worker_name) > 3 and wn_w > max_w:
                    worker_name = worker_name[:-1]
                    wn_w, _ = text_bbox_size(row1_font, worker_name + "..")
                worker_name = worker_name + ".."
            wn_color = ROLE_COLORS.get(role, (200, 200, 200))  # Issue #2: brighter fallback
            draw_outlined_text(odraw, (ix, row1_y), worker_name, row1_font, fill=wn_color)

        # Row 2: Role label
        color = ROLE_COLORS.get(role, (128, 128, 128))
        if status == "error":
            color = (255, 0, 0)
        elif status == "waiting":
            pass  # full brightness
        elif status not in ("active",):
            color = (color[0] * 2 // 3, color[1] * 2 // 3, color[2] * 2 // 3)

        draw_outlined_text(odraw, (ix, row2_y), label, row2_font, fill=color)
    elif is_main and main_active:
        label = ROLE_LABELS.get("DIR", "DIR")
        color = ROLE_COLORS.get("DIR", (180, 0, 255))
        draw_outlined_text(odraw, (ix, row2_y), label, row2_font, fill=color)

    # Timer in row 2 right side
    if timer_str:
        timer_color = TIMER_COLORS[color_tick % len(TIMER_COLORS)]
        timer_x = DISPLAY_SIZE - timer_w + 2
        draw_outlined_text(odraw, (timer_x, row2_y + 1), timer_str, timer_font, fill=timer_color)

    # --- Top-right count: xN (agent count) in row 1 ---
    agent_count = len(agents)
    if agent_count >= 1:
        count_str = str(agent_count)
        x_label = "x"
        count_color = get_count_color(agent_count)
        x_w, _ = text_bbox_size(ui_font, x_label)
        n_w, _ = text_bbox_size(ui_font, count_str)
        gap = 1
        total_w = x_w + gap + n_w
        x0 = DISPLAY_SIZE - total_w - 1
        y0 = 1
        draw_outlined_text(odraw, (x0, y0), x_label, ui_font, fill=(140, 140, 140))
        draw_outlined_text(odraw, (x0 + x_w + gap, y0), count_str, ui_font, fill=count_color)

    # Composite transparent overlay onto sprite
    img.paste(overlay, (0, 0), overlay)

    # --- Scroll text: paste pre-rendered strip (fast!) ---
    strip = _scroll_cache.get_strip(scroll_text, scroll_font)
    src_x = max(0, -scroll_x)
    dst_x = max(0, scroll_x)
    visible_w = min(DISPLAY_SIZE - dst_x, strip.width - src_x)
    if visible_w > 0 and src_x < strip.width:
        text_region = strip.crop((src_x, 0, src_x + visible_w, strip.height))
        img.paste(text_region, (dst_x, marquee_y - 2), text_region)

    return img


def run(duration_sec: float | None = None) -> None:
    opus_frames = load_frames(CHARACTER_FRAMES["opus"])
    if not opus_frames:
        raise RuntimeError("Opus frames not found!")

    sleep_frames = load_frames(SLEEP_FRAMES)
    if not sleep_frames:
        print("[!] Sleep frames not found, using opus")
        sleep_frames = opus_frames

    scroll_font = load_font(size=SCROLL_FONT_SIZE)
    ui_font = load_font(size=UI_FONT_SIZE)
    # Use descender-heavy chars for accurate height measurement
    _probe = Image.new("RGB", (1, 1))
    _bbox = ImageDraw.Draw(_probe).textbbox((0, 0), "あgyj漢", font=scroll_font)
    scroll_text_h = _bbox[3] - _bbox[1]

    pixoo = None
    try:
        for _attempt in range(3):
            try:
                pixoo = Pixoo(PIXOO_IP)
                break
            except Exception as e:
                print(f"[!] Pixoo init failed (attempt {_attempt + 1}/3): {e}")
                if _attempt < 2:  # no sleep after the final failed attempt
                    time.sleep(5)
    except KeyboardInterrupt:
        print("\n[i] Interrupted during init")
        return
    if pixoo is None:
        raise RuntimeError(f"Cannot connect to Pixoo at {PIXOO_IP} after 3 attempts")
    char_frame_cache: dict[str, List[Image.Image]] = {"opus": opus_frames}

    for name, paths in CHARACTER_FRAMES.items():
        if name not in char_frame_cache:
            loaded = load_frames(paths)
            if loaded:
                char_frame_cache[name] = loaded
                print(f"[i] Loaded: {name}")

    # Scroll text state — Git commit ticker (primary), todo fallback
    default_ticker = get_latest_git_commits()
    current_ticker = default_ticker
    _scroll_cache.get_strip(current_ticker, scroll_font)
    current_ticker_w = _scroll_cache.width
    last_todo_check_t = time.monotonic()

    anim_frame_idx = 0
    text_x = DISPLAY_SIZE
    color_tick = 0
    display_list: list = []
    display_idx = 0
    current_display_char: str | None = None  # Track by name, not index
    agent_count = 0
    current_agents: list = []       # Phase 2: full agent list for icon bar
    current_main_active: bool = False
    is_sleeping = False
    last_active_time = time.monotonic()
    last_pushed_key: tuple | None = None  # Phase 5-C: skip redundant pushes

    start = time.monotonic()
    next_frame_t = start
    next_scroll_t = start
    last_char_swap_t = start
    last_state_check_t = 0.0

    print(f"[i] Connected to Pixoo at {PIXOO_IP}")
    print(f"[i] Characters: {', '.join(char_frame_cache.keys())}")
    print(f"[i] Sleep: after {SLEEP_AFTER_SEC}s idle")
    print(f"[i] Dynamic scroll text: enabled")
    print("[i] Press Ctrl+C to stop" if duration_sec is None else f"[i] Running for {duration_sec:.1f}s")

    try:
        while True:
            now = time.monotonic()
            wall_now = time.time()

            if duration_sec is not None and (now - start) >= duration_sec:
                break

            # Poll state file
            if now - last_state_check_t >= STATE_POLL_SEC:
                agents, main_active = read_agent_state()
                current_agents = agents
                current_main_active = main_active
                new_count = len(agents)

                # サブエージェント活動中 → サブエージェントだけ表示（ロブ🦞なし）
                # アイドル時 → ロブ🦞のみ表示
                if agents:
                    new_display_list = []
                    for a in agents:
                        char_name = a.get("char", "sonnet")
                        if char_name not in char_frame_cache:
                            char_name = "opus"
                        new_display_list.append({
                            "char": char_name,
                            "started": a.get("started"),
                            "is_main": False,
                        })
                else:
                    new_display_list = [{"char": "opus", "started": None, "is_main": True}]

                if new_count != agent_count:
                    old_count = agent_count
                    new_chars = [d["char"] for d in new_display_list]
                    print(f"[i] Subagents: {new_count} chars={new_chars} display_idx={display_idx}")
                    # Reset swap timer on 0→N transition to prevent immediate swap
                    if old_count == 0 and new_count > 0:
                        last_char_swap_t = now
                        print(f"[rot] reset-timer: agents 0→{new_count}, swap timer reset")
                    # All agents gone
                    if old_count > 0 and new_count == 0:
                        print(f"[rot] reset: agents gone, fallback to idx 0 (opus)")
                    # Single agent: log only on 0→1 transition (P1-C fix)
                    if new_count == 1 and old_count == 0:
                        print(f"[rot] single-agent: {new_chars[0]} (no rotation needed)")
                    agent_count = new_count

                # Re-scan git repos periodically for latest commit
                if now - last_todo_check_t >= GIT_POLL_SEC:
                    default_ticker = get_latest_git_commits()
                    last_todo_check_t = now

                # Update scroll text dynamically
                task_text = get_latest_task_text(agents)
                if task_text:
                    new_ticker = task_text
                elif is_sleeping:
                    new_ticker = SLEEP_TICKER
                else:
                    new_ticker = default_ticker

                if new_ticker != current_ticker:
                    current_ticker = new_ticker
                    _scroll_cache.get_strip(current_ticker, scroll_font)
                    current_ticker_w = _scroll_cache.width
                    text_x = DISPLAY_SIZE  # reset scroll position
                    print(f"[i] Ticker: {current_ticker}")

                if new_count > 0 or main_active:
                    last_active_time = now
                    if is_sleeping:
                        is_sleeping = False
                        wake_reason = "subagents" if new_count > 0 else "main session"
                        print(f"[i] Woke up! ({wake_reason})")

                # Sleep check — only sleep if both subagents AND main are idle
                if new_count == 0 and not main_active and (now - last_active_time) >= SLEEP_AFTER_SEC:
                    if not is_sleeping:
                        is_sleeping = True
                        print("[i] Sleep mode")

                # Preserve current character across list rebuilds to prevent
                # mid-rotation jumps (fixes Grok early-disappear bug).
                old_chars = [d["char"] for d in display_list]
                old_char = current_display_char
                old_is_main = display_list[display_idx]["is_main"] if display_list and display_idx < len(display_list) else True
                old_display_idx = display_idx
                display_list = new_display_list
                new_chars_rebuild = [d["char"] for d in display_list]

                if old_char and display_list:
                    found_idx = None
                    # Try to find exact match (same char + same is_main flag)
                    for i, entry in enumerate(display_list):
                        if entry["char"] == old_char and entry["is_main"] == old_is_main:
                            found_idx = i
                            break
                    if found_idx is None:
                        # Fallback: match by char name only
                        for i, entry in enumerate(display_list):
                            if entry["char"] == old_char:
                                found_idx = i
                                break
                    if found_idx is not None:
                        display_idx = found_idx
                        current_display_char = display_list[display_idx]["char"]  # P1-A fix: sync char name
                        if old_chars != new_chars_rebuild:
                            print(f"[rot] list-rebuild: {old_chars} → {new_chars_rebuild} (preserved: {old_char}@{display_idx})")
                    else:
                        # Character gone: clamp to nearest valid position instead of resetting to 0
                        display_idx = min(old_display_idx, len(display_list) - 1) if display_list else 0
                        current_display_char = display_list[display_idx]["char"] if display_list else "opus"
                        print(f"[rot] list-rebuild: {old_chars} → {new_chars_rebuild} (gone: {old_char}, fallback idx {display_idx} → {current_display_char})")
                elif display_idx >= len(display_list):
                    display_idx = 0
                last_state_check_t = now

            if agent_count == 0:
                display_idx = 0
                current_display_char = "opus"

            if agent_count > 0 and now - last_char_swap_t >= CHARACTER_SWAP_SEC:
                if len(display_list) <= 1:
                    # Single agent: just reset timer, no rotation
                    last_char_swap_t = now
                else:
                    old_idx = display_idx
                    old_char_name = display_list[old_idx]["char"] if old_idx < len(display_list) else "?"
                    display_idx = (display_idx + 1) % len(display_list)
                    anim_frame_idx = 0
                    last_char_swap_t = now
                    cur = display_list[display_idx]
                    current_display_char = cur["char"]
                    print(f"[rot] swap: {old_char_name} → {current_display_char} (idx {old_idx}→{display_idx}/{len(display_list)}, interval={CHARACTER_SWAP_SEC}s)")

            updated = False

            while now >= next_frame_t:
                if is_sleeping:
                    anim_frame_idx = (anim_frame_idx + 1) % len(sleep_frames)
                else:
                    cur_char = display_list[display_idx]["char"] if display_list else "opus"
                    frames = char_frame_cache.get(cur_char, opus_frames)
                    anim_frame_idx = (anim_frame_idx + 1) % len(frames)
                color_tick += 1
                next_frame_t += FRAME_INTERVAL_MS / 1000.0
                updated = True

            while now >= next_scroll_t:
                text_x -= TEXT_STEP_PX
                if text_x + current_ticker_w < 0:
                    text_x = DISPLAY_SIZE
                next_scroll_t += SCROLL_SPEED_MS / 1000.0
                updated = True

            if updated:
                if is_sleeping:
                    bg = sleep_frames[anim_frame_idx % len(sleep_frames)]
                    is_main_flag = True
                    elapsed = None
                else:
                    cur_entry = display_list[display_idx] if display_list else {"char": "opus", "started": None, "is_main": True}
                    cur_char = cur_entry["char"]
                    frames = char_frame_cache.get(cur_char, opus_frames)
                    bg = frames[anim_frame_idx % len(frames)]
                    is_main_flag = cur_entry["is_main"]
                    elapsed = None
                    if not is_main_flag and cur_entry.get("started"):
                        elapsed = wall_now - cur_entry["started"]

                # Phase 5-A: find the current agent dict for icon bar
                cur_agent = None
                if not is_sleeping and not is_main_flag and current_agents:
                    # Match by display_idx position in agent list
                    if display_idx < len(current_agents):
                        cur_agent = current_agents[display_idx]

                # Phase 5-C: dirty-frame detection — skip push if visual state unchanged
                # Key: (anim_frame, scroll_x, display_char, color_tick, timer_min)
                timer_min = int(elapsed) // 60 if elapsed is not None else -1
                cur_char_name = display_list[display_idx]["char"] if (not is_sleeping and display_list) else "_sleep"
                push_key = (anim_frame_idx, text_x, cur_char_name, color_tick, timer_min, is_sleeping)
                if push_key == last_pushed_key:
                    pass  # skip redundant push
                else:
                    composed = compose_frame(
                        bg_frame=bg,
                        scroll_font=scroll_font,
                        ui_font=ui_font,
                        scroll_text=current_ticker,
                        scroll_x=text_x,
                        agents=current_agents,
                        main_active=current_main_active,
                        elapsed_sec=elapsed,
                        color_tick=color_tick,
                        is_main=is_main_flag,
                        scroll_text_h=scroll_text_h,
                        current_agent=cur_agent,
                    )
                    try:
                        pixoo.draw_image(composed)
                        pixoo.push()
                        last_pushed_key = push_key
                    except Exception as e:
                        print(f"[!] Pixoo send failed: {e}")
                        last_pushed_key = None  # force retry next frame
                        time.sleep(5)  # Back off before retry
                        try:
                            pixoo = Pixoo(PIXOO_IP)
                            print("[i] Pixoo reconnect attempted")
                        except Exception:
                            print("[!] Pixoo reconnect failed, will retry next frame")

            # Sleep until next event (frame or scroll)
            # Phase 5-C: cap at 50ms (was 20ms) — reduces busy-loop overhead
            next_event = min(next_frame_t, next_scroll_t)
            wait = max(0.001, next_event - time.monotonic())
            time.sleep(min(wait, 0.050))

    except KeyboardInterrupt:
        print("\n[i] Stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pixoo-64 lobster status display v6")
    parser.add_argument("--duration", type=float, default=None)
    args = parser.parse_args()
    run(duration_sec=args.duration)
