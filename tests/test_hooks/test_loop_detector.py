"""Tests for hooks/pre/loop-detector.py — at least 7 scenarios."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import make_pretooluse, run_hook

_HOOK = Path(__file__).resolve().parent.parent.parent / "hooks" / "pre" / "loop-detector.py"


def _run(stdin_data, cwd):
    return run_hook(_HOOK, stdin_data, cwd)


def _write_loop_state(op_dir: Path, failures: list, session_id: str = "test-session") -> None:
    data = {"session_id": session_id, "consecutive_failures": failures}
    (op_dir / "loop-state.json").write_text(json.dumps(data), encoding="utf-8")


def _failure(tool="Edit", target="src/foo.py", error="SyntaxError line 42"):
    return {"tool": tool, "target": target, "error": error, "sig": "abc123", "timestamp": "2026-06-27T10:00:00Z"}


# ── 1. Missing loop-state.json → exit 0 ───────────────────────────────────

def test_missing_loop_state_exits_zero(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    loop_state = op_dir / "loop-state.json"
    loop_state.unlink(missing_ok=True)

    stdout, _, rc = _run(
        make_pretooluse("Edit", {"file_path": "src/foo.py"}),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 0
    assert stdout.strip() == ""


# ── 2. Only 4 failures → not blocked (under threshold of 5) ───────────────

def test_four_failures_not_blocked(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    _write_loop_state(op_dir, [_failure()] * 4)

    stdout, _, rc = _run(
        make_pretooluse("Edit", {"file_path": "src/foo.py"}, session_id="test-session"),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 0


# ── 3. Five identical failures → exit 2 ───────────────────────────────────

def test_five_identical_failures_blocked(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    _write_loop_state(op_dir, [_failure()] * 5)

    stdout, _, rc = _run(
        make_pretooluse("Edit", {"file_path": "src/foo.py"}, session_id="test-session"),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 2
    decision = json.loads(stdout.strip())
    assert decision["decision"] == "block"
    assert "Loop detected" in decision["reason"]


# ── 4. Different tool after 2 → not blocked ───────────────────────────────

def test_different_tool_not_blocked(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    _write_loop_state(op_dir, [
        _failure(tool="Edit"),
        _failure(tool="Edit"),
        _failure(tool="Bash"),  # different tool breaks the streak
    ])

    stdout, _, rc = _run(
        make_pretooluse("Edit", {"file_path": "src/foo.py"}, session_id="test-session"),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 0


# ── 5. 80% similar error treated as same (near-duplicate) ─────────────────

def test_similar_errors_trigger_block(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    # These errors are > 90% similar with ≤1 new word each
    _write_loop_state(op_dir, [
        _failure(error="SyntaxError: invalid syntax on line 42"),
        _failure(error="SyntaxError: invalid syntax on line 43"),
        _failure(error="SyntaxError: invalid syntax on line 44"),
        _failure(error="SyntaxError: invalid syntax on line 45"),
        _failure(error="SyntaxError: invalid syntax on line 46"),
    ])

    stdout, _, rc = _run(
        make_pretooluse("Edit", {"file_path": "src/foo.py"}, session_id="test-session"),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 2


# ── 6. Different session_id → loop state ignored ──────────────────────────

def test_different_session_id_ignored(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    # State was written by a different session
    _write_loop_state(op_dir, [_failure()] * 5, session_id="other-session")

    stdout, _, rc = _run(
        # Our session_id differs
        make_pretooluse("Edit", {"file_path": "src/foo.py"}, session_id="our-session"),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 0


# ── 7. Empty failures list → exit 0 ───────────────────────────────────────

def test_empty_failures_exits_zero(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    _write_loop_state(op_dir, [])

    stdout, _, rc = _run(
        make_pretooluse("Edit", {"file_path": "src/foo.py"}),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 0


# ── 8. Different target file → not a loop ────────────────────────────────

def test_different_target_not_blocked(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    _write_loop_state(op_dir, [_failure(target="src/foo.py")] * 5)

    # Editing a different file — should not be blocked
    stdout, _, rc = _run(
        make_pretooluse("Edit", {"file_path": "src/bar.py"}, session_id="test-session"),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 0
