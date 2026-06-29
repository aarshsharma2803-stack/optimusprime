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
    append_event,
    find_optimusprime_dir,
    load_contract,
    utcnow_iso,
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

    _REDIR_OPS = frozenset({">", "<", ">>", ">&", "2>"})
    _SKIP_OPS = frozenset({"|", ">", "<", ">>", "&&", "||", ";", "&", "2>&1", ">&", "2>"})
    paths = []
    next_is_redir_target = False
    for tok in tokens:
        if next_is_redir_target:
            next_is_redir_target = False
            if tok and not tok.startswith("-"):
                paths.append(tok)
            continue
        if tok in _REDIR_OPS:
            next_is_redir_target = True
            continue
        if tok in _SKIP_OPS or tok.startswith("-"):
            continue
        # Looks path-like: contains / or starts with ./ or ../ or dot-file
        if "/" in tok or tok.startswith("./") or tok.startswith("../") or tok.startswith("."):
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


def _log_scope_block(op_dir: Path, file_path: str, tool_name: str) -> None:
    """Append a blocked file entry to scope-guard-log.json. Silent on any error."""
    import os
    import tempfile
    try:
        log_path = op_dir / "scope-guard-log.json"
        existing: list = []
        if log_path.is_file():
            try:
                data = json.loads(log_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    existing = data
            except Exception:
                pass
        existing.append({
            "file_path": file_path,
            "timestamp": utcnow_iso(),
            "tool_name": tool_name,
        })
        fd, tmp = tempfile.mkstemp(dir=op_dir, prefix=".tmp_sgl_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        os.rename(tmp, log_path)
    except Exception:
        pass


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
                    _log_scope_block(op_dir, path_str, tool_name)
                    append_event(op_dir, "PreToolUse", tool=tool_name, file=path_str, action="blocked")
                    _block(reason)
            append_event(op_dir, "PreToolUse", tool=tool_name, file="", action="passed")
        else:
            path_str = _target_path(tool_name, tool_input)
            blocked, pattern = _is_blocked(path_str, out_of_scope, project_root)
            if blocked:
                reason = (
                    f"Write to '{path_str}' blocked — "
                    f"matches out-of-scope pattern '{pattern}'"
                )
                append_block(op_dir, reason, agent_id)
                _log_scope_block(op_dir, path_str, tool_name)
                append_event(op_dir, "PreToolUse", tool=tool_name, file=path_str, action="blocked")
                _block(reason)
            else:
                append_event(op_dir, "PreToolUse", tool=tool_name, file=path_str, action="passed")

        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
