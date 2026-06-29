#!/usr/bin/env python3
"""Stop / SubagentStop / PreCompact hook: writes session bridge files.

Writes:
  .optimusprime/session-snapshot.md  — human-readable, ~200 token budget
  .optimusprime/resume.json          — structured, for programmatic use

On PreCompact: also injects snapshot as additionalContext so it survives
compaction and the next context window starts with full session state.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

from optimusprime.utils import (
    append_event,
    find_optimusprime_dir,
    load_contract,
    utcnow_iso,
    write_json_safe,
)

_GIT_TIMEOUT = 10
_MAX_DECISIONS_SHOWN = 8
_MAX_ATTEMPTS_SHOWN = 5
_MAX_TODOS_SHOWN = 6


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------


def _git_changed_files(project_root: Path) -> list[tuple[str, str]]:
    """Return list of (status, filepath). status: + created, ~ modified, - deleted."""
    for ref in ("HEAD", "--cached"):
        try:
            result = subprocess.run(
                ["git", "diff", ref, "--name-status", "--diff-filter=d"],
                capture_output=True, text=True,
                timeout=_GIT_TIMEOUT, cwd=str(project_root),
            )
            if result.returncode == 0:
                items = []
                for line in result.stdout.splitlines():
                    parts = line.split("\t", 1)
                    if len(parts) == 2:
                        status_char = parts[0].strip()[:1]
                        filepath = parts[1].strip()
                        symbol = {"A": "+", "M": "~", "D": "-", "R": "→"}.get(status_char, "?")
                        items.append((symbol, filepath))
                return items
        except Exception:
            continue
    return []


def _read_tail(path: Path, n: int) -> list[str]:
    """Return last n non-empty lines from a text file. [] on any error."""
    try:
        if not path.exists():
            return []
        lines = [l.rstrip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return lines[-n:]
    except Exception:
        return []


def _count_lines(path: Path) -> int:
    try:
        if not path.exists():
            return 0
        return sum(1 for l in path.read_text(encoding="utf-8").splitlines() if l.strip())
    except Exception:
        return 0


def _parse_decisions(lines: list[str]) -> list[str]:
    """Extract body text from DECISION: lines."""
    result = []
    for line in lines:
        m = re.search(r"DECISION:\s*(.+)$", line)
        if m:
            body = m.group(1).strip()
            result.append(body[:90])
    return result


def _parse_attempts(lines: list[str]) -> list[str]:
    """Extract short summary from FAIL lines."""
    result = []
    for line in lines:
        m = re.search(r"FAIL\s+(.+)$", line)
        if m:
            result.append(m.group(1).strip()[:90])
    return result


def _parse_todos(lines: list[str]) -> list[str]:
    """Extract unresolved TODO entries."""
    result = []
    for line in lines:
        if re.search(r"\[deferred", line, re.IGNORECASE):
            continue
        m = re.search(r"(?:TODO|FIXME|HACK|XXX)\s+(.+)$", line, re.IGNORECASE)
        if m:
            result.append(m.group(1).strip()[:90])
    return result


def _infer_next_action(
    decisions: list[str],
    todos: list[str],
    contract: dict,
) -> str:
    """Best-effort next action from available data."""
    if todos:
        return f"Resolve TODO: {todos[0]}"
    if decisions:
        last = decisions[-1]
        if "session" in last.lower() or "next" in last.lower() or "build" in last.lower():
            return last
    goal = contract.get("goal", "")
    if goal:
        return f"Continue: {goal[:80]}"
    return "Review session snapshot and plan next steps."


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _write_snapshot(
    op_dir: Path,
    contract: dict,
    changed: list[tuple[str, str]],
    decisions: list[str],
    decision_count: int,
    attempts: list[str],
    attempt_count: int,
    todos: list[str],
    session_id: str,
    timestamp: str,
) -> str:
    """Build and write session-snapshot.md. Returns the snapshot text."""
    agent_id = contract.get("agent_id", "main")
    goal = contract.get("goal", "(no goal in contract — paste your goal here)")

    next_action = _infer_next_action(decisions, todos, contract)

    lines: list[str] = [
        "# OPTIMUSPRIME SESSION SNAPSHOT",
        f"Generated: {timestamp} | Session: {session_id[:8]} | Agent: {agent_id}",
        "",
        "## Goal",
        goal,
        "",
    ]

    # Changed files
    if changed:
        lines.append(f"## Changed ({len(changed)} file{'s' if len(changed) != 1 else ''})")
        for symbol, filepath in changed[:12]:
            lines.append(f"{symbol} {filepath}")
        if len(changed) > 12:
            lines.append(f"... and {len(changed) - 12} more")
    else:
        lines.append("## Changed")
        lines.append("(no tracked file changes)")
    lines.append("")

    # Decisions
    lines.append(f"## Decisions ({decision_count} total)")
    if decisions:
        for d in decisions[-_MAX_DECISIONS_SHOWN:]:
            lines.append(f"- {d}")
        if decision_count > _MAX_DECISIONS_SHOWN:
            lines.append(f"[see .optimusprime/decisions.md for all {decision_count}]")
    else:
        lines.append("(none logged)")
    lines.append("")

    # Failed attempts
    lines.append(f"## Failed Attempts ({attempt_count} total)")
    if attempts:
        for a in attempts[-_MAX_ATTEMPTS_SHOWN:]:
            lines.append(f"- {a}")
    else:
        lines.append("(none)")
    lines.append("")

    # Open TODOs
    lines.append(f"## Open TODOs ({len(todos)})")
    if todos:
        for t in todos[:_MAX_TODOS_SHOWN]:
            lines.append(f"- [ ] {t}")
        if len(todos) > _MAX_TODOS_SHOWN:
            lines.append(f"... and {len(todos) - _MAX_TODOS_SHOWN} more")
    else:
        lines.append("(none)")
    lines.append("")

    # Next action
    lines.append("## Next Action")
    lines.append(next_action)

    snapshot_text = "\n".join(lines)
    snapshot_path = op_dir / "session-snapshot.md"
    try:
        snapshot_path.write_text(snapshot_text, encoding="utf-8")
    except Exception:
        pass

    return snapshot_text


def _write_resume(
    op_dir: Path,
    contract: dict,
    changed: list[tuple[str, str]],
    decision_count: int,
    decisions: list[str],
    attempt_count: int,
    attempts: list[str],
    todos: list[str],
    session_id: str,
    timestamp: str,
) -> None:
    resume = {
        "version": "0.1.0",
        "session_id": session_id,
        "agent_id": contract.get("agent_id", "main"),
        "goal": contract.get("goal", ""),
        "captured_at": timestamp,
        "changed_files": [f"{s} {p}" for s, p in changed],
        "decision_count": decision_count,
        "recent_decisions": decisions[-10:],
        "attempt_count": attempt_count,
        "recent_attempts": attempts[-5:],
        "open_todos": todos,
        "next_action": _infer_next_action(decisions, todos, contract),
    }
    write_json_safe(op_dir / "resume.json", resume)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        payload = json.loads(raw)
        event = payload.get("hook_event_name", "")
        if event not in ("Stop", "SubagentStop", "PreCompact", ""):
            sys.exit(0)

        session_id: str = payload.get("session_id", "unknown")
        timestamp = utcnow_iso()

        op_dir = find_optimusprime_dir()
        if op_dir is None:
            sys.exit(0)

        project_root = op_dir.parent
        contract = load_contract(op_dir)

        # Gather data
        changed = _git_changed_files(project_root)

        decision_lines = _read_tail(op_dir / "decisions.md", 50)
        decision_count = _count_lines(op_dir / "decisions.md")
        decisions = _parse_decisions(decision_lines)

        attempt_lines = _read_tail(op_dir / "attempts.md", 20)
        attempt_count = _count_lines(op_dir / "attempts.md")
        attempts = _parse_attempts(attempt_lines)

        todo_lines = _read_tail(op_dir / "todos.md", 20)
        todos = _parse_todos(todo_lines)

        # Write files
        snapshot_text = _write_snapshot(
            op_dir, contract, changed,
            decisions, decision_count,
            attempts, attempt_count,
            todos, session_id, timestamp,
        )
        _write_resume(
            op_dir, contract, changed,
            decision_count, decisions,
            attempt_count, attempts,
            todos, session_id, timestamp,
        )

        # On PreCompact: inject snapshot as context so it survives compaction
        if event == "PreCompact":
            print(json.dumps({
                "additionalContext": (
                    "OPTIMUSPRIME: Session snapshot written before compaction. "
                    "Paste the content below into a new session to restore context:\n\n"
                    + snapshot_text
                )
            }))

        # Reset session-state.json so the next session gets first-call context injection
        if event in ("Stop", "SubagentStop"):
            write_json_safe(op_dir / "session-state.json", {
                "first_call_done": False,
                "tool_call_count": 0,
                "session_end": timestamp,
            })
            append_event(op_dir, "Stop", tool="", file="", action="session-end")

        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
