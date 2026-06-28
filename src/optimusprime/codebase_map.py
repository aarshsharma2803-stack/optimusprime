"""Codebase scanner for OptimusPrime.

Scans the project directory and builds a structured map:
existing utilities, dependencies, code patterns, and anti-patterns.

Output: .optimusprime/codebase-map.json
Used by pre-write-injector.py to inject context before every Write/Edit.

Pure stdlib — no pip dependencies.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from optimusprime.utils import load_json, write_json_safe

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", "dist", "build",
    ".venv", "venv", "env", ".env", ".tox", ".eggs", "*.egg-info",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage",
    ".next", ".nuxt", "target",  # rust/java build dirs
})

_MAX_UTILITIES = 500
_STALE_HOURS = 24

_SOURCE_EXTS = frozenset({".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go"})

# Regex patterns per language
_PY_FUNC = re.compile(r"^((?:async\s+)?def\s+\w[\w_]*)\s*\(", re.MULTILINE)
_PY_CLASS = re.compile(r"^(class\s+\w[\w_]*)", re.MULTILINE)

_TS_FUNC = re.compile(
    r"(?:^|\n)(?:export\s+)?(?:async\s+)?function\s+(\w[\w_]*)\s*\(",
)
_TS_ARROW = re.compile(
    r"(?:^|\n)export\s+const\s+(\w[\w_]*)\s*=\s*(?:async\s*)?\(",
)
_TS_CLASS = re.compile(r"(?:^|\n)export\s+class\s+(\w[\w_]*)")
_TS_CLASS_NOEXP = re.compile(r"(?:^|\n)class\s+(\w[\w_]*)")

_RS_FN = re.compile(r"(?:^|\n)(?:pub\s+)?fn\s+(\w[\w_]*)\s*\(")
_RS_STRUCT = re.compile(r"(?:^|\n)(?:pub\s+)?struct\s+(\w[\w_]*)")

_GO_FN = re.compile(r"(?:^|\n)func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w[\w_]*)\s*\(")

# Version specifiers to strip
_VER_RE = re.compile(r"[><=!~^@\[].*$")

# Rejected dependency keywords in decisions
_REJECT_KEYWORDS = frozenset({"reject", "rejected", "avoid", "never", "banned", "don't use", "do not use"})


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class CodebaseEntry:
    name: str
    file_path: str
    line_number: int
    entry_type: str   # "function", "class", "constant", "type"
    signature: str


# ---------------------------------------------------------------------------
# CodebaseMap
# ---------------------------------------------------------------------------

class CodebaseMap:
    """Scans the project and builds a map of what already exists."""

    def __init__(self, project_root: Path, optimusprime_dir: Path) -> None:
        self._root = Path(project_root).resolve()
        self._op_dir = Path(optimusprime_dir)
        self._map: Dict[str, Any] = {}
        self._load_cached()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> Dict[str, Any]:
        """Full scan. Writes codebase-map.json. Returns built map."""
        utilities = self._scan_utilities()
        installed_deps, dev_deps = self._scan_dependencies()
        patterns = self._extract_patterns()
        never_use = self._detect_never_use(installed_deps)
        language = self._detect_language()

        self._map = {
            "built_at": _utcnow(),
            "project_root": str(self._root),
            "utilities": utilities,
            "installed_deps": installed_deps,
            "dev_deps": dev_deps,
            "patterns": patterns,
            "never_use": never_use,
            "file_count": self._count_source_files(),
            "language": language,
        }
        write_json_safe(self._op_dir / "codebase-map.json", self._map)
        return self._map

    def get_relevant_for_file(self, file_path: str) -> Dict[str, Any]:
        """Return subset of map most relevant to file_path. At most 10 items."""
        if not self._map:
            return {}

        utilities = self._map.get("utilities", {})
        if not utilities:
            return {}

        target = Path(file_path)
        target_dir = str(target.parent)
        target_stem = target.stem.lower()
        result: List[Tuple[int, str, Dict[str, Any]]] = []

        for name, entry in utilities.items():
            score = 0
            entry_file = entry.get("file", "")
            entry_dir = str(Path(entry_file).parent)

            # Same directory wins highest priority
            if entry_dir == target_dir:
                score += 10
            elif target_dir in entry_dir or entry_dir in target_dir:
                score += 5

            # Name overlap with target file stem
            if target_stem in name.lower() or name.lower() in target_stem:
                score += 3

            if score > 0:
                result.append((score, name, entry))

        result.sort(key=lambda x: -x[0])
        top_10 = {name: entry for _, name, entry in result[:10]}
        return top_10

    def get_existing_utility(self, query: str) -> List[CodebaseEntry]:
        """Search utilities by name similarity. Returns top 3 matches."""
        utilities = self._map.get("utilities", {})
        if not utilities:
            return []

        query_lower = query.lower()
        query_tokens = set(re.findall(r"\w+", query_lower))
        scored: List[Tuple[float, str, Dict[str, Any]]] = []

        for name, entry in utilities.items():
            name_lower = name.lower()
            score = 0.0
            # Substring match
            if query_lower in name_lower:
                score += 2.0
            elif name_lower in query_lower:
                score += 1.5
            # Token overlap
            name_tokens = set(re.findall(r"\w+", name_lower))
            overlap = query_tokens & name_tokens
            score += len(overlap) * 0.5
            if score > 0:
                scored.append((score, name, entry))

        scored.sort(key=lambda x: -x[0])
        top = scored[:3]
        return [
            CodebaseEntry(
                name=name,
                file_path=entry.get("file", ""),
                line_number=entry.get("line", 0),
                entry_type=entry.get("type", "function"),
                signature=entry.get("signature", name),
            )
            for _, name, entry in top
        ]

    def is_stale(self) -> bool:
        """True if codebase-map.json is missing or older than 24 hours."""
        path = self._op_dir / "codebase-map.json"
        if not path.is_file():
            return True
        try:
            age_hours = (time.time() - path.stat().st_mtime) / 3600
            return age_hours > _STALE_HOURS
        except OSError:
            return True

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

    def _scan_utilities(self) -> Dict[str, Any]:
        """Scan source files for function/class definitions. Max 500."""
        utilities: Dict[str, Any] = {}

        for root, dirs, files in os.walk(self._root):
            # Prune skip dirs in-place
            dirs[:] = [
                d for d in dirs
                if d not in _SKIP_DIRS and not d.endswith(".egg-info")
            ]
            for fname in files:
                if len(utilities) >= _MAX_UTILITIES:
                    return utilities
                ext = Path(fname).suffix.lower()
                if ext not in _SOURCE_EXTS:
                    continue
                fpath = Path(root) / fname
                try:
                    rel = str(fpath.relative_to(self._root))
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                entries = _extract_entries(content, rel, ext)
                for entry in entries:
                    if len(utilities) >= _MAX_UTILITIES:
                        return utilities
                    # Use mangled name if collision
                    key = entry.name
                    if key in utilities:
                        key = f"{entry.name}__{rel.replace('/', '_')}"
                    utilities[key] = {
                        "file": entry.file_path,
                        "line": entry.line_number,
                        "type": entry.entry_type,
                        "signature": entry.signature,
                    }
        return utilities

    def _scan_dependencies(self) -> Tuple[List[str], List[str]]:
        """Return (installed_deps, dev_deps). Checks pyproject.toml, package.json, etc."""
        # pyproject.toml
        pyproject = self._root / "pyproject.toml"
        if pyproject.is_file():
            return _parse_pyproject(pyproject)

        # requirements.txt
        req = self._root / "requirements.txt"
        if req.is_file():
            return _parse_requirements(req), []

        # package.json
        pkg = self._root / "package.json"
        if pkg.is_file():
            return _parse_package_json(pkg)

        # Cargo.toml
        cargo = self._root / "Cargo.toml"
        if cargo.is_file():
            return _parse_cargo_toml(cargo)

        return [], []

    def _extract_patterns(self) -> Dict[str, str]:
        """Read up to 5 source files and infer code patterns."""
        patterns: Dict[str, str] = {}
        source_files = _find_source_files(self._root, limit=5)
        if not source_files:
            return patterns

        all_content = ""
        for fpath in source_files:
            try:
                all_content += fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass

        if not all_content:
            return patterns

        # Error handling pattern
        if "Result<" in all_content or "Result[" in all_content:
            patterns["error_handling"] = "Result type returns, not exceptions"
        elif "try:" in all_content or "try {" in all_content:
            if "raise" in all_content or "throw" in all_content:
                patterns["error_handling"] = "try/except with explicit raises"
            else:
                patterns["error_handling"] = "try/except, no re-raise"
        else:
            patterns["error_handling"] = "no explicit error handling detected"

        # Naming pattern
        snake_count = len(re.findall(r"\bdef\s+[a-z][a-z0-9]*_[a-z]", all_content))
        camel_count = len(re.findall(r"\bfunction\s+[a-z][a-zA-Z0-9]+\b", all_content))
        if snake_count > camel_count:
            patterns["naming"] = "snake_case functions, PascalCase classes"
        elif camel_count > snake_count:
            patterns["naming"] = "camelCase functions, PascalCase classes"
        else:
            patterns["naming"] = "mixed"

        # Testing pattern
        test_files = list(self._root.rglob("test_*.py")) + list(self._root.rglob("*.test.ts"))
        test_files = [f for f in test_files if "node_modules" not in str(f)]
        if test_files:
            patterns["testing"] = "pytest" if any(f.suffix == ".py" for f in test_files) else "jest"
        else:
            patterns["testing"] = "no test files detected"

        # Import style
        rel_imports = len(re.findall(r"from\s+\.", all_content))
        abs_imports = len(re.findall(r"^from\s+\w", all_content, re.MULTILINE))
        if abs_imports > rel_imports:
            patterns["imports"] = "absolute imports preferred"
        elif rel_imports > 0:
            patterns["imports"] = "relative imports used"
        else:
            patterns["imports"] = "absolute imports only"

        return patterns

    def _detect_never_use(self, installed_deps: List[str]) -> List[str]:
        """Find rejected deps from decisions.md and cross-reference alternatives."""
        never_use: List[str] = []

        # Known alternative pairs (rejected → alternative)
        _alternatives = {
            "requests": "httpx",
            "moment": "date-fns",
            "yup": "zod",
            "lodash": "native ES6",
            "axios": "fetch/httpx",
        }

        # Check decisions.md for explicit rejections
        decisions_path = self._op_dir / "decisions.md"
        if decisions_path.is_file():
            try:
                text = decisions_path.read_text(encoding="utf-8")
                for line in text.splitlines():
                    line_lower = line.lower()
                    if any(kw in line_lower for kw in _REJECT_KEYWORDS):
                        # Extract package name from the line
                        m = re.search(r"\b([a-zA-Z][\w\-]+)\b", line)
                        if m:
                            rejected = m.group(1)
                            if rejected not in installed_deps:
                                never_use.append(f"{rejected} — explicitly rejected in decisions.md")
            except Exception:
                pass

        # Cross-reference: if alternative is installed, reject the original
        installed_set = set(installed_deps)
        for rejected, alt in _alternatives.items():
            if alt in installed_set and rejected not in installed_set:
                never_use.append(f"{rejected} — project uses {alt}")

        return list(dict.fromkeys(never_use))  # deduplicate, preserve order

    def _detect_language(self) -> str:
        """Count files by extension and return dominant language."""
        counts: Dict[str, int] = {}
        lang_map = {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".rs": "rust",
            ".go": "go",
        }
        for root, dirs, files in os.walk(self._root):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fname in files:
                ext = Path(fname).suffix.lower()
                lang = lang_map.get(ext)
                if lang:
                    counts[lang] = counts.get(lang, 0) + 1

        if not counts:
            return "unknown"
        dominant = max(counts, key=lambda k: counts[k])
        total = sum(counts.values())
        if counts[dominant] / total < 0.7 and len(counts) > 1:
            return "mixed"
        return dominant

    def _count_source_files(self) -> int:
        """Count total source files in project."""
        count = 0
        for root, dirs, files in os.walk(self._root):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fname in files:
                ext = Path(fname).suffix.lower()
                if ext in _SOURCE_EXTS:
                    count += 1
        return count

    def _load_cached(self) -> None:
        """Load cached map if it's fresh (<24h)."""
        if not self.is_stale():
            self._map = load_json(self._op_dir / "codebase-map.json")


# ---------------------------------------------------------------------------
# Entry extraction helpers
# ---------------------------------------------------------------------------

def _extract_entries(content: str, rel_path: str, ext: str) -> List[CodebaseEntry]:
    """Extract function/class definitions from file content."""
    entries: List[CodebaseEntry] = []
    lines = content.splitlines()

    if ext == ".py":
        for m in _PY_FUNC.finditer(content):
            ln = content.count("\n", 0, m.start()) + 1
            sig = lines[ln - 1].strip()[:80] if ln <= len(lines) else m.group(1)
            name = re.search(r"def\s+(\w+)", m.group(1))
            if name:
                entries.append(CodebaseEntry(
                    name=name.group(1), file_path=rel_path, line_number=ln,
                    entry_type="function", signature=sig
                ))
        for m in _PY_CLASS.finditer(content):
            ln = content.count("\n", 0, m.start()) + 1
            sig = lines[ln - 1].strip()[:80] if ln <= len(lines) else m.group(1)
            name = re.search(r"class\s+(\w+)", m.group(1))
            if name:
                entries.append(CodebaseEntry(
                    name=name.group(1), file_path=rel_path, line_number=ln,
                    entry_type="class", signature=sig
                ))

    elif ext in {".ts", ".tsx"}:
        for m in _TS_FUNC.finditer(content):
            ln = content.count("\n", 0, m.start()) + 1
            sig = lines[ln - 1].strip()[:80] if ln <= len(lines) else m.group(1)
            entries.append(CodebaseEntry(
                name=m.group(1), file_path=rel_path, line_number=ln,
                entry_type="function", signature=sig
            ))
        for m in _TS_ARROW.finditer(content):
            ln = content.count("\n", 0, m.start()) + 1
            sig = lines[ln - 1].strip()[:80] if ln <= len(lines) else m.group(1)
            entries.append(CodebaseEntry(
                name=m.group(1), file_path=rel_path, line_number=ln,
                entry_type="function", signature=sig
            ))
        for m in list(_TS_CLASS.finditer(content)) + list(_TS_CLASS_NOEXP.finditer(content)):
            ln = content.count("\n", 0, m.start()) + 1
            sig = lines[ln - 1].strip()[:80] if ln <= len(lines) else m.group(1)
            entries.append(CodebaseEntry(
                name=m.group(1), file_path=rel_path, line_number=ln,
                entry_type="class", signature=sig
            ))

    elif ext in {".js", ".jsx"}:
        for m in _TS_FUNC.finditer(content):
            ln = content.count("\n", 0, m.start()) + 1
            sig = lines[ln - 1].strip()[:80] if ln <= len(lines) else m.group(1)
            entries.append(CodebaseEntry(
                name=m.group(1), file_path=rel_path, line_number=ln,
                entry_type="function", signature=sig
            ))

    elif ext == ".rs":
        for m in _RS_FN.finditer(content):
            ln = content.count("\n", 0, m.start()) + 1
            sig = lines[ln - 1].strip()[:80] if ln <= len(lines) else m.group(1)
            entries.append(CodebaseEntry(
                name=m.group(1), file_path=rel_path, line_number=ln,
                entry_type="function", signature=sig
            ))
        for m in _RS_STRUCT.finditer(content):
            ln = content.count("\n", 0, m.start()) + 1
            sig = lines[ln - 1].strip()[:80] if ln <= len(lines) else m.group(1)
            entries.append(CodebaseEntry(
                name=m.group(1), file_path=rel_path, line_number=ln,
                entry_type="class", signature=sig
            ))

    elif ext == ".go":
        for m in _GO_FN.finditer(content):
            ln = content.count("\n", 0, m.start()) + 1
            sig = lines[ln - 1].strip()[:80] if ln <= len(lines) else m.group(1)
            entries.append(CodebaseEntry(
                name=m.group(1), file_path=rel_path, line_number=ln,
                entry_type="function", signature=sig
            ))

    return entries


# ---------------------------------------------------------------------------
# Dependency parsers
# ---------------------------------------------------------------------------

def _parse_pyproject(path: Path) -> Tuple[List[str], List[str]]:
    """Parse pyproject.toml for dependencies."""
    installed: List[str] = []
    dev: List[str] = []
    try:
        text = path.read_text(encoding="utf-8")

        # [project.dependencies] — modern format
        m = re.search(r"\[project\].*?dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL)
        if m:
            installed = _extract_dep_names(m.group(1))

        # [tool.poetry.dependencies]
        if not installed:
            m = re.search(
                r"\[tool\.poetry\.dependencies\](.*?)(?=\[|$)", text, re.DOTALL
            )
            if m:
                installed = _extract_toml_deps(m.group(1))

        # optional-dependencies / dev
        m = re.search(
            r"\[project\.optional-dependencies\](.*?)(?=\[|$)", text, re.DOTALL
        )
        if m:
            for block in re.findall(r"=\s*\[(.*?)\]", m.group(1), re.DOTALL):
                dev.extend(_extract_dep_names(block))

        # [tool.poetry.dev-dependencies]
        m = re.search(
            r"\[tool\.poetry\.dev-dependencies\](.*?)(?=\[|$)", text, re.DOTALL
        )
        if m:
            dev = _extract_toml_deps(m.group(1))

    except Exception:
        pass
    return installed, dev


def _parse_requirements(path: Path) -> List[str]:
    deps: List[str] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            name = _VER_RE.sub("", line).strip()
            if name:
                deps.append(name)
    except Exception:
        pass
    return deps


def _parse_package_json(path: Path) -> Tuple[List[str], List[str]]:
    installed: List[str] = []
    dev: List[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        installed = list(data.get("dependencies", {}).keys())
        dev = list(data.get("devDependencies", {}).keys())
    except Exception:
        pass
    return installed, dev


def _parse_cargo_toml(path: Path) -> Tuple[List[str], List[str]]:
    installed: List[str] = []
    dev: List[str] = []
    try:
        text = path.read_text(encoding="utf-8")
        m = re.search(r"\[dependencies\](.*?)(?=\[|$)", text, re.DOTALL)
        if m:
            installed = [
                line.split("=")[0].strip()
                for line in m.group(1).splitlines()
                if "=" in line and not line.strip().startswith("#")
            ]
        m = re.search(r"\[dev-dependencies\](.*?)(?=\[|$)", text, re.DOTALL)
        if m:
            dev = [
                line.split("=")[0].strip()
                for line in m.group(1).splitlines()
                if "=" in line and not line.strip().startswith("#")
            ]
    except Exception:
        pass
    return installed, dev


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _extract_dep_names(block: str) -> List[str]:
    """Extract package names from a TOML array block string."""
    names: List[str] = []
    for m in re.finditer(r'"([^"]+)"', block):
        raw = m.group(1)
        name = _VER_RE.sub("", raw).strip()
        if name:
            names.append(name)
    return names


def _extract_toml_deps(block: str) -> List[str]:
    """Extract dep names from a [tool.poetry.dependencies] block."""
    names: List[str] = []
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("[") or line.startswith("#"):
            continue
        if "=" in line:
            name = line.split("=")[0].strip()
            if name and name != "python":
                names.append(name)
    return names


def _find_source_files(root: Path, limit: int = 5) -> List[Path]:
    """Find source files, skipping skip dirs."""
    found: List[Path] = []
    for fpath in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in fpath.parts):
            continue
        if "test" in fpath.name.lower():
            continue
        found.append(fpath)
        if len(found) >= limit:
            break
    return found


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_codebase_map(
    project_root: Optional[Path] = None,
    op_dir: Optional[Path] = None,
) -> CodebaseMap:
    """Module-level factory. Auto-finds roots if not provided."""
    if project_root is None:
        from optimusprime.utils import find_project_root
        project_root = find_project_root() or Path.cwd()
    if op_dir is None:
        from optimusprime.utils import find_optimusprime_dir
        op_dir = find_optimusprime_dir()
        if op_dir is None:
            raise FileNotFoundError("No .optimusprime/ directory found")
    return CodebaseMap(project_root, op_dir)
