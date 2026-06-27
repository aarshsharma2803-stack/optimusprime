#!/usr/bin/env python3
"""Stop hook: scans git diff for newly added TODO/FIXME/HACK/XXX comments.

Writes findings to .optimusprime/todos.md.
Outputs additionalContext summary when new TODOs found.
Exit 0 silently when none found.
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
    append_to_file,
    find_optimusprime_dir,
    utcnow_iso,
)

_TODO_PATTERN = re.compile(
    r"\b(TODO|FIXME|HACK|XXX)\b[:\s]*(.*)",
    re.IGNORECASE,
)
# Files we care about scanning
_SCAN_EXTENSIONS = {".py", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java", ".c", ".cpp", ".h"}
_GIT_TIMEOUT = 10


def _git_diff_added_lines(project_root: Path) -> list[tuple[str, int, str]]:
    """Run git diff HEAD, return list of (filepath, approx_lineno, line_text) for added lines.

    Falls back to git diff --cached if HEAD doesn't exist (initial commit scenario).
    Returns [] on any error.
    """
    for ref in ("HEAD", "--cached"):
        try:
            result = subprocess.run(
                ["git", "diff", ref, "--unified=0", "--diff-filter=d"],
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
                cwd=str(project_root),
            )
            if result.returncode == 0:
                return _parse_diff(result.stdout)
        except Exception:
            continue
    return []


def _parse_diff(diff_text: str) -> list[tuple[str, int, str]]:
    """Parse unified diff output. Returns (filepath, lineno, line_text) for added lines."""
    results: list[tuple[str, int, str]] = []
    current_file = ""
    current_lineno = 0

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            current_lineno = 0
        elif line.startswith("@@ "):
            # @@ -a,b +c,d @@
            m = re.search(r"\+(\d+)", line)
            if m:
                current_lineno = int(m.group(1)) - 1
        elif line.startswith("+") and not line.startswith("+++"):
            current_lineno += 1
            ext = Path(current_file).suffix.lower()
            if ext in _SCAN_EXTENSIONS:
                results.append((current_file, current_lineno, line[1:]))
        elif line.startswith(" "):
            current_lineno += 1
        # Lines starting with "-" don't advance the new-file line number

    return results


def _extract_todos(
    added_lines: list[tuple[str, int, str]],
) -> list[tuple[str, int, str, str]]:
    """Filter added_lines to those containing TODO/FIXME/HACK/XXX.

    Returns list of (filepath, lineno, tag, description).
    """
    found: list[tuple[str, int, str, str]] = []
    for filepath, lineno, text in added_lines:
        m = _TODO_PATTERN.search(text)
        if m:
            tag = m.group(1).upper()
            desc = m.group(2).strip()[:80]
            found.append((filepath, lineno, tag, desc))
    return found


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        payload = json.loads(raw)
        event = payload.get("hook_event_name", "")
        if event not in ("Stop", "SubagentStop", ""):
            sys.exit(0)

        session_id: str = payload.get("session_id", "unknown")

        op_dir = find_optimusprime_dir()
        if op_dir is None:
            sys.exit(0)

        project_root = op_dir.parent
        added_lines = _git_diff_added_lines(project_root)
        if not added_lines:
            sys.exit(0)

        todos = _extract_todos(added_lines)
        if not todos:
            sys.exit(0)

        # Write to todos.md
        todos_path = op_dir / "todos.md"
        timestamp = utcnow_iso()
        for filepath, lineno, tag, desc in todos:
            body = f"{tag} {filepath}:{lineno} \"{desc}\""
            append_to_file(
                todos_path,
                prefix=tag,
                body=f"{filepath}:{lineno} \"{desc}\"",
                session_id=session_id,
            )

        # Output summary
        summary_lines = [
            f"OPTIMUSPRIME todo-scanner: {len(todos)} new {_tag_str(todos)} added this session",
            "See .optimusprime/todos.md — resolve or mark [deferred: reason] before next Stop.",
        ]
        for filepath, lineno, tag, desc in todos[:8]:
            summary_lines.append(f"  [{tag}] {filepath}:{lineno} — {desc[:60]}")
        if len(todos) > 8:
            summary_lines.append(f"  ... and {len(todos) - 8} more")

        print(json.dumps({"additionalContext": "\n".join(summary_lines)}))
        sys.exit(0)

    except Exception:
        sys.exit(0)


def _tag_str(todos: list) -> str:
    tags = sorted({t[2] for t in todos})
    return "/".join(tags)


if __name__ == "__main__":
    main()
