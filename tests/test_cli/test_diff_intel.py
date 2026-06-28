"""Tests for cli/commands/diff_intel.py — op diff-intel command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from optimusprime.cli.commands.diff_intel import (
    _check_scope_violations,
    _check_rejected_deps,
    _load_out_of_scope,
    _load_rejected_terms,
    _get_baseline,
    _is_git_repo,
    _get_new_decision_count,
    diff_intel,
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
        "Generated: 2026-06-27T23:00:00Z | Session: s1 | Agent: main\n\n"
        "## Goal\nBuild auth\n\n"
        "## Changed (1 files)\n~ src/auth.py\n\n"
        "## Decisions (3 total)\n\n"
        "## Failed Attempts (0 total)\n\n"
        "## Open TODOs (0)\n\n"
        "## Next Action\ncontinue\n"
    )
    (op / "decisions.md").write_text(
        "[2026-06-27T20:00:00Z] [agent:main] DECIDED: use httpx | REJECTED: requests | REASON: better async\n"
        "[2026-06-27T21:00:00Z] [agent:main] DECIDED: use zod | REJECTED: yup | REASON: better ts types\n"
        "[2026-06-28T09:00:00Z] [agent:main] DECIDED: add caching | REJECTED: none | REASON: performance\n"
    )
    (op / "contract.json").write_text(json.dumps({
        "goal": "Build auth",
        "in_scope": ["src/**", "tests/**"],
        "out_of_scope": [".env", "secrets/**", "prisma/migrations"],
        "complexity_budget": "full",
    }))
    return op


# ---------------------------------------------------------------------------
# 1. No git repo
# ---------------------------------------------------------------------------

def test_no_git_repo_skips_analysis(tmp_path):
    runner = CliRunner()
    op = tmp_path / ".optimusprime"
    op.mkdir()
    result = runner.invoke(cli, ["--dir", str(op), "diff-intel"])
    assert result.exit_code == 0
    assert "git" in result.output.lower() or "no git" in result.output.lower()


def test_is_git_repo_returns_false_for_non_repo(tmp_path):
    assert _is_git_repo(tmp_path) is False


# ---------------------------------------------------------------------------
# 2. Scope violations
# ---------------------------------------------------------------------------

def test_check_scope_violations_detects_env_file():
    oos = [".env", "secrets/**", "prisma/migrations"]
    changed = [".env", "src/auth.py", "prisma/migrations/001.sql"]
    violations = _check_scope_violations(changed, oos)
    assert ".env" in violations


def test_check_scope_violations_in_scope_file_not_flagged():
    oos = [".env", "secrets/**"]
    changed = ["src/auth.py", "tests/test_auth.py"]
    violations = _check_scope_violations(changed, oos)
    assert violations == []


def test_check_scope_violations_path_prefix_match():
    oos = ["prisma/migrations"]
    changed = ["prisma/migrations/0001_initial.sql"]
    violations = _check_scope_violations(changed, oos)
    assert "prisma/migrations/0001_initial.sql" in violations


# ---------------------------------------------------------------------------
# 3. Dependency checking
# ---------------------------------------------------------------------------

def test_check_rejected_deps_detects_requirements_txt(tmp_path):
    # Create a requirements.txt with a rejected dep
    (tmp_path / "requirements.txt").write_text("requests>=2.0\nhttpx>=0.24\n")
    rejected = {"requests": "2026-06-27"}
    findings = _check_rejected_deps(["requirements.txt"], tmp_path, rejected)
    assert len(findings) > 0
    assert any("requests" in f[1] for f in findings)


def test_check_rejected_deps_detects_package_json(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "dependencies": {"yup": "^1.0.0", "zod": "^3.0.0"}
    }))
    rejected = {"yup": "2026-06-27"}
    findings = _check_rejected_deps(["package.json"], tmp_path, rejected)
    assert len(findings) > 0
    assert any("yup" in f[1] for f in findings)


def test_check_rejected_deps_no_violations(tmp_path):
    (tmp_path / "requirements.txt").write_text("httpx>=0.24\n")
    rejected = {"requests": "2026-06-27"}
    findings = _check_rejected_deps(["requirements.txt"], tmp_path, rejected)
    assert findings == []


def test_load_rejected_terms_parses_decisions(full_op_dir):
    terms = _load_rejected_terms(full_op_dir)
    assert "requests" in terms or "httpx" not in terms
    # requests was rejected
    assert "requests" in terms


def test_missing_decisions_gives_empty_rejected_terms(op_dir):
    terms = _load_rejected_terms(op_dir)
    assert terms == {}


# ---------------------------------------------------------------------------
# 4. Baseline detection
# ---------------------------------------------------------------------------

def test_get_baseline_uses_snapshot_date(full_op_dir):
    baseline = _get_baseline(full_op_dir, None)
    assert baseline == "2026-06-27"


def test_get_baseline_uses_since_override(full_op_dir):
    baseline = _get_baseline(full_op_dir, "2026-06-20")
    assert baseline == "2026-06-20"


def test_get_baseline_defaults_when_no_snapshot(op_dir):
    baseline = _get_baseline(op_dir, None)
    # Should be yesterday or today
    assert len(baseline) == 10
    assert baseline[:4] == "2026"


# ---------------------------------------------------------------------------
# 5. Test count analysis
# ---------------------------------------------------------------------------

def test_new_decision_count_since_baseline(full_op_dir):
    # 1 decision is from 2026-06-28, 2 from 2026-06-27
    count = _get_new_decision_count(full_op_dir, "2026-06-28")
    assert count == 1


def test_new_decision_count_zero_when_none_after_baseline(full_op_dir):
    count = _get_new_decision_count(full_op_dir, "2026-06-29")
    assert count == 0


# ---------------------------------------------------------------------------
# 6. Empty .optimusprime/ and CLI flags
# ---------------------------------------------------------------------------

def test_empty_op_dir_no_crash(op_dir):
    runner = CliRunner()
    # Without git, should just print "no git" message
    result = runner.invoke(cli, ["--dir", str(op_dir), "diff-intel"])
    assert result.exit_code == 0


def test_since_flag_changes_baseline(full_op_dir):
    """--since flag should be used as baseline instead of snapshot date."""
    # Can't run real git, but the baseline resolution should use since flag
    baseline = _get_baseline(full_op_dir, "2026-06-25")
    assert baseline == "2026-06-25"


def test_load_out_of_scope_reads_contract(full_op_dir):
    oos = _load_out_of_scope(full_op_dir)
    assert ".env" in oos


def test_load_out_of_scope_empty_without_contract(op_dir):
    oos = _load_out_of_scope(op_dir)
    assert oos == []


def test_clean_state_message_shown_when_no_issues(op_dir):
    """With no git and no issues, should show clean state message."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--dir", str(op_dir), "diff-intel"])
    assert result.exit_code == 0
    # Either no-git message or clean state
    assert "git" in result.output.lower() or "clean" in result.output.lower()
