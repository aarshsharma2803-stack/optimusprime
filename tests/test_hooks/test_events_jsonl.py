"""Tests for events.jsonl append_event() and hook integration."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_REPO_SRC = _REPO_ROOT / "src"
_SCOPE_GUARD = _REPO_ROOT / "hooks" / "pre" / "scope-guard.py"
_COMPRESSOR = _REPO_ROOT / "hooks" / "post" / "output-compressor.py"
_ATTEMPT_LOGGER = _REPO_ROOT / "hooks" / "post" / "attempt-logger.py"
_PRE_RESPONSE = _REPO_ROOT / "hooks" / "pre" / "pre-response.py"

if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from optimusprime.utils import append_event


# ---------------------------------------------------------------------------
# Unit tests for append_event()
# ---------------------------------------------------------------------------

def test_append_event_creates_file(tmp_path: Path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    result = append_event(op, "PreToolUse", tool="Write", file="src/foo.py", action="passed")
    assert result is True
    assert (op / "events.jsonl").is_file()


def test_append_event_valid_json_line(tmp_path: Path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    append_event(op, "PostToolUse", tool="Bash", file="", action="failed")
    lines = [l for l in (op / "events.jsonl").read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "PostToolUse"
    assert entry["action"] == "failed"
    assert "ts" in entry


def test_events_trimmed_to_100(tmp_path: Path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    for i in range(110):
        append_event(op, "PreToolUse", tool="Write", file=f"file{i}.py", action="passed")
    lines = [l for l in (op / "events.jsonl").read_text().splitlines() if l.strip()]
    assert len(lines) == 100


def test_missing_op_dir_no_crash(tmp_path: Path):
    """append_event() with non-existent directory returns False, never crashes."""
    result = append_event(tmp_path / ".nonexistent", "PreToolUse")
    assert result is False


# ---------------------------------------------------------------------------
# Integration: scope-guard writes event on block
# ---------------------------------------------------------------------------

def test_scope_guard_writes_event_on_block(tmp_path: Path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    (op / "contract.json").write_text(json.dumps({
        "out_of_scope": ["secrets/"],
        "agent_id": "main",
    }))
    payload = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": "secrets/key.txt", "content": "x"},
    })
    result = subprocess.run(
        [sys.executable, str(_SCOPE_GUARD)],
        input=payload, capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 2
    events_file = op / "events.jsonl"
    assert events_file.is_file()
    lines = [l for l in events_file.read_text().splitlines() if l.strip()]
    event = json.loads(lines[-1])
    assert event["action"] == "blocked"
    assert event["event"] == "PreToolUse"


# ---------------------------------------------------------------------------
# Integration: scope-guard writes event on pass
# ---------------------------------------------------------------------------

def test_scope_guard_writes_event_on_pass(tmp_path: Path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    (op / "contract.json").write_text(json.dumps({
        "out_of_scope": ["secrets/"],
        "agent_id": "main",
    }))
    payload = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": "src/test.py", "content": "x"},
    })
    result = subprocess.run(
        [sys.executable, str(_SCOPE_GUARD)],
        input=payload, capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0
    events_file = op / "events.jsonl"
    assert events_file.is_file()
    lines = [l for l in events_file.read_text().splitlines() if l.strip()]
    event = json.loads(lines[-1])
    assert event["action"] == "passed"


# ---------------------------------------------------------------------------
# Integration: attempt-logger writes event on failure
# ---------------------------------------------------------------------------

def test_attempt_logger_writes_event_on_failure(tmp_path: Path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    payload = json.dumps({
        "hook_event_name": "PostToolUse",
        "session_id": "test-s1",
        "tool_name": "Bash",
        "tool_input": {"command": "cat missing.txt"},
        "tool_response": {"is_error": True, "output": "Error: No such file"},
    })
    result = subprocess.run(
        [sys.executable, str(_ATTEMPT_LOGGER)],
        input=payload, capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert result.returncode == 0
    events_file = op / "events.jsonl"
    assert events_file.is_file()
    lines = [l for l in events_file.read_text().splitlines() if l.strip()]
    event = json.loads(lines[-1])
    assert event["action"] == "failed"
    assert event["event"] == "PostToolUse"


# ---------------------------------------------------------------------------
# Integration: pre-response writes event on UserPromptSubmit
# ---------------------------------------------------------------------------

def test_pre_response_writes_event_on_prompt(tmp_path: Path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    payload = json.dumps({"session_id": "s1", "prompt": "fix the login bug"})
    subprocess.run(
        [sys.executable, str(_PRE_RESPONSE)],
        input=payload, capture_output=True, text=True, cwd=str(tmp_path),
    )
    events_file = op / "events.jsonl"
    assert events_file.is_file()
    lines = [l for l in events_file.read_text().splitlines() if l.strip()]
    assert len(lines) >= 1
    event = json.loads(lines[-1])
    assert event["event"] == "UserPromptSubmit"
