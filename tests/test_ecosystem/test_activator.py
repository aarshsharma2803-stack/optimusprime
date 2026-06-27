"""Tests for ecosystem/activator.py — at least 5 scenarios."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "ecosystem"))

from activator import SkillActivator, _eval_signal


def _write_installed(op_dir, skills):
    data = {"version": "0.1.0", "installed": skills, "last_checked": ""}
    (op_dir / "skills.json").write_text(json.dumps(data))


def _write_contract(op_dir, goal, budget="full"):
    (op_dir / "contract.json").write_text(json.dumps({
        "goal": goal,
        "complexity_budget": budget,
        "agent_id": "main",
        "session_id": "test",
        "created_at": "2026-06-27T00:00:00Z",
    }))


# ── 1. get_active_signals() reads real contract.json ─────────────────────

def test_get_active_signals_reads_contract(op_dir):
    activator = SkillActivator(op_dir=op_dir)
    signals = activator.get_active_signals(op_dir)
    assert signals["complexity_budget"] == "full"
    assert "Build the OptimusPrime" in signals["goal_keywords"]
    assert isinstance(signals["token_estimate"], int)
    assert isinstance(signals["session_duration_mins"], float)


# ── 2. evaluate() → "activate" for caveman when token_estimate > 60k ─────

def test_evaluate_activate_caveman_high_tokens(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    _write_installed(op_dir, {
        "caveman": {"source": "github:JuliusBrussee/caveman", "mode": "auto", "auto_update": "patch"},
    })
    activator = SkillActivator(op_dir=op_dir)
    signals = {
        "complexity_budget": "minimal",
        "goal_keywords": "refactor the codebase",
        "files_touched": [],
        "token_estimate": 70000,
        "session_duration_mins": 45.0,
    }
    action = activator.evaluate("caveman", signals)
    assert action == "activate"


# ── 3. evaluate() → "skip" for uninstalled skill ─────────────────────────

def test_evaluate_skip_uninstalled(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    _write_installed(op_dir, {})  # nothing installed
    activator = SkillActivator(op_dir=op_dir)
    signals = {"complexity_budget": "full", "goal_keywords": "build auth", "files_touched": [], "token_estimate": 80000, "session_duration_mins": 0.0}
    assert activator.evaluate("caveman", signals) == "skip"
    assert activator.evaluate("superpowers", signals) == "skip"


# ── 4. evaluate() respects manual mode → always "skip" ───────────────────

def test_evaluate_manual_mode_always_skip(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    _write_installed(op_dir, {
        "caveman": {"mode": "manual", "auto_update": "patch"},
        "superpowers": {"mode": "manual", "auto_update": "minor"},
    })
    activator = SkillActivator(op_dir=op_dir)
    signals = {"complexity_budget": "full", "goal_keywords": "build", "files_touched": [], "token_estimate": 999999, "session_duration_mins": 0.0}
    assert activator.evaluate("caveman", signals) == "skip"
    assert activator.evaluate("superpowers", signals) == "skip"


# ── 5. get_recommendations() not empty when signals match ────────────────

def test_get_recommendations_returns_matches(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    _write_installed(op_dir, {
        "caveman": {"mode": "auto", "auto_update": "patch"},
        "superpowers": {"mode": "suggested", "auto_update": "minor"},
    })
    _write_contract(op_dir, "build a new authentication system", budget="full")
    (op_dir / "cost-log.json").write_text(json.dumps({
        "sessions": [{"session_id": "s1", "input_tokens": 50000, "output_tokens": 15000}]
    }))
    activator = SkillActivator(op_dir=op_dir)
    recs = activator.get_recommendations(op_dir)
    assert len(recs) >= 1
    rec_map = {r["skill"]: r["action"] for r in recs}
    # caveman should activate (65k tokens > 60k threshold)
    assert rec_map.get("caveman") == "activate"
    # All recs have required fields
    for r in recs:
        assert "skill" in r and "action" in r and "reason" in r


# ── 6. evaluate() → "suggest" not "activate" for suggested mode skill ─────

def test_evaluate_suggest_for_suggested_mode(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    _write_installed(op_dir, {
        "superpowers": {"mode": "suggested", "auto_update": "minor"},
    })
    activator = SkillActivator(op_dir=op_dir)
    signals = {
        "complexity_budget": "full",
        "goal_keywords": "build and implement the new architecture",
        "files_touched": [],
        "token_estimate": 5000,
        "session_duration_mins": 10.0,
    }
    action = activator.evaluate("superpowers", signals)
    assert action == "suggest"


# ── 7. _eval_signal grammar: all four types ──────────────────────────────

def test_eval_signal_all_types():
    signals = {
        "complexity_budget": "full",
        "goal_keywords": "build auth system with JWT tokens",
        "files_touched": ["src/App.tsx", "src/styles.css"],
        "token_estimate": 75000,
        "session_duration_mins": 30.0,
    }
    assert _eval_signal("complexity_budget:full", signals) is True
    assert _eval_signal("complexity_budget:minimal", signals) is False
    assert _eval_signal("goal_keywords:build,implement", signals) is True
    assert _eval_signal("goal_keywords:deploy,ship", signals) is False
    assert _eval_signal("files_touched:.tsx,.jsx", signals) is True
    assert _eval_signal("files_touched:.vue", signals) is False
    assert _eval_signal("token_estimate_over:60000", signals) is True
    assert _eval_signal("token_estimate_over:80000", signals) is False
