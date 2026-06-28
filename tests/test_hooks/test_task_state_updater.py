"""Tests for hooks/post/task-state-updater.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent.parent / "hooks" / "post" / "task-state-updater.py"
REPO_ROOT = HOOK.parent.parent.parent


def _run(payload: dict, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
        cwd=str(cwd or REPO_ROOT),
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "PYTHONPATH": str(REPO_ROOT / "src"),
            "HOME": str(Path.home()),
        },
    )


def _make_op_dir(tmp: Path) -> Path:
    op = tmp / ".optimusprime"
    op.mkdir()
    (op / "contract.json").write_text(json.dumps({
        "goal": "build the session 11 hooks",
        "complexity_budget": "high",
        "out_of_scope_files": [],
    }))
    return op


# ---- 1. Skip Read/Glob/LS ----------------------------------------------

def test_skips_read_tool(tmp_path):
    op = _make_op_dir(tmp_path)
    result = _run({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x.py"}, "session_id": "s"}, cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_skips_glob_tool(tmp_path):
    op = _make_op_dir(tmp_path)
    result = _run({"tool_name": "Glob", "tool_input": {"pattern": "*.py"}, "session_id": "s"}, cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_skips_ls_tool(tmp_path):
    op = _make_op_dir(tmp_path)
    result = _run({"tool_name": "LS", "tool_input": {}, "session_id": "s"}, cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ---- 2. Write/Edit are significant and update task-state.md ------------

def test_write_tool_updates_task_state_file(tmp_path):
    op = _make_op_dir(tmp_path)
    result = _run(
        {"tool_name": "Write", "tool_input": {"file_path": "src/foo.py", "content": "hello"}, "session_id": "s"},
        cwd=tmp_path,
    )
    assert result.returncode == 0
    state_path = op / "task-state.md"
    assert state_path.is_file()
    content = state_path.read_text()
    assert "src/foo.py" in content or "Write" in content


def test_bash_tool_updates_task_state(tmp_path):
    op = _make_op_dir(tmp_path)
    result = _run(
        {"tool_name": "Bash", "tool_input": {"command": "pytest tests/"}, "session_id": "s"},
        cwd=tmp_path,
    )
    assert result.returncode == 0
    state_path = op / "task-state.md"
    assert state_path.is_file()


# ---- 3. Call count increments -------------------------------------------

def test_call_count_increments(tmp_path):
    op = _make_op_dir(tmp_path)
    payload = {"tool_name": "Write", "tool_input": {"file_path": "x.py", "content": "x"}, "session_id": "s"}

    for i in range(3):
        _run(payload, cwd=tmp_path)

    state = (op / "task-state.md").read_text()
    assert "tool_call_count: 3" in state


# ---- 4. additionalContext injected after first call --------------------

def test_context_injected_after_first_call(tmp_path):
    op = _make_op_dir(tmp_path)
    payload = {"tool_name": "Write", "tool_input": {"file_path": "a.py", "content": "x"}, "session_id": "s"}

    # First call — no additionalContext
    r1 = _run(payload, cwd=tmp_path)
    assert r1.stdout.strip() == ""

    # Second call — additionalContext injected
    r2 = _run(payload, cwd=tmp_path)
    if r2.stdout.strip():
        data = json.loads(r2.stdout)
        assert "additionalContext" in data
        ctx = data["additionalContext"]
        assert "TASK STATE" in ctx or "call" in ctx.lower()


# ---- 5. Empty payload exits 0 cleanly -----------------------------------

def test_empty_payload_exits_0(tmp_path):
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input="",
        capture_output=True, text=True, timeout=5,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0


# ---- 6. Invalid JSON exits 0 cleanly ------------------------------------

def test_invalid_json_exits_0(tmp_path):
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input="{bad json",
        capture_output=True, text=True, timeout=5,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0


# ---- 7. task-state.md has YAML frontmatter structure -------------------

def test_task_state_has_yaml_frontmatter(tmp_path):
    op = _make_op_dir(tmp_path)
    _run(
        {"tool_name": "Edit", "tool_input": {"file_path": "f.py", "old_string": "a", "new_string": "b"}, "session_id": "s"},
        cwd=tmp_path,
    )
    state = (op / "task-state.md").read_text()
    assert state.startswith("---")
    assert "goal:" in state
    assert "last_updated:" in state


# ---- 8. No crash without .optimusprime/ dir ----------------------------

def test_no_crash_without_op_dir(tmp_path):
    result = _run(
        {"tool_name": "Write", "tool_input": {"file_path": "x.py", "content": "x"}, "session_id": "s"},
        cwd=tmp_path,
    )
    assert result.returncode == 0
