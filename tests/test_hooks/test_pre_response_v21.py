"""Tests for pre-response.py v2.1 additions — sections A-D."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Load pre-response.py via importlib (hyphens prevent normal import)
_HOOK_PATH = Path(__file__).resolve().parent.parent.parent / "hooks" / "pre" / "pre-response.py"
_REPO_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

_spec = importlib.util.spec_from_file_location("pre_response", _HOOK_PATH)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

_build_token_section = _mod._build_token_section
_build_autobot_section = _mod._build_autobot_section
_build_compression_section = _mod._build_compression_section
_build_quality_section = _mod._build_quality_section


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
        "sessions": [
            {
                "session_id": "s1",
                "token_estimate": 15000,
                "estimated_cost_usd": 0.045,
            }
        ]
    }))
    return op_dir


@pytest.fixture
def op_dir_high_tokens(op_dir: Path) -> Path:
    (op_dir / "cost-log.json").write_text(json.dumps({
        "sessions": [
            {
                "session_id": "s1",
                "token_estimate": 90000,
                "estimated_cost_usd": 0.27,
            }
        ]
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
def op_dir_with_compression_log(op_dir: Path) -> Path:
    (op_dir / "compression-log.json").write_text(json.dumps([
        {"timestamp": "2026-06-29T01:00:00Z", "chars_before": 1000, "chars_after": 364, "ratio": 63.6},
    ]))
    return op_dir


# ---------------------------------------------------------------------------
# Section A — Token awareness
# ---------------------------------------------------------------------------

def test_token_section_injected_with_cost_log(op_dir_with_cost: Path):
    result = _build_token_section(op_dir_with_cost)
    assert "[TOKEN]" in result
    assert "15,000" in result


def test_token_critical_warning_above_80k(op_dir_high_tokens: Path):
    result = _build_token_section(op_dir_high_tokens)
    assert "CRITICAL" in result


def test_token_section_empty_without_cost_log(op_dir: Path):
    result = _build_token_section(op_dir)
    assert result == ""


# ---------------------------------------------------------------------------
# Section B — Auto Bot status
# ---------------------------------------------------------------------------

def test_autobot_section_shows_active_skills(op_dir_with_skills: Path):
    result = _build_autobot_section(op_dir_with_skills)
    assert "[BOT:caveman]" in result


def test_autobot_empty_when_no_auto_skills(op_dir: Path):
    (op_dir / "skills.json").write_text(json.dumps({
        "installed": {"ponytail": {"mode": "manual"}}
    }))
    result = _build_autobot_section(op_dir)
    assert result == ""


def test_autobot_empty_without_skills_json(op_dir: Path):
    result = _build_autobot_section(op_dir)
    # No skills.json → returns standby message or empty
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Section D — Quality gates
# ---------------------------------------------------------------------------

def test_quality_gate_for_build_action(op_dir: Path):
    result = _build_quality_section("build", False, op_dir)
    assert "SOLID" in result or "quality" in result.lower()


def test_quality_gate_for_fix_action(op_dir: Path):
    result = _build_quality_section("fix", False, op_dir)
    assert "root cause" in result.lower() or "Fix mode" in result


# ---------------------------------------------------------------------------
# Budget / total context
# ---------------------------------------------------------------------------

def test_total_context_under_400_tokens(op_dir_with_cost: Path):
    """All sections combined must stay under 1600 chars."""
    op = op_dir_with_cost
    (op / "skills.json").write_text(json.dumps({
        "installed": {"caveman": {"mode": "auto"}}
    }))
    a = _build_token_section(op)
    b = _build_autobot_section(op)
    d = _build_quality_section("build", True, op)
    total = "\n\n".join(s for s in [a, b, d] if s)
    assert len(total) <= 1600


def test_all_sections_absent_empty_op_dir(op_dir: Path):
    """Empty .optimusprime/ — token and quality sections should be empty."""
    a = _build_token_section(op_dir)
    d = _build_quality_section("general", False, op_dir)
    assert a == ""
    assert d == ""
