"""Tests for OptimusPrime menu bar data layer and CLI commands."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from optimusprime.menubar_data import MenuBarData
from optimusprime.cli.op import cli
from optimusprime.cli.commands.menubar import _PID_FILE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def op_dir(tmp_path: Path) -> Path:
    op = tmp_path / ".optimusprime"
    op.mkdir()
    return op


@pytest.fixture
def mdata(op_dir: Path) -> MenuBarData:
    return MenuBarData(op_dir)


@pytest.fixture(autouse=True)
def clean_pid():
    _PID_FILE.unlink(missing_ok=True)
    yield
    _PID_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Data loading tests
# ---------------------------------------------------------------------------

def test_load_data_reads_contract(mdata: MenuBarData, op_dir: Path):
    (op_dir / "contract.json").write_text(json.dumps({
        "goal": "build the auth system",
        "complexity_budget": "medium",
    }))
    mdata.load()
    assert mdata.data["goal"] == "build the auth system"
    assert mdata.data["budget"] == "medium"


def test_load_data_reads_cost_log(mdata: MenuBarData, op_dir: Path):
    (op_dir / "cost-log.json").write_text(json.dumps({
        "sessions": [{"token_estimate": 25000, "estimated_cost_usd": 0.075}]
    }))
    mdata.load()
    assert mdata.data["tokens"] == 25000
    assert abs(mdata.data["cost"] - 0.075) < 0.001


def test_load_data_reads_decisions(mdata: MenuBarData, op_dir: Path):
    (op_dir / "decisions.md").write_text(
        "[T1] [agent:main] DECIDED: use jwt\n"
        "[T2] [agent:main] DECIDED: use httponly cookies\n"
    )
    mdata.load()
    assert mdata.data["decision_count"] == 2


def test_load_data_reads_skills(mdata: MenuBarData, op_dir: Path):
    (op_dir / "skills.json").write_text(json.dumps({
        "installed": {
            "caveman": {"mode": "auto", "version": "2.0.0"},
            "ponytail": {"mode": "manual", "version": "1.0.0"},
        }
    }))
    mdata.load()
    assert "caveman" in mdata.data["skills"]
    assert mdata.data["skills"]["caveman"] == "auto"
    assert mdata.data["skills"]["ponytail"] == "manual"


def test_load_data_missing_op_dir(tmp_path: Path):
    """Non-existent op_dir with find_op_dir disabled → data is empty, no crash."""
    mdata = MenuBarData(tmp_path / ".nonexistent")
    # Patch find_op_dir so it can't fall back to the real repo's .optimusprime/
    with patch.object(mdata, "find_op_dir", return_value=False):
        mdata.load()
    assert mdata.data == {}


def test_load_data_malformed_json(mdata: MenuBarData, op_dir: Path):
    """Malformed JSON in one file → silently skipped; valid files still loaded."""
    (op_dir / "contract.json").write_text("NOT VALID JSON {{{")
    (op_dir / "cost-log.json").write_text(json.dumps({
        "sessions": [{"token_estimate": 5000, "estimated_cost_usd": 0.01}]
    }))
    mdata.load()
    assert "goal" not in mdata.data        # malformed contract skipped
    assert mdata.data.get("tokens") == 5000  # valid cost-log still read


# ---------------------------------------------------------------------------
# Display / title tests
# ---------------------------------------------------------------------------

def test_update_display_shows_token_count(mdata: MenuBarData, op_dir: Path):
    (op_dir / "cost-log.json").write_text(json.dumps({
        "sessions": [{"token_estimate": 42000, "estimated_cost_usd": 0.18}]
    }))
    mdata.load()
    title = mdata.title()
    assert "42k" in title
    assert "⚡OP" in title


def test_update_display_shows_base_when_no_data(mdata: MenuBarData):
    """With no data, title() returns '⚡OP' exactly."""
    title = mdata.title()
    assert title == "⚡OP"


# ---------------------------------------------------------------------------
# CLI tests (via CliRunner — no PID needed)
# ---------------------------------------------------------------------------

def test_menubar_status_not_running_initially():
    runner = CliRunner()
    result = runner.invoke(cli, ["menubar", "status"])
    assert result.exit_code == 0
    assert "Not running" in result.output


def test_menubar_stop_handles_missing_pid():
    """op menubar stop with no PID file should report 'Not running' gracefully."""
    runner = CliRunner()
    result = runner.invoke(cli, ["menubar", "stop"])
    assert result.exit_code == 0
    assert "Not running" in result.output
