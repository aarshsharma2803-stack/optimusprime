"""Tests for op decision CLI commands."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from optimusprime.cli.op import cli

_REAL_OP_DIR = str(_REPO_ROOT / ".optimusprime")


def _invoke(*args, op_dir=_REAL_OP_DIR):
    runner = CliRunner()
    return runner.invoke(cli, ["--dir", op_dir] + list(args), catch_exceptions=False)


def _invoke_tmp(*args, tmp_op_dir):
    runner = CliRunner()
    return runner.invoke(cli, ["--dir", str(tmp_op_dir)] + list(args), catch_exceptions=False)


# ── 1. op decision count → correct count from real decisions.md ──────────

def test_decision_count_real_data():
    result = _invoke("decision", "count")
    assert result.exit_code == 0
    output = result.output
    # Should show total count (we know there are 60+ entries)
    import re
    m = re.search(r"(\d+) total", output)
    assert m, f"No count found in: {output}"
    count = int(m.group(1))
    assert count >= 60, f"Expected ≥60, got {count}"


# ── 2. op decision list --last 5 → 5 entries ─────────────────────────────

def test_decision_list_last_5():
    result = _invoke("decision", "list", "--last", "5")
    assert result.exit_code == 0
    # Should mention "5 of N decisions"
    assert "5 of" in result.output or "Last 5" in result.output


# ── 3. op decision search "atomic" → relevant results ────────────────────

def test_decision_search_relevant():
    result = _invoke("decision", "search", "atomic")
    assert result.exit_code == 0
    output = result.output.lower()
    # Should mention atomic write (we know that decision exists)
    assert "atomic" in output


# ── 4. op decision search nonexistent → empty, helpful msg ───────────────

def test_decision_search_no_results():
    result = _invoke("decision", "search", "zzz_nonexistent_zzz_12345")
    assert result.exit_code == 0
    output = result.output.lower()
    assert "no decision" in output or "0 result" in output or "no result" in output or "matching" in output


# ── 5. Missing .optimusprime/ → helpful error, no traceback ──────────────

def test_missing_op_dir_helpful_error(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--dir", str(tmp_path / "nonexistent"), "decision", "count"]
    )
    assert result.exit_code != 0
    assert "Error" in result.output or "not found" in result.output.lower()
    assert "Traceback" not in result.output


# ── 6. op decision list --all shows everything ───────────────────────────

def test_decision_list_all(op_dir):
    result = _invoke_tmp("decision", "list", "--all", tmp_op_dir=op_dir)
    assert result.exit_code == 0
    # Should show the 11 decisions + 1 block from our fixture
    assert "DECISION" in result.output


# ── 7. op decision count breakdown by prefix ─────────────────────────────

def test_decision_count_shows_breakdown():
    result = _invoke("decision", "count")
    assert result.exit_code == 0
    # Should show DECISION: and BLOCK: counts
    assert "DECISION" in result.output
    assert "BLOCK" in result.output
