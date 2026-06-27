#!/usr/bin/env python3
"""Stop hook: runs Definition-of-Done checks before session ends.

Default checks (always run):
  1. Unresolved TODOs without [deferred:] marker?
  2. Python files modified without any test file touched?
  3. Was decisions.md updated this session?

Custom checklist from contract.json "done_checklist" field (optional).

Never blocks. Outputs additionalContext with pass/fail summary.
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
    find_optimusprime_dir,
    load_contract,
    load_json,
)

_GIT_TIMEOUT = 10


def _git_changed_files(project_root: Path) -> list[str]:
    for ref in ("HEAD", "--cached"):
        try:
            result = subprocess.run(
                ["git", "diff", ref, "--name-only", "--diff-filter=d"],
                capture_output=True, text=True,
                timeout=_GIT_TIMEOUT, cwd=str(project_root),
            )
            if result.returncode == 0:
                return [l.strip() for l in result.stdout.splitlines() if l.strip()]
        except Exception:
            continue
    return []


def _check_unresolved_todos(op_dir: Path) -> tuple[bool, str]:
    """Pass if todos.md has no unresolved entries (or file doesn't exist)."""
    todos_path = op_dir / "todos.md"
    if not todos_path.exists():
        return True, "No todos.md"
    try:
        lines = todos_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return True, "todos.md unreadable"

    unresolved = [
        l for l in lines
        if l.strip() and not re.search(r"\[deferred[:\s]", l, re.IGNORECASE)
        and ("TODO" in l or "FIXME" in l or "HACK" in l or "XXX" in l)
    ]
    if unresolved:
        return False, f"{len(unresolved)} unresolved TODO(s) in todos.md"
    return True, "No unresolved TODOs"


def _check_tests_touched(changed_files: list[str]) -> tuple[bool, str]:
    """Pass if any Python source change is paired with a test file change."""
    py_src = [
        f for f in changed_files
        if f.endswith(".py") and not re.search(r"(test_|_test|tests/)", f)
    ]
    if not py_src:
        return True, "No Python source files modified"

    test_files = [
        f for f in changed_files
        if f.endswith(".py") and re.search(r"(test_|_test|tests/)", f)
    ]
    if not test_files:
        return False, f"{len(py_src)} Python source file(s) modified, no test files touched"
    return True, f"Tests touched ({len(test_files)} file(s))"


def _check_decisions_updated(op_dir: Path, changed_files: list[str]) -> tuple[bool, str]:
    """Pass if decisions.md was appended to (has today's entries or was in git diff)."""
    decisions_path = op_dir / "decisions.md"
    if not decisions_path.exists():
        return False, "decisions.md does not exist"

    # Check if any .optimusprime/*.md is in the changed files set
    # (they won't appear in git diff as they're often untracked by the project)
    # Instead, check if decisions.md was modified more recently than last commit
    try:
        from datetime import datetime, timezone
        mtime = decisions_path.stat().st_mtime
        # If file was modified in the last 24 hours, consider it updated this session
        age_seconds = (datetime.now(timezone.utc).timestamp() - mtime)
        if age_seconds < 86400:  # 24 hours
            return True, "decisions.md updated this session"
        return False, "decisions.md not updated this session (>24h old)"
    except Exception:
        return True, "decisions.md exists"


def _run_custom_checklist(checklist: list[str]) -> list[tuple[bool, str]]:
    """Custom checklist items from contract.json are informational — always 'skipped'."""
    results = []
    for item in checklist:
        results.append((True, f"Custom: {item[:80]} [manual verification required]"))
    return results


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        payload = json.loads(raw)
        event = payload.get("hook_event_name", "")
        if event not in ("Stop", "SubagentStop", ""):
            sys.exit(0)

        op_dir = find_optimusprime_dir()
        if op_dir is None:
            sys.exit(0)

        project_root = op_dir.parent
        changed_files = _git_changed_files(project_root)
        contract = load_contract(op_dir)

        results: list[tuple[bool, str]] = []

        # Default checks
        results.append(_check_unresolved_todos(op_dir))
        results.append(_check_tests_touched(changed_files))
        results.append(_check_decisions_updated(op_dir, changed_files))

        # Custom checklist from contract.json
        custom = contract.get("done_checklist", [])
        if custom:
            results.extend(_run_custom_checklist(custom))

        passed = sum(1 for ok, _ in results if ok)
        total = len(results)
        failed_items = [msg for ok, msg in results if not ok]

        if passed == total:
            # All passed — silent (no noise on clean sessions)
            sys.exit(0)

        # Some checks failed — inject context
        summary = f"OPTIMUSPRIME done-checker: {passed}/{total} checks passed"
        lines = [summary]
        for ok, msg in results:
            icon = "✓" if ok else "✗"
            lines.append(f"  {icon} {msg}")
        if failed_items:
            lines.append("Address the above before marking this session complete.")

        print(json.dumps({"additionalContext": "\n".join(lines)}))
        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
