"""Tests for cli/commands/conductor_cmd.py — op conductor command group."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

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
def op_dir_with_contract(tmp_path: Path) -> Path:
    op = tmp_path / ".optimusprime"
    op.mkdir()
    (op / "contract.json").write_text(json.dumps({
        "goal": "Build auth system",
        "in_scope": ["src/", "tests/"],
        "out_of_scope": [".env"],
        "complexity_budget": "full",
    }))
    return op


@pytest.fixture
def op_dir_with_session(op_dir_with_contract: Path) -> Path:
    op = op_dir_with_contract
    (op / "conductor-session.json").write_text(json.dumps({
        "session_id": "20260628-120000",
        "goal": "Build auth system",
        "status": "paused",
        "created_at": "2026-06-28T12:00:00Z",
        "total_tokens": 4200,
        "total_cost_estimate": 0.0126,
        "escalation_count": 1,
        "human_interventions": [],
        "subtasks": [
            {
                "id": "subtask-001",
                "description": "Implement core auth utilities",
                "file_scope": ["src/"],
                "status": "done",
                "attempts": 1,
                "max_attempts": 3,
                "output": "SUBTASK COMPLETE",
                "error": "",
                "started_at": "2026-06-28T12:00:00Z",
                "completed_at": "2026-06-28T12:03:00Z",
                "token_estimate": 2100,
                "decisions_made": 2,
            },
            {
                "id": "subtask-002",
                "description": "Implement JWT token logic",
                "file_scope": ["src/"],
                "status": "escalated",
                "attempts": 3,
                "max_attempts": 3,
                "output": "",
                "error": "scope violation attempted",
                "started_at": "2026-06-28T12:04:00Z",
                "completed_at": "2026-06-28T12:09:00Z",
                "token_estimate": 2100,
                "decisions_made": 0,
            },
            {
                "id": "subtask-003",
                "description": "Write auth tests",
                "file_scope": ["tests/"],
                "status": "pending",
                "attempts": 0,
                "max_attempts": 3,
                "output": "",
                "error": "",
                "started_at": "",
                "completed_at": "",
                "token_estimate": 0,
                "decisions_made": 0,
            },
        ],
    }))
    (op / "conductor-log.md").write_text(
        "[2026-06-28T12:03:00Z] SUBTASK DONE: subtask-001 — Implement core auth utilities\n"
    )
    (op / "conductor-escalations.md").write_text(
        "[2026-06-28T12:09:00Z] ESCALATED: subtask-002\n"
        "REASON: scope_violation\n"
        "SUBTASK: Implement JWT token logic\n"
        "CONTEXT: tried to write .env\n"
        "SUGGESTED ACTION: Review contract.json\n"
        "────────────────────────────────────────────────────────────\n"
    )
    return op


# ---------------------------------------------------------------------------
# 1. Help
# ---------------------------------------------------------------------------

def test_conductor_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["conductor", "--help"])
    assert result.exit_code == 0
    assert "conductor" in result.output.lower() or "goal" in result.output.lower()


# ---------------------------------------------------------------------------
# 2. Status — no session
# ---------------------------------------------------------------------------

def test_conductor_status_no_session(op_dir: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(op_dir), "conductor", "status"])
    assert result.exit_code == 0
    assert "no conductor session" in result.output.lower() or "start" in result.output.lower()


# ---------------------------------------------------------------------------
# 3. Status — with session
# ---------------------------------------------------------------------------

def test_conductor_status_shows_session_info(op_dir_with_session: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(op_dir_with_session), "conductor", "status"])
    assert result.exit_code == 0
    assert "20260628-120000" in result.output or "paused" in result.output


def test_conductor_status_shows_subtask_table(op_dir_with_session: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(op_dir_with_session), "conductor", "status"])
    assert result.exit_code == 0
    assert "subtask-001" in result.output or "done" in result.output


# ---------------------------------------------------------------------------
# 4. Start --dry-run
# ---------------------------------------------------------------------------

def test_conductor_start_dry_run_shows_plan(op_dir_with_contract: Path):
    runner = CliRunner()
    with patch("shutil.which", return_value="/usr/bin/claude"):
        result = runner.invoke(
            cli,
            ["--dir", str(op_dir_with_contract), "conductor", "start",
             "--goal", "add input validation to all API endpoints", "--dry-run"],
        )
    assert result.exit_code == 0
    output = result.output.lower()
    assert "plan" in output or "subtask" in output or "dry" in output


def test_conductor_start_dry_run_no_execution(op_dir_with_contract: Path):
    runner = CliRunner()
    with patch("shutil.which", return_value="/usr/bin/claude"):
        with patch("subprocess.run") as mock_sub:
            runner.invoke(
                cli,
                ["--dir", str(op_dir_with_contract), "conductor", "start",
                 "--goal", "build something", "--dry-run"],
            )
    mock_sub.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Log
# ---------------------------------------------------------------------------

def test_conductor_log_no_file(op_dir: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(op_dir), "conductor", "log"])
    assert result.exit_code == 0
    assert "no conductor log" in result.output.lower() or "start" in result.output.lower()


def test_conductor_log_shows_content(op_dir_with_session: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(op_dir_with_session), "conductor", "log"])
    assert result.exit_code == 0
    assert "SUBTASK DONE" in result.output


# ---------------------------------------------------------------------------
# 6. Escalations
# ---------------------------------------------------------------------------

def test_conductor_escalations_no_file(op_dir: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(op_dir), "conductor", "escalations"])
    assert result.exit_code == 0
    assert "no escalation" in result.output.lower() or "successfully" in result.output.lower()


def test_conductor_escalations_shows_content(op_dir_with_session: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(op_dir_with_session), "conductor", "escalations"])
    assert result.exit_code == 0
    assert "ESCALATED" in result.output or "scope_violation" in result.output


# ---------------------------------------------------------------------------
# 7. Abort — no session
# ---------------------------------------------------------------------------

def test_conductor_abort_no_session(op_dir: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(op_dir), "conductor", "abort"])
    assert result.exit_code == 0
    assert "no conductor session" in result.output.lower() or "nothing" in result.output.lower()


# ---------------------------------------------------------------------------
# 8. Plan command
# ---------------------------------------------------------------------------

def test_conductor_plan_shows_breakdown(op_dir_with_contract: Path):
    runner = CliRunner()
    with patch("shutil.which", return_value="/usr/bin/claude"):
        result = runner.invoke(
            cli,
            ["--dir", str(op_dir_with_contract), "conductor", "plan",
             "--goal", "refactor the intelligence module"],
        )
    assert result.exit_code == 0
    output = result.output.lower()
    assert "plan" in output or "subtask" in output or "goal" in output


# ---------------------------------------------------------------------------
# 9. Resume — no paused session
# ---------------------------------------------------------------------------

def test_conductor_resume_no_session(op_dir: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(op_dir), "conductor", "resume", "--context", "ctx"])
    assert result.exit_code == 0
    assert "no conductor session" in result.output.lower() or "nothing to resume" in result.output.lower()


# ---------------------------------------------------------------------------
# 10. Start — missing --goal
# ---------------------------------------------------------------------------

def test_conductor_start_missing_goal():
    runner = CliRunner()
    result = runner.invoke(cli, ["conductor", "start"])
    # Click should report missing required option
    assert result.exit_code != 0 or "goal" in result.output.lower() or "missing" in result.output.lower()
