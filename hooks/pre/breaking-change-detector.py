#!/usr/bin/env python3
"""PreToolUse hook: warns when an edit removes public symbols vs. the first-seen snapshot.

Never blocks. Injects additionalContext warning when breaking changes detected.
Snapshots are stored in .optimusprime/api-snapshots/<sha256_of_abspath>.json

Snapshot schema:
{
  "path": "/abs/path/to/file",
  "symbols": ["list", "of", "public", "names"],
  "saved_at": "<iso8601>"
}
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

from optimusprime.utils import find_optimusprime_dir, utcnow_iso, write_json_safe

_SUPPORTED_EXTS = frozenset({".py", ".ts", ".js", ".tsx", ".jsx", ".pyi"})
_SNAPSHOTS_DIR = "api-snapshots"


def _snapshot_key(abs_path: str) -> str:
    """SHA-256 of the absolute path, first 24 hex chars."""
    return hashlib.sha256(abs_path.encode()).hexdigest()[:24]


def _extract_symbols(path: Path, ext: str) -> set[str]:
    """Extract public symbol names from a source file."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return set()

    symbols: set[str] = set()

    if ext in {".py", ".pyi"}:
        # top-level def/class not prefixed with _
        for m in re.finditer(r"^(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            name = m.group(1)
            if not name.startswith("_"):
                symbols.add(name)
        # __all__ contents count as public API
        all_match = re.search(r"__all__\s*=\s*\[([^\]]+)\]", content, re.DOTALL)
        if all_match:
            for m in re.finditer(r"['\"]([A-Za-z_]\w*)['\"]", all_match.group(1)):
                symbols.add(m.group(1))

    elif ext in {".ts", ".tsx", ".js", ".jsx"}:
        # export function/class/const/let/var Name
        for m in re.finditer(
            r"export\s+(?:default\s+)?(?:async\s+)?(?:function\s*\*?\s*|class\s+|const\s+|let\s+|var\s+)([A-Za-z_$]\w*)",
            content,
            re.MULTILINE,
        ):
            symbols.add(m.group(1))
        # export { foo, bar as baz }
        for m in re.finditer(r"export\s*\{([^}]+)\}", content, re.MULTILINE):
            for part in m.group(1).split(","):
                name = part.strip().split(" as ")[0].strip()
                if name and re.match(r"^[A-Za-z_$]\w*$", name):
                    symbols.add(name)
        # export type { Foo }  (TypeScript)
        for m in re.finditer(r"export\s+type\s*\{([^}]+)\}", content, re.MULTILINE):
            for part in m.group(1).split(","):
                name = part.strip().split(" as ")[0].strip()
                if name and re.match(r"^[A-Za-z_$]\w*$", name):
                    symbols.add(name)

    return symbols


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

        # Only analyze files that already exist (new files have no API to break)
        if not target.exists():
            sys.exit(0)

        op_dir = find_optimusprime_dir()
        if op_dir is None:
            sys.exit(0)

        snapshots_dir = op_dir / _SNAPSHOTS_DIR
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        abs_path = str(target.resolve())
        key = _snapshot_key(abs_path)
        snapshot_path = snapshots_dir / f"{key}.json"

        current_symbols = _extract_symbols(target, ext)

        if not snapshot_path.exists():
            # First time seeing this file — save snapshot, no warning
            write_json_safe(
                snapshot_path,
                {
                    "path": abs_path,
                    "symbols": sorted(current_symbols),
                    "saved_at": utcnow_iso(),
                },
            )
            sys.exit(0)

        # Load existing snapshot
        try:
            snap_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            original_symbols: set[str] = set(snap_data.get("symbols", []))
        except Exception:
            sys.exit(0)

        removed = original_symbols - current_symbols
        if not removed:
            sys.exit(0)

        # Breaking changes detected — inject warning
        removed_list = sorted(removed)
        lines = [
            f"OPTIMUSPRIME breaking-change-detector: '{target.name}' — "
            f"{len(removed_list)} public symbol(s) removed since first snapshot:"
        ]
        for sym in removed_list[:15]:
            lines.append(f"  - {sym}")
        if len(removed_list) > 15:
            lines.append(f"  ... and {len(removed_list) - 15} more")
        lines.append(
            "Callers of these symbols will break. Verify or update callers before proceeding."
        )

        context = "\n".join(lines)
        print(json.dumps({"additionalContext": context}))
        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
