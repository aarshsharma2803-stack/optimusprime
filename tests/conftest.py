"""Shared pytest fixtures for OptimusPrime tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOKS_PRE = _REPO_ROOT / "hooks" / "pre"
_HOOKS_POST = _REPO_ROOT / "hooks" / "post"

# Sample data used across test suites
_SAMPLE_DECISIONS = """\
[2026-06-27T00:00:00Z] [agent:main] DECISION: chose atomic write for JSON safety — tmp+rename
[2026-06-27T00:00:01Z] [agent:main] DECISION: hooks use stdlib only — no pip deps per invariant 4
[2026-06-27T00:00:02Z] [agent:main] DECISION: find_optimusprime_dir walks up from cwd — never hardcoded
[2026-06-27T00:00:03Z] [agent:main] DECISION: exit 0 on any unexpected error — hooks never crash Claude
[2026-06-27T00:00:04Z] [agent:main] DECISION: loop detection threshold is 3 — balances sensitivity vs noise
[2026-06-27T00:00:05Z] [agent:main] DECISION: TF-IDF search with exact fallback — fast, no cloud deps
[2026-06-27T00:00:06Z] [agent:main] DECISION: session-snapshot.md under 200 token budget — fits in context
[2026-06-27T00:00:07Z] [agent:main] DECISION: FastMCP for MCP server — cleaner API, same wire protocol
[2026-06-27T00:00:08Z] [agent:main] DECISION: skills install to ~/.optimusprime/skills/ — OP controls path
[2026-06-27T00:00:09Z] [agent:main] DECISION: registry.json has 5 curated skills — quality over quantity
[2026-06-27T00:00:10Z] [agent:main] BLOCK: Write to 'secrets/key.pem' blocked — out-of-scope pattern
"""

_SAMPLE_ATTEMPTS = """\
[2026-06-27T10:00:00Z] [agent:main] FAILED: tool=Edit target=src/foo.py error=SyntaxError line 42
[2026-06-27T10:01:00Z] [agent:main] FAILED: tool=Bash target=python run.py error=ModuleNotFoundError
[2026-06-27T10:02:00Z] [agent:main] FAILED: tool=Edit target=hooks/pre/scope-guard.py error=IndentationError
"""

_SAMPLE_TODOS = """\
[2026-06-27T10:00:00Z] [agent:main] TODO src/optimusprime/utils.py:42 "handle symlink loops in find_optimusprime_dir"
[2026-06-27T10:01:00Z] [agent:main] FIXME hooks/pre/scope-guard.py:18 "glob matching is case-sensitive on Linux"
"""

_SAMPLE_SNAPSHOT = """\
# OPTIMUSPRIME SESSION SNAPSHOT
Generated: 2026-06-27T10:00:00Z | Session: abc12345 | Agent: main

## Goal
Build the OptimusPrime session state protocol

## Changed (3 files)
+ src/optimusprime/utils.py
+ hooks/pre/scope-guard.py
~ pyproject.toml

## Decisions (10 total)
- chose atomic write for JSON safety
- hooks use stdlib only

## Failed Attempts (0 total)
(none)

## Open TODOs (1)
- [ ] handle symlink loops in find_optimusprime_dir

## Next Action
Continue: Build the OptimusPrime session state protocol
"""

_SAMPLE_CONTRACT = {
    "version": "0.1.0",
    "goal": "Build the OptimusPrime session state protocol",
    "in_scope": ["src/**", "hooks/**", "tests/**", "mcp/**"],
    "out_of_scope": [".env", "secrets/**", "*.key", "node_modules/**", "*.pem"],
    "complexity_budget": "full",
    "agent_id": "main",
    "session_id": "test-session-abc12345",
    "created_at": "2026-06-27T00:00:00Z",
}


@pytest.fixture
def tmp_optimusprime_dir(tmp_path: Path) -> Path:
    """Create a temporary project root with a populated .optimusprime/ directory.

    Returns the project root (parent of .optimusprime/).
    Hooks find it via find_optimusprime_dir() when subprocess cwd=tmp_path.
    """
    op_dir = tmp_path / ".optimusprime"
    op_dir.mkdir()

    (op_dir / "contract.json").write_text(
        json.dumps(_SAMPLE_CONTRACT, indent=2), encoding="utf-8"
    )
    (op_dir / "decisions.md").write_text(_SAMPLE_DECISIONS, encoding="utf-8")
    (op_dir / "attempts.md").write_text(_SAMPLE_ATTEMPTS, encoding="utf-8")
    (op_dir / "todos.md").write_text(_SAMPLE_TODOS, encoding="utf-8")
    (op_dir / "session-snapshot.md").write_text(_SAMPLE_SNAPSHOT, encoding="utf-8")
    (op_dir / "resume.json").write_text(
        json.dumps({
            "version": "0.1.0",
            "session_id": "test-session-abc12345",
            "agent_id": "main",
            "goal": "Build the OptimusPrime session state protocol",
            "captured_at": "2026-06-27T10:00:00Z",
            "changed_files": ["+ src/optimusprime/utils.py"],
            "decision_count": 10,
            "recent_decisions": ["chose atomic write for JSON safety"],
            "attempt_count": 0,
            "recent_attempts": [],
            "open_todos": ["handle symlink loops"],
            "next_action": "Continue: Build the OptimusPrime session state protocol",
        }, indent=2),
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def op_dir(tmp_optimusprime_dir: Path) -> Path:
    """Return the .optimusprime/ subdirectory directly."""
    return tmp_optimusprime_dir / ".optimusprime"


def run_hook(
    hook_path: Path,
    stdin_data: Dict[str, Any],
    cwd: Path = None,
) -> Tuple[str, str, int]:
    """Run a hook script with JSON via stdin. Returns (stdout, stderr, exit_code)."""
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps(stdin_data),
        capture_output=True,
        text=True,
        cwd=str(cwd or _REPO_ROOT),
        timeout=15,
    )
    return result.stdout, result.stderr, result.returncode


@pytest.fixture
def run_hook_fn():
    """Fixture that exposes run_hook as a callable."""
    return run_hook


@pytest.fixture
def real_decisions_md() -> Path:
    """Points at the actual .optimusprime/decisions.md in this repository."""
    path = _REPO_ROOT / ".optimusprime" / "decisions.md"
    assert path.is_file(), f"Missing real decisions.md at {path}"
    return path


@pytest.fixture
def scope_guard():
    return _HOOKS_PRE / "scope-guard.py"


@pytest.fixture
def loop_detector():
    return _HOOKS_PRE / "loop-detector.py"


@pytest.fixture
def output_compressor():
    return _HOOKS_POST / "output-compressor.py"


@pytest.fixture
def session_logger():
    return _HOOKS_POST / "session-logger.py"


def make_pretooluse(tool_name: str, tool_input: dict, session_id: str = "test-session") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def make_posttooluse(tool_name: str, output: str, session_id: str = "test-session") -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": {},
        "tool_response": {"output": output},
    }


def make_stop(session_id: str = "test-session") -> dict:
    return {"hook_event_name": "Stop", "session_id": session_id}


def make_precompact(session_id: str = "test-session") -> dict:
    return {"hook_event_name": "PreCompact", "session_id": session_id}
