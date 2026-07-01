"""Tests for pre-response.py _build_status_line() and chat status injection."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_HOOK_PATH = Path(__file__).resolve().parent.parent.parent / "hooks" / "pre" / "pre-response.py"
_REPO_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

_spec = importlib.util.spec_from_file_location("pre_response", _HOOK_PATH)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

_build_status_line = _mod._build_status_line


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def op_dir(tmp_path: Path) -> Path:
    op = tmp_path / ".optimusprime"
    op.mkdir()
    return op


@pytest.fixture
def op_dir_with_cost(op_dir: Path) -> Path:
    (op_dir / "cost-log.json").write_text(json.dumps({
        "sessions": [{"session_id": "s1", "token_estimate": 15000, "estimated_cost_usd": 0.045}]
    }))
    return op_dir


@pytest.fixture
def op_dir_with_skills(op_dir: Path) -> Path:
    (op_dir / "skills.json").write_text(json.dumps({
        "installed": {
            "caveman": {"mode": "auto", "version": "2.0.0"},
            "ponytail": {"mode": "manual", "version": "1.0.0"},
        }
    }))
    return op_dir


@pytest.fixture
def op_dir_high_streak(op_dir: Path) -> Path:
    (op_dir / "loop-state.json").write_text(json.dumps({
        "consecutive_failures": [{"tool": "Write"}, {"tool": "Edit"}, {"tool": "Write"}]
    }))
    return op_dir


@pytest.fixture
def op_dir_with_compression(op_dir: Path) -> Path:
    (op_dir / "compression-log.json").write_text(json.dumps([
        {"timestamp": "2026-06-29T01:00:00Z", "chars_before": 1000, "chars_after": 370, "ratio": 63.0}
    ]))
    return op_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_status_line_always_present(op_dir: Path):
    result = _build_status_line(op_dir)
    assert "⚡OP" in result


def test_status_line_under_120_chars(op_dir: Path):
    result = _build_status_line(op_dir)
    assert len(result) <= 120


def test_token_count_shows_k_format(op_dir_with_cost: Path):
    result = _build_status_line(op_dir_with_cost)
    assert "~15k" in result


def test_active_bots_shown(op_dir_with_skills: Path):
    result = _build_status_line(op_dir_with_skills)
    assert "Caveman Bot" in result  # bot_name from registry
    assert "🤖" in result


def test_loop_streak_warning_at_limit(op_dir_high_streak: Path):
    result = _build_status_line(op_dir_high_streak)
    assert "⚠3" in result


def test_compression_ratio_shown(op_dir_with_compression: Path):
    result = _build_status_line(op_dir_with_compression)
    assert "cmp:63%" in result


def test_minimum_on_bad_data(tmp_path: Path):
    """With a completely absent op_dir, always starts with '⚡OP' at minimum."""
    absent = tmp_path / ".nonexistent"
    result = _build_status_line(absent)
    assert result.startswith("⚡OP")


def test_status_line_first_in_additional_context(op_dir_with_cost: Path):
    """main() always emits status line as first line of additionalContext."""
    payload = json.dumps({"session_id": "s1", "prompt": "fix the authentication bug"})
    captured = io.StringIO()
    with patch.object(_mod, "_find_op_dir", return_value=op_dir_with_cost):
        with patch("sys.stdin", io.StringIO(payload)):
            with patch("sys.stdout", captured):
                with pytest.raises(SystemExit):
                    _mod.main()
    output = captured.getvalue().strip()
    assert output, "hook produced no output"
    data = json.loads(output)
    ctx = data["additionalContext"]
    first_line = ctx.split("\n")[0]
    assert first_line.startswith("⚡OP")
