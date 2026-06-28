#!/usr/bin/env python3
"""PostToolUse hook: maintains .optimusprime/task-state.md in real time.

Updated after every significant tool call (Write/Edit/MultiEdit/Bash/Task).
Skips: Read, Glob, LS, WebFetch — those are not significant.
Injects task state summary as additionalContext.
Exit 0 always — never blocks.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

# Tools that are significant (state-changing or meaningful)
_SIGNIFICANT_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "Bash", "Task"})
# Tools to skip (read-only observation)
_SKIP_TOOLS = frozenset({"Read", "Glob", "LS", "WebFetch", "WebSearch", "Grep"})

_STATE_FILE = "task-state.md"


def main() -> None:
    try:
        _run()
    except Exception:
        sys.exit(0)


def _run() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = payload.get("tool_name", "")
    if tool_name in _SKIP_TOOLS or tool_name not in _SIGNIFICANT_TOOLS:
        sys.exit(0)

    tool_input = payload.get("tool_input", {})
    session_id = payload.get("session_id", "")

    from optimusprime.utils import find_optimusprime_dir, load_contract, utcnow_iso
    op_dir = find_optimusprime_dir()
    if op_dir is None:
        sys.exit(0)

    # ---- Load existing task-state.md ----------------------------------------
    state_path = op_dir / _STATE_FILE
    existing = _load_state(state_path)

    now = utcnow_iso()

    # ---- Determine what was just done ---------------------------------------
    what_done = _describe_action(tool_name, tool_input)
    file_path = _extract_file_path(tool_name, tool_input)

    # ---- Increment call count -----------------------------------------------
    call_count = existing.get("tool_call_count", 0) + 1

    # ---- Update completed subtasks list -------------------------------------
    completed = existing.get("completed_subtasks", [])
    if file_path and file_path not in [c.get("file", "") for c in completed]:
        completed.append({"file": file_path, "action": what_done, "ts": now[:10]})
    # Keep max 10 entries
    completed = completed[-10:]

    # ---- Load contract for goal + constraints --------------------------------
    contract = load_contract(op_dir)
    goal = contract.get("goal", "")[:80] or existing.get("goal", "unknown goal")
    complexity = contract.get("complexity_budget", "")
    out_of_scope = contract.get("out_of_scope_files", [])[:3]

    # ---- Load last 3 decisions ----------------------------------------------
    decisions_tail = _read_tail(op_dir / "decisions.md", n=3)

    # ---- Load open TODOs ---------------------------------------------------
    todos_tail = _read_tail(op_dir / "todos.md", n=3)
    todo_count = _count_lines(op_dir / "todos.md")

    # ---- Infer current step -----------------------------------------------
    action_phase = _action_phase(tool_name, call_count)

    # ---- Build task-state.md content ----------------------------------------
    started = existing.get("started", now)
    if not session_id:
        session_id = existing.get("session_id", now[:16].replace(":", "").replace("-", ""))

    content = _build_markdown(
        session_id=session_id,
        goal=goal,
        started=started,
        last_updated=now,
        tool_call_count=call_count,
        current_step=action_phase,
        what_was_just_done=what_done,
        complexity=complexity,
        out_of_scope=out_of_scope,
        completed_subtasks=completed,
        todo_count=todo_count,
        todos_tail=todos_tail,
        decisions_tail=decisions_tail,
    )

    # ---- Write atomically ---------------------------------------------------
    try:
        tmp = op_dir / f".task-state.tmp.{os.getpid()}"
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(state_path)
    except Exception:
        pass

    # ---- Build additionalContext (injected only after first call) -----------
    if call_count <= 1:
        sys.exit(0)

    ctx_lines = [
        f"TASK STATE (call {call_count}):",
        f"Goal: {goal[:60]}",
        f"Just did: {what_done[:60]}",
        f"Files touched: {len(completed)} file(s)",
        f"Open TODOs: {todo_count}",
    ]
    if decisions_tail:
        last = decisions_tail[-1].strip()
        if last:
            ctx_lines.append(f"Last decision: {last[:80]}")

    context = "\n".join(ctx_lines)
    print(json.dumps({"additionalContext": context}))
    sys.exit(0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_state(path: Path) -> dict:
    """Load existing task-state.md into a dict of key fields."""
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        state: dict = {}
        # Extract YAML-ish frontmatter
        fm_match = re.search(r"^---\n(.*?)\n---", text, re.DOTALL)
        if fm_match:
            for line in fm_match.group(1).splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    state[k.strip()] = v.strip()

        # Extract completed_subtasks from ## Completed Subtasks section
        ct_match = re.search(r"## Completed Subtasks\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
        if ct_match:
            entries = []
            for line in ct_match.group(1).splitlines():
                m = re.match(r"- (.+): (.+) \[(.+)\]", line.strip())
                if m:
                    entries.append({"file": m.group(1), "action": m.group(2), "ts": m.group(3)})
            state["completed_subtasks"] = entries

        try:
            state["tool_call_count"] = int(state.get("tool_call_count", 0))
        except (ValueError, TypeError):
            state["tool_call_count"] = 0

        return state
    except Exception:
        return {}


def _describe_action(tool_name: str, tool_input: dict) -> str:
    if tool_name in ("Write", "Edit", "MultiEdit"):
        fp = _extract_file_path(tool_name, tool_input)
        return f"{tool_name} on {fp}"
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")[:60]
        return f"ran: {cmd}"
    elif tool_name == "Task":
        desc = tool_input.get("description", "")[:60]
        return f"subtask: {desc}"
    return f"{tool_name}"


def _extract_file_path(tool_name: str, tool_input: dict) -> str:
    if tool_name in ("Write", "Edit"):
        return tool_input.get("file_path", "")
    elif tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
        if edits and isinstance(edits, list):
            return edits[0].get("file_path", "") if isinstance(edits[0], dict) else ""
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        m = re.search(r"[\w./]+\.[a-z]{2,5}", cmd)
        return m.group(0) if m else ""
    return ""


def _action_phase(tool_name: str, call_count: int) -> str:
    if tool_name in ("Write", "Edit", "MultiEdit"):
        return f"Step {call_count}: writing/editing files"
    elif tool_name == "Bash":
        return f"Step {call_count}: running commands"
    elif tool_name == "Task":
        return f"Step {call_count}: executing subtask"
    return f"Step {call_count}: {tool_name}"


def _read_tail(path: Path, n: int = 3) -> list[str]:
    """Return last n non-empty lines of a file."""
    if not path.is_file():
        return []
    try:
        lines = [
            l.strip() for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        return lines[-n:]
    except Exception:
        return []


def _count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        return sum(1 for l in path.read_text(encoding="utf-8").splitlines() if l.strip())
    except Exception:
        return 0


def _build_markdown(
    *,
    session_id: str,
    goal: str,
    started: str,
    last_updated: str,
    tool_call_count: int,
    current_step: str,
    what_was_just_done: str,
    complexity: str,
    out_of_scope: list,
    completed_subtasks: list,
    todo_count: int,
    todos_tail: list,
    decisions_tail: list,
) -> str:
    lines = [
        "---",
        f"session_id: {session_id}",
        f"goal: {goal}",
        f"started: {started}",
        f"last_updated: {last_updated}",
        f"tool_call_count: {tool_call_count}",
        "---",
        "",
        "## Current Step",
        current_step,
        "",
        "## What Was Just Done",
        what_was_just_done,
        "",
        "## Active Constraints",
    ]
    if complexity:
        lines.append(f"- Complexity budget: {complexity}")
    if out_of_scope:
        lines.append(f"- Out of scope: {', '.join(str(p) for p in out_of_scope)}")
    if not complexity and not out_of_scope:
        lines.append("- None recorded")

    lines.extend(["", "## Completed Subtasks"])
    if completed_subtasks:
        for entry in completed_subtasks:
            lines.append(f"- {entry['file']}: {entry['action']} [{entry['ts']}]")
    else:
        lines.append("- (none yet)")

    lines.extend(["", "## Open Items"])
    if todos_tail:
        for t in todos_tail:
            lines.append(f"- {t[:100]}")
    else:
        lines.append(f"- {todo_count} open TODOs" if todo_count else "- None")

    lines.extend(["", "## Reasoning Chain (last 3 decisions)"])
    if decisions_tail:
        for d in decisions_tail:
            lines.append(f"- {d[:120]}")
    else:
        lines.append("- (no decisions yet)")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
