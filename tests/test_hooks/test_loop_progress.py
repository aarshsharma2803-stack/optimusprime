"""Tests for progress-based loop detection (Issue 13)."""
from __future__ import annotations

import importlib.util
import json
import sys
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LOOP_DETECTOR = _REPO_ROOT / "hooks" / "pre" / "loop-detector.py"
_ATTEMPT_LOGGER = _REPO_ROOT / "hooks" / "post" / "attempt-logger.py"


def _load_detector():
    spec = importlib.util.spec_from_file_location("loop_detector", _LOOP_DETECTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def det():
    return _load_detector()


# ---- Progress analysis unit tests ----------------------------------------

def test_no_progress_identical_errors(det):
    failures = [
        {"tool": "Edit", "target": "src/auth.py", "error": "SyntaxError line 42"},
    ] * 5
    count, msg_type, _ = det._analyze_failure_tail(failures, "Edit", "src/auth.py")
    assert count >= 5
    assert msg_type in ("no_progress", "regressing")


def test_progress_resets_counter(det):
    """Different errors = progress made → should NOT block."""
    failures = [
        {"tool": "Edit", "target": "src/auth.py", "error": "ImportError: requests not found"},
        {"tool": "Edit", "target": "src/auth.py", "error": "SyntaxError: unexpected indent"},
        {"tool": "Edit", "target": "src/auth.py", "error": "TypeError: expected str got int"},
    ]
    count, _, _ = det._analyze_failure_tail(failures, "Edit", "src/auth.py")
    assert count < 3, "Different errors = progress → no block"


def test_five_different_errors_not_blocked(det):
    """5 completely different errors = progress every step → no block."""
    failures = [
        {"tool": "Bash", "target": "pytest", "error": "ModuleNotFoundError: no module named pytest"},
        {"tool": "Bash", "target": "pytest", "error": "FileNotFoundError: conftest.py missing"},
        {"tool": "Bash", "target": "pytest", "error": "AssertionError: expected 42 got 0"},
        {"tool": "Bash", "target": "pytest", "error": "PermissionError: cannot write to /tmp"},
        {"tool": "Bash", "target": "pytest", "error": "TimeoutError: test exceeded 30 seconds"},
    ]
    count, _, _ = det._analyze_failure_tail(failures, "Bash", "pytest")
    assert count < 3


def test_five_identical_errors_blocked(det):
    """5 identical errors → block."""
    failures = [
        {"tool": "Edit", "target": "app.py", "error": "NameError: name 'db' is not defined"},
    ] * 5
    count, msg_type, _ = det._analyze_failure_tail(failures, "Edit", "app.py")
    assert count >= 5
    assert msg_type == "no_progress"


def test_block_message_no_progress(det):
    failures = [
        {"tool": "Edit", "target": "x.py", "error": "ValueError: invalid literal"},
    ] * 5
    count, msg_type, latest = det._analyze_failure_tail(failures, "Edit", "x.py")
    assert msg_type == "no_progress"
    assert "invalid literal" in latest


def test_different_tool_not_counted(det):
    """Failures on different tools don't stack."""
    failures = [
        {"tool": "Bash", "target": "test.py", "error": "exit 1"},
        {"tool": "Edit", "target": "test.py", "error": "exit 1"},
        {"tool": "Write", "target": "test.py", "error": "exit 1"},
    ]
    count, _, _ = det._analyze_failure_tail(failures, "Edit", "test.py")
    assert count < 3


def test_different_target_not_counted(det):
    """Failures on different targets don't stack."""
    failures = [
        {"tool": "Edit", "target": "a.py", "error": "SyntaxError"},
        {"tool": "Edit", "target": "b.py", "error": "SyntaxError"},
        {"tool": "Edit", "target": "c.py", "error": "SyntaxError"},
    ]
    count, _, _ = det._analyze_failure_tail(failures, "Edit", "d.py")
    assert count == 0


def test_loop_state_json_schema_updated(tmp_path):
    """loop-state.json gets consecutive_no_progress and progress_detected fields."""
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    loop_state = {
        "session_id": "s1",
        "consecutive_failures": [
            {"tool": "Edit", "target": "src/a.py", "error": "SyntaxError line 1"},
        ] * 5,
    }
    (op_dir / "loop-state.json").write_text(json.dumps(loop_state))

    payload = json.dumps({
        "session_id": "s1",
        "tool_name": "Edit",
        "tool_input": {"file_path": "src/a.py"},
    })
    result = subprocess.run(
        [sys.executable, str(_LOOP_DETECTOR)],
        input=payload, capture_output=True, text=True,
        cwd=str(tmp_path), timeout=5,
    )
    # Should block (exit 2) and update the json
    assert result.returncode == 2
    updated = json.loads((op_dir / "loop-state.json").read_text())
    assert "consecutive_no_progress" in updated
    assert updated["progress_detected"] is False


def test_progress_detected_true_when_no_block(tmp_path):
    """When no block, progress_detected set to True."""
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    loop_state = {
        "session_id": "s1",
        "consecutive_failures": [
            {"tool": "Edit", "target": "src/a.py", "error": "ImportError"},
            {"tool": "Edit", "target": "src/a.py", "error": "SyntaxError on a completely new line"},
        ],
    }
    (op_dir / "loop-state.json").write_text(json.dumps(loop_state))

    payload = json.dumps({
        "session_id": "s1",
        "tool_name": "Edit",
        "tool_input": {"file_path": "src/a.py"},
    })
    result = subprocess.run(
        [sys.executable, str(_LOOP_DETECTOR)],
        input=payload, capture_output=True, text=True,
        cwd=str(tmp_path), timeout=5,
    )
    assert result.returncode == 0
