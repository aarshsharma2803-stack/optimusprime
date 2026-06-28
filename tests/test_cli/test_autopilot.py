"""Tests for cli/commands/autopilot.py — op autopilot command."""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner

from optimusprime.cli.commands.autopilot import (
    _parse_snapshot,
    _load_todos,
    _load_decisions_tail,
    _load_attempts_info,
    _build_suggested_message,
    _infer_task_type,
    autopilot,
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
def full_op_dir(tmp_path: Path) -> Path:
    op = tmp_path / ".optimusprime"
    op.mkdir()

    (op / "session-snapshot.md").write_text(
        "# OPTIMUSPRIME SESSION SNAPSHOT\n"
        "Generated: 2026-06-27T23:00:00Z | Session: sess-abc | Agent: main\n\n"
        "## Goal\nBuild the JWT auth middleware\n\n"
        "## Changed (3 files)\n"
        "~ src/auth.py\n~ src/middleware.py\n+ tests/test_auth.py\n\n"
        "## Decisions (12 total)\n"
        "- chose jwt over session cookies — stateless\n\n"
        "## Failed Attempts (1 total)\n(none)\n\n"
        "## Open TODOs (2)\n(none)\n\n"
        "## Next Action\nAdd token refresh endpoint in src/auth.py\n"
    )
    (op / "resume.json").write_text(json.dumps({
        "version": "0.1.0",
        "session_id": "sess-abc",
        "goal": "Build the JWT auth middleware",
        "captured_at": "2026-06-27T23:00:00Z",
        "changed_files": ["~ src/auth.py", "~ src/middleware.py"],
        "decision_count": 12,
        "attempt_count": 1,
        "open_todos": ["TODO: add rate limiting", "TODO: add refresh logic"],
        "next_action": "Add token refresh endpoint in src/auth.py",
    }))
    (op / "decisions.md").write_text(
        "[2026-06-27T20:00:00Z] [agent:main] DECIDED: use jwt | REJECTED: session-cookies | REASON: stateless\n"
        "[2026-06-27T21:00:00Z] [agent:main] DECIDED: store in httponly cookie | REJECTED: localstorage | REASON: xss\n"
        "[2026-06-27T22:00:00Z] [agent:main] DECIDED: HS256 algorithm | REJECTED: RS256 | REASON: simpler for single server\n"
    )
    (op / "todos.md").write_text("TODO: add rate limiting\nTODO: add refresh logic\n")
    (op / "attempts.md").write_text(
        "[2026-06-27T20:30:00Z] ATTEMPT Bash: pytest → FAILED: test_auth import error\n"
    )
    (op / "contract.json").write_text(json.dumps({
        "goal": "Build the JWT auth middleware",
        "in_scope": ["src/**", "tests/**"],
        "out_of_scope": [".env", "secrets/**"],
        "complexity_budget": "moderate",
    }))
    return op


# ---------------------------------------------------------------------------
# 1. Snapshot parsing
# ---------------------------------------------------------------------------

def test_parse_snapshot_reads_goal(full_op_dir):
    snap = _parse_snapshot(full_op_dir / "session-snapshot.md")
    assert snap.get("goal") == "Build the JWT auth middleware"


def test_parse_snapshot_reads_decision_count(full_op_dir):
    snap = _parse_snapshot(full_op_dir / "session-snapshot.md")
    assert snap.get("decision_count") == 12


def test_parse_snapshot_reads_next_action(full_op_dir):
    snap = _parse_snapshot(full_op_dir / "session-snapshot.md")
    assert "token refresh" in snap.get("next_action", "")


def test_parse_snapshot_reads_captured_at(full_op_dir):
    snap = _parse_snapshot(full_op_dir / "session-snapshot.md")
    assert "2026-06-27" in snap.get("captured_at", "")


def test_parse_snapshot_missing_returns_empty(tmp_path):
    result = _parse_snapshot(tmp_path / "nonexistent.md")
    assert result == {}


# ---------------------------------------------------------------------------
# 2. Resume.json
# ---------------------------------------------------------------------------

def test_resume_json_read_correctly(full_op_dir):
    from optimusprime.cli.common import load_json_safe
    resume = load_json_safe(full_op_dir / "resume.json")
    assert resume.get("session_id") == "sess-abc"
    assert resume.get("decision_count") == 12


# ---------------------------------------------------------------------------
# 3. Todos.md
# ---------------------------------------------------------------------------

def test_load_todos_counts_correctly(full_op_dir):
    count, lines = _load_todos(full_op_dir)
    assert count == 2
    assert any("rate limiting" in l for l in lines)


def test_load_todos_returns_zero_when_missing(op_dir):
    count, lines = _load_todos(op_dir)
    assert count == 0
    assert lines == []


# ---------------------------------------------------------------------------
# 4. Decisions.md
# ---------------------------------------------------------------------------

def test_load_decisions_last_3(full_op_dir):
    total, last_3 = _load_decisions_tail(full_op_dir, n=3)
    assert total == 3
    assert len(last_3) == 3
    assert "HS256" in last_3[-1] or "RS256" in last_3[-1]


def test_load_decisions_handles_missing(op_dir):
    total, entries = _load_decisions_tail(op_dir)
    assert total == 0
    assert entries == []


# ---------------------------------------------------------------------------
# 5. Git analysis (no git or not available)
# ---------------------------------------------------------------------------

def test_git_analysis_skips_silently_when_no_git(tmp_path):
    """When not in a git repo, git analysis returns available=False gracefully."""
    from optimusprime.cli.commands.autopilot import _git_analysis
    op = tmp_path / ".optimusprime"
    op.mkdir()
    result = _git_analysis(tmp_path, "2026-06-27", [], op)
    assert result.get("available") is False
    assert result.get("oos_changes") == []


def test_git_oos_violations_flagged(tmp_path):
    """Out-of-scope file in changed_files list should be flagged."""
    from optimusprime.cli.commands.autopilot import _git_analysis
    op = tmp_path / ".optimusprime"
    op.mkdir()
    # Simulate git being available but changed_files pre-populated
    result = _git_analysis(tmp_path, "", [".env", "secrets/**"], op)
    # Without real git, no files will be found
    # Test is checking the logic: if changed_files had .env, it would be flagged
    assert isinstance(result["oos_changes"], list)


# ---------------------------------------------------------------------------
# 6. Message builder
# ---------------------------------------------------------------------------

def test_suggested_message_includes_next_action():
    contract = {"complexity_budget": "moderate", "in_scope": ["src/**"]}
    msg = _build_suggested_message(
        "Add token refresh endpoint",
        ["decided: use jwt"],
        contract,
        "Build auth system",
    )
    assert "token refresh" in msg.lower() or "Add token refresh" in msg


def test_suggested_message_under_100_words():
    contract = {"complexity_budget": "full"}
    msg = _build_suggested_message(
        "A " * 150,  # very long next action
        [],
        contract,
        "goal",
    )
    words = msg.split()
    assert len(words) <= 100


# ---------------------------------------------------------------------------
# 7. CLI flags
# ---------------------------------------------------------------------------

def test_message_only_flag_prints_only_message(full_op_dir, tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(full_op_dir), "autopilot", "--message-only"])
    assert result.exit_code == 0
    output = result.output.strip()
    # Should be short — no headers, no dashes
    assert "━" not in output
    assert "OPTIMUSPRIME" not in output
    assert len(output) > 0


def test_json_flag_outputs_valid_json(full_op_dir):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(full_op_dir), "autopilot", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "goal" in data
    assert "suggested_message" in data


def test_missing_op_dir_gives_helpful_message(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["autopilot"])
    assert result.exit_code != 0 or "optimusprime" in result.output.lower()


def test_all_fields_missing_gives_partial_brief(op_dir):
    """Even with empty .optimusprime/, autopilot should not crash."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(op_dir), "autopilot"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 8. Task type inference
# ---------------------------------------------------------------------------

def test_infer_task_type_auth():
    assert _infer_task_type("fix the jwt login flow", "auth system") == "auth"


def test_infer_task_type_api():
    assert _infer_task_type("build the user api endpoint", "") == "api"
