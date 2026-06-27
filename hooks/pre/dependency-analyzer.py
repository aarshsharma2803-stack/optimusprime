#!/usr/bin/env python3
"""PreToolUse hook: injects caller/importer info before editing source files.

Never blocks. Injects additionalContext when callers are found.
Supports: .py, .ts, .js, .tsx, .jsx
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

from optimusprime.utils import find_optimusprime_dir, find_project_root

_SUPPORTED_EXTS = frozenset({".py", ".ts", ".js", ".tsx", ".jsx"})
_GREP_TIMEOUT = 8  # seconds
_MAX_CALLERS_SHOWN = 10


def _extract_public_symbols(path: Path, ext: str) -> list[str]:
    """Return list of public top-level symbol names defined in path."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    symbols: list[str] = []

    if ext == ".py":
        # Top-level def / class not starting with _
        for m in re.finditer(r"^(?:def|class)\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            name = m.group(1)
            if not name.startswith("_"):
                symbols.append(name)

    elif ext in {".ts", ".tsx", ".js", ".jsx"}:
        # export function/class/const/let/var Foo
        for m in re.finditer(
            r"export\s+(?:default\s+)?(?:async\s+)?(?:function\s*\*?\s*|class\s+|const\s+|let\s+|var\s+)([A-Za-z_$]\w*)",
            content,
            re.MULTILINE,
        ):
            symbols.append(m.group(1))
        # export { foo, bar as baz }
        for m in re.finditer(r"export\s*\{([^}]+)\}", content, re.MULTILINE):
            for part in m.group(1).split(","):
                name = part.strip().split(" as ")[0].strip()
                if name and re.match(r"^[A-Za-z_$]\w*$", name):
                    symbols.append(name)

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def _find_callers(symbol: str, project_root: Path, target_path: Path, ext: str) -> list[str]:
    """Return list of relative file paths that reference symbol. Max _MAX_CALLERS_SHOWN."""
    include_patterns: list[str] = []
    if ext == ".py":
        include_patterns = ["*.py"]
    elif ext in {".ts", ".tsx"}:
        include_patterns = ["*.ts", "*.tsx"]
    elif ext in {".js", ".jsx"}:
        include_patterns = ["*.js", "*.jsx", "*.ts", "*.tsx"]

    cmd = ["grep", "-rl", symbol]
    for pat in include_patterns:
        cmd += ["--include=" + pat]
    cmd.append(str(project_root))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_GREP_TIMEOUT,
        )
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        # Exclude the target file itself
        target_abs = str(target_path.resolve())
        lines = [l for l in lines if Path(l).resolve() != Path(target_abs)]
        # Make relative to project root
        rel_lines: list[str] = []
        for l in lines[:_MAX_CALLERS_SHOWN]:
            try:
                rel_lines.append(str(Path(l).relative_to(project_root)))
            except ValueError:
                rel_lines.append(l)
        return rel_lines
    except Exception:
        return []


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        payload = json.loads(raw)
        tool_name: str = payload.get("tool_name", "")
        tool_input: dict = payload.get("tool_input", {})

        if tool_name not in ("Write", "Edit", "MultiEdit"):
            sys.exit(0)

        file_path_str: str = tool_input.get("file_path", "")
        if not file_path_str:
            sys.exit(0)

        target = Path(file_path_str)
        ext = target.suffix.lower()
        if ext not in _SUPPORTED_EXTS:
            sys.exit(0)

        # File must exist — nothing to analyze if it's brand new
        if not target.exists():
            sys.exit(0)

        project_root = find_project_root(target.parent) or target.parent
        symbols = _extract_public_symbols(target, ext)
        if not symbols:
            sys.exit(0)

        # Find callers for each symbol; aggregate unique files
        caller_map: dict[str, list[str]] = {}
        for sym in symbols[:20]:  # cap at 20 symbols to avoid grep overload
            callers = _find_callers(sym, project_root, target, ext)
            if callers:
                caller_map[sym] = callers

        if not caller_map:
            sys.exit(0)

        # Build context string
        lines = [f"OPTIMUSPRIME dependency-analyzer: callers found for '{target.name}'"]
        total_files: set[str] = set()
        for sym, callers in caller_map.items():
            total_files.update(callers)
            files_str = ", ".join(callers[:5])
            if len(callers) > 5:
                files_str += f" (+{len(callers) - 5} more)"
            lines.append(f"  {sym}() → {files_str}")
        lines.append(
            f"Total: {len(total_files)} file(s) reference symbols in this file — "
            "review callers before changing signatures."
        )

        context = "\n".join(lines)
        print(json.dumps({"additionalContext": context}))
        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
