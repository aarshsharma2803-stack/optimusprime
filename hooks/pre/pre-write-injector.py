#!/usr/bin/env python3
"""PreToolUse hook: injects codebase context before Write/Edit/MultiEdit.

Reads codebase-map.json and self-model.json.
Outputs additionalContext with relevant utilities, deps, and warnings.
Exit 0 always — never blocks.
Performance target: under 50ms with warm cache.

Hot path: pure stdlib only — no optimusprime imports needed for cache reads.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent

_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})


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
    if tool_name not in _WRITE_TOOLS:
        sys.exit(0)

    tool_input = payload.get("tool_input", {})
    file_path = _extract_file_path(tool_name, tool_input)
    if not file_path:
        sys.exit(0)

    # Find .optimusprime/ via pure stdlib walk (no imports)
    op_dir = _find_op_dir()
    if op_dir is None:
        sys.exit(0)

    # Load codebase map — pure JSON read, no module imports
    map_path = op_dir / "codebase-map.json"
    cmap: dict = {}
    if map_path.is_file():
        try:
            cmap = json.loads(map_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if not cmap:
        # Try rebuilding (slower path, only when stale/missing)
        sys.path.insert(0, str(_PLUGIN_ROOT / "src"))
        try:
            from optimusprime.codebase_map import CodebaseMap
            root = _find_project_root() or Path.cwd()
            cm = CodebaseMap(root, op_dir)
            if cm.is_stale():
                cmap = cm.build()
        except Exception:
            pass

    if not cmap:
        sys.exit(0)

    # Get relevant utilities — pure dict lookup, no imports
    relevant = _get_relevant(cmap, file_path)
    installed_deps = cmap.get("installed_deps", [])
    never_use = cmap.get("never_use", [])

    # Load self-model warnings — only if we have a model file (lazy)
    warnings: list = []
    sm_path = op_dir / "self-model.json"
    if sm_path.is_file():
        try:
            sys.path.insert(0, str(_PLUGIN_ROOT / "src"))
            from optimusprime.self_model import SelfModel
            sm = SelfModel(op_dir)
            warnings = sm.get_warnings_for_task(
                task_description=json.dumps(tool_input)[:200],
                file_path=file_path,
            )
        except Exception:
            pass

    # Filter deps relevant to the file
    file_lower = file_path.lower()
    relevant_deps = _filter_relevant_deps(installed_deps, file_lower)

    # Build additionalContext
    sections: list = []

    if relevant:
        lines = ["EXISTING UTILITIES (reuse before writing new):"]
        for name, entry in list(relevant.items())[:8]:
            f = entry.get("file", "")
            ln = entry.get("line", 0)
            lines.append(f"  {name} → {f}:{ln}")
        sections.append("\n".join(lines))

    if relevant_deps:
        sections.append(
            "INSTALLED DEPS (use these, don't add new):\n"
            + "  " + ", ".join(relevant_deps[:10])
        )

    if never_use:
        lines = ["NEVER USE IN THIS PROJECT:"]
        for entry in never_use[:5]:
            lines.append(f"  {entry}")
        sections.append("\n".join(lines))

    if warnings:
        lines = ["SELF-MODEL WARNINGS:"]
        for w in warnings:
            lines.append(f"  {w}")
        sections.append("\n".join(lines))

    if not sections:
        sys.exit(0)

    context = "\n\n".join(sections)
    print(json.dumps({"additionalContext": context}))
    sys.exit(0)


# ---------------------------------------------------------------------------
# Pure-stdlib helpers (no optimusprime imports on hot path)
# ---------------------------------------------------------------------------

def _find_op_dir() -> "Path | None":
    """Walk up from cwd looking for .optimusprime/."""
    current = Path.cwd()
    for _ in range(10):
        candidate = current / ".optimusprime"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _find_project_root() -> "Path | None":
    current = Path.cwd()
    for _ in range(10):
        if (current / ".git").exists() or (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _get_relevant(cmap: dict, file_path: str) -> dict:
    """Return utilities relevant to file_path. At most 10 items."""
    utilities = cmap.get("utilities", {})
    if not utilities:
        return {}

    target_dir = str(Path(file_path).parent)
    target_stem = Path(file_path).stem.lower()
    scored: list = []

    for name, entry in utilities.items():
        entry_file = entry.get("file", "")
        entry_dir = str(Path(entry_file).parent)
        score = 0

        if entry_dir == target_dir:
            score += 10
        elif target_dir in entry_dir or entry_dir in target_dir:
            score += 5

        if target_stem in name.lower() or name.lower() in target_stem:
            score += 3

        if score > 0:
            scored.append((score, name, entry))

    scored.sort(key=lambda x: -x[0])
    return {name: entry for _, name, entry in scored[:10]}


def _extract_file_path(tool_name: str, tool_input: dict) -> str:
    if tool_name in {"Write", "Edit"}:
        return tool_input.get("file_path", "")
    elif tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
        if edits and isinstance(edits, list):
            first = edits[0]
            if isinstance(first, dict):
                return first.get("file_path", "")
    return ""


def _filter_relevant_deps(deps: list, file_lower: str) -> list:
    if not deps:
        return []
    if "test" in file_lower:
        return [d for d in deps if any(kw in d.lower() for kw in {"test", "pytest", "jest", "mock"})]
    return deps[:15]


if __name__ == "__main__":
    main()
