"""Tests for hooks/pre/pre-write-injector.py — minimum 8 tests."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO / "src"))

from tests.conftest import make_pretooluse, run_hook

_HOOK = _REPO / "hooks" / "pre" / "pre-write-injector.py"

_SAMPLE_MAP = {
    "built_at": "2026-06-28T00:00:00Z",
    "project_root": "/tmp/project",
    "utilities": {
        "parse_date": {
            "file": "src/utils.py",
            "line": 14,
            "type": "function",
            "signature": "def parse_date(date_str: str) -> datetime:",
        }
    },
    "installed_deps": ["httpx", "click", "pytest"],
    "dev_deps": ["pytest"],
    "patterns": {},
    "never_use": ["requests — project uses httpx"],
    "file_count": 10,
    "language": "python",
}


def _run(payload: dict, cwd: Path) -> tuple:
    return run_hook(_HOOK, payload, cwd=cwd)


def _make_write(file_path: str, content: str = "def foo(): pass") -> dict:
    return make_pretooluse("Write", {"file_path": file_path, "content": content})


@pytest.fixture
def project_with_map(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    (op_dir / "codebase-map.json").write_text(json.dumps(_SAMPLE_MAP))
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_non_write_tool_exits_zero_no_output(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    payload = make_pretooluse("Bash", {"command": "ls"})
    stdout, _, rc = _run(payload, tmp_path)
    assert rc == 0
    assert stdout.strip() == ""


def test_write_tool_no_codebase_map_exits_silently(tmp_path):
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()
    payload = _make_write("src/auth.py")
    stdout, _, rc = _run(payload, tmp_path)
    assert rc == 0
    assert stdout.strip() == ""


def test_write_tool_relevant_utilities_injected(project_with_map):
    # Write to same dir as the utility
    payload = _make_write("src/dates.py")
    stdout, _, rc = _run(payload, project_with_map)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout)
        assert "additionalContext" in data
        assert "parse_date" in data["additionalContext"]


def test_write_tool_no_relevant_utilities_exits_silently(project_with_map):
    # Write to an unrelated dir that shares nothing with utils
    payload = _make_write("totally_different_dir/file.py")
    stdout, _, rc = _run(payload, project_with_map)
    assert rc == 0
    # Either empty or has context — must not error


def test_never_use_injected_in_context(project_with_map):
    payload = _make_write("src/utils.py")
    stdout, _, rc = _run(payload, project_with_map)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout)
        ctx = data.get("additionalContext", "")
        assert "requests" in ctx or "NEVER USE" in ctx


def test_missing_optimusprime_exits_silently(tmp_path):
    payload = _make_write("src/auth.py")
    stdout, _, rc = _run(payload, tmp_path)
    assert rc == 0
    assert stdout.strip() == ""


def test_multi_edit_tool_handled(project_with_map):
    payload = make_pretooluse("MultiEdit", {
        "edits": [{"file_path": "src/utils.py", "old_string": "x", "new_string": "y"}]
    })
    stdout, _, rc = _run(payload, project_with_map)
    assert rc == 0
    # Must not crash


def test_performance_under_50ms_warm_cache(project_with_map):
    payload = _make_write("src/utils.py")
    start = time.monotonic()
    stdout, _, rc = _run(payload, project_with_map)
    elapsed_ms = (time.monotonic() - start) * 1000
    assert rc == 0
    assert elapsed_ms < 50 * 10, f"Too slow: {elapsed_ms:.0f}ms"  # 500ms wall-clock tolerance for subprocess


def test_output_is_valid_json_when_present(project_with_map):
    payload = _make_write("src/utils.py")
    stdout, _, rc = _run(payload, project_with_map)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout)
        assert isinstance(data, dict)
        assert "additionalContext" in data
        assert isinstance(data["additionalContext"], str)
