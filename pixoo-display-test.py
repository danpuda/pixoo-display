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
SCROLL_SPEED_MS = 100  # 10 FPS scroll (was 50ms=20FPS, Pilmoji redraw was burning CPU)
TEXT_STEP_PX = 1
CHARACTER_SWAP_SEC = 5.0
STATE_FILE = Path("/tmp/pixoo-agents.json")
STATE_POLL_SEC = 1.0
SLEEP_AFTER_SEC = 600  # 10 minutes idle
AGENT_TTL_SEC = 600    # auto-expire agents after 10 minutes (safety net)

SCROLL_FONT_SIZE = 10
UI_FONT_SIZE = 8

FALLBACK_TICKER = "ロブ稼働中！サブエージェント待機中..."
SLEEP_TICKER = "ロブ就寝中...zzZ"
TODO_FILE = Path("/mnt/c/Users/danpu/OneDrive/Desktop/obsidianVault/openclaw/memory/tasks/todo-priority.md")
TODO_POLL_SEC = 60  # re-read todo file every 60s

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

FONT_CANDIDATES = [
    "/home/yama/.fonts/meiryo.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


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
        live = [a for a in agents if now - a.get("last_seen", a.get("started", now)) < AGENT_TTL_SEC]
        if len(live) < len(agents):
            expired = len(agents) - len(live)
            print(f"[i] TTL expired {expired} agent(s)")
            data["agents"] = live
            try:
                STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            except OSError:
                pass
        return live, main_active
    except (json.JSONDecodeError, OSError):
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
    """Get the most recent subagent's task as scroll text."""
    if not agents:
        return None
    sorted_agents = sorted(agents, key=lambda a: a.get("started", 0), reverse=True)
    latest = sorted_agents[0]
    task = latest.get("task", "")
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
                task = line.lstrip("#").strip()
                return f"TOP: {task}"
            if in_priority and line.startswith("## ") and not line.startswith("## 🔥"):
                break  # next section
        return FALLBACK_TICKER
    except Exception:
        return FALLBACK_TICKER


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
    agent_count: int,
    elapsed_sec: float | None,
    color_tick: int,
    is_main: bool,
    scroll_text_h: int,
) -> Image.Image:
    # Shift lobster up by 4px
    img = Image.new("RGB", (DISPLAY_SIZE, DISPLAY_SIZE), (0, 0, 0))
    img.paste(bg_frame.crop((0, 4, DISPLAY_SIZE, DISPLAY_SIZE)), (0, 0))
    draw = ImageDraw.Draw(img)

    # --- Scroll text position ---
    marquee_y = DISPLAY_SIZE - scroll_text_h - 5  # adjusted: was -8 (too high), -5 balances visibility + descender safety

    # --- Timer: subagents only, rainbow color cycling ---
    # Pre-compute max timer height to prevent vertical jitter
    # (different digits have different bbox y_top: "1:23" → h=8, "0:00" → h=7)
    _TIMER_MAX_H = text_bbox_size(ui_font, "12:34")[1]  # worst-case height

    timer_str = None
    if not is_main and elapsed_sec is not None:
        minutes = int(elapsed_sec) // 60
        seconds = int(elapsed_sec) % 60
        timer_str = f"{minutes}:{seconds:02d}"
        tw, _ = text_bbox_size(ui_font, timer_str)
        timer_x = DISPLAY_SIZE - tw - 1
        timer_y = marquee_y - _TIMER_MAX_H - 3  # fixed height, no jitter
        timer_color = TIMER_COLORS[color_tick % len(TIMER_COLORS)]
        draw_outlined_text(draw, (timer_x, timer_y), timer_str, ui_font, fill=timer_color)

    # --- Scroll text: paste pre-rendered strip (fast!) ---
    strip = _scroll_cache.get_strip(scroll_text, scroll_font)
    # Crop the visible portion of the strip
    src_x = max(0, -scroll_x)
    dst_x = max(0, scroll_x)
    visible_w = min(DISPLAY_SIZE - dst_x, strip.width - src_x)
    if visible_w > 0 and src_x < strip.width:
        text_region = strip.crop((src_x, 0, src_x + visible_w, strip.height))
        img.paste(text_region, (dst_x, marquee_y - 2), text_region)

    # --- Top-right count ---
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
        draw_outlined_text(draw, (x0, y0), x_label, ui_font, fill=(140, 140, 140))
        draw_outlined_text(draw, (x0 + x_w + gap, y0), count_str, ui_font, fill=count_color)

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

    pixoo = Pixoo(PIXOO_IP)
    char_frame_cache: dict[str, List[Image.Image]] = {"opus": opus_frames}

    for name, paths in CHARACTER_FRAMES.items():
        if name not in char_frame_cache:
            loaded = load_frames(paths)
            if loaded:
                char_frame_cache[name] = loaded
                print(f"[i] Loaded: {name}")

    # Scroll text state
    default_ticker = get_top_priority_task()
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
    is_sleeping = False
    last_active_time = time.monotonic()

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
                    print(f"[i] Subagents: {new_count}")
                    agent_count = new_count

                # Re-read todo priority periodically
                if now - last_todo_check_t >= TODO_POLL_SEC:
                    default_ticker = get_top_priority_task()
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
                old_char = current_display_char
                old_is_main = display_idx == 0
                display_list = new_display_list

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
                    else:
                        display_idx = 0
                        current_display_char = display_list[0]["char"] if display_list else "opus"
                elif display_idx >= len(display_list):
                    display_idx = 0
                last_state_check_t = now

            if agent_count == 0:
                display_idx = 0
                current_display_char = "opus"

            if agent_count > 0 and now - last_char_swap_t >= CHARACTER_SWAP_SEC:
                display_idx = (display_idx + 1) % len(display_list)
                anim_frame_idx = 0
                last_char_swap_t = now
                cur = display_list[display_idx]
                current_display_char = cur["char"]
                label = "Rob" if cur["is_main"] else cur["char"]
                print(f"[i] -> {label}")

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

                composed = compose_frame(
                    bg_frame=bg,
                    scroll_font=scroll_font,
                    ui_font=ui_font,
                    scroll_text=current_ticker,
                    scroll_x=text_x,
                    agent_count=agent_count,
                    elapsed_sec=elapsed,
                    color_tick=color_tick,
                    is_main=is_main_flag,
                    scroll_text_h=scroll_text_h,
                )
                pixoo.draw_image(composed)
                pixoo.push()

            # Sleep until next event (frame or scroll), capped at 20ms
            next_event = min(next_frame_t, next_scroll_t)
            wait = max(0.001, next_event - time.monotonic())
            time.sleep(min(wait, 0.020))

    except KeyboardInterrupt:
        print("\n[i] Stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pixoo-64 lobster status display v6")
    parser.add_argument("--duration", type=float, default=None)
    args = parser.parse_args()
    run(duration_sec=args.duration)
