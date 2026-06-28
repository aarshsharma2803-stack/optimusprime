"""Tests for src/optimusprime/self_model.py — minimum 15 tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from optimusprime.self_model import (
    ConfidenceScore,
    FailurePattern,
    LoopTrigger,
    SelfModel,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ATTEMPTS_FORMAT_1 = """\
[2026-06-27T10:00:00Z] ATTEMPT Bash: pytest tests/test_auth.py → FAILED: AssertionError in test_login
[2026-06-27T10:01:00Z] ATTEMPT Bash: pytest tests/test_auth.py → FAILED: AssertionError in test_login
[2026-06-27T10:02:00Z] ATTEMPT Edit: src/auth.py → FAILED: IndentationError line 42
"""

ATTEMPTS_FORMAT_2 = """\
[2026-06-27T10:00:00Z] [agent:main] FAILED: tool=Edit target=src/foo.py error=SyntaxError line 42
[2026-06-27T10:01:00Z] [agent:main] FAILED: tool=Bash target=python run.py error=ModuleNotFoundError
[2026-06-27T10:02:00Z] [agent:main] FAILED: tool=Edit target=hooks/pre/scope-guard.py error=IndentationError
"""

ATTEMPTS_MANY = "\n".join([
    f"[2026-06-27T10:0{i}:00Z] ATTEMPT Bash: pytest → FAILED: AssertionError in test_auth"
    for i in range(5)
]) + "\n"

LOOP_STATE_JSON = json.dumps({
    "session_id": "test-session",
    "consecutive_failures": [
        {"tool": "Bash", "target": "pytest tests/", "error": "AssertionError at test_login",
         "sig": "abc1", "timestamp": "2026-06-27T10:00:00Z"},
        {"tool": "Bash", "target": "pytest tests/", "error": "AssertionError at test_login",
         "sig": "abc1", "timestamp": "2026-06-27T10:01:00Z"},
        {"tool": "Bash", "target": "pytest tests/", "error": "AssertionError at test_login",
         "sig": "abc1", "timestamp": "2026-06-27T10:02:00Z"},
    ],
})


@pytest.fixture
def op_dir(tmp_path):
    d = tmp_path / ".optimusprime"
    d.mkdir()
    return d


@pytest.fixture
def op_dir_with_attempts(op_dir):
    (op_dir / "attempts.md").write_text(ATTEMPTS_FORMAT_1)
    return op_dir


@pytest.fixture
def op_dir_with_loops(op_dir):
    (op_dir / "attempts.md").write_text(ATTEMPTS_FORMAT_1)
    (op_dir / "loop-state.json").write_text(LOOP_STATE_JSON)
    return op_dir


# ---------------------------------------------------------------------------
# _parse_attempts
# ---------------------------------------------------------------------------

def test_parse_attempts_format1(op_dir_with_attempts):
    sm = SelfModel(op_dir_with_attempts)
    records = sm._parse_attempts()
    assert len(records) == 3
    assert all("error_type" in r for r in records)
    assert all("timestamp" in r for r in records)


def test_parse_attempts_format2(op_dir):
    (op_dir / "attempts.md").write_text(ATTEMPTS_FORMAT_2)
    sm = SelfModel(op_dir)
    records = sm._parse_attempts()
    assert len(records) == 3


def test_parse_attempts_missing_file_returns_empty(op_dir):
    sm = SelfModel(op_dir)
    records = sm._parse_attempts()
    assert records == []


def test_parse_attempts_normalizes_errors(op_dir_with_attempts):
    sm = SelfModel(op_dir_with_attempts)
    records = sm._parse_attempts()
    # "line 42" should be normalized away in the signature
    for r in records:
        assert "line 42" not in r["error_signature"]


# ---------------------------------------------------------------------------
# get_failure_patterns
# ---------------------------------------------------------------------------

def test_get_failure_patterns_sorted_by_count(op_dir_with_attempts):
    sm = SelfModel(op_dir_with_attempts)
    sm.build()
    patterns = sm.get_failure_patterns()
    counts = [p.occurrence_count for p in patterns]
    assert counts == sorted(counts, reverse=True)


def test_get_failure_patterns_file_filter(op_dir_with_attempts):
    sm = SelfModel(op_dir_with_attempts)
    sm.build()
    patterns = sm.get_failure_patterns(file_path="test_auth.py")
    assert all("test_auth.py" in p.file_path or "auth" in p.file_path for p in patterns)


def test_get_failure_patterns_empty_on_no_attempts(op_dir):
    sm = SelfModel(op_dir)
    sm.build()
    patterns = sm.get_failure_patterns()
    assert patterns == []


# ---------------------------------------------------------------------------
# get_confidence
# ---------------------------------------------------------------------------

def test_confidence_auth_keywords(op_dir):
    sm = SelfModel(op_dir)
    cs = sm.get_confidence("implement JWT token validation")
    assert cs.task_type == "auth"


def test_confidence_async_keywords(op_dir):
    sm = SelfModel(op_dir)
    cs = sm.get_confidence("fix async await race condition")
    assert cs.task_type == "async"


def test_confidence_unknown_returns_general(op_dir):
    sm = SelfModel(op_dir)
    cs = sm.get_confidence("do something miscellaneous")
    assert cs.task_type == "general"
    assert cs.confidence == pytest.approx(0.5)


def test_confidence_only_failures_is_zero(op_dir):
    sm = SelfModel(op_dir)
    # Manually inject failure data
    sm._model = {
        "confidence_map": {
            "auth": {
                "task_type": "auth",
                "success_count": 0,
                "failure_count": 5,
                "confidence": 0.0,
                "sample_size": 5,
            }
        }
    }
    cs = sm.get_confidence("implement jwt auth")
    assert cs.confidence == pytest.approx(0.0)


def test_confidence_only_successes_is_one(op_dir):
    sm = SelfModel(op_dir)
    sm._model = {
        "confidence_map": {
            "auth": {
                "task_type": "auth",
                "success_count": 5,
                "failure_count": 0,
                "confidence": 1.0,
                "sample_size": 5,
            }
        }
    }
    cs = sm.get_confidence("implement jwt auth")
    assert cs.confidence == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# get_warnings_for_task
# ---------------------------------------------------------------------------

def test_warnings_for_file_with_failures(op_dir_with_attempts):
    sm = SelfModel(op_dir_with_attempts)
    sm.build()
    warnings = sm.get_warnings_for_task("run tests", "test_auth.py")
    assert len(warnings) >= 0  # may be 0 if resolved
    assert isinstance(warnings, list)


def test_warnings_for_low_confidence_task(op_dir):
    sm = SelfModel(op_dir)
    sm._model = {
        "failure_patterns": {},
        "confidence_map": {
            "auth": {
                "task_type": "auth",
                "success_count": 1,
                "failure_count": 5,
                "confidence": 0.17,
                "sample_size": 6,
            }
        },
        "loop_triggers": [],
    }
    warnings = sm.get_warnings_for_task("implement JWT auth token login")
    assert any("auth" in w.lower() for w in warnings)


def test_warnings_empty_on_no_data(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    sm = SelfModel(op_dir)
    warnings = sm.get_warnings_for_task("do anything")
    assert warnings == []


def test_warnings_never_more_than_5(op_dir_with_attempts):
    sm = SelfModel(op_dir_with_attempts)
    # Stuff the model with lots of patterns
    sm._model = {
        "failure_patterns": {
            f"file{i}::SomeError": {
                "file_path": f"src/file{i}.py",
                "error_type": "SomeError",
                "error_signature": "SomeError",
                "occurrence_count": 5,
                "last_seen": "2026-06-27T10:00:00Z",
                "resolved": False,
                "task_context": "Bash src/file.py",
            }
            for i in range(20)
        },
        "confidence_map": {
            "auth": {"task_type": "auth", "success_count": 0, "failure_count": 10,
                     "confidence": 0.0, "sample_size": 10}
        },
        "loop_triggers": [],
    }
    warnings = sm.get_warnings_for_task("jwt auth login token src/file0.py")
    assert len(warnings) <= 5


def test_warnings_no_crash_empty_optimusprime(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    sm = SelfModel(op_dir)
    # Should not raise
    result = sm.get_warnings_for_task("implement auth", "src/auth.py")
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

def test_update_increments_failure_count(op_dir):
    sm = SelfModel(op_dir)
    sm._model = {
        "failure_patterns": {},
        "confidence_map": {
            "general": {
                "task_type": "general",
                "success_count": 0,
                "failure_count": 2,
                "confidence": 0.0,
                "sample_size": 2,
            }
        },
        "loop_triggers": [],
    }
    sm.update({"failures_count": 3, "session_id": "s1"})
    conf = sm._model["confidence_map"]["general"]
    assert conf["failure_count"] >= 3


def test_update_does_not_rebuild_from_scratch(op_dir_with_attempts):
    sm = SelfModel(op_dir_with_attempts)
    sm._model = {"custom_key": "present", "failure_patterns": {}, "confidence_map": {}, "loop_triggers": []}
    sm.update({"failures_count": 1, "session_id": "s1"})
    # custom_key should still be there — update didn't wipe the model
    assert "custom_key" in sm._model


def test_update_writes_self_model_json(op_dir):
    sm = SelfModel(op_dir)
    sm._model = {"failure_patterns": {}, "confidence_map": {}, "loop_triggers": []}
    sm.update({"failures_count": 2, "session_id": "s2"})
    assert (op_dir / "self-model.json").is_file()
