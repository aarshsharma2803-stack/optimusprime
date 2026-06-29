#!/usr/bin/env python3
"""PostToolUse hook: logs failed tool calls to .optimusprime/attempts.md.

Also maintains .optimusprime/loop-state.json for loop-detector.py:
  - On failure: append to consecutive_failures
  - On success: clear consecutive_failures (reset loop state)

Line format in attempts.md:
  [timestamp] TOOL: X | TARGET: Y | ERROR: Z  (120 char max)
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

from optimusprime.utils import (
    append_event,
    append_to_file,
    find_optimusprime_dir,
    load_json,
    utcnow_iso,
    write_json_safe,
)

_LOOP_STATE_FILE = "loop-state.json"
_ATTEMPTS_FILE = "attempts.md"
_MAX_CONSECUTIVE = 10  # cap list size


def _target(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        return tool_input.get("command", "")[:60]
    return tool_input.get("file_path", "") or tool_input.get("notebook_path", "")


def _first_error_line(tool_response: dict) -> str:
    """Extract shortest useful error string from tool response."""
    out = tool_response.get("output", "") or tool_response.get("stderr", "")
    if isinstance(out, list):
        out = " ".join(block.get("text", "") for block in out if isinstance(block, dict))
    for line in str(out).splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return "unknown error"


def _is_failure(tool_response: dict) -> bool:
    """Return True if the tool call failed."""
    if tool_response.get("is_error") is True:
        return True
    # Bash: Claude Code surfaces non-zero exit as is_error=True but check output too
    output = str(tool_response.get("output", ""))
    if any(
        output.lstrip().startswith(prefix)
        for prefix in ("Error:", "error:", "Traceback", "FAILED", "fatal:")
    ):
        return True
    return False


def _sig(tool_name: str, target_str: str, error: str) -> str:
    """Short hash for loop-detection grouping."""
    raw = f"{tool_name}:{target_str}:{error[:40]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _update_loop_state(
    op_dir: Path,
    session_id: str,
    tool_name: str,
    target_str: str,
    error: str,
    *,
    failed: bool,
) -> None:
    """Update loop-state.json based on success/failure of this tool call."""
    state_path = op_dir / _LOOP_STATE_FILE
    state = load_json(state_path)

    # Reset if different session
    if state.get("session_id") and state["session_id"] != session_id:
        state = {}

    if not failed:
        # Success → clear consecutive failures (loop broken)
        if state.get("consecutive_failures"):
            write_json_safe(state_path, {
                "session_id": session_id,
                "consecutive_failures": [],
            })
        return

    failures: list[dict] = list(state.get("consecutive_failures", []))
    failures.append({
        "tool": tool_name,
        "target": target_str,
        "error": error,
        "sig": _sig(tool_name, target_str, error),
        "timestamp": utcnow_iso(),
    })
    # Cap to avoid unbounded growth
    if len(failures) > _MAX_CONSECUTIVE:
        failures = failures[-_MAX_CONSECUTIVE:]

    write_json_safe(state_path, {
        "session_id": session_id,
        "consecutive_failures": failures,
    })


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        payload = json.loads(raw)

        if payload.get("hook_event_name") not in ("PostToolUse", None, ""):
            sys.exit(0)

        session_id: str = payload.get("session_id", "unknown")
        tool_name: str = payload.get("tool_name", "")
        tool_input: dict = payload.get("tool_input", {})
        tool_response: dict = payload.get("tool_response", {})
        if isinstance(tool_response, str):
            tool_response = {"output": tool_response}

        failed = _is_failure(tool_response)
        target_str = _target(tool_name, tool_input)

        op_dir = find_optimusprime_dir()
        if op_dir is None:
            sys.exit(0)

        if failed:
            error = _first_error_line(tool_response)
            # Log to attempts.md
            body = f"TOOL: {tool_name} | TARGET: {target_str[:40]} | ERROR: {error}"
            append_to_file(
                op_dir / _ATTEMPTS_FILE,
                prefix="FAIL",
                body=body,
                session_id=session_id,
            )
            append_event(op_dir, "PostToolUse", tool=tool_name, file=target_str, action="failed")

        # Always update loop state (success clears, failure appends)
        _update_loop_state(
            op_dir, session_id, tool_name, target_str,
            _first_error_line(tool_response) if failed else "",
            failed=failed,
        )

        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
