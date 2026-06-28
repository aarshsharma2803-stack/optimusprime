"""Tests for src/optimusprime/cli/commands/watch.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from optimusprime.cli.commands.watch import (
    _build_compact_line,
    _find_op_dir,
    _load_json,
    _read_tail,
    _read_task_state,
)


@pytest.fixture
def op_dir(tmp_path: Path) -> Path:
    op = tmp_path / ".optimusprime"
    op.mkdir()
    return op


# ---- 1. _find_op_dir walks up correctly --------------------------------

def test_find_op_dir_finds_parent(tmp_path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    subdir = tmp_path / "a" / "b"
    subdir.mkdir(parents=True)
    result = _find_op_dir(subdir)
    assert result == op


def test_find_op_dir_returns_none_when_missing(tmp_path):
    result = _find_op_dir(tmp_path)
    assert result is None


# ---- 2. _load_json returns empty dict on bad file ----------------------

def test_load_json_missing_file(tmp_path):
    result = _load_json(tmp_path / "doesntexist.json")
    assert result == {}


def test_load_json_parses_valid_json(tmp_path):
    f = tmp_path / "data.json"
    f.write_text(json.dumps({"key": "value"}))
    result = _load_json(f)
    assert result == {"key": "value"}


def test_load_json_returns_empty_on_malformed(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{bad json}")
    result = _load_json(f)
    assert result == {}


# ---- 3. _read_tail returns last n non-empty lines ----------------------

def test_read_tail_returns_last_n(tmp_path):
    f = tmp_path / "lines.txt"
    f.write_text("\n".join(f"line {i}" for i in range(10)))
    result = _read_tail(f, n=3)
    assert len(result) == 3
    assert "line 9" in result[-1]


def test_read_tail_missing_file(tmp_path):
    result = _read_tail(tmp_path / "missing.txt", n=5)
    assert result == []


def test_read_tail_skips_blank_lines(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("a\n\nb\n\nc\n")
    result = _read_tail(f, n=5)
    assert "" not in result


# ---- 4. _read_task_state parses frontmatter ---------------------------

def test_read_task_state_parses_frontmatter(tmp_path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    (op / "task-state.md").write_text(
        "---\nsession_id: abc123\ngoal: build the auth\ntool_call_count: 5\n---\n\n## Current Step\nStep 5: writing\n"
    )
    state = _read_task_state(op)
    assert state.get("session_id") == "abc123"
    assert state.get("goal") == "build the auth"
    assert state.get("current_step") == "Step 5: writing"


def test_read_task_state_returns_empty_for_missing(tmp_path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    state = _read_task_state(op)
    assert state == {}


# ---- 5. _build_compact_line returns a string --------------------------

def test_build_compact_line_returns_string(tmp_path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    (op / "task-state.md").write_text(
        "---\nsession_id: x\ngoal: fix the login bug\ntool_call_count: 3\n---\n"
    )
    (op / "decisions.md").write_text("[2024-01-01] DECIDED: use sqlite\n")
    line = _build_compact_line(op)
    assert isinstance(line, str)
    assert "op |" in line


def test_build_compact_line_no_crash_empty_state(tmp_path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    line = _build_compact_line(op)
    assert isinstance(line, str)


# ---- 6. watch command registered in CLI --------------------------------

def test_watch_command_registered():
    from optimusprime.cli.op import cli
    assert "watch" in cli.commands


# ---- 7. watch --help works -----------------------------------------------

def test_watch_help_exits_0():
    from click.testing import CliRunner
    from optimusprime.cli.commands.watch import watch
    runner = CliRunner()
    result = runner.invoke(watch, ["--help"])
    assert result.exit_code == 0
    assert "--interval" in result.output or "--compact" in result.output


# ---- 8. watch exits when no op dir found --------------------------------

def test_watch_errors_without_op_dir(tmp_path):
    from click.testing import CliRunner
    from optimusprime.cli.commands.watch import watch
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(watch, ["--compact", "--interval", "1"])
    assert result.exit_code != 0 or "ERROR" in result.output
