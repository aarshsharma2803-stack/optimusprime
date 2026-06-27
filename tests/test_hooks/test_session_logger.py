"""Tests for hooks/post/session-logger.py — at least 6 scenarios."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import make_precompact, make_stop, run_hook

_HOOK = Path(__file__).resolve().parent.parent.parent / "hooks" / "post" / "session-logger.py"


def _run(stdin_data, cwd):
    return run_hook(_HOOK, stdin_data, cwd)


# ── 1. Stop event → writes session-snapshot.md ───────────────────────────

def test_stop_writes_snapshot(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    # Remove any pre-existing snapshot
    snap = op_dir / "session-snapshot.md"
    snap.unlink(missing_ok=True)

    stdout, _, rc = _run(make_stop(), cwd=tmp_optimusprime_dir)
    assert rc == 0
    assert snap.is_file()
    content = snap.read_text(encoding="utf-8")
    assert "## Goal" in content
    assert "## Decisions" in content
    assert "## Next Action" in content


# ── 2. Snapshot has all required sections ────────────────────────────────

def test_snapshot_has_all_sections(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    _run(make_stop(), cwd=tmp_optimusprime_dir)
    content = (op_dir / "session-snapshot.md").read_text(encoding="utf-8")

    for section in ("## Goal", "## Changed", "## Decisions", "## Failed Attempts",
                    "## Open TODOs", "## Next Action"):
        assert section in content, f"Missing section: {section}"


# ── 3. Snapshot stays under 200 tokens (approx: ~800 chars / 4) ──────────

def test_snapshot_token_budget(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    _run(make_stop(), cwd=tmp_optimusprime_dir)
    content = (op_dir / "session-snapshot.md").read_text(encoding="utf-8")
    # Rough token estimate: chars / 4 (GPT tokenizer average)
    estimated_tokens = len(content) / 4
    assert estimated_tokens < 400, f"Snapshot too long: ~{estimated_tokens:.0f} tokens"


# ── 4. Stop event → writes resume.json with correct structure ────────────

def test_stop_writes_resume_json(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    resume_path = op_dir / "resume.json"
    resume_path.unlink(missing_ok=True)

    _run(make_stop(session_id="my-session-99"), cwd=tmp_optimusprime_dir)
    assert resume_path.is_file()
    data = json.loads(resume_path.read_text(encoding="utf-8"))

    assert data["version"] == "0.1.0"
    assert "goal" in data
    assert "decision_count" in data
    assert isinstance(data["recent_decisions"], list)
    assert "next_action" in data


# ── 5. Missing contract.json → still writes partial snapshot ─────────────

def test_missing_contract_still_writes(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    (op_dir / "decisions.md").write_text(
        "[2026-06-27T10:00:00Z] [agent:main] DECISION: test decision\n", encoding="utf-8"
    )

    stdout, _, rc = _run(make_stop(), cwd=tmp_path)
    assert rc == 0
    snap = op_dir / "session-snapshot.md"
    assert snap.is_file()
    content = snap.read_text(encoding="utf-8")
    assert "## Goal" in content


# ── 6. Missing decisions.md → "0 total" in snapshot ─────────────────────

def test_missing_decisions_shows_zero(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    (op_dir / "contract.json").write_text(
        json.dumps({"goal": "test goal", "agent_id": "main", "session_id": "s1"}), encoding="utf-8"
    )

    _run(make_stop(), cwd=tmp_path)
    content = (op_dir / "session-snapshot.md").read_text(encoding="utf-8")
    assert "0 total" in content or "(none logged)" in content


# ── 7. PreCompact → outputs additionalContext with snapshot ──────────────

def test_precompact_outputs_additional_context(tmp_optimusprime_dir):
    stdout, _, rc = _run(make_precompact(), cwd=tmp_optimusprime_dir)
    assert rc == 0
    assert stdout.strip() != ""
    data = json.loads(stdout.strip())
    assert "additionalContext" in data
    ctx = data["additionalContext"]
    assert "OPTIMUSPRIME" in ctx
    assert "## Goal" in ctx


# ── 8. Decisions count in snapshot matches actual decisions.md ───────────

def test_decision_count_matches_file(tmp_optimusprime_dir):
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    decisions_path = op_dir / "decisions.md"
    actual_count = sum(
        1 for line in decisions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )

    _run(make_stop(), cwd=tmp_optimusprime_dir)
    content = (op_dir / "session-snapshot.md").read_text(encoding="utf-8")
    # Look for "Decisions (N total)" line
    assert f"({actual_count} total)" in content
