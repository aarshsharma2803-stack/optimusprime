#!/usr/bin/env python3
"""PreToolUse hook: blocks failure loops with no measurable progress.

Reads .optimusprime/loop-state.json written by attempt-logger.py (PostToolUse).
Blocks after 3 consecutive failures with no measurable progress.
Progress = new error elements introduced between consecutive failures.
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
  ],
  "consecutive_no_progress": 0,
  "progress_detected": true
}
"""

from __future__ import annotations

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

from optimusprime.utils import (
    append_block,
    find_optimusprime_dir,
    load_json,
    write_json_safe,
)

_LOOP_STATE_FILE = "loop-state.json"
_FAILURE_THRESHOLD = 5
_TARGET_SIM_THRESHOLD = 0.80
# Errors with similarity > this AND ≤ 1 new word = no progress
_NO_PROGRESS_SIM = 0.90
_MAX_NEW_WORDS_NO_PROGRESS = 1
# Errors with similarity < this AND many new words = regressing (different failures piling up)
_REGRESSION_SIM = 0.50
_MIN_NEW_WORDS_REGRESSION = 3


def _target_of(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        return tool_input.get("command", "")[:60]
    return tool_input.get("file_path", "") or tool_input.get("notebook_path", "")


def _similar_target(a: str, b: str) -> bool:
    if not a or not b:
        return a == b
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= _TARGET_SIM_THRESHOLD


def _error_words(err: str) -> set[str]:
    return set(re.findall(r'\w{3,}', err.lower()))


def _analyze_failure_tail(
    failures: list[dict], tool: str, target: str
) -> tuple[int, str, str]:
    """
    Walk backwards through failures for this (tool, target).
    Returns (consecutive_no_progress, message_type, latest_error).
    message_type: "no_progress" | "regressing" | ""
    """
    # Collect relevant failures in order (oldest→newest)
    relevant: list[str] = []
    for entry in reversed(failures):
        if entry.get("tool") != tool:
            break
        if not _similar_target(entry.get("target", ""), target):
            break
        relevant.append(entry.get("error", ""))
    if len(relevant) < _FAILURE_THRESHOLD:
        return 0, "", relevant[0] if relevant else ""

    relevant.reverse()  # oldest first
    latest = relevant[-1]

    consecutive_no_progress = 0
    for i in range(len(relevant) - 1, 0, -1):
        e_new = relevant[i]
        e_old = relevant[i - 1]
        sim = SequenceMatcher(None, e_old.lower(), e_new.lower()).ratio()
        words_new = _error_words(e_new) - _error_words(e_old)
        if sim >= _NO_PROGRESS_SIM and len(words_new) <= _MAX_NEW_WORDS_NO_PROGRESS:
            # Near-identical error — no progress
            consecutive_no_progress += 1
        else:
            # Different error content = progress; stop counting
            break

    # _FAILURE_THRESHOLD-1 no-progress pairs = _FAILURE_THRESHOLD stuck failures
    if consecutive_no_progress < _FAILURE_THRESHOLD - 1:
        return 0, "", latest

    return len(relevant), "no_progress", latest


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

        if state.get("session_id") and session_id and state["session_id"] != session_id:
            sys.exit(0)

        failures: list[dict] = state.get("consecutive_failures", [])
        if len(failures) < _FAILURE_THRESHOLD:
            sys.exit(0)

        target = _target_of(tool_name, tool_input)
        count, msg_type, latest_error = _analyze_failure_tail(failures, tool_name, target)

        if count >= _FAILURE_THRESHOLD:
            # Update loop-state.json with progress tracking fields
            try:
                state["consecutive_no_progress"] = count
                state["progress_detected"] = False
                write_json_safe(state_path, state)
            except Exception:
                pass

            reason = (
                f"Loop detected: no progress in {count} attempts "
                f"(tool={tool_name}, target='{target[:50]}'). "
                f"Last error: {latest_error[:60]}. "
                "Stop and ask the user."
            )
            append_block(op_dir, reason, "main")
            _block(reason)

        # Record that progress was detected (or no loop yet)
        try:
            state["consecutive_no_progress"] = count
            state["progress_detected"] = count < _FAILURE_THRESHOLD
            write_json_safe(state_path, state)
        except Exception:
            pass

        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
