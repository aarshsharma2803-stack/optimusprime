"""Tests for token accuracy (Issue 8) and reduction strategies (Issue 9)."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SESSION_LOGGER = _REPO_ROOT / "hooks" / "post" / "session-logger.py"
_PRE_RESPONSE = _REPO_ROOT / "hooks" / "pre" / "pre-response.py"
_TASK_UPDATER = _REPO_ROOT / "hooks" / "post" / "task-state-updater.py"
_ATTEMPT_LOGGER = _REPO_ROOT / "hooks" / "post" / "attempt-logger.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def op_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".optimusprime"
    d.mkdir()
    return d


@pytest.fixture
def pre_mod():
    return _load_module(_PRE_RESPONSE, "pre_response")


@pytest.fixture
def sl_mod():
    return _load_module(_SESSION_LOGGER, "session_logger")


# ---------------------------------------------------------------------------
# Issue 8: Token accuracy
# ---------------------------------------------------------------------------

def test_cost_log_written_with_real_source(op_dir, sl_mod):
    sl_mod._update_cost_log(
        op_dir, "sess-001", "2026-01-01T00:00:00Z",
        total_real=42000, input_tokens=30000, output_tokens=12000,
        cache_tokens=0, thinking_tokens=0,
    )
    data = json.loads((op_dir / "cost-log.json").read_text())
    entry = data["sessions"][-1]
    assert entry["token_source"] == "real"
    assert entry["token_accuracy"] == "exact"
    assert entry["token_estimate"] == 42000


def test_cost_log_breakdown_present_when_real(op_dir, sl_mod):
    sl_mod._update_cost_log(
        op_dir, "sess-002", "2026-01-01T00:00:00Z",
        total_real=50000, input_tokens=35000, output_tokens=15000,
        cache_tokens=0, thinking_tokens=0,
    )
    data = json.loads((op_dir / "cost-log.json").read_text())
    entry = data["sessions"][-1]
    assert "breakdown" in entry
    assert entry["breakdown"]["input"] == 35000
    assert entry["breakdown"]["output"] == 15000
    assert entry["breakdown"]["total"] == 50000


def test_cost_log_estimated_source_when_no_usage(op_dir, sl_mod):
    sl_mod._update_cost_log(
        op_dir, "sess-003", "2026-01-01T00:00:00Z",
        total_real=0,
    )
    data = json.loads((op_dir / "cost-log.json").read_text())
    entry = data["sessions"][-1]
    assert entry["token_source"] == "estimated"
    assert entry["token_accuracy"] == "approximate"
    assert "breakdown" not in entry


def test_session_tokens_accumulates(op_dir):
    al_mod = _load_module(_ATTEMPT_LOGGER, "attempt_logger")
    al_mod._accumulate_session_tokens(op_dir, "s1", "Write", 450)
    al_mod._accumulate_session_tokens(op_dir, "s1", "Bash", 200)
    data = json.loads((op_dir / "session-tokens.json").read_text())
    assert data["running_total"] == 650
    assert len(data["calls"]) == 2


def test_session_tokens_resets_on_new_session(op_dir):
    al_mod = _load_module(_ATTEMPT_LOGGER, "attempt_logger")
    al_mod._accumulate_session_tokens(op_dir, "s1", "Write", 500)
    al_mod._accumulate_session_tokens(op_dir, "s2", "Write", 100)  # new session
    data = json.loads((op_dir / "session-tokens.json").read_text())
    assert data["session_id"] == "s2"
    assert data["running_total"] == 100  # reset, not 600


# ---------------------------------------------------------------------------
# Issue 9: Token reduction strategies
# ---------------------------------------------------------------------------

def test_status_line_shows_checkmark_for_real(op_dir, pre_mod):
    (op_dir / "cost-log.json").write_text(json.dumps({
        "sessions": [{
            "token_estimate": 42000,
            "estimated_cost_usd": 0.13,
            "token_source": "real",
        }]
    }))
    result = pre_mod._build_status_line(op_dir)
    assert "✓" in result, f"Expected ✓ in status line for real tokens, got: {result}"


def test_status_line_shows_tilde_for_estimated(op_dir, pre_mod):
    (op_dir / "cost-log.json").write_text(json.dumps({
        "sessions": [{
            "token_estimate": 42000,
            "estimated_cost_usd": 0.13,
            "token_source": "estimated",
        }]
    }))
    result = pre_mod._build_status_line(op_dir)
    assert "~" in result, f"Expected ~ in status line for estimated tokens, got: {result}"


def test_throttle_suppresses_after_threshold(op_dir, pre_mod):
    # Set state: last full inject was at prompt 1, current is 4 → interval not reached
    (op_dir / "session-state.json").write_text(json.dumps({
        "session_id": "s1",
        "prompt_count": 3,
        "last_full_inject_at": 1,
    }))
    # 4th prompt, last_full was at 1 → 4-1=3 < 5 → throttle
    result = pre_mod._should_throttle(op_dir, "s1")
    assert result is True


def test_throttle_allows_at_threshold(op_dir, pre_mod):
    # prompt_count=4, last_full_inject_at=0 → first prompt → no throttle
    (op_dir / "session-state.json").write_text(json.dumps({
        "session_id": "s1",
        "prompt_count": 0,
        "last_full_inject_at": 0,
    }))
    result = pre_mod._should_throttle(op_dir, "s1")
    assert result is False  # first prompt always does full inject


def test_injection_dedup_skips_seen_content(op_dir, pre_mod):
    section = "[WARNINGS]\n  • Use zod not yup"
    h = hashlib.md5(section.encode()).hexdigest()[:8]
    (op_dir / "injection-log.json").write_text(json.dumps({
        "session_id": "s1",
        "hashes": {h: 1},
    }))
    result = pre_mod._dedup_sections(op_dir, "s1", [section])
    assert result == [], "Duplicate section should be filtered out"


def test_injection_dedup_allows_new_content(op_dir, pre_mod):
    (op_dir / "injection-log.json").write_text(json.dumps({
        "session_id": "s1",
        "hashes": {},
    }))
    section = "[WARNINGS]\n  • New warning not seen before"
    result = pre_mod._dedup_sections(op_dir, "s1", [section])
    assert result == [section]
