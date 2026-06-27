#!/usr/bin/env python3
"""PreToolUse hook: blocks repeated identical failures (loop detection).

Reads .optimusprime/loop-state.json written by attempt-logger.py (PostToolUse).
Blocks after 3 consecutive near-identical failures for the same action.
Clears when any tool call succeeds (handled by attempt-logger.py).

loop-state.json schema (written by attempt-logger.py):
{
  "session_id": "<uuid>",
  "consecutive_failures": [
    {
      "tool": "Edit",
      "target": "src/foo.py",
      "error": "SyntaxError on line 42",
      "sig": "<sha256[:16]>",
      "timestamp": "<iso8601>"
    }
  ]
}
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

from optimusprime.utils import (
    append_block,
    find_optimusprime_dir,
    load_json,
)

_LOOP_STATE_FILE = "loop-state.json"
_FAILURE_THRESHOLD = 3
_SIMILARITY_THRESHOLD = 0.80


def _target_of(tool_name: str, tool_input: dict) -> str:
    """Canonical target string for the current tool call."""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        # Use first 60 chars as identity — avoids noise from long commands
        return cmd[:60]
    return tool_input.get("file_path", "") or tool_input.get("notebook_path", "")


def _similar(a: str, b: str) -> bool:
    if not a or not b:
        return a == b
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= _SIMILARITY_THRESHOLD


def _count_matching_tail(failures: list[dict], tool: str, target: str) -> tuple[int, str]:
    """Count consecutive tail entries matching (tool, near-identical target, near-identical error).

    Returns (count, latest_error).
    Resets if any non-matching entry is found working backwards.
    """
    count = 0
    latest_error = ""
    errors_seen: list[str] = []

    for entry in reversed(failures):
        if entry.get("tool") != tool:
            break
        if not _similar(entry.get("target", ""), target):
            break

        err = entry.get("error", "")
        # First entry anchors the error signature
        if not errors_seen:
            errors_seen.append(err)
            latest_error = err
            count += 1
            continue

        # Subsequent entries must be near-identical to the anchor error
        if _similar(err, errors_seen[0]):
            count += 1
        else:
            break

    return count, latest_error


def _block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": f"OPTIMUSPRIME: {reason}"}))
    print(f"OPTIMUSPRIME BLOCK: {reason}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        payload = json.loads(raw)
        session_id: str = payload.get("session_id", "")
        tool_name: str = payload.get("tool_name", "")
        tool_input: dict = payload.get("tool_input", {})

        op_dir = find_optimusprime_dir()
        if op_dir is None:
            sys.exit(0)

        state_path = op_dir / _LOOP_STATE_FILE
        state = load_json(state_path)
        if not state:
            sys.exit(0)

        # Ignore state from a different session
        if state.get("session_id") and session_id and state["session_id"] != session_id:
            sys.exit(0)

        failures: list[dict] = state.get("consecutive_failures", [])
        if len(failures) < _FAILURE_THRESHOLD:
            sys.exit(0)

        target = _target_of(tool_name, tool_input)
        count, latest_error = _count_matching_tail(failures, tool_name, target)

        if count >= _FAILURE_THRESHOLD:
            reason = (
                f"Loop detected — same failure {count} times in a row "
                f"(tool={tool_name}, target='{target[:50]}'). "
                f"Last error: {latest_error[:60]}. "
                "Stop and ask the user."
            )
            agent_id = "main"
            append_block(op_dir, reason, agent_id)
            _block(reason)

        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
