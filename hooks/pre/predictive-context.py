#!/usr/bin/env python3
"""PreToolUse hook: injects semantically relevant context before each tool call.

Uses IntelligenceEngine to predict which decisions, failures, and patterns
are most relevant to the current tool call. Injects this as additionalContext.

On first call per session: also injects full session snapshot.
On subsequent calls: injects only predicted context (lightweight).

Never blocks. Always exits 0. Silent when nothing relevant found.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

# ---------------------------------------------------------------------------
# Signal extraction helpers (pure stdlib, no external imports needed)
# ---------------------------------------------------------------------------

_FUNC_PATTERNS = [
    re.compile(r"def\s+([a-zA-Z_]\w+)"),
    re.compile(r"function\s+([a-zA-Z_]\w+)"),
    re.compile(r"const\s+([a-zA-Z_]\w+)\s*=\s*(?:async\s+)?\("),
    re.compile(r"export\s+(?:default\s+)?function\s+([a-zA-Z_]\w+)"),
    re.compile(r"class\s+([A-Z]\w*)"),
]

_STOP = frozenset({
    "the", "a", "an", "is", "in", "of", "to", "and", "or", "for",
    "on", "at", "by", "with", "as", "be", "was", "are", "not",
    "it", "we", "i", "do", "so", "up", "no", "via",
})


def _extract_function_names(text: str) -> list:
    found = []
    for pat in _FUNC_PATTERNS:
        found.extend(pat.findall(text))
    return found[:6]


def _signals_for_write_edit(tool_name: str, tool_input: dict) -> list:
    sigs = [tool_name]
    fp = tool_input.get("file_path", "")
    if fp:
        p = Path(fp)
        sigs.extend([p.name, p.suffix.lstrip("."), p.parent.name])
    for key in ("content", "old_string", "new_string"):
        val = tool_input.get(key, "")
        if val and isinstance(val, str):
            sigs.extend(_extract_function_names(val))
            break
    return [s for s in sigs if s and len(s) > 1]


def _signals_for_bash(tool_input: dict) -> list:
    cmd = tool_input.get("command", "")
    sigs = ["Bash"]
    for tok in cmd.split():
        if "/" in tok or (len(tok) > 3 and "." in tok[1:-1]):
            sigs.append(tok)
        if len(sigs) > 8:
            break
    cmd_lower = cmd.lower()
    for kw in ("fix", "debug", "error", "test", "fail"):
        pos = cmd_lower.find(kw)
        if pos != -1:
            sigs.append(cmd[pos : pos + 25])
    return sigs


def _signals_generic(tool_name: str, tool_input: dict) -> list:
    sigs = [tool_name]
    for val in tool_input.values():
        if isinstance(val, str):
            for tok in val.split():
                if len(tok) > 2 and tok.lower() not in _STOP:
                    sigs.append(tok)
                    if len(sigs) > 20:
                        return sigs
    return sigs


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------


def _read_session_state(op_dir: Path) -> dict:
    path = op_dir / "session-state.json"
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _write_session_state(op_dir: Path, state: dict) -> None:
    import os
    import tempfile
    path = op_dir / "session-state.json"
    try:
        fd, tmp = tempfile.mkstemp(dir=op_dir, prefix=".tmp_ss_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.rename(tmp, path)
    except Exception:
        pass


def _read_snapshot(op_dir: Path) -> str:
    path = op_dir / "session-snapshot.md"
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def _recent_failures_for_file(op_dir: Path, file_basename: str, n: int = 5) -> list:
    attempts_path = op_dir / "attempts.md"
    if not attempts_path.is_file() or not file_basename:
        return []
    results = []
    try:
        lines = attempts_path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if file_basename.lower() in line.lower():
                results.append(line.strip())
                if len(results) >= n:
                    break
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def _build_context(
    is_first_call: bool,
    snapshot: str,
    predictions: list,
    file_failures: list,
    contradictions: list,
    total_decisions: int,
) -> str:
    parts = []

    if is_first_call and snapshot:
        parts.append("=== SESSION CONTEXT ===")
        parts.append(snapshot)
        parts.append("")

    if predictions:
        decision_items = [p for p in predictions if p.get("type") == "decision"]
        failure_items = [p for p in predictions if p.get("type") == "failure"]
        if decision_items:
            label = f"=== RELEVANT DECISIONS ({len(decision_items)} of {total_decisions}) ==="
            parts.append(label)
            for item in decision_items:
                content = item.get("content", "").strip()
                score = item.get("score", 0)
                if content:
                    # Strip log prefix [ts] [tag] PREFIX: from the line
                    body = re.sub(r"^\[[^\]]+\]\s+\[[^\]]+\]\s+\w+:\s*", "", content)
                    parts.append(f"  [{score:.2f}] {body[:100]}")
            if failure_items:
                parts.append("")
                parts.append("=== KNOWN FAILURE PATTERNS ===")
                for item in failure_items:
                    parts.append(f"  {item.get('content', '')[:100]}")
        parts.append("")

    if file_failures:
        fname = ""
        for line in file_failures[:1]:
            m = re.search(r"target=(\S+)", line)
            if m:
                fname = m.group(1)
        header = f"=== KNOWN FAILURES{' on ' + fname if fname else ''} ==="
        parts.append(header)
        for f in file_failures:
            parts.append(f"  {f[:120]}")
        parts.append("")

    if contradictions:
        parts.append("=== CONTRADICTIONS ===")
        for c in contradictions:
            parts.append(f"  WARNING: {c}")
        parts.append("")

    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            sys.exit(0)

        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input") or {}
        session_id = payload.get("session_id", "")

        if not isinstance(tool_input, dict):
            tool_input = {}

        # Step 2 — Extract signals
        tn_lower = tool_name.lower()
        if tn_lower in ("write", "edit", "multiedit", "notebookedit"):
            signals = _signals_for_write_edit(tool_name, tool_input)
        elif tn_lower == "bash":
            signals = _signals_for_bash(tool_input)
        else:
            signals = _signals_generic(tool_name, tool_input)

        # Step 3 — Locate .optimusprime/
        try:
            from optimusprime.utils import find_optimusprime_dir, write_json_safe
        except Exception:
            sys.exit(0)

        op_dir = find_optimusprime_dir()
        if op_dir is None:
            sys.exit(0)

        # Step 3b — Load IntelligenceEngine (wraps import failure safely)
        try:
            from optimusprime.intelligence import IntelligenceEngine
            engine = IntelligenceEngine(op_dir)
        except Exception:
            sys.exit(0)

        total_decisions = len(engine._decisions)

        # Step 4 — Get predictions
        predictions = []
        try:
            predictions = engine.predict_context_needs(
                tool_name=tool_name,
                tool_input=tool_input,
                top_k=5,
            )
        except Exception:
            pass

        # Step 5 — Load patterns.json for failure patterns
        patterns_data = {}
        try:
            import json as _json
            pf = op_dir / "patterns.json"
            if pf.is_file():
                patterns_data = _json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            pass

        # Step 6 — File-specific failure history
        file_basename = ""
        fp = tool_input.get("file_path", "")
        if fp:
            file_basename = Path(fp).name

        file_failures = _recent_failures_for_file(op_dir, file_basename)

        # Step 7 — Contradiction check on most recent decision
        contradictions = []
        try:
            if engine._decisions and len(engine._decisions) >= 2:
                last_dec = engine._decisions[-1]
                cs = engine.detect_contradictions(last_dec, engine._decisions[:-1])
                hard = [c for c in cs if c.severity == "hard"]
                for c in hard[:2]:
                    contradictions.append(c.explanation)
        except Exception:
            pass

        # Step 8 — Session state (first call vs subsequent)
        state = _read_session_state(op_dir)
        is_first_call = not state.get("first_call_done", False)

        # Update state
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        date_part = now_iso[:10].replace("-", "")
        time_part = now_iso[11:19].replace(":", "")
        new_state = {
            "first_call_done": True,
            "session_start": state.get("session_start", now_iso),
            "session_id": state.get("session_id", f"{date_part}-{time_part}"),
            "tool_call_count": state.get("tool_call_count", 0) + 1,
        }
        _write_session_state(op_dir, new_state)

        # Step 9 — Snapshot (first call only)
        snapshot = ""
        if is_first_call:
            snapshot = _read_snapshot(op_dir)

        # Only inject context if there's something useful
        if not predictions and not file_failures and not contradictions and not (is_first_call and snapshot):
            sys.exit(0)

        # Step 9b — Build context
        context = _build_context(
            is_first_call=is_first_call,
            snapshot=snapshot,
            predictions=predictions,
            file_failures=file_failures,
            contradictions=contradictions,
            total_decisions=total_decisions,
        )

        if not context.strip():
            sys.exit(0)

        # Step 10 — Output and exit
        print(json.dumps({"additionalContext": context}))
        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
