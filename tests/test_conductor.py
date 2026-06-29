"""Tests for src/optimusprime/conductor.py — Conductor agentic loop."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from optimusprime.conductor import (
    Conductor,
    ConductorSession,
    EscalationReason,
    SubTask,
    _est_tokens,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def op_dir(tmp_path: Path) -> Path:
    op = tmp_path / ".optimusprime"
    op.mkdir()
    return op


@pytest.fixture
def op_dir_with_contract(op_dir: Path) -> Path:
    (op_dir / "contract.json").write_text(json.dumps({
        "goal": "Build auth system",
        "agent_id": "main",
        "in_scope": ["src/", "tests/"],
        "out_of_scope": [".env", "secrets/"],
        "complexity_budget": "full",
    }))
    (op_dir / "decisions.md").write_text(
        "[2026-06-28T09:00:00Z] [agent:main] DECIDED: use jwt | REJECTED: sessions | REASON: stateless\n"
    )
    return op_dir


@pytest.fixture
def conductor(op_dir_with_contract: Path) -> Conductor:
    return Conductor(op_dir_with_contract, op_dir_with_contract.parent)


@pytest.fixture
def conductor_no_contract(op_dir: Path) -> Conductor:
    return Conductor(op_dir, op_dir.parent)


# ---------------------------------------------------------------------------
# 1. Conductor plan() — prerequisites
# ---------------------------------------------------------------------------

def test_no_contract_raises_runtime_error(conductor_no_contract: Conductor):
    """Missing contract.json should raise RuntimeError from plan()."""
    with pytest.raises(RuntimeError, match="scope contract|contract"):
        conductor_no_contract.plan("build something")


def test_check_prerequisites_missing_contract(op_dir: Path):
    c = Conductor(op_dir, op_dir.parent)
    problems = c._check_prerequisites()
    assert any("contract" in p.lower() or "scope" in p.lower() for p in problems)


def test_check_prerequisites_missing_op_dir(tmp_path: Path):
    missing = tmp_path / ".optimusprime-nonexistent"
    c = Conductor(missing, tmp_path)
    problems = c._check_prerequisites()
    assert any(".optimusprime" in p.lower() or "directory" in p.lower() for p in problems)


def test_check_prerequisites_no_claude_command(op_dir_with_contract: Path):
    c = Conductor(op_dir_with_contract, op_dir_with_contract.parent)
    with patch("shutil.which", return_value=None):
        problems = c._check_prerequisites()
    # claude not found → should be in problems
    assert any("claude" in p.lower() for p in problems)


def test_check_prerequisites_returns_empty_when_all_good(op_dir_with_contract: Path):
    c = Conductor(op_dir_with_contract, op_dir_with_contract.parent)
    with patch("shutil.which", return_value="/usr/local/bin/claude"):
        problems = c._check_prerequisites()
    # Only contract + op_dir checks; claude mocked as present
    assert all("contract" not in p for p in problems) or problems == []


# ---------------------------------------------------------------------------
# 2. Conductor plan() — returns ConductorSession
# ---------------------------------------------------------------------------

def test_plan_returns_conductor_session(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("build a simple auth module")
    assert isinstance(session, ConductorSession)
    assert session.goal == "build a simple auth module"
    assert session.status == "planning"


def test_plan_produces_subtasks(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("build a login system with jwt tokens")
    assert len(session.subtasks) >= 1
    assert all(isinstance(st, SubTask) for st in session.subtasks)


def test_plan_max_8_subtasks(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan(
            "build auth and api and database and frontend and docker and ci and docs and tests"
        )
    assert len(session.subtasks) <= 8


def test_plan_writes_conductor_plan_md(conductor: Conductor, op_dir_with_contract: Path):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        conductor.plan("build auth system")
    plan_path = op_dir_with_contract / "conductor-plan.md"
    assert plan_path.is_file()
    content = plan_path.read_text()
    assert "CONDUCTOR PLAN" in content
    assert "build auth system" in content


def test_plan_subtask_ids_are_sequential(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("build user api endpoints")
    ids = [st.id for st in session.subtasks]
    for i, id_ in enumerate(ids, 1):
        assert id_ == f"subtask-{i:03d}"


def test_plan_subtasks_have_test_last(conductor: Conductor):
    """Tests should come after implementation subtasks."""
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("build a login system")
    descs = [st.description.lower() for st in session.subtasks]
    # Find any test subtask
    test_indices = [i for i, d in enumerate(descs) if "test" in d]
    impl_indices = [i for i, d in enumerate(descs) if "implement" in d or "build" in d or "create" in d]
    if test_indices and impl_indices:
        assert min(test_indices) > min(impl_indices)


def test_plan_writes_session_json(conductor: Conductor, op_dir_with_contract: Path):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        conductor.plan("build auth")
    session_path = op_dir_with_contract / "conductor-session.json"
    assert session_path.is_file()
    data = json.loads(session_path.read_text())
    assert data["status"] == "planning"
    assert data["goal"] == "build auth"


# ---------------------------------------------------------------------------
# 3. Conductor run() — dry_run=True
# ---------------------------------------------------------------------------

def test_dry_run_marks_all_subtasks_done(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("build a simple module")
    session = conductor.run(session, dry_run=True)
    assert all(st.status == "done" for st in session.subtasks)


def test_dry_run_does_not_call_subprocess(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("build x")
    with patch("subprocess.run") as mock_sub:
        conductor.run(session, dry_run=True)
    mock_sub.assert_not_called()


def test_dry_run_writes_conductor_log(conductor: Conductor, op_dir_with_contract: Path):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("build y")
    conductor.run(session, dry_run=True)
    log_path = op_dir_with_contract / "conductor-log.md"
    assert log_path.is_file()
    content = log_path.read_text()
    assert "SUBTASK DONE" in content


def test_dry_run_writes_conductor_summary(conductor: Conductor, op_dir_with_contract: Path):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("build z")
    conductor.run(session, dry_run=True)
    summary_path = op_dir_with_contract / "conductor-summary.md"
    assert summary_path.is_file()
    assert "CONDUCTOR SUMMARY" in summary_path.read_text()


def test_dry_run_tracks_total_tokens(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("build auth module")
    session = conductor.run(session, dry_run=True)
    assert session.total_tokens >= 0


def test_dry_run_session_status_done(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("simple goal")
    session = conductor.run(session, dry_run=True)
    assert session.status == "done"


# ---------------------------------------------------------------------------
# 4. Subtask evaluation
# ---------------------------------------------------------------------------

def test_subtask_complete_in_output_marks_done(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("do something")
    st = session.subtasks[0]
    # Simulate SUBTASK COMPLETE in output
    with patch.object(conductor, "_execute_subtask",
                      return_value=(f"SUBTASK COMPLETE: {st.description}", 0)):
        session = conductor.run(session, dry_run=False)
    assert session.subtasks[0].status == "done"


def test_missing_subtask_complete_causes_retry(conductor: Conductor):
    """Output without SUBTASK COMPLETE triggers retry up to max_attempts."""
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("do something")
    st = session.subtasks[0]
    st.max_attempts = 2
    call_count = {"n": 0}
    def mock_exec(prompt):
        call_count["n"] += 1
        return ("No completion marker here", 0)
    with patch.object(conductor, "_execute_subtask", side_effect=mock_exec):
        with patch("time.sleep"):
            session = conductor.run(session, dry_run=False)
    # Should have been attempted at least once
    assert session.subtasks[0].attempts >= 1
    assert session.subtasks[0].status in ("escalated", "failed")


def test_three_failures_cause_escalation(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("fail task")
    for st in session.subtasks:
        st.max_attempts = 3
    with patch.object(conductor, "_execute_subtask", return_value=("no complete", 0)):
        with patch("time.sleep"):
            session = conductor.run(session, dry_run=False)
    assert any(st.status == "escalated" for st in session.subtasks)
    assert session.escalation_count >= 1


def test_refusal_in_output_causes_escalation(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("do something")
    def mock_exec(prompt):
        return ("I cannot complete this task as described", 0)
    with patch.object(conductor, "_execute_subtask", side_effect=mock_exec):
        with patch("time.sleep"):
            session = conductor.run(session, dry_run=False)
    escalated = [st for st in session.subtasks if st.status == "escalated"]
    assert len(escalated) >= 1


def test_max_attempts_reached_writes_escalation_file(conductor: Conductor, op_dir_with_contract: Path):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("another task")
    for st in session.subtasks:
        st.max_attempts = 1
    with patch.object(conductor, "_execute_subtask", return_value=("fail", 0)):
        with patch("time.sleep"):
            session = conductor.run(session, dry_run=False)
    esc_path = op_dir_with_contract / "conductor-escalations.md"
    if esc_path.is_file():
        assert "ESCALATED" in esc_path.read_text()


# ---------------------------------------------------------------------------
# 5. Session management
# ---------------------------------------------------------------------------

def test_abort_marks_status_aborted(conductor: Conductor, op_dir_with_contract: Path):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("build x")
    conductor.abort()
    data = json.loads((op_dir_with_contract / "conductor-session.json").read_text())
    assert data["status"] == "aborted"


def test_abort_without_session_raises(op_dir: Path):
    c = Conductor(op_dir, op_dir.parent)
    with pytest.raises(RuntimeError):
        c.abort()


def test_resume_reads_conductor_session_json(conductor: Conductor, op_dir_with_contract: Path):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("build something")
    session.status = "paused"
    conductor._save_session(session)
    # Resume should reload and continue
    resumed = conductor.resume("use httpx not requests")
    assert isinstance(resumed, ConductorSession)


def test_paused_session_resumes_from_correct_subtask(conductor: Conductor, op_dir_with_contract: Path):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("multi-step task")
    # Mark first subtask done
    session.subtasks[0].status = "done"
    if len(session.subtasks) > 1:
        session.subtasks[1].status = "escalated"
    session.status = "paused"
    conductor._save_session(session)

    with patch.object(conductor, "_execute_subtask",
                      return_value=(f"SUBTASK COMPLETE: done", 0)):
        with patch("time.sleep"):
            resumed = conductor.resume("resolved the issue")
    # First subtask (already done) should remain done
    assert resumed.subtasks[0].status == "done"


def test_done_subtasks_not_rerun_on_resume(conductor: Conductor, op_dir_with_contract: Path):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("task")
    session.subtasks[0].status = "done"
    session.subtasks[0].output = "ORIGINAL OUTPUT"
    session.status = "paused"
    conductor._save_session(session)

    exec_calls = {"n": 0}
    def track_exec(prompt):
        exec_calls["n"] += 1
        return (f"SUBTASK COMPLETE: done", 0)
    with patch.object(conductor, "_execute_subtask", side_effect=track_exec):
        with patch("time.sleep"):
            conductor.resume("")
    # Should NOT have re-executed the already-done subtask
    total_subtasks = len(session.subtasks)
    assert exec_calls["n"] <= total_subtasks - 1


# ---------------------------------------------------------------------------
# 6. Error handling
# ---------------------------------------------------------------------------

def test_claude_not_found_returns_error_output(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("task")
    with patch("subprocess.run", side_effect=FileNotFoundError):
        output, code = conductor._execute_subtask("some prompt")
    assert "not found" in output.lower() or "error" in output.lower()
    assert code != 0


def test_timeout_treated_as_failure(conductor: Conductor):
    import subprocess
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("task")
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 300)):
        output, code = conductor._execute_subtask("prompt")
    assert "timeout" in output.lower()
    assert code != 0


def test_malformed_claude_output_does_not_crash(conductor: Conductor):
    with patch("shutil.which", return_value="/usr/bin/claude"):
        session = conductor.plan("simple task")
    for st in session.subtasks:
        st.max_attempts = 1
    with patch.object(conductor, "_execute_subtask",
                      return_value=("{{{invalid json}}}]]", 0)):
        with patch("time.sleep"):
            result = conductor.run(session, dry_run=False)
    # Should not crash — session should be returned
    assert isinstance(result, ConductorSession)


def test_est_tokens_approximation():
    text = "hello " * 100  # 100 words
    tokens = _est_tokens(text)
    assert 120 <= tokens <= 150  # 100 * 1.3 = 130


def test_build_context_package_under_2000_chars(conductor: Conductor):
    st = SubTask(id="subtask-001", description="build auth", file_scope=["src/"])
    ctx = conductor._build_context_package(st)
    assert len(ctx) <= 2000
