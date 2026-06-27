"""Tests for op contract CLI commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from optimusprime.cli.op import cli


def _invoke(op_dir, *args):
    runner = CliRunner()
    return runner.invoke(cli, ["--dir", str(op_dir)] + list(args), catch_exceptions=False)


# ── 1. op contract show → prints contract fields ─────────────────────────

def test_contract_show(op_dir):
    result = _invoke(op_dir, "contract", "show")
    assert result.exit_code == 0
    output = result.output
    assert "Scope Contract" in output
    assert "Build the OptimusPrime" in output
    assert "In scope" in output
    assert "Out of scope" in output


# ── 2. op contract (no subcommand) → same as show ────────────────────────

def test_contract_default_is_show(op_dir):
    result = _invoke(op_dir, "contract")
    assert result.exit_code == 0
    assert "Scope Contract" in result.output


# ── 3. op contract show-scope → two clear lists ──────────────────────────

def test_contract_show_scope(op_dir):
    result = _invoke(op_dir, "contract", "show-scope")
    assert result.exit_code == 0
    assert "IN SCOPE" in result.output
    assert "OUT OF SCOPE" in result.output
    # Fixture has src/**, hooks/**, tests/**, mcp/**
    assert "src/**" in result.output
    # Fixture has .env in out_of_scope
    assert ".env" in result.output


# ── 4. op contract reset --yes → deletes contract.json ───────────────────

def test_contract_reset_with_yes(op_dir):
    contract_path = op_dir / "contract.json"
    assert contract_path.exists()

    result = _invoke(op_dir, "contract", "reset", "--yes")
    assert result.exit_code == 0
    assert not contract_path.exists()
    assert "deleted" in result.output.lower() or "disabled" in result.output.lower()


# ── 5. op contract show after reset → helpful error message ──────────────

def test_contract_show_after_reset(op_dir):
    # Delete the contract
    (op_dir / "contract.json").unlink()

    result = _invoke(op_dir, "contract", "show")
    # Should not crash, should give a helpful message
    assert result.exit_code != 0 or "not found" in result.output.lower() or "No scope" in result.output


# ── 6. op contract show-scope with no in_scope → "all files in scope" ────

def test_contract_show_scope_empty_in_scope(op_dir):
    contract = {
        "goal": "minimal test",
        "in_scope": [],
        "out_of_scope": [".env"],
        "agent_id": "main",
    }
    (op_dir / "contract.json").write_text(json.dumps(contract))
    result = _invoke(op_dir, "contract", "show-scope")
    assert result.exit_code == 0
    assert "all files in scope" in result.output.lower()
