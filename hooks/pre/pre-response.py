#!/usr/bin/env python3
"""UserPromptSubmit hook: pre-response intelligence injection.

Fires BEFORE Claude responds to any user message.
Reads IntelligenceEngine + SelfModel + codebase-map to inject
relevant warnings, past decisions, and contradiction risks
before Claude forms its approach.

Exit 0 always — never blocks.
Performance target: under 150ms total.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

# ---------------------------------------------------------------------------
# Signal patterns
# ---------------------------------------------------------------------------

_ACTION_VERBS: dict[str, list[str]] = {
    "fix":     ["fix", "debug", "repair", "patch", "broken", "bug", "error", "wrong"],
    "build":   ["build", "create", "add", "implement", "write", "make", "new"],
    "refactor":["refactor", "restructure", "rename", "move", "reorganize", "clean"],
    "test":    ["test", "verify", "check", "validate", "assert", "coverage"],
    "review":  ["review", "audit", "analyse", "analyze", "inspect", "read"],
}

_COMPLEXITY_SIGNALS = frozenset({
    "entire", "all", "everything", "complete", "full", "whole",
    "every", "all of", "the whole", "end to end", "end-to-end",
    "comprehensive", "rewrite",
})

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "it", "in", "of", "to", "and", "or", "for",
    "on", "at", "by", "with", "as", "be", "was", "are", "not", "we", "i",
    "via", "vs", "per", "its", "this", "that", "our", "all", "can", "has",
    "had", "have", "will", "from", "into", "over", "when", "than", "then",
    "so", "also", "more", "no", "up", "out", "if", "do", "use", "using",
})

# File path patterns in a prompt
_FILE_REF_RE = re.compile(
    r"(?:^|[\s\"'])([./~]?[\w./\-]+\.[a-zA-Z]{1,5})(?:[\s\"':,]|$)"
)


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

    # UserPromptSubmit format: {session_id, prompt}
    prompt = payload.get("prompt", "")
    if not prompt or len(prompt.strip()) < 10:
        sys.exit(0)

    # Find .optimusprime/
    op_dir = _find_op_dir()
    if op_dir is None:
        sys.exit(0)

    # ---- Step 3: Extract signals from prompt --------------------------------
    file_refs = _extract_file_refs(prompt)
    action_type = _infer_action_type(prompt)
    topic_keywords = _extract_keywords(prompt)
    complexity_flag = _detect_complexity(prompt)

    # ---- Step 4: SelfModel warnings -----------------------------------------
    warnings: list[str] = []
    try:
        from optimusprime.self_model import SelfModel
        sm = SelfModel(op_dir)
        warnings = sm.get_warnings_for_task(
            task_description=prompt,
            file_path=file_refs[0] if file_refs else None,
        )
    except Exception:
        pass

    # ---- Step 5: IntelligenceEngine past decisions --------------------------
    past_decisions: list[dict] = []
    try:
        from optimusprime.intelligence import IntelligenceEngine
        engine = IntelligenceEngine(op_dir)
        results = engine.predict_context_needs(
            tool_name="UserPromptSubmit",
            tool_input={"prompt": prompt[:200]},
            top_k=3,
        )
        past_decisions = [r for r in results if r.get("score", 0) > 0.3]
    except Exception:
        pass

    # ---- Step 6: Contradiction risk -----------------------------------------
    contradictions: list[str] = []
    if action_type in ("build", "refactor"):
        try:
            contradictions = _check_contradictions(op_dir, prompt)
        except Exception:
            pass

    # ---- Step 7: Complexity budget check ------------------------------------
    scope_alert: str = ""
    if complexity_flag:
        try:
            contract = _load_json_safe(op_dir / "contract.json")
            budget = contract.get("complexity_budget", "")
            if budget and budget.lower() in ("minimal", "low", "small"):
                scope_alert = (
                    f"Task sounds complex but budget is {budget}"
                )
        except Exception:
            pass

    # ---- Step 8: Codebase map context ---------------------------------------
    existing_code: list[str] = []
    if file_refs:
        try:
            from optimusprime.codebase_map import CodebaseMap
            root = _find_project_root() or Path.cwd()
            cm = CodebaseMap(root, op_dir)
            # Use cached map only — no scanning
            relevant = cm.get_relevant_for_file(file_refs[0])
            for name, entry in list(relevant.items())[:3]:
                f = entry.get("file", "")
                existing_code.append(f"{name} exists in {f}")
        except Exception:
            pass

    # ---- Step 9: Build pre-response context ---------------------------------
    sections: list[str] = []

    if warnings:
        lines = ["[WARNINGS]"]
        for w in warnings[:3]:
            lines.append(f"  • {w}")
        sections.append("\n".join(lines))

    if past_decisions:
        lines = ["[PAST DECISIONS]"]
        for d in past_decisions[:3]:
            content = d.get("content", "")
            score = d.get("score", 0)
            # Truncate and clean
            snippet = content[:80].replace("\n", " ").strip()
            lines.append(f"  • {snippet} (score={score:.2f})")
        sections.append("\n".join(lines))

    if contradictions:
        lines = ["[CONTRADICTION RISK]"]
        for c in contradictions[:2]:
            lines.append(f"  • {c}")
        sections.append("\n".join(lines))

    if scope_alert:
        sections.append(f"[SCOPE ALERT]\n  • {scope_alert}")

    if existing_code:
        lines = ["[EXISTING CODE]"]
        for item in existing_code:
            lines.append(f"  • {item} — consider reusing")
        sections.append("\n".join(lines))

    if not sections:
        sys.exit(0)

    body = "\n\n".join(sections)
    context = f"=== PRE-RESPONSE INTEL ===\n{body}\n=== END ==="

    # Keep total under 300 tokens (~1200 chars)
    if len(context) > 1200:
        context = context[:1197] + "..."

    print(json.dumps({"additionalContext": context}))
    sys.exit(0)


# ---------------------------------------------------------------------------
# Signal extraction helpers
# ---------------------------------------------------------------------------

def _extract_file_refs(prompt: str) -> list[str]:
    """Extract file paths mentioned in the prompt."""
    refs = []
    for m in _FILE_REF_RE.finditer(prompt):
        path = m.group(1).strip()
        # Must look like a real path (has / or .)
        if ("/" in path or path.startswith(".")) and len(path) > 3:
            refs.append(path)
    # Also look for bare python module names like "src/foo.py"
    for m in re.finditer(r"\b(src/\S+|hooks/\S+|tests/\S+)\b", prompt):
        p = m.group(1).rstrip(".,)")
        if p not in refs:
            refs.append(p)
    return refs[:5]


def _infer_action_type(prompt: str) -> str:
    """Infer the action type from the prompt verbs."""
    lower = prompt.lower()
    best = "general"
    best_count = 0
    for action, verbs in _ACTION_VERBS.items():
        count = sum(1 for v in verbs if re.search(r"\b" + re.escape(v) + r"\b", lower))
        if count > best_count:
            best_count = count
            best = action
    return best


def _extract_keywords(prompt: str) -> list[str]:
    """Tokenize prompt, remove stop words, return content words."""
    words = re.findall(r"\b[a-z]\w+\b", prompt.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 3]


def _detect_complexity(prompt: str) -> bool:
    """Return True if prompt contains high-complexity signal words."""
    lower = prompt.lower()
    return any(sig in lower for sig in _COMPLEXITY_SIGNALS)


def _check_contradictions(op_dir: Path, prompt: str) -> list[str]:
    """Quick check: does the prompt mention anything previously REJECTED?"""
    contradictions = []
    decisions_path = op_dir / "decisions.md"
    if not decisions_path.is_file():
        return []

    prompt_lower = prompt.lower()
    prompt_words = set(re.findall(r"\b\w{4,}\b", prompt_lower))

    try:
        lines = decisions_path.read_text(encoding="utf-8").splitlines()
        # Only check last 20 decisions for speed
        for line in reversed(lines[-20:]):
            # Look for REJECTED: field
            m = re.search(r"REJECTED:\s*([^|]+)", line, re.IGNORECASE)
            if m:
                rejected_terms = [t.strip().lower() for t in m.group(1).split(",")]
                for term in rejected_terms:
                    term_words = set(re.findall(r"\b\w{4,}\b", term))
                    if term_words and term_words & prompt_words:
                        ts_m = re.match(r"^\[([^\]]+)\]", line)
                        ts = ts_m.group(1) if ts_m else "?"
                        contradictions.append(
                            f"Prompt mentions '{term}' — previously REJECTED ({ts[:10]})"
                        )
    except Exception:
        pass
    return contradictions[:2]


# ---------------------------------------------------------------------------
# Pure-stdlib helpers
# ---------------------------------------------------------------------------

def _find_op_dir() -> "Path | None":
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


def _load_json_safe(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


if __name__ == "__main__":
    main()
