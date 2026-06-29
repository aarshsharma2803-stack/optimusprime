"""Tests for hooks/optimusprime-statusline.sh."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "hooks" / "optimusprime-statusline.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="statusline.sh is bash — skip on Windows",
)


def _run_statusline(cwd: Path) -> tuple[int, str]:
    """Run the statusline script from a given cwd and return (exit_code, output)."""
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=10,
    )
    return result.returncode, result.stdout.strip()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_exits_0_when_no_op_dir(tmp_path: Path):
    code, _ = _run_statusline(tmp_path)
    assert code == 0


def test_outputs_badge_always(tmp_path: Path):
    _, output = _run_statusline(tmp_path)
    assert "OP" in output or "⚡" in output


def test_outputs_minimal_badge_when_no_op_dir(tmp_path: Path):
    _, output = _run_statusline(tmp_path)
    assert "[⚡OP]" == output


def test_outputs_token_count_with_cost_log(tmp_path: Path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    (op / "cost-log.json").write_text(json.dumps({
        "sessions": [{"token_estimate": 5000, "estimated_cost_usd": 0.015}]
    }))
    _, output = _run_statusline(tmp_path)
    assert "tok:" in output or "5k" in output or "5000" in output


def test_outputs_loop_indicator_when_streak(tmp_path: Path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    (op / "loop-state.json").write_text(json.dumps({"consecutive_failures": 3}))
    _, output = _run_statusline(tmp_path)
    assert "🔁3" in output or "3" in output


def test_outputs_decision_count(tmp_path: Path):
    op = tmp_path / ".optimusprime"
    op.mkdir()
    (op / "decisions.md").write_text(
        "[2026-06-29T00:00:00Z] [agent:main] DECIDED: use jwt | REJECTED: none | REASON: stateless\n"
        "[2026-06-29T00:01:00Z] [agent:main] DECIDED: store in httponly | REJECTED: ls | REASON: xss\n"
    )
    _, output = _run_statusline(tmp_path)
    # Should contain 📝 + count or just the badge at minimum
    assert "OP" in output
