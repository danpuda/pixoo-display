"""Tests for pixoo_tmux_sync.py — Phase 4 edge case coverage.

Covers: classify_window, determine_status (including flicker fix),
build_agents, sanitize_output, extract_scroll_text, and tmux
window add/remove/restart scenarios.
"""

import time

import pytest

# Import module-under-test
import pixoo_tmux_sync as sync


# ── classify_window ─────────────────────────────────────────────

class TestClassifyWindow:
    """Window name → role mapping (design doc section 3)."""

    def test_monitor_is_dir(self):
        role, idle = sync.classify_window("monitor")
        assert role == "DIR"
        assert not idle

    def test_lead_is_pl(self):
        role, idle = sync.classify_window("ebay-ph4-lead")
        assert role == "PL"
        assert not idle

    def test_review_is_qa(self):
        role, idle = sync.classify_window("codex-review")
        assert role == "QA"
        assert not idle

    def test_qa_suffix_is_qa(self):
        role, idle = sync.classify_window("test-qa")
        assert role == "QA"
        assert not idle

    def test_fl3_suffix_is_qa(self):
        role, idle = sync.classify_window("codex-fl3-check")
        assert role == "QA"
        assert not idle

    def test_sec_is_sec(self):
        role, idle = sync.classify_window("audit-sec")
        assert role == "SEC"
        assert not idle

    def test_impl_is_dev(self):
        role, idle = sync.classify_window("ebay-ph4-impl")
        assert role == "DEV"
        assert not idle

    def test_dev_suffix_is_dev(self):
        role, idle = sync.classify_window("feature-dev")
        assert role == "DEV"
        assert not idle

    def test_research_is_res(self):
        role, idle = sync.classify_window("api-research")
        assert role == "RES"
        assert not idle

    def test_worker_n_is_idle(self):
        role, idle = sync.classify_window("worker-3")
        assert idle
        assert role == "---"

    def test_worker_large_number(self):
        role, idle = sync.classify_window("worker-42")
        assert idle

    def test_unknown_name_defaults_to_dev(self):
        role, idle = sync.classify_window("some-random-name")
        assert role == "DEV"
        assert not idle

    def test_case_insensitive_monitor(self):
        """monitor should match case-insensitively."""
        role, _ = sync.classify_window("Monitor")
        assert role == "DIR"

    def test_priority_order_lead_over_impl(self):
        """'-lead' should take priority over '-impl' if both present."""
        role, _ = sync.classify_window("impl-lead")
        assert role == "PL"


# ── sanitize_output ─────────────────────────────────────────────

class TestSanitizeOutput:
    """ANSI escape removal and control character cleanup."""

    def test_removes_ansi_color(self):
        raw = "\x1b[32mGreen text\x1b[0m"
        assert sync.sanitize_output(raw) == "Green text"

    def test_removes_osc_sequences(self):
        raw = "\x1b]0;title\x07normal text"
        assert sync.sanitize_output(raw) == "normal text"

    def test_preserves_newlines_and_tabs(self):
        raw = "line1\nline2\tindented"
        assert sync.sanitize_output(raw) == "line1\nline2\tindented"

    def test_removes_control_chars(self):
        raw = "hello\x01\x02\x03world"
        assert sync.sanitize_output(raw) == "helloworld"

    def test_empty_string(self):
        assert sync.sanitize_output("") == ""

    def test_complex_ansi(self):
        raw = "\x1b[1;31;40mBold red on black\x1b[0m normal"
        result = sync.sanitize_output(raw)
        assert "Bold red on black" in result
        assert "\x1b" not in result


# ── extract_scroll_text ─────────────────────────────────────────

class TestExtractScrollText:
    """Extract last meaningful line for scroll display."""

    def test_returns_last_non_empty_line(self):
        captured = "line1\nline2\nlast line\n\n"
        assert sync.extract_scroll_text(captured) == "last line"

    def test_returns_empty_for_none(self):
        assert sync.extract_scroll_text(None) == ""

    def test_returns_empty_for_blank(self):
        assert sync.extract_scroll_text("   \n  \n") == ""

    def test_truncates_long_lines(self):
        long_line = "x" * 200
        result = sync.extract_scroll_text(long_line)
        assert len(result) <= 80
        assert result.endswith("...")

    def test_single_line(self):
        assert sync.extract_scroll_text("hello") == "hello"


# ── determine_status (flicker fix) ─────────────────────────────

class TestDetermineStatus:
    """Status determination with output diff tracking."""

    def test_none_captured_is_waiting(self):
        outputs, times = {}, {}
        assert sync.determine_status(None, "w0", outputs, times, 100.0) == "waiting"

    def test_first_observation_is_active(self):
        outputs, times = {}, {}
        assert sync.determine_status("hello", "w0", outputs, times, 100.0) == "active"
        assert outputs["w0"] == "hello"

    def test_same_output_stays_active_within_threshold(self):
        outputs = {"w0": "hello"}
        times = {"w0": 100.0}
        assert sync.determine_status("hello", "w0", outputs, times, 110.0) == "active"

    def test_same_output_becomes_waiting_after_threshold(self):
        outputs = {"w0": "hello"}
        times = {"w0": 100.0}
        after_threshold = 100.0 + sync.WAITING_THRESHOLD_SEC + 1
        assert sync.determine_status("hello", "w0", outputs, times, after_threshold) == "waiting"

    def test_same_output_becomes_waiting_at_exact_threshold(self):
        """Boundary: exactly at WAITING_THRESHOLD_SEC should be waiting (>= not >)."""
        outputs = {"w0": "hello"}
        times = {"w0": 100.0}
        exactly_threshold = 100.0 + sync.WAITING_THRESHOLD_SEC
        assert sync.determine_status("hello", "w0", outputs, times, exactly_threshold) == "waiting"

    def test_output_change_resets_to_active(self):
        outputs = {"w0": "hello"}
        times = {"w0": 50.0}
        assert sync.determine_status("world", "w0", outputs, times, 200.0) == "active"
        assert outputs["w0"] == "world"
        assert times["w0"] == 200.0

    def test_error_detected_in_output(self):
        outputs, times = {}, {}
        assert sync.determine_status("some error here", "w0", outputs, times, 100.0) == "error"

    def test_error_pattern_failed(self):
        outputs, times = {}, {}
        assert sync.determine_status("test FAILED badly", "w0", outputs, times, 100.0) == "error"

    def test_error_pattern_traceback(self):
        outputs, times = {}, {}
        assert sync.determine_status("Traceback (most recent call last):", "w0", outputs, times, 100.0) == "error"

    def test_flicker_fix_error_does_not_refresh_change_time_on_static(self):
        """Key flicker fix: static error output should NOT keep refreshing
        last_change_times, so that after error clears, staleness is accurate."""
        outputs = {}
        times = {}

        # First observation: error output
        sync.determine_status("error detected", "w0", outputs, times, 100.0)
        assert times["w0"] == 100.0

        # Same error output 3 seconds later — should NOT update last_change_times
        sync.determine_status("error detected", "w0", outputs, times, 103.0)
        assert times["w0"] == 100.0  # unchanged because output didn't change

    def test_flicker_fix_error_to_clean_transition(self):
        """After error clears, status should be based on actual output change time."""
        outputs = {}
        times = {}

        # t=0: error output
        sync.determine_status("error found", "w0", outputs, times, 0.0)
        assert outputs["w0"] == "error found"

        # t=3: same error, no diff → times stays at 0.0
        result = sync.determine_status("error found", "w0", outputs, times, 3.0)
        assert result == "error"
        assert times["w0"] == 0.0

        # t=6: error clears, new output
        result = sync.determine_status("all clear", "w0", outputs, times, 6.0)
        assert result == "active"
        assert outputs["w0"] == "all clear"
        assert times["w0"] == 6.0

        # t=40: output still "all clear" → should be waiting (6+30 < 40)
        result = sync.determine_status("all clear", "w0", outputs, times, 40.0)
        assert result == "waiting"

    def test_flicker_fix_no_stale_active_after_error(self):
        """Regression: old code kept refreshing last_change_times during error,
        so after error cleared, the window stayed 'active' for 30s.
        With the fix, staleness is tracked correctly."""
        outputs = {}
        times = {}

        # Error persists for 60 seconds (20 polls at 3s)
        for t in range(0, 60, 3):
            sync.determine_status("persistent error message", "w0", outputs, times, float(t))

        # last_change_times should be 0.0 (first observation), not 57.0
        assert times["w0"] == 0.0

        # Error clears at t=60
        sync.determine_status("ok now", "w0", outputs, times, 60.0)
        assert times["w0"] == 60.0

        # At t=95 (35s after clear), should be waiting
        result = sync.determine_status("ok now", "w0", outputs, times, 95.0)
        assert result == "waiting"


# ── build_agents ────────────────────────────────────────────────

class TestBuildAgents:
    """tmux windows → agent list conversion."""

    def test_empty_windows(self):
        agents, main_active = sync.build_agents([], {}, {})
        assert agents == []
        assert not main_active

    def test_monitor_sets_main_active(self):
        windows = [{"window_index": 0, "window_name": "monitor", "pane_pid": 100}]
        agents, main_active = sync.build_agents(windows, {}, {})
        assert main_active
        assert len(agents) == 0  # DIR is not in agents list

    def test_single_dev(self):
        windows = [{"window_index": 1, "window_name": "feature-impl", "pane_pid": 200}]
        first_seen = {}
        agents, main_active = sync.build_agents(windows, {}, first_seen)
        assert not main_active
        assert len(agents) == 1
        assert agents[0]["role"] == "DEV"
        assert agents[0]["id"] == "1"        # window_index-based id
        assert agents[0]["task"] == "feature-impl"  # task keeps window_name
        assert agents[0]["char"] == "codex"

    def test_pl_selection_lowest_index(self):
        """When multiple -lead windows, lowest index wins."""
        windows = [
            {"window_index": 3, "window_name": "b-lead", "pane_pid": 300},
            {"window_index": 1, "window_name": "a-lead", "pane_pid": 100},
        ]
        agents, _ = sync.build_agents(windows, {}, {})
        pl_agents = [a for a in agents if a["role"] == "PL"]
        dev_agents = [a for a in agents if a["role"] == "DEV"]
        assert len(pl_agents) == 1
        assert pl_agents[0]["id"] == "1"   # a-lead has window_index=1
        assert len(dev_agents) == 1  # other lead demoted to DEV

    def test_pl_selection_config_override(self):
        """Config file can force a specific PL window."""
        windows = [
            {"window_index": 1, "window_name": "a-lead", "pane_pid": 100},
            {"window_index": 3, "window_name": "b-lead", "pane_pid": 300},
        ]
        config = {"pl_window": "b-lead"}
        agents, _ = sync.build_agents(windows, config, {})
        pl_agents = [a for a in agents if a["role"] == "PL"]
        assert len(pl_agents) == 1
        assert pl_agents[0]["id"] == "3"   # b-lead has window_index=3

    def test_idle_workers_excluded(self):
        windows = [
            {"window_index": 0, "window_name": "worker-1", "pane_pid": 100},
            {"window_index": 1, "window_name": "feature-impl", "pane_pid": 200},
        ]
        agents, _ = sync.build_agents(windows, {}, {})
        assert len(agents) == 1
        assert agents[0]["role"] == "DEV"

    def test_compatible_keys_present(self):
        """All agents must have the compatibility-required keys."""
        windows = [{"window_index": 1, "window_name": "test-impl", "pane_pid": 200}]
        agents, _ = sync.build_agents(windows, {}, {})
        required_keys = {"id", "char", "task", "started", "last_seen", "role", "status", "scroll_text"}
        assert required_keys.issubset(set(agents[0].keys()))

    def test_first_seen_tracking(self):
        """first_seen dict should track window creation time (keyed by window_index)."""
        first_seen = {}
        windows = [{"window_index": 1, "window_name": "test-impl", "pane_pid": 200}]
        sync.build_agents(windows, {}, first_seen)
        assert "1" in first_seen  # keyed by str(window_index)

    def test_first_seen_pruning(self):
        """Removed windows should be pruned from first_seen."""
        first_seen = {"old-window": 100.0}
        windows = [{"window_index": 1, "window_name": "new-impl", "pane_pid": 200}]
        sync.build_agents(windows, {}, first_seen)
        assert "old-window" not in first_seen

    def test_mixed_team(self):
        """Full team scenario: DIR + PL + DEV + QA."""
        windows = [
            {"window_index": 0, "window_name": "monitor", "pane_pid": 100},
            {"window_index": 1, "window_name": "ebay-lead", "pane_pid": 200},
            {"window_index": 2, "window_name": "codex-review", "pane_pid": 300},
            {"window_index": 3, "window_name": "ebay-impl", "pane_pid": 400},
            {"window_index": 4, "window_name": "worker-5", "pane_pid": 500},
        ]
        agents, main_active = sync.build_agents(windows, {}, {})
        assert main_active
        roles = {a["role"] for a in agents}
        assert roles == {"PL", "QA", "DEV"}
        assert len(agents) == 3  # DIR not in list, worker-5 idle

    def test_same_name_windows_get_unique_ids(self):
        """Two windows with identical names must produce unique ids (window_index-based)."""
        windows = [
            {"window_index": 2, "window_name": "codex-impl", "pane_pid": 200},
            {"window_index": 5, "window_name": "codex-impl", "pane_pid": 500},
        ]
        agents, _ = sync.build_agents(windows, {}, {})
        assert len(agents) == 2
        ids = [a["id"] for a in agents]
        assert len(set(ids)) == 2, "same-name windows must not share an id"
        assert "2" in ids
        assert "5" in ids
        # task (display name) is still the window_name
        assert all(a["task"] == "codex-impl" for a in agents)


# ── Window add/remove simulation ───────────────────────────────

class TestWindowDynamics:
    """Simulate tmux window add/remove (edge cases)."""

    def test_window_added(self):
        """Adding a new window should appear in next build."""
        first_seen = {}
        windows_v1 = [{"window_index": 1, "window_name": "task-impl", "pane_pid": 100}]
        agents1, _ = sync.build_agents(windows_v1, {}, first_seen)
        assert len(agents1) == 1

        windows_v2 = windows_v1 + [{"window_index": 2, "window_name": "codex-review", "pane_pid": 200}]
        agents2, _ = sync.build_agents(windows_v2, {}, first_seen)
        assert len(agents2) == 2

    def test_window_removed(self):
        """Removing a window should drop it from agents and prune first_seen."""
        first_seen = {}
        windows = [
            {"window_index": 1, "window_name": "a-impl", "pane_pid": 100},
            {"window_index": 2, "window_name": "b-impl", "pane_pid": 200},
        ]
        sync.build_agents(windows, {}, first_seen)
        assert "1" in first_seen   # keyed by str(window_index)
        assert "2" in first_seen

        # Remove window 1
        windows_after = [{"window_index": 2, "window_name": "b-impl", "pane_pid": 200}]
        agents, _ = sync.build_agents(windows_after, {}, first_seen)
        assert len(agents) == 1
        assert "1" not in first_seen  # pruned

    def test_tmux_restart_empty(self):
        """Simulating tmux restart: empty window list → no agents."""
        first_seen = {"old": 100.0}
        agents, main_active = sync.build_agents([], {}, first_seen)
        assert agents == []
        assert not main_active


# ── capture-pane alt-screen ─────────────────────────────────────

class TestAltScreen:
    """Alt-screen (vim/less) returns None from capture_pane → waiting."""

    def test_alt_screen_returns_waiting(self):
        outputs, times = {}, {}
        result = sync.determine_status(None, "w0", outputs, times, 100.0)
        assert result == "waiting"
        # Should not update tracking dicts
        assert "w0" not in outputs
        assert "w0" not in times
