"""Unit tests for worker name scroll logic in pixoo-display-test.py.

Imports the display module via importlib (dashes in filename) with mocked
hardware dependencies so no Pixoo device or display is needed.
"""
import sys
import types
import importlib.util
from pathlib import Path


def _mock_external_deps() -> None:
    """Pre-populate sys.modules with stubs so the display script can be loaded."""
    if "pixoo" not in sys.modules:
        m = types.ModuleType("pixoo")

        class _Pixoo:
            def __init__(self, *a, **k):
                pass

        m.Pixoo = _Pixoo
        sys.modules["pixoo"] = m

    if "pilmoji" not in sys.modules:
        m = types.ModuleType("pilmoji")

        class _Pilmoji:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def text(self, *a, **k):
                pass

            def getsize(self, text, font):
                return (len(text) * 8, 12)

        m.Pilmoji = _Pilmoji
        sys.modules["pilmoji"] = m


_mock_external_deps()

_spec = importlib.util.spec_from_file_location(
    "pixoo_display",
    Path(__file__).parent.parent / "pixoo-display-test.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

advance_worker_scroll = _mod.advance_worker_scroll
WORKER_SCROLL_PAUSE_TICKS = _mod.WORKER_SCROLL_PAUSE_TICKS
DISPLAY_SIZE = _mod.DISPLAY_SIZE


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

MAX_W = DISPLAY_SIZE - 2  # 62 — same constant used in compose_frame / run


class TestAdvanceWorkerScrollNoScroll:
    """Names that fit within max_w should never move."""

    def test_short_name_offset_zero(self):
        assert advance_worker_scroll(0, 50, MAX_W) == 0

    def test_exact_fit_no_scroll(self):
        # wn_w == max_w → fits exactly, no scroll needed
        assert advance_worker_scroll(0, MAX_W, MAX_W) == 0

    def test_prior_offset_reset_to_zero_for_short_name(self):
        # Any leftover offset should be cleared when name fits
        assert advance_worker_scroll(20, 50, MAX_W) == 0


class TestAdvanceWorkerScrollLongName:
    """Names wider than max_w scroll by 1px per call and wrap correctly."""

    def test_advances_by_one(self):
        assert advance_worker_scroll(0, 100, MAX_W) == 1
        assert advance_worker_scroll(10, 100, MAX_W) == 11

    def test_does_not_wrap_before_pause_end(self):
        # stop_point = 100 - 62 = 38; pause ends at 38 + WORKER_SCROLL_PAUSE_TICKS
        stop = 100 - MAX_W  # 38
        pause_end = stop + WORKER_SCROLL_PAUSE_TICKS
        # One tick before the wrap threshold → still incrementing
        assert advance_worker_scroll(pause_end - 1, 100, MAX_W) == pause_end

    def test_wraps_to_negative_pause_after_tail_pause(self):
        # Exactly at pause_end → next call should wrap to -WORKER_SCROLL_PAUSE_TICKS
        stop = 100 - MAX_W
        pause_end = stop + WORKER_SCROLL_PAUSE_TICKS
        assert advance_worker_scroll(pause_end, 100, MAX_W) == -WORKER_SCROLL_PAUSE_TICKS

    def test_head_pause_counts_up_to_zero(self):
        # During head-pause phase (negative offset), offset advances toward 0
        assert advance_worker_scroll(-WORKER_SCROLL_PAUSE_TICKS, 100, MAX_W) == -WORKER_SCROLL_PAUSE_TICKS + 1
        assert advance_worker_scroll(-1, 100, MAX_W) == 0

    def test_full_cycle(self):
        """Simulate a full scroll cycle: 0 → stop_point → tail-pause → head-pause → 0."""
        wn_w = 80
        stop = wn_w - MAX_W  # 18
        offset = 0
        # Scroll phase: offset increases to stop_point
        for _ in range(stop):
            offset = advance_worker_scroll(offset, wn_w, MAX_W)
        assert offset == stop
        # Tail-pause phase: offset continues to stop + PAUSE_TICKS
        for _ in range(WORKER_SCROLL_PAUSE_TICKS):
            offset = advance_worker_scroll(offset, wn_w, MAX_W)
        assert offset == stop + WORKER_SCROLL_PAUSE_TICKS
        # Wraps to head-pause start
        offset = advance_worker_scroll(offset, wn_w, MAX_W)
        assert offset == -WORKER_SCROLL_PAUSE_TICKS
        # Head-pause phase: offset counts up to 0
        for _ in range(WORKER_SCROLL_PAUSE_TICKS):
            offset = advance_worker_scroll(offset, wn_w, MAX_W)
        assert offset == 0
        # Scroll starts again
        offset = advance_worker_scroll(offset, wn_w, MAX_W)
        assert offset == 1
