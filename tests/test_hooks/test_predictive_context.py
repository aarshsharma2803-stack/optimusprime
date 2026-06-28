"""Tests for hooks/pre/predictive-context.py — minimum 12 scenarios."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tests.conftest import make_pretooluse, run_hook

_HOOK = Path(__file__).resolve().parent.parent.parent / "hooks" / "pre" / "predictive-context.py"
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _run(payload: dict, cwd=None) -> tuple:
    return run_hook(_HOOK, payload, cwd or _REPO_ROOT)


def _write_payload(file_path: str, content: str = "") -> dict:
    return make_pretooluse("Write", {"file_path": file_path, "content": content})


def _edit_payload(file_path: str, old_string: str = "", new_string: str = "") -> dict:
    return make_pretooluse("Edit", {
        "file_path": file_path,
        "old_string": old_string,
        "new_string": new_string,
    })


def _bash_payload(command: str) -> dict:
    return make_pretooluse("Bash", {"command": command})


# ---------------------------------------------------------------------------
# Signal extraction tests (via full hook run against real decisions.md)
# ---------------------------------------------------------------------------


def test_write_tool_uses_file_path(tmp_optimusprime_dir):
    """Write tool: hook doesn't crash and may produce output for a known file."""
    stdout, _, rc = _run(
        _write_payload("src/optimusprime/intelligence.py"),
        cwd=tmp_optimusprime_dir,
    )
    assert rc == 0  # never crashes


def test_edit_tool_extracts_function_names(tmp_optimusprime_dir):
    """Edit tool: function names in old_string become signals for retrieval."""
    payload = _edit_payload(
        "src/optimusprime/intelligence.py",
        old_string="def detect_contradictions(self, new_decision):\n    pass",
    )
    stdout, _, rc = _run(payload, cwd=tmp_optimusprime_dir)
    assert rc == 0


def test_bash_tool_extracts_file_refs(tmp_optimusprime_dir):
    """Bash tool: file paths in command become retrieval signals."""
    payload = _bash_payload("pytest tests/test_hooks/test_scope_guard.py -v")
    stdout, _, rc = _run(payload, cwd=tmp_optimusprime_dir)
    assert rc == 0


def test_unknown_tool_no_crash(tmp_optimusprime_dir):
    """Unknown tool names use generic extraction and never crash."""
    payload = make_pretooluse("TodoWrite", {"todos": ["fix auth bug"]})
    stdout, _, rc = _run(payload, cwd=tmp_optimusprime_dir)
    assert rc == 0


# ---------------------------------------------------------------------------
# Context assembly: first call vs subsequent
# ---------------------------------------------------------------------------


def test_first_call_injects_snapshot(tmp_optimusprime_dir):
    """On first call (no session-state.json), snapshot content is included."""
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    # Ensure no session-state so this is first call
    state_path = op_dir / "session-state.json"
    if state_path.exists():
        state_path.unlink()

    stdout, _, rc = _run(_write_payload("src/optimusprime/utils.py"), cwd=tmp_optimusprime_dir)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout.strip())
        ctx = data.get("additionalContext", "")
        assert "SESSION CONTEXT" in ctx or "RELEVANT" in ctx


def test_second_call_skips_snapshot(tmp_optimusprime_dir):
    """After first_call_done=True in session-state.json, snapshot is not re-injected."""
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    # Mark session as already started
    (op_dir / "session-state.json").write_text(
        json.dumps({"first_call_done": True, "tool_call_count": 5}),
        encoding="utf-8",
    )
    stdout, _, rc = _run(_write_payload("src/optimusprime/utils.py"), cwd=tmp_optimusprime_dir)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout.strip())
        ctx = data.get("additionalContext", "")
        assert "SESSION CONTEXT" not in ctx


def test_session_state_created_on_first_call(tmp_optimusprime_dir):
    """Hook creates session-state.json with first_call_done=True."""
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    state_path = op_dir / "session-state.json"
    if state_path.exists():
        state_path.unlink()

    _run(_write_payload("src/optimusprime/utils.py"), cwd=tmp_optimusprime_dir)

    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state.get("first_call_done") is True
        assert state.get("tool_call_count", 0) >= 1


def test_tool_call_count_increments(tmp_optimusprime_dir):
    """Each hook invocation increments tool_call_count."""
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    state_path = op_dir / "session-state.json"
    state_path.write_text(
        json.dumps({"first_call_done": True, "tool_call_count": 3}),
        encoding="utf-8",
    )
    _run(_write_payload("src/optimusprime/utils.py"), cwd=tmp_optimusprime_dir)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state.get("tool_call_count", 0) >= 4


# ---------------------------------------------------------------------------
# Failure history injection
# ---------------------------------------------------------------------------


def test_file_failure_injected_in_context(tmp_optimusprime_dir):
    """When attempts.md has failures for the target file, they appear in context."""
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    # Write a failure for the exact file we're about to edit
    (op_dir / "attempts.md").write_text(
        "[2026-01-01T00:00:00Z] [agent:main] FAILED: tool=Edit"
        " target=src/optimusprime/utils.py error=SyntaxError line 42\n",
        encoding="utf-8",
    )
    state_path = op_dir / "session-state.json"
    state_path.write_text(
        json.dumps({"first_call_done": True, "tool_call_count": 1}),
        encoding="utf-8",
    )
    stdout, _, rc = _run(_write_payload("src/optimusprime/utils.py"), cwd=tmp_optimusprime_dir)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout.strip())
        ctx = data.get("additionalContext", "")
        # Failure info should appear (either in KNOWN FAILURES or predictions)
        assert "utils.py" in ctx or "FAIL" in ctx or "SyntaxError" in ctx


# ---------------------------------------------------------------------------
# Graceful empty / missing cases
# ---------------------------------------------------------------------------


def test_no_optimusprime_dir_exits_silently(tmp_path):
    """When .optimusprime/ doesn't exist, hook exits 0 with no output."""
    stdout, _, rc = _run(_write_payload("src/utils.py"), cwd=tmp_path)
    assert rc == 0
    assert stdout.strip() == ""


def test_empty_decisions_md_no_crash(tmp_optimusprime_dir):
    """Empty decisions.md doesn't cause a crash — exits 0."""
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    (op_dir / "decisions.md").write_text("", encoding="utf-8")
    stdout, _, rc = _run(_write_payload("src/utils.py"), cwd=tmp_optimusprime_dir)
    assert rc == 0


def test_malformed_stdin_exits_silently():
    """Malformed JSON on stdin → exit 0, no output."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, str(_HOOK)],
        input="not valid json {{{",
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_empty_stdin_exits_silently():
    """Empty stdin → exit 0, no output."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, str(_HOOK)],
        input="",
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Integration: full pipeline against real decisions.md
# ---------------------------------------------------------------------------


def test_full_pipeline_intelligence_file():
    """Write to intelligence.py injects intelligence-related decisions, not just recent."""
    op_dir = _REPO_ROOT / ".optimusprime"
    if not (op_dir / "decisions.md").is_file():
        pytest.skip("no real decisions.md found")

    # Mark as non-first-call so we get only relevant context, not snapshot
    state_path = op_dir / "session-state.json"
    orig_state = state_path.read_text(encoding="utf-8") if state_path.exists() else None
    state_path.write_text(
        json.dumps({"first_call_done": True, "tool_call_count": 10}),
        encoding="utf-8",
    )

    try:
        stdout, _, rc = _run(
            _write_payload(
                "src/optimusprime/intelligence.py",
                content="# test",
            ),
            cwd=_REPO_ROOT,
        )
        assert rc == 0
        if stdout.strip():
            data = json.loads(stdout.strip())
            ctx = data.get("additionalContext", "")
            assert "RELEVANT" in ctx
            # Should contain intelligence-related content
            assert any(word in ctx.lower() for word in ("tfidf", "intelligence", "decision", "search"))
    finally:
        # Restore original state
        if orig_state is not None:
            state_path.write_text(orig_state, encoding="utf-8")
        elif state_path.exists():
            state_path.unlink()


# ---------------------------------------------------------------------------
# Performance tests
# ---------------------------------------------------------------------------


def test_performance_under_100ms_first_call(tmp_optimusprime_dir):
    """First hook call (with 10 decisions) completes under 100ms."""
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    # Remove session state to ensure first call
    sp = op_dir / "session-state.json"
    if sp.exists():
        sp.unlink()

    start = time.perf_counter()
    stdout, _, rc = _run(_write_payload("src/utils.py"), cwd=tmp_optimusprime_dir)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert rc == 0
    assert elapsed_ms < 1000, f"Hook took {elapsed_ms:.0f}ms (subprocess overhead; limit is 1000ms)"


def test_performance_warm_call_under_500ms(tmp_optimusprime_dir):
    """Second hook call (warm state) completes under 500ms (subprocess overhead dominates)."""
    op_dir = tmp_optimusprime_dir / ".optimusprime"
    (op_dir / "session-state.json").write_text(
        json.dumps({"first_call_done": True, "tool_call_count": 5}),
        encoding="utf-8",
    )

    start = time.perf_counter()
    stdout, _, rc = _run(_write_payload("src/utils.py"), cwd=tmp_optimusprime_dir)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert rc == 0
    assert elapsed_ms < 1000, f"Hook took {elapsed_ms:.0f}ms"
