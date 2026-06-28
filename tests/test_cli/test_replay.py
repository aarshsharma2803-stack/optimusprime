"""Tests for cli/commands/replay.py — op replay command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from optimusprime.cli.commands.replay import (
    _filter_by_date,
    _extract_ts,
    _parse_decision_line,
    _parse_attempt_line,
    _load_events_for_date,
    _get_available_sessions,
    _resolve_session_date,
    DECISION, FAILURE, BLOCKED, LOOP,
)
from optimusprime.cli.op import cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def op_dir(tmp_path: Path) -> Path:
    op = tmp_path / ".optimusprime"
    op.mkdir()
    return op


@pytest.fixture
def session_op_dir(tmp_path: Path) -> Path:
    op = tmp_path / ".optimusprime"
    op.mkdir()

    (op / "decisions.md").write_text(
        "[2026-06-27T10:00:00Z] [agent:main] DECIDED: use jwt | REJECTED: session-cookies | REASON: stateless\n"
        "[2026-06-27T11:00:00Z] [agent:main] DECIDED: store in httponly | REJECTED: localstorage | REASON: xss\n"
        "[2026-06-28T09:00:00Z] [agent:main] DECIDED: add rate limiting | REJECTED: none | REASON: security\n"
    )
    (op / "attempts.md").write_text(
        "[2026-06-27T10:30:00Z] [agent:main] FAIL TOOL: Bash | TARGET: pytest | ERROR: ImportError\n"
        "[2026-06-28T09:30:00Z] [agent:main] FAIL TOOL: Write | TARGET: src/auth.py | ERROR: permission denied\n"
    )
    (op / "scope-guard-log.json").write_text(json.dumps([
        {"file_path": ".env", "timestamp": "2026-06-27T10:45:00Z", "tool_name": "Write"},
    ]))
    (op / "loop-state.json").write_text(json.dumps({
        "session_id": "sess-1",
        "consecutive_failures": 0,
    }))
    (op / "resume.json").write_text(json.dumps({
        "session_id": "sess-20260628",
        "goal": "build jwt auth",
        "captured_at": "2026-06-28T12:00:00Z",
        "decision_count": 3,
        "attempt_count": 2,
        "open_todos": [],
        "next_action": "continue",
    }))
    (op / "session-snapshot.md").write_text(
        "# OPTIMUSPRIME SESSION SNAPSHOT\n"
        "Generated: 2026-06-28T12:00:00Z | Session: sess-20260628 | Agent: main\n\n"
        "## Goal\nbuild jwt auth\n\n"
        "## Changed (2 files)\n~ src/auth.py\n\n"
        "## Decisions (3 total)\n- use jwt\n\n"
        "## Failed Attempts (2 total)\n(none)\n\n"
        "## Open TODOs (0)\n(none)\n\n"
        "## Next Action\ncontinue\n"
    )
    return op


# ---------------------------------------------------------------------------
# 1. Date filtering
# ---------------------------------------------------------------------------

def test_filter_by_date_keeps_matching(session_op_dir):
    lines = [
        "[2026-06-27T10:00:00Z] decision A",
        "[2026-06-28T09:00:00Z] decision B",
    ]
    result = _filter_by_date(lines, "2026-06-27")
    assert len(result) == 1
    assert "decision A" in result[0]


def test_filter_by_date_empty_prefix_returns_all(session_op_dir):
    lines = ["[2026-06-27T10:00:00Z] A", "[2026-06-28T09:00:00Z] B"]
    result = _filter_by_date(lines, "")
    assert len(result) == 2


# ---------------------------------------------------------------------------
# 2. Event parsing
# ---------------------------------------------------------------------------

def test_parse_decision_line_extracts_decided():
    line = "[2026-06-27T10:00:00Z] [agent:main] DECIDED: use jwt | REJECTED: session | REASON: stateless"
    d = _parse_decision_line(line)
    assert "jwt" in d["decided"]
    assert d["ts"] == "2026-06-27T10:00:00Z"


def test_parse_decision_line_extracts_rejected():
    line = "[2026-06-27T10:00:00Z] [agent:main] DECIDED: jwt | REJECTED: session-cookies | REASON: x"
    d = _parse_decision_line(line)
    assert "session" in d["rejected"]


def test_parse_attempt_line_extracts_tool():
    line = "[2026-06-27T10:30:00Z] [agent:main] FAIL TOOL: Bash | TARGET: pytest | ERROR: ImportError"
    a = _parse_attempt_line(line)
    assert a["tool"] == "Bash"


def test_parse_attempt_line_extracts_error():
    line = "[2026-06-27T10:30:00Z] [agent:main] FAIL TOOL: Write | TARGET: x.py | ERROR: permission denied"
    a = _parse_attempt_line(line)
    assert "permission" in a["error"] or "denied" in a["error"]


# ---------------------------------------------------------------------------
# 3. Event loading
# ---------------------------------------------------------------------------

def test_load_events_filters_by_date(session_op_dir):
    events = _load_events_for_date(session_op_dir, "2026-06-27")
    dates = [e["ts"][:10] for e in events]
    assert all(d == "2026-06-27" for d in dates)


def test_load_events_includes_decisions(session_op_dir):
    events = _load_events_for_date(session_op_dir, "2026-06-27")
    assert any(e["type"] == DECISION for e in events)


def test_load_events_includes_failures(session_op_dir):
    events = _load_events_for_date(session_op_dir, "2026-06-27")
    assert any(e["type"] == FAILURE for e in events)


def test_load_events_includes_blocks(session_op_dir):
    events = _load_events_for_date(session_op_dir, "2026-06-27")
    assert any(e["type"] == BLOCKED for e in events)


def test_load_events_sorted_by_timestamp(session_op_dir):
    events = _load_events_for_date(session_op_dir, "")
    timestamps = [e["ts"] for e in events]
    assert timestamps == sorted(timestamps)


def test_load_events_empty_when_no_data(op_dir):
    events = _load_events_for_date(op_dir, "2026-01-01")
    assert events == []


def test_missing_attempts_skips_gracefully(op_dir):
    (op_dir / "decisions.md").write_text(
        "[2026-06-27T10:00:00Z] [agent:main] DECIDED: use jwt | REJECTED: none | REASON: best\n"
    )
    events = _load_events_for_date(op_dir, "2026-06-27")
    assert any(e["type"] == DECISION for e in events)


def test_missing_scope_guard_log_skips_gracefully(op_dir):
    (op_dir / "decisions.md").write_text(
        "[2026-06-27T10:00:00Z] [agent:main] DECIDED: use jwt | REJECTED: none | REASON: ok\n"
    )
    # No scope-guard-log.json
    events = _load_events_for_date(op_dir, "2026-06-27")
    assert len(events) >= 1


# ---------------------------------------------------------------------------
# 4. CLI commands
# ---------------------------------------------------------------------------

def test_replay_list_shows_sessions(session_op_dir):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(session_op_dir), "replay", "--list"])
    assert result.exit_code == 0
    assert "2026-06-28" in result.output or "2026-06-27" in result.output


def test_replay_summary_works(session_op_dir):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(session_op_dir), "replay", "--summary"])
    assert result.exit_code == 0
    assert "Decisions" in result.output or "2026" in result.output


def test_replay_default_uses_most_recent(session_op_dir):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(session_op_dir), "replay", "--summary"])
    assert result.exit_code == 0
    # Most recent session is 2026-06-28
    assert "2026-06-28" in result.output


def test_replay_unknown_session_gives_helpful_message(session_op_dir):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(session_op_dir), "replay", "--session", "2020-01-01"])
    assert result.exit_code == 0
    # Either no events message or graceful handling
    assert result.output.strip() != ""


def test_replay_no_op_dir_gives_helpful_message(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["replay"])
    assert result.exit_code != 0 or "optimusprime" in result.output.lower()


# ---------------------------------------------------------------------------
# 5. Session listing
# ---------------------------------------------------------------------------

def test_get_available_sessions_returns_list(session_op_dir):
    sessions = _get_available_sessions(session_op_dir)
    assert isinstance(sessions, list)
    assert len(sessions) > 0


def test_get_available_sessions_sorted_newest_first(session_op_dir):
    sessions = _get_available_sessions(session_op_dir)
    dates = [s["date"] for s in sessions]
    assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# 6. Session resolution
# ---------------------------------------------------------------------------

def test_resolve_session_date_defaults_to_most_recent(session_op_dir):
    date = _resolve_session_date(session_op_dir, None)
    assert date == "2026-06-28"


def test_resolve_session_date_uses_explicit_date(session_op_dir):
    date = _resolve_session_date(session_op_dir, "2026-06-27")
    assert date == "2026-06-27"
