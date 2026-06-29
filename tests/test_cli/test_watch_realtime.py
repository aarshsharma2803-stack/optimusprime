"""Tests for op watch real-time EventWatcher and event state."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from optimusprime.cli.commands.watch import (
    EventState,
    EventWatcher,
    _read_live_events,
    _update_event_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def op_dir(tmp_path: Path) -> Path:
    op = tmp_path / ".optimusprime"
    op.mkdir()
    return op


def _write_events(op_dir: Path, events: list) -> None:
    lines = [json.dumps(ev) for ev in events]
    (op_dir / "events.jsonl").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# EventWatcher tests
# ---------------------------------------------------------------------------

def test_event_watcher_is_daemon_thread(op_dir: Path):
    state = EventState()
    cb_called = []
    watcher = EventWatcher(op_dir / "events.jsonl", lambda: cb_called.append(1))
    assert watcher.daemon is True


def test_event_watcher_detects_mtime_change(op_dir: Path, tmp_path: Path):
    events_path = op_dir / "events.jsonl"
    cb_called = threading.Event()
    watcher = EventWatcher(events_path, lambda: cb_called.set())
    watcher.start()

    time.sleep(0.1)
    events_path.write_text(json.dumps({"ts": "2026-06-29T00:00:00Z", "event": "PreToolUse", "tool": "Write", "file": "", "action": "passed"}) + "\n")

    triggered = cb_called.wait(timeout=2.0)
    assert triggered, "EventWatcher did not detect file change within 2s"


def test_event_watcher_triggers_callback(op_dir: Path):
    events_path = op_dir / "events.jsonl"
    call_count = [0]
    lock = threading.Lock()

    def cb():
        with lock:
            call_count[0] += 1

    watcher = EventWatcher(events_path, cb)
    watcher.start()
    time.sleep(0.05)

    events_path.write_text('{"ts":"2026-06-29T00:00:00Z","event":"Stop","tool":"","file":"","action":"session-end"}\n')
    time.sleep(0.8)

    with lock:
        assert call_count[0] >= 1


# ---------------------------------------------------------------------------
# _read_live_events tests
# ---------------------------------------------------------------------------

def test_read_live_events_returns_list(op_dir: Path):
    _write_events(op_dir, [
        {"ts": "T1", "event": "PreToolUse", "tool": "Write", "file": "a.py", "action": "passed"},
        {"ts": "T2", "event": "PostToolUse", "tool": "Write", "file": "a.py", "action": "failed"},
    ])
    events = _read_live_events(op_dir)
    assert len(events) == 2
    assert events[0]["event"] == "PreToolUse"


def test_read_live_events_empty_when_no_file(op_dir: Path):
    events = _read_live_events(op_dir)
    assert events == []


# ---------------------------------------------------------------------------
# EventState + thinking detection
# ---------------------------------------------------------------------------

def test_thinking_state_after_prompt(op_dir: Path):
    state = EventState()
    events = [
        {"ts": "T1", "event": "UserPromptSubmit", "tool": "", "file": "", "action": "pre-response"},
    ]
    state.update(events)
    # Inject a past prompt time to simulate 3 seconds ago
    state.last_prompt_time = time.monotonic() - 3.0
    state.update(events)  # re-update with stale time
    snap = state.snapshot()
    # thinking is set when > 2s since UserPromptSubmit with no PostToolUse
    assert snap["thinking"] is True


def test_thinking_clears_after_tool_use(op_dir: Path):
    state = EventState()
    # First: UserPromptSubmit (thinking)
    state.update([
        {"ts": "T1", "event": "UserPromptSubmit", "tool": "", "file": "", "action": "pre-response"},
    ])
    state.last_prompt_time = time.monotonic() - 3.0

    # Then: PostToolUse arrives → clears thinking
    state.update([
        {"ts": "T1", "event": "UserPromptSubmit", "tool": "", "file": "", "action": "pre-response"},
        {"ts": "T2", "event": "PostToolUse", "tool": "Write", "file": "a.py", "action": "passed"},
    ])
    snap = state.snapshot()
    assert snap["thinking"] is False
