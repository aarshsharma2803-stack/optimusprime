#!/usr/bin/env python3
"""PreToolUse hook: blocks writes/edits to out-of-scope files per contract.json.

Exit 2 + JSON stdout to block. Exit 0 to pass silently.
Never crashes Claude Code — all errors exit 0.
"""

from __future__ import annotations

import fnmatch
import json
import shlex
import sys
from pathlib import Path

# Resolve src/ so we can import utils without installing the package.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

from optimusprime.utils import (
    append_block,
    find_optimusprime_dir,
    load_contract,
)

# Tools that perform writes the hook should guard.
_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})


def _target_path(tool_name: str, tool_input: dict) -> str:
    if tool_name in _WRITE_TOOLS:
        return tool_input.get("file_path", "")
    return ""


def _bash_candidate_paths(command: str) -> list[str]:
    """Extract tokens from a bash command that look like file paths."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    skip = frozenset({"|", ">", "<", ">>", "&&", "||", ";", "&", "2>&1"})
    paths = []
    for tok in tokens:
        if tok in skip or tok.startswith("-"):
            continue
        # Looks path-like: contains / or starts with ./ or ../
        if "/" in tok or tok.startswith("./") or tok.startswith("../"):
            paths.append(tok)
    return paths


def _is_blocked(path_str: str, out_of_scope: list[str], project_root: Path) -> tuple[bool, str]:
    """Return (blocked, matched_pattern). Never raises."""
    if not path_str:
        return False, ""
    try:
        p = Path(path_str)
        if p.is_absolute():
            try:
                rel = str(p.relative_to(project_root))
            except ValueError:
                rel = str(p)
        else:
            # str(Path("./src/foo")) → "src/foo", str(Path(".env")) → ".env"
            rel = str(p)
    except Exception:
        rel = path_str

    rel_norm = rel.replace("\\", "/")
    basename = Path(rel).name

    for pattern in out_of_scope:
        pat = pattern.strip()
        if not pat:
            continue
        # Full path glob
        if fnmatch.fnmatch(rel_norm, pat):
            return True, pat
        # Basename glob (e.g. "*.env" blocks any ".env" file)
        if fnmatch.fnmatch(basename, pat):
            return True, pat
        # Directory prefix (e.g. "secrets/" blocks "secrets/foo.py")
        pat_dir = pat.rstrip("/*")
        if rel_norm == pat_dir or rel_norm.startswith(pat_dir + "/"):
            return True, pat

    return False, ""


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
        tool_name: str = payload.get("tool_name", "")
        tool_input: dict = payload.get("tool_input", {})

        if tool_name not in _WRITE_TOOLS and tool_name != "Bash":
            sys.exit(0)

        op_dir = find_optimusprime_dir()
        if op_dir is None:
            sys.exit(0)

        contract = load_contract(op_dir)
        if not contract:
            sys.exit(0)

        out_of_scope: list[str] = contract.get("out_of_scope", [])
        if not out_of_scope:
            sys.exit(0)

        agent_id: str = contract.get("agent_id", "main")
        project_root = op_dir.parent

        if tool_name == "Bash":
            command = tool_input.get("command", "")
            for path_str in _bash_candidate_paths(command):
                blocked, pattern = _is_blocked(path_str, out_of_scope, project_root)
                if blocked:
                    reason = (
                        f"Bash references out-of-scope path '{path_str}' "
                        f"(pattern '{pattern}')"
                    )
                    append_block(op_dir, reason, agent_id)
                    _block(reason)
        else:
            path_str = _target_path(tool_name, tool_input)
            blocked, pattern = _is_blocked(path_str, out_of_scope, project_root)
            if blocked:
                reason = (
                    f"Write to '{path_str}' blocked — "
                    f"matches out-of-scope pattern '{pattern}'"
                )
                append_block(op_dir, reason, agent_id)
                _block(reason)

        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
