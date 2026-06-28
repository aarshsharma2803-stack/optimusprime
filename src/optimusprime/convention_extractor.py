"""Convention extractor for OptimusPrime.

Reads the actual codebase and extracts implicit coding conventions
as structured, checkable rules.

Output: .optimusprime/conventions.json
Used by post-write-analyzer.py as Check F (convention violations).

Pure stdlib — no pip dependencies.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from optimusprime.utils import write_json_safe

_SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", "dist", "build",
    ".venv", "venv", "env", ".tox", ".eggs", ".next", ".nuxt",
    "target", ".pytest_cache", ".mypy_cache",
})


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Convention:
    category: str
    rule: str
    confidence: float
    evidence_count: int
    examples: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ConventionExtractor
# ---------------------------------------------------------------------------

class ConventionExtractor:
    """Extract implicit coding conventions from a project."""

    def __init__(self, project_root: Path, optimusprime_dir: Path) -> None:
        self._root = Path(project_root).resolve()
        self._op_dir = Path(optimusprime_dir)

    def extract(self) -> List[Convention]:
        """Main entry. Calls all _extract methods. Writes conventions.json."""
        conventions: List[Convention] = []
        conventions.extend(self._extract_error_handling())
        conventions.extend(self._extract_naming())
        conventions.extend(self._extract_testing())
        conventions.extend(self._extract_imports())
        conventions.extend(self._extract_structure())

        # Sort by confidence descending
        conventions.sort(key=lambda c: -c.confidence)

        data = {
            "version": "0.1.0",
            "extracted_from": str(self._root),
            "conventions": [asdict(c) for c in conventions],
        }
        write_json_safe(self._op_dir / "conventions.json", data)
        return conventions

    def get_violations(self, content: str, file_path: str) -> List[str]:
        """Check content against extracted conventions. Return violation descriptions."""
        conv_path = self._op_dir / "conventions.json"
        if not conv_path.is_file():
            return []

        try:
            data = json.loads(conv_path.read_text(encoding="utf-8"))
        except Exception:
            return []

        violations: List[str] = []
        for entry in data.get("conventions", []):
            if entry.get("confidence", 0) < 0.6:
                continue
            cat = entry.get("category", "")
            rule = entry.get("rule", "")
            violation = self._check_violation(content, file_path, cat, rule)
            if violation:
                violations.append(violation)

        return violations[:5]

    # ------------------------------------------------------------------
    # Private extraction methods
    # ------------------------------------------------------------------

    def _extract_error_handling(self) -> List[Convention]:
        """Detect dominant error handling pattern from source files."""
        files = self._sample_files(".py", max_files=20)
        if not files:
            return []

        result_count = 0
        try_count = 0
        raise_count = 0
        tuple_count = 0
        total = 0
        examples: List[str] = []

        for fpath in files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            total += 1
            if "Result[" in text or "Result<" in text or "Either[" in text:
                result_count += 1
                if len(examples) < 3:
                    m = re.search(r".{0,20}Result\[.{0,40}", text)
                    if m:
                        examples.append(m.group(0).strip())
            if re.search(r"\btry\s*:", text):
                try_count += 1
                if len(examples) < 3:
                    m = re.search(r"try:.{0,40}", text, re.DOTALL)
                    if m:
                        examples.append(m.group(0)[:60].replace("\n", " ").strip())
            if re.search(r"\braise\s+\w+", text):
                raise_count += 1
            if re.search(r"return\s+\w+,\s*(?:None|False|True|\"\")", text):
                tuple_count += 1

        if total == 0:
            return []

        conventions = []
        if result_count / total > 0.5:
            conventions.append(Convention(
                category="error_handling",
                rule="Uses Result type returns — avoid raising exceptions",
                confidence=round(result_count / total, 2),
                evidence_count=result_count,
                examples=examples[:3],
            ))
        elif try_count / total > 0.4:
            verb = "with re-raise" if raise_count / total > 0.3 else "swallowed"
            conventions.append(Convention(
                category="error_handling",
                rule=f"Uses try/except {verb} — wrap external calls",
                confidence=round(try_count / total, 2),
                evidence_count=try_count,
                examples=examples[:3],
            ))
        elif tuple_count / total > 0.3:
            conventions.append(Convention(
                category="error_handling",
                rule="Uses error return tuples (value, error) — no exceptions",
                confidence=round(tuple_count / total, 2),
                evidence_count=tuple_count,
                examples=[],
            ))
        return conventions

    def _extract_naming(self) -> List[Convention]:
        """Detect naming conventions from function and variable names."""
        files = self._sample_files(".py", max_files=20)
        files += self._sample_files(".ts", max_files=10)
        files += self._sample_files(".tsx", max_files=10)

        snake_count = 0
        camel_count = 0
        pascal_count = 0
        screaming_count = 0
        total_names = 0
        examples: List[str] = []

        for fpath in files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            # Python function names
            for m in re.finditer(r"\bdef\s+([a-zA-Z_]\w*)", text):
                name = m.group(1)
                total_names += 1
                if re.match(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$", name):
                    snake_count += 1
                elif re.match(r"^[a-z][A-Z]", name):
                    camel_count += 1
                if len(examples) < 3:
                    examples.append(name)
            # TS/JS function names
            for m in re.finditer(r"\bfunction\s+([a-zA-Z_]\w*)", text):
                name = m.group(1)
                total_names += 1
                if re.match(r"^[a-z][A-Z]", name):
                    camel_count += 1
            # Constants
            for m in re.finditer(r"\b([A-Z][A-Z0-9_]{2,})\b", text):
                screaming_count += 1

        if total_names == 0:
            return []

        conventions = []
        if snake_count > camel_count and snake_count / total_names > 0.5:
            conventions.append(Convention(
                category="naming",
                rule="Functions: snake_case (Python convention)",
                confidence=round(snake_count / total_names, 2),
                evidence_count=snake_count,
                examples=examples[:3],
            ))
        elif camel_count > snake_count and camel_count / total_names > 0.4:
            conventions.append(Convention(
                category="naming",
                rule="Functions: camelCase (JS/TS convention)",
                confidence=round(camel_count / total_names, 2),
                evidence_count=camel_count,
                examples=examples[:3],
            ))

        if screaming_count > 5:
            conventions.append(Convention(
                category="naming",
                rule="Constants: SCREAMING_SNAKE_CASE",
                confidence=0.7,
                evidence_count=screaming_count,
                examples=[],
            ))
        return conventions

    def _extract_testing(self) -> List[Convention]:
        """Detect testing conventions: location, naming, framework."""
        # Find test files
        test_files_py = list(self._root.rglob("test_*.py"))
        test_files_ts = list(self._root.rglob("*.test.ts")) + list(self._root.rglob("*.spec.ts"))
        test_files_py = [f for f in test_files_py if not any(p in _SKIP_DIRS for p in f.parts)]
        test_files_ts = [f for f in test_files_ts if not any(p in _SKIP_DIRS for p in f.parts)]

        conventions = []

        if test_files_py:
            # Check location: in tests/ dir?
            in_tests_dir = sum(1 for f in test_files_py if "tests" in f.parts)
            location = "tests/ directory" if in_tests_dir / len(test_files_py) > 0.5 else "colocated"
            framework = "pytest"
            # Check if pytest imported
            for fpath in test_files_py[:3]:
                try:
                    if "import pytest" in fpath.read_text(encoding="utf-8", errors="ignore"):
                        framework = "pytest"
                        break
                except Exception:
                    pass

            conventions.append(Convention(
                category="testing",
                rule=f"Tests in {location}, named test_*.py, using {framework}",
                confidence=0.85,
                evidence_count=len(test_files_py),
                examples=[str(f.relative_to(self._root)) for f in test_files_py[:3]],
            ))

            # Coverage ratio
            src_files = list(self._root.rglob("*.py"))
            src_files = [f for f in src_files if not any(p in _SKIP_DIRS for p in f.parts)
                         and "test" not in f.name]
            if src_files:
                ratio = round(len(test_files_py) / len(src_files), 2)
                if ratio > 0.3:
                    quality = "high" if ratio > 0.7 else "moderate"
                    conventions.append(Convention(
                        category="testing",
                        rule=f"Test coverage ratio: {ratio} ({quality})",
                        confidence=0.7,
                        evidence_count=len(test_files_py),
                        examples=[],
                    ))

        elif test_files_ts:
            conventions.append(Convention(
                category="testing",
                rule="Tests using jest/vitest, named *.test.ts",
                confidence=0.8,
                evidence_count=len(test_files_ts),
                examples=[str(f.relative_to(self._root)) for f in test_files_ts[:3]],
            ))

        return conventions

    def _extract_imports(self) -> List[Convention]:
        """Detect import style conventions."""
        files = self._sample_files(".py", max_files=20)
        if not files:
            return []

        rel_import_count = 0
        abs_import_count = 0
        star_import_count = 0
        total = 0

        for fpath in files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            total += 1
            rel = len(re.findall(r"^from\s+\.", text, re.MULTILINE))
            abso = len(re.findall(r"^from\s+[a-zA-Z]", text, re.MULTILINE))
            star = len(re.findall(r"^from\s+\S+\s+import\s+\*", text, re.MULTILINE))
            if rel > 0:
                rel_import_count += 1
            if abso > 0:
                abs_import_count += 1
            if star > 0:
                star_import_count += 1

        if total == 0:
            return []

        conventions = []
        if abs_import_count > rel_import_count:
            conventions.append(Convention(
                category="imports",
                rule="Absolute imports preferred — avoid relative imports",
                confidence=round(abs_import_count / total, 2),
                evidence_count=abs_import_count,
                examples=[],
            ))
        elif rel_import_count > abs_import_count:
            conventions.append(Convention(
                category="imports",
                rule="Relative imports used for within-package imports",
                confidence=round(rel_import_count / total, 2),
                evidence_count=rel_import_count,
                examples=[],
            ))

        if star_import_count == 0:
            conventions.append(Convention(
                category="imports",
                rule="No star imports — always explicit",
                confidence=0.9,
                evidence_count=total,
                examples=[],
            ))

        return conventions

    def _extract_structure(self) -> List[Convention]:
        """Detect directory layout patterns."""
        conventions = []
        dirs = [
            d for d in self._root.iterdir()
            if d.is_dir() and d.name not in _SKIP_DIRS and not d.name.startswith(".")
        ]
        dir_names = {d.name for d in dirs}

        # Detect src/ layout
        if "src" in dir_names:
            conventions.append(Convention(
                category="structure",
                rule="Source code in src/ directory",
                confidence=0.9,
                evidence_count=1,
                examples=["src/"],
            ))

        # Detect feature vs layer structure
        if {"routes", "models", "services"} & dir_names:
            conventions.append(Convention(
                category="structure",
                rule="Layer-based structure: routes/, models/, services/",
                confidence=0.8,
                evidence_count=len({"routes", "models", "services"} & dir_names),
                examples=list({"routes", "models", "services"} & dir_names)[:3],
            ))
        elif all(any((self._root / n / sub).exists()
                     for sub in ["models.py", "routes.py", "service.py"])
                 for n in list(dir_names)[:2] if (self._root / n).is_dir()):
            conventions.append(Convention(
                category="structure",
                rule="Feature-based structure: each feature has own directory",
                confidence=0.7,
                evidence_count=len(dirs),
                examples=[d.name for d in dirs[:3]],
            ))

        return conventions

    def _sample_files(self, extension: str, max_files: int = 20) -> List[Path]:
        """Return up to max_files source files with the given extension."""
        found: List[Path] = []
        # Prefer src/ or lib/ — if found there, don't fall back to root
        for prio_dir in ["src", "lib"]:
            pdir = self._root / prio_dir
            if pdir.is_dir():
                for fpath in sorted(pdir.rglob(f"*{extension}")):
                    if not any(p in _SKIP_DIRS for p in fpath.parts):
                        found.append(fpath)
                        if len(found) >= max_files:
                            return found
        if found:
            return found

        # Fall back to root only when src/lib have nothing
        for fpath in sorted(self._root.rglob(f"*{extension}")):
            if any(p in _SKIP_DIRS for p in fpath.parts):
                continue
            if fpath not in found:
                found.append(fpath)
            if len(found) >= max_files:
                break
        return found

    # ------------------------------------------------------------------
    # Violation checker
    # ------------------------------------------------------------------

    def _check_violation(
        self, content: str, file_path: str, category: str, rule: str
    ) -> Optional[str]:
        """Check if content violates a specific rule."""
        ext = Path(file_path).suffix.lower()

        if category == "error_handling":
            if "avoid raising exceptions" in rule:
                # Check for raise statements in new Python content
                if ext == ".py" and re.search(r"\braise\s+\w+", content):
                    return f"CONVENTION (error_handling): uses 'raise' but project uses Result types"
            elif "wrap external calls" in rule:
                # Check boundary files for missing try/except
                if ext == ".py" and not re.search(r"\btry\s*:", content):
                    if len(content.splitlines()) > 8:  # only flag non-trivial content
                        return None  # handled by Check C in post-write-analyzer

        elif category == "naming":
            if "snake_case" in rule and ext == ".py":
                # Check for camelCase function names
                camel_funcs = re.findall(r"\bdef\s+([a-z][A-Za-z0-9]*[A-Z][a-z])", content)
                if camel_funcs:
                    return f"CONVENTION (naming): camelCase function '{camel_funcs[0]}' — project uses snake_case"
            elif "camelCase" in rule and ext in {".ts", ".tsx", ".js"}:
                snake_funcs = re.findall(r"\bfunction\s+([a-z][a-z0-9]+_[a-z])", content)
                if snake_funcs:
                    return f"CONVENTION (naming): snake_case function '{snake_funcs[0]}' — project uses camelCase"

        elif category == "imports":
            if "No star imports" in rule and ext == ".py":
                if re.search(r"^from\s+\S+\s+import\s+\*", content, re.MULTILINE):
                    return "CONVENTION (imports): star import found — project uses explicit imports"
            elif "Absolute imports" in rule and ext == ".py":
                if re.search(r"^from\s+\.", content, re.MULTILINE):
                    return "CONVENTION (imports): relative import found — project uses absolute imports"

        return None


def get_convention_extractor(
    project_root: Optional[Path] = None,
    op_dir: Optional[Path] = None,
) -> ConventionExtractor:
    """Module-level factory."""
    if project_root is None:
        from optimusprime.utils import find_project_root
        project_root = find_project_root() or Path.cwd()
    if op_dir is None:
        from optimusprime.utils import find_optimusprime_dir
        op_dir = find_optimusprime_dir()
        if op_dir is None:
            raise FileNotFoundError("No .optimusprime/ directory found")
    return ConventionExtractor(project_root, op_dir)
