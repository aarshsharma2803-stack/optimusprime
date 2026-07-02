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


_THROTTLE_INTERVAL = 5  # full intel inject every N prompts


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
    session_id = payload.get("session_id", "")
    if not prompt or len(prompt.strip()) < 10:
        sys.exit(0)

    # Find .optimusprime/
    op_dir = _find_op_dir()
    if op_dir is None:
        # Auto-create in cwd so first-run works without manual setup
        try:
            op_dir = Path.cwd() / ".optimusprime"
            op_dir.mkdir(exist_ok=True)
        except Exception:
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

    # ---- Step 8b: Status line (always built) --------------------------------
    status_line = _build_status_line(op_dir)

    # ---- Log UserPromptSubmit event -----------------------------------------
    _log_prompt_event(op_dir)

    # ---- Throttle: status-line-only every N-1 prompts out of N ---------------
    if _should_throttle(op_dir, session_id):
        print(json.dumps({"additionalContext": status_line}))
        sys.exit(0)

    # ---- Adaptive injection: suppress sections by task type -----------------
    if action_type == "test":
        existing_code = []
    if action_type == "fix":
        pass  # keep all; quality gate "root cause" is useful
    if action_type == "review":
        existing_code = []

    # ---- Step 9: Build pre-response context ---------------------------------
    sections: list[str] = []

    # Issue 12: session start injection when no tokens yet
    try:
        cost_data = _load_json_safe(op_dir / "cost-log.json")
        sess = cost_data.get("sessions", [])
        session_tokens = sess[-1].get("token_estimate", 0) if sess else 0
        if session_tokens == 0:
            sections.append(
                "[SESSION START] Output optimization active. "
                "Minimum viable responses only."
            )
    except Exception:
        pass

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

    # ---- Section A — Token awareness ----------------------------------------
    section_a = _build_token_section(op_dir)

    # ---- Section B — Auto Bot status ----------------------------------------
    section_b = _build_autobot_section(op_dir)

    # ---- Section C — Compression status -------------------------------------
    section_c = _build_compression_section(op_dir)

    # ---- Section D — Quality gate -------------------------------------------
    section_d = _build_quality_section(action_type, complexity_flag, op_dir)

    # ---- Assemble context with priority budget (~400 tokens / 1600 chars) ---
    # Intelligence sections always first; A-D fill remaining budget.
    # Drop D → C → B → A if over limit.
    intel_body = "\n\n".join(sections)
    intel_chars = len(intel_body)
    budget = 1600 - intel_chars - 40  # 40 for wrapper

    secondary: list[tuple[str, str]] = [
        ("d", section_d),
        ("c", section_c),
        ("b", section_b),
        ("a", section_a),
    ]
    kept_secondary: list[str] = []
    remaining = budget
    for _, sec in reversed(secondary):  # priority: A > B > C > D
        if sec and len(sec) + 2 <= remaining:
            kept_secondary.append(sec)
            remaining -= len(sec) + 2

    # ---- Deduplication: skip sections already injected this session ----------
    all_sections = _dedup_sections(op_dir, session_id, sections + kept_secondary)
    if not all_sections:
        # No intel — output status line alone
        print(json.dumps({"additionalContext": status_line}))
        sys.exit(0)

    body = "\n\n".join(all_sections)
    context = f"{status_line}\n=== PRE-RESPONSE INTEL ===\n{body}\n=== END ==="

    # Hard cap (status line ≤120 + intel ≤1600)
    if len(context) > 1720:
        context = context[:1717] + "..."

    print(json.dumps({"additionalContext": context}))
    sys.exit(0)


# ---------------------------------------------------------------------------
# Sections A-D helpers
# ---------------------------------------------------------------------------

def _build_token_section(op_dir: Path) -> str:
    """Section A: token usage and compression warnings."""
    try:
        cost_path = op_dir / "cost-log.json"
        if not cost_path.is_file():
            return ""
        data = _load_json_safe(cost_path)
        sessions = data.get("sessions", [])
        if not sessions:
            return ""
        last = sessions[-1]
        tokens = last.get("token_estimate", last.get("estimated_input_tokens", 0))
        cost = last.get("estimated_cost_usd", last.get("cost_estimate", 0.0))
        if not tokens:
            return ""
        lines = [f"[TOKEN] Session: ~{tokens:,} tokens (~${cost:.4f})"]
        if tokens > 80000:
            lines.append("[TOKEN] CRITICAL — consider /compact before continuing")
            lines.append(
                "[AUTO-CAVEMAN] Caveman Bot ACTIVE. Maximum compression required. "
                "Drop all articles/filler/pleasantries. Fragments mandatory. "
                "Single-word answers when one word suffices. Technical substance only."
            )
        elif tokens > 40000:
            lines.append("[TOKEN] High usage — output-mode compression active")
            lines.append(
                "[AUTO-CAVEMAN] Caveman Bot activated. Compress all responses: "
                "drop articles/filler/pleasantries, fragments OK, keep technical substance intact."
            )
        return "\n".join(lines)
    except Exception:
        return ""


def _build_autobot_section(op_dir: Path) -> str:
    """Section B: active auto bots from skills.json."""
    try:
        skills_path = op_dir / "skills.json"
        if not skills_path.is_file():
            return ""
        data = _load_json_safe(skills_path)
        installed = data.get("installed", {})
        active = [
            name for name, meta in installed.items()
            if meta.get("mode") in ("auto", "suggested", "always")
        ]
        if active:
            return f"[AUTO BOTS] Active: {', '.join(active[:4])}"
        return "[AUTO BOTS] Standby — will activate based on context"
    except Exception:
        return ""


def _build_compression_section(op_dir: Path) -> str:
    """Section C: compression status from hooks.json + compression-log.json."""
    try:
        # Check hook registration
        hooks_path = op_dir.parent / "hooks" / "hooks.json"
        compressor_active = False
        if hooks_path.is_file():
            hooks_data = _load_json_safe(hooks_path)
            for event_hooks in hooks_data.values():
                if isinstance(event_hooks, list):
                    for h in event_hooks:
                        cmd = h.get("command", "") if isinstance(h, dict) else ""
                        if "output-compressor" in cmd:
                            compressor_active = True
                            break
        if not compressor_active:
            # Fallback: check settings.json
            import os
            settings_path = Path(os.path.expanduser("~/.claude/settings.json"))
            if settings_path.is_file():
                try:
                    s = json.loads(settings_path.read_text(encoding="utf-8"))
                    for hooks in s.get("hooks", {}).values():
                        if isinstance(hooks, list):
                            for h in hooks:
                                if "output-compressor" in h.get("command", ""):
                                    compressor_active = True
                                    break
                except Exception:
                    pass
        if not compressor_active:
            return ""
        # Check compression-log.json for ratio
        log_path = op_dir / "compression-log.json"
        if log_path.is_file():
            entries = _load_json_safe(log_path)
            if isinstance(entries, list) and entries:
                last = entries[-1]
                ratio = last.get("ratio", 0)
                if ratio > 0:
                    return f"[COMPRESSION] Active — {ratio:.1f}% avg reduction"
        return "[COMPRESSION] Active"
    except Exception:
        return ""


def _build_quality_section(action_type: str, complexity_flag: bool, op_dir: Path) -> str:
    """Section D: quality gates based on prompt action type."""
    try:
        lines = []
        if action_type in ("build", "refactor"):
            lines.append("[QUALITY] Code quality gates active — SOLID, DRY, KISS, YAGNI enforced")
        elif action_type == "fix":
            lines.append("[QUALITY] Fix mode — root cause required, not symptom patching")
        if complexity_flag:
            contract = _load_json_safe(op_dir / "contract.json")
            budget = contract.get("complexity_budget", "unknown")
            lines.append(f"[SCOPE] Complex task detected — budget is {budget}")
        return "\n".join(lines)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Status line + event logging
# ---------------------------------------------------------------------------

def _build_status_line(op_dir: Path) -> str:
    """Build compact one-line status badge. Returns '⚡OP' minimum on any error."""
    try:
        # tokens + cost
        tokens_str = "~0"
        cost_str = "$0.00"
        try:
            cost_data = _load_json_safe(op_dir / "cost-log.json")
            sessions = cost_data.get("sessions", [])
            if sessions:
                last = sessions[-1]
                t = last.get("token_estimate", last.get("estimated_input_tokens", 0))
                c = last.get("estimated_cost_usd", last.get("cost_estimate", 0.0))
                is_real = last.get("token_source", "estimated") == "real"
                if t >= 1000:
                    tokens_str = f"{t // 1000}k✓" if is_real else f"~{t // 1000}k"
                elif t > 0:
                    tokens_str = f"{t}✓" if is_real else f"~{t}"
                cost_str = f"${c:.2f}"
        except Exception:
            pass

        # decisions count
        dec_count = 0
        try:
            dp = op_dir / "decisions.md"
            if dp.is_file():
                dec_count = sum(1 for l in dp.read_text(encoding="utf-8").splitlines() if l.strip())
        except Exception:
            pass

        # active bots — Auto Bots naming
        bots_str = "standby"
        try:
            skills_data = _load_json_safe(op_dir / "skills.json")
            installed = skills_data.get("installed", {})
            active = [n for n, m in installed.items() if m.get("mode") in ("auto", "always", "suggested")]
            if active:
                # Use bot_name from registry if available
                registry = _load_registry(op_dir)
                bot_names = []
                for n in active[:3]:
                    skill_def = registry.get(n, {})
                    bot_name = skill_def.get("bot_name", f"{n.title()} Bot")
                    bot_names.append(bot_name)
                bots_str = ",".join(bot_names)
        except Exception:
            pass

        # loop streak
        loop_str = "0"
        try:
            ls = _load_json_safe(op_dir / "loop-state.json")
            streak = len(ls.get("consecutive_failures", []))
            loop_str = f"⚠{streak}" if streak >= 3 else str(streak)
        except Exception:
            pass

        # compression
        cmp_str = ""
        try:
            cl = op_dir / "compression-log.json"
            if cl.is_file():
                raw = cl.read_text(encoding="utf-8")
                entries = json.loads(raw) if raw.strip() else []
                if isinstance(entries, list) and entries:
                    ratio = entries[-1].get("ratio", 0)
                    cmp_str = f" | cmp:{ratio:.0f}%" if ratio else " | cmp:ON"
                else:
                    cmp_str = " | cmp:ON"
        except Exception:
            pass

        line = f"⚡OP | tok:{tokens_str} {cost_str} | 📝{dec_count} | 🤖{bots_str} | 🔁{loop_str}{cmp_str}"
        return line[:120] if len(line) > 120 else line
    except Exception:
        return "⚡OP"


def _log_prompt_event(op_dir: Path) -> None:
    """Append UserPromptSubmit event to events.jsonl. Silent on any error."""
    try:
        import datetime
        entry = json.dumps({
            "ts": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "event": "UserPromptSubmit",
            "tool": "",
            "file": "",
            "action": "pre-response",
        })
        log_path = op_dir / "events.jsonl"
        lines: list[str] = []
        if log_path.is_file():
            try:
                lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            except Exception:
                lines = []
        lines.append(entry)
        if len(lines) > 100:
            lines = lines[-100:]
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


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
# Throttle + dedup helpers
# ---------------------------------------------------------------------------

def _load_registry(op_dir: Path) -> dict:
    """Load ecosystem/registry.json skill definitions. Returns {} on any error."""
    try:
        plugin_root = Path(__file__).resolve().parent.parent.parent
        reg_path = plugin_root / "ecosystem" / "registry.json"
        if reg_path.is_file():
            data = json.loads(reg_path.read_text(encoding="utf-8"))
            return data.get("skills", {})
    except Exception:
        pass
    return {}


def _write_json_local(path: Path, data: dict) -> None:
    try:
        import os as _os
        tmp = path.parent / f".{path.name}.tmp.{_os.getpid()}"
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _should_throttle(op_dir: Path, session_id: str) -> bool:
    """Return True if this prompt should get status-line-only (no full intel)."""
    try:
        state_path = op_dir / "session-state.json"
        state = _load_json_safe(state_path)
        if session_id and state.get("session_id") != session_id:
            state = {}
        prompt_count = state.get("prompt_count", 0) + 1
        last_full = state.get("last_full_inject_at", 0)
        do_full = (last_full == 0) or (prompt_count - last_full >= _THROTTLE_INTERVAL)
        state["session_id"] = session_id
        state["prompt_count"] = prompt_count
        if do_full:
            state["last_full_inject_at"] = prompt_count
        _write_json_local(state_path, state)
        return not do_full
    except Exception:
        return False


def _hash_content(content: str) -> str:
    import hashlib
    return hashlib.md5(content.encode()).hexdigest()[:8]


def _dedup_sections(op_dir: Path, session_id: str, sections: list) -> list:
    """Return sections not already injected this session."""
    try:
        log_path = op_dir / "injection-log.json"
        log = _load_json_safe(log_path)
        if log.get("session_id") != session_id:
            log = {"session_id": session_id, "hashes": {}}
        existing = set(log.get("hashes", {}).keys())
        result = []
        new_hashes: dict = {}
        for sec in sections:
            h = _hash_content(sec)
            if h not in existing:
                result.append(sec)
                new_hashes[h] = 1
        all_hashes = {**log.get("hashes", {}), **new_hashes}
        if len(all_hashes) > 100:
            keys = list(all_hashes.keys())[-100:]
            all_hashes = {k: all_hashes[k] for k in keys}
        log["hashes"] = all_hashes
        _write_json_local(log_path, log)
        return result
    except Exception:
        return sections


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
