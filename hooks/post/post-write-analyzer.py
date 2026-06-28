#!/usr/bin/env python3
"""PostToolUse hook: analyzes written content and flags structural issues.

Fires after Write/Edit/MultiEdit.
Checks: new deps, unnecessary abstractions, missing error handling,
missing tests, duplicate utilities.
Exit 0 always — never blocks.
"""

from __future__ import annotations

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})

# File path patterns indicating API/trust boundary handlers
_BOUNDARY_PATTERNS = re.compile(
    r"(api|route|endpoint|controller|view|handler|server|webhook|middleware)",
    re.IGNORECASE,
)

# Patterns for detecting error handling
_PY_TRY = re.compile(r"\btry\s*:", re.MULTILINE)
_JS_TRY = re.compile(r"\btry\s*\{", re.MULTILINE)

# Patterns for class definitions
_PY_CLASS = re.compile(r"^class\s+\w", re.MULTILINE)
_TS_CLASS = re.compile(r"(?:^|\n)(?:export\s+)?class\s+\w", re.MULTILINE)

# Patterns for import statements
_PY_IMPORT = re.compile(r"^(?:import|from)\s+([\w.]+)", re.MULTILINE)
_TS_IMPORT = re.compile(r"""^import\s+.*?\s+from\s+['"]([^'"./][^'"]*)['""]""", re.MULTILINE)

# Test file patterns
_TEST_FILE_RE = re.compile(r"(test_|_test\.|\.test\.|\.spec\.)", re.IGNORECASE)

# Trivial code markers
_LOOP_RE = re.compile(r"\b(for|while)\b")
_BRANCH_RE = re.compile(r"\b(if|elif|else|switch|case)\b")


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
    tool_response = payload.get("tool_response", {})

    file_path = _extract_file_path(tool_name, tool_input)
    content = _extract_content(tool_name, tool_input)
    if not content or not file_path:
        sys.exit(0)

    # Find .optimusprime/
    from optimusprime.utils import find_optimusprime_dir, find_project_root
    op_dir = find_optimusprime_dir()

    installed_deps: list[str] = []
    utilities: dict = {}

    if op_dir:
        map_path = op_dir / "codebase-map.json"
        if map_path.is_file():
            try:
                cmap = json.loads(map_path.read_text(encoding="utf-8"))
                installed_deps = cmap.get("installed_deps", [])
                utilities = cmap.get("utilities", {})
            except Exception:
                pass

    flags: list[str] = []

    # Check A: New dependency imported but not in installed deps
    flags.extend(_check_new_deps(content, file_path, installed_deps))

    # Check B: Unnecessary abstraction (multiple new classes in non-model file)
    flags.extend(_check_abstractions(content, file_path))

    # Check C: Missing error handling at trust boundary
    flags.extend(_check_error_handling(content, file_path))

    # Check D: Missing test coverage for non-trivial logic
    if op_dir:
        root = find_project_root() or Path.cwd()
        flags.extend(_check_test_coverage(content, file_path, root))

    # Check E: Duplicate utility
    flags.extend(_check_duplicates(content, utilities))

    if not flags:
        sys.exit(0)

    lines = ["POST-WRITE ANALYSIS:"]
    for flag in flags:
        lines.append(f"⚠ {flag}")
    lines.append("\n(informational — proceed as you judge best)")

    context = "\n".join(lines)
    print(json.dumps({"additionalContext": context}))
    sys.exit(0)


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def _check_new_deps(content: str, file_path: str, installed_deps: list[str]) -> list[str]:
    """Flag imports that aren't in installed deps."""
    flags: list[str] = []
    installed_lower = {d.lower() for d in installed_deps}
    installed_lower |= _STDLIB_MODULES  # don't flag stdlib

    ext = Path(file_path).suffix.lower()
    if ext == ".py":
        for m in _PY_IMPORT.finditer(content):
            pkg = m.group(1).split(".")[0].lower()
            if pkg and pkg not in installed_lower and not pkg.startswith("_"):
                flags.append(
                    f"NEW DEP: '{pkg}' imported but not in installed deps — "
                    f"was an existing dep considered?"
                )
                break  # report once per file
    elif ext in {".ts", ".tsx", ".js", ".jsx"}:
        for m in _TS_IMPORT.finditer(content):
            pkg = m.group(1).split("/")[0].lower()
            # Strip @scope prefix for matching
            if pkg.startswith("@"):
                pkg = pkg  # keep scoped name as-is
            if pkg and pkg not in installed_lower:
                flags.append(
                    f"NEW DEP: '{pkg}' imported but not in installed deps — "
                    f"was an existing dep considered?"
                )
                break

    return flags


def _check_abstractions(content: str, file_path: str) -> list[str]:
    """Flag multiple new classes in non-model files."""
    path_lower = file_path.lower()
    is_model_file = any(kw in path_lower for kw in {
        "model", "schema", "type", "entity", "dto", "interface", "struct"
    })
    if is_model_file:
        return []

    ext = Path(file_path).suffix.lower()
    if ext == ".py":
        count = len(_PY_CLASS.findall(content))
    elif ext in {".ts", ".tsx"}:
        count = len(_TS_CLASS.findall(content))
    else:
        return []

    if count > 1:
        return [
            f"ABSTRACTION CHECK: {count} new classes added — "
            f"is this abstraction necessary?"
        ]
    return []


def _check_error_handling(content: str, file_path: str) -> list[str]:
    """Flag missing error handling at API/trust boundaries."""
    if not _BOUNDARY_PATTERNS.search(file_path):
        return []

    ext = Path(file_path).suffix.lower()
    if ext == ".py":
        has_try = bool(_PY_TRY.search(content))
    elif ext in {".ts", ".tsx", ".js", ".jsx"}:
        has_try = bool(_JS_TRY.search(content))
    else:
        return []

    if not has_try:
        return [
            f"TRUST BOUNDARY: {Path(file_path).name} handles external input "
            f"but has no error handling"
        ]
    return []


def _check_test_coverage(
    content: str, file_path: str, project_root: Path
) -> list[str]:
    """Flag non-trivial logic without a corresponding test file."""
    if _TEST_FILE_RE.search(file_path):
        return []  # is a test file

    if not _is_nontrivial(content):
        return []

    # Look for a test file
    target = Path(file_path)
    stem = target.stem

    # Common test file naming patterns
    candidates = [
        project_root / "tests" / f"test_{stem}.py",
        project_root / "tests" / f"{stem}_test.py",
        project_root / f"test_{stem}.py",
        target.parent / f"test_{stem}.py",
        project_root / "tests" / f"{stem}.test.ts",
        project_root / f"{stem}.test.ts",
        project_root / f"{stem}.spec.ts",
    ]

    if any(c.is_file() for c in candidates):
        return []

    return [
        "TEST COVERAGE: non-trivial logic added — consider one small test"
    ]


def _check_duplicates(content: str, utilities: dict) -> list[str]:
    """Flag new functions that look very similar to existing ones."""
    flags: list[str] = []

    # Extract function names from written content
    new_funcs = re.findall(r"\bdef\s+(\w[\w_]*)\s*\(", content)
    new_funcs += re.findall(r"\bfunction\s+(\w[\w_]*)\s*\(", content)

    for new_func in new_funcs:
        for existing_name in utilities:
            # Skip the same name (expected)
            if new_func.lower() == existing_name.lower():
                continue
            ratio = SequenceMatcher(None, new_func.lower(), existing_name.lower()).ratio()
            if ratio > 0.8:
                entry = utilities[existing_name]
                flags.append(
                    f"DUPLICATE: '{new_func}' looks similar to existing "
                    f"'{existing_name}' in {entry.get('file', 'unknown')}"
                )
                break  # one warning per new function

    return flags[:2]  # cap at 2 duplicate warnings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_file_path(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Write":
        return tool_input.get("file_path", "")
    elif tool_name == "Edit":
        return tool_input.get("file_path", "")
    elif tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
        if edits and isinstance(edits, list):
            first = edits[0]
            if isinstance(first, dict):
                return first.get("file_path", "")
    return ""


def _extract_content(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Write":
        return tool_input.get("content", "")
    elif tool_name == "Edit":
        return (
            tool_input.get("new_content", "")
            or tool_input.get("new_string", "")
        )
    elif tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
        if edits and isinstance(edits, list):
            first = edits[0]
            if isinstance(first, dict):
                return first.get("new_string", "") or first.get("new_content", "")
    return ""


def _is_nontrivial(content: str) -> bool:
    """True if content has a loop, branch, or >10 non-blank lines."""
    non_blank = [ln for ln in content.splitlines() if ln.strip()]
    if len(non_blank) > 10:
        return True
    if _LOOP_RE.search(content):
        return True
    if _BRANCH_RE.search(content):
        return True
    return False


# Python stdlib modules that should NOT trigger dep warnings
_STDLIB_MODULES: frozenset[str] = frozenset({
    "os", "sys", "re", "json", "pathlib", "typing", "collections",
    "datetime", "time", "math", "itertools", "functools", "io",
    "string", "hashlib", "hmac", "base64", "urllib", "http",
    "email", "html", "xml", "csv", "configparser", "argparse",
    "logging", "warnings", "copy", "dataclasses", "enum", "abc",
    "contextlib", "threading", "multiprocessing", "subprocess",
    "socket", "ssl", "struct", "array", "queue", "heapq",
    "bisect", "decimal", "fractions", "random", "statistics",
    "tempfile", "shutil", "glob", "fnmatch", "stat", "uuid",
    "platform", "traceback", "inspect", "ast", "dis", "token",
    "tokenize", "compileall", "importlib", "pkgutil", "unittest",
    "__future__", "typing_extensions",
    # common test helpers
    "pytest", "unittest", "mock",
})


if __name__ == "__main__":
    main()
