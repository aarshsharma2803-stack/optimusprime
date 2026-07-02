#!/usr/bin/env python3
"""PostToolUse hook: 6-pass compression of tool response text.

Pass 1: strip full preamble/postamble/filler lines
Pass 2: collapse multi-sentence explanation paragraphs after code blocks
Pass 3: remove inline technical restatement sentences from mixed paragraphs
Pass 4: repeated reasoning compression (heavy explanation → first sentence only)
Pass 5: strip verbose tool success messages
Pass 6: strip boilerplate code comments that mirror function signatures

Zero overhead when nothing to strip — exits 0 immediately.
Code blocks untouched except Pass 6 (redundant comment removal).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

_MIN_COMPRESS_LEN = 200

# ---------------------------------------------------------------------------
# Pass 1 — full filler line removal (existing)
# ---------------------------------------------------------------------------

_PROSE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Preambles
    (re.compile(
        r"^(?:Here(?:'s| is) (?:the |my |an? )?(?:implementation|solution|code|file|update(?:d)?(?: (?:file|version))?|change|modification)[^\n]{0,200})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Let me (?:create|write|implement|update|modify|fix|add|show|walk you through|break down)[^\n]{0,200})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:I(?:'ll| will)(?: now)? (?:create|write|implement|update|modify|fix|add|show|walk you through)[^\n]{0,200})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Sure[!,]?\s+(?:I(?:'ll| will|'d be happy to)|Let me|Here(?:'s| is))[^\n]{0,200})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Of course[!,]?\s+[^\n]{0,200})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Certainly[!,]?\s+[^\n]{0,200})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    # Postambles
    (re.compile(
        r"^(?:I(?:'ve| have) (?:created|written|implemented|updated|modified|added)[^\n]{0,100}(?:above|file|implementation|code)[^\n]{0,100})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:The (?:above |)(?:code|implementation|file|solution|change)[^\n]{0,100})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:This (?:implementation|code|file|solution|change)[^\n]{0,100})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    # Restatements
    (re.compile(
        r"^(?:As you (?:asked|requested)[^\n]{0,200})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Following your (?:instructions?|request)[^\n]{0,200})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Per your (?:instructions?|request)[^\n]{0,200})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    # Filler transitions
    (re.compile(
        r"^(?:Now let(?:'s|'s|s) [^\n]{0,200})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Next,? I(?:'ll| will) [^\n]{0,200})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Moving on to [^\n]{0,200})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
]

_MULTI_BLANK = re.compile(r"\n{3,}")

# ---------------------------------------------------------------------------
# Pass 5 — tool success message stripping
# ---------------------------------------------------------------------------

_SUCCESS_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"^Successfully (?:created|written|implemented|added|updated|modified|"
        r"installed|removed|deleted|applied|saved|set up|completed|generated|"
        r"configured|deployed|built|fixed|resolved)[^\n]{0,250}$",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(
        r"^I(?:'ve| have) successfully [^\n]{0,250}$",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(
        r"^The (?:file|function|method|class|module|script|test|migration|"
        r"implementation|configuration) (?:has been|was) "
        r"(?:created|updated|modified|fixed|added|written|completed|generated)[^\n]{0,150}$",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(
        r"^Done[.!]\s+(?:The |I |Everything|All)[^\n]{0,150}$",
        re.MULTILINE | re.IGNORECASE,
    ),
]


def _strip_tool_success(text: str) -> str:
    """Pass 5: strip verbose tool success messages."""
    for pat in _SUCCESS_PATTERNS:
        text = pat.sub("", text)
    return _MULTI_BLANK.sub("\n\n", text)


def _strip_prose(text: str) -> str:
    for pattern, replacement in _PROSE_PATTERNS:
        text = pattern.sub(replacement, text)
    return _MULTI_BLANK.sub("\n\n", text)


# ---------------------------------------------------------------------------
# Pass 2 — post-code explanation paragraph collapse
# ---------------------------------------------------------------------------

# Sentence boundary: period/!/? followed by whitespace and a capital letter
_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')

# Signals that mean "keep this paragraph — it's user-facing or conditional"
_KEEP_SIGNALS = re.compile(
    r'\b(?:'
    r'you(?:r|\s+should|\s+can|\s+must|\s+need|\s+may|\s+want)?'
    r'|configure|install|set\s+(?:the|your)|deploy'
    r'|note(?:\s+that)?|warning|caution|important|caveat'
    r'|however\b|but\b|alternatively\b|instead\b'
    r'|if\b|when\b|unless\b|before\b|after\b'
    r'|make\s+sure|requires?|must\b|need\s+to'
    r'|raise[sd]?|throw[sn]?|exception|error(?:\s+if|\s+when)'
    r')\b',
    re.IGNORECASE,
)

# Zero-information transition/meta-commentary sentences. Pass 1 only strips
# these when they're the ENTIRE line; this catches them mid-paragraph, as the
# opening sentence of a multi-sentence explanation ("Let me explain how this
# works in detail. When you create an instance...").
_TRANSITION_SENT = re.compile(
    r'^(?:'
    r'Let me (?:explain|walk you through|break (?:this|it) down)\b'
    r'|Here(?:\'s| is) how (?:this|it) works\b'
    r'|To (?:explain|break (?:this|it) down)\b'
    r'|I(?:\'ll| will) (?:explain|walk you through)\b'
    r')',
    re.IGNORECASE,
)


def _is_self_documenting(code_block: str) -> bool:
    """True when code doesn't need prose explanation."""
    lines = code_block.splitlines()
    content = '\n'.join(l for l in lines if not l.strip().startswith('```'))
    non_blank = [l for l in content.splitlines() if l.strip()]
    if len(non_blank) <= 10:
        return True
    if '"""' in content or "'''" in content:
        return True
    # No unmistakable single-letter vars outside common loop/exception names
    allowed = set('ijknxye')
    singles = re.findall(r'\b([a-z])\s*=', content)
    if singles and all(c in allowed for c in singles):
        return True
    return False


def _collapse_post_code_prose(prose: str, is_self_doc: bool) -> str:
    """Pass 2: collapse multi-sentence explanation blocks that follow a code block.

    Per-sentence, not per-paragraph: a sentence carrying real signal (warning,
    conditional, usage instruction) survives on its own merit. Pure restatement
    sentences around it still collapse — one real warning no longer has to
    drag four filler sentences along with it to survive.
    """
    # Split preserving blank-line separators between paragraphs
    parts = re.split(r'(\n{2,})', prose)
    result: list[str] = []
    for chunk in parts:
        if re.fullmatch(r'\n*', chunk):
            result.append(chunk)
            continue
        stripped = chunk.strip()
        if not stripped:
            result.append(chunk)
            continue
        sentences = [s for s in _SENT_SPLIT.split(stripped) if s.strip()]
        # Only collapse multi-sentence chunks
        if len(sentences) <= 1:
            result.append(chunk)
            continue

        kept: list[str] = []
        found_anchor = False
        for sent in sentences:
            s = sent.strip()
            has_signal = bool(_KEEP_SIGNALS.search(s))
            if not found_anchor:
                # Zero-information transitions ("Let me explain how this works")
                # don't count as the anchor — skip to the first real sentence.
                if _TRANSITION_SENT.match(s) and not has_signal:
                    continue
                found_anchor = True
                # Anchor sentence. For self-documenting code, only keep it if
                # short (concise) or it carries real signal.
                if not is_self_doc or len(s.split()) <= 15 or has_signal:
                    kept.append(s)
            elif has_signal:
                kept.append(s)
        if kept:
            trailing = '\n' if chunk.endswith('\n') else ''
            result.append(' '.join(kept) + trailing)
        # else: nothing survived (self-doc, long/signal-free first sentence,
        # no signal sentences elsewhere) — paragraph dropped entirely
    return ''.join(result)


# ---------------------------------------------------------------------------
# Pass 3 — inline restatement sentence removal
# ---------------------------------------------------------------------------

# Sentence starters that purely describe code with no user-facing content.
# These appear within multi-sentence paragraphs (not caught by Pass 1's ^...$).
_RESTATEMENT_SENT = re.compile(
    r'^(?:'
    r'The\s+(?:\w+\s+){0,3}(?:function|method|class|middleware|decorator|handler|endpoint|'
    r'model|service|component|approach|pattern|algorithm|module|script|result|variable|'
    r'output|parameter|validator|manager|router|client|server|worker)\b'
    r'|This\s+(?:\w+\s+){0,2}(?:function|method|class|middleware|decorator|handler|endpoint|'
    r'model|service|component|approach|pattern|algorithm|ensures?|allows?|works?|uses?|provides?)\b'
    r'|It\s+(?:uses?|implements?|handles?|provides?|creates?|returns?|works?|'
    r'validates?|checks?|reads?|writes?|stores?|loads?|extracts?|attaches?|'
    r'generates?|converts?|computes?|calculates?|ensures?|allows?|supports?|maps?|wraps?)\b'
    r'|The\s+above\s+'
    r'|As\s+you\s+can\s+see'
    r')',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Pass 4 — repeated reasoning compression
# ---------------------------------------------------------------------------

def _compress_heavy_explanation(prose: str) -> str:
    """Pass 4: when response is explanation-heavy, keep first sentence per paragraph
    plus any sentence carrying real signal (warning, conditional, instruction).
    Everything else — pure restatement filler — collapses, per-sentence, not
    per-paragraph. Same reasoning as Pass 2.
    """
    parts = re.split(r'(\n{2,})', prose)
    result: list[str] = []
    for chunk in parts:
        if re.fullmatch(r'\n*', chunk):
            result.append(chunk)
            continue
        stripped = chunk.strip()
        if not stripped:
            result.append(chunk)
            continue
        sentences = [s for s in _SENT_SPLIT.split(stripped) if s.strip()]
        if len(sentences) <= 1:
            result.append(chunk)
            continue
        kept: list[str] = []
        found_anchor = False
        for sent in sentences:
            s = sent.strip()
            has_signal = bool(_KEEP_SIGNALS.search(s))
            if not found_anchor:
                if _TRANSITION_SENT.match(s) and not has_signal:
                    continue
                found_anchor = True
                kept.append(s)
            elif has_signal:
                kept.append(s)
        trailing = '\n' if chunk.endswith('\n') else ''
        result.append(' '.join(kept) + trailing)
    return ''.join(result)


def _strip_inline_restatements(prose: str) -> str:
    """Pass 3: remove restatement sentences from all paragraphs (including single-sentence).

    Pass 2 may reduce a 5-sentence explanation to 1 restatement sentence. Without
    handling the single-sentence case here that lone sentence would survive forever.
    """
    parts = re.split(r'(\n{2,})', prose)
    result: list[str] = []
    for chunk in parts:
        if re.fullmatch(r'\n*', chunk):
            result.append(chunk)
            continue
        stripped = chunk.strip()
        if not stripped:
            result.append(chunk)
            continue
        sentences = [s for s in _SENT_SPLIT.split(stripped) if s.strip()]
        if not sentences:
            result.append(chunk)
            continue
        kept: list[str] = []
        for sent in sentences:
            s = sent.strip()
            if _RESTATEMENT_SENT.match(s) and not _KEEP_SIGNALS.search(s):
                continue  # drop this sentence
            kept.append(s)
        if kept:
            trailing = '\n' if chunk.endswith('\n') else ''
            result.append(' '.join(kept) + trailing)
        # else: all sentences were restatements → paragraph dropped
    return ''.join(result)


# ---------------------------------------------------------------------------
# Pass 6 — boilerplate code comment stripping
# ---------------------------------------------------------------------------

_COMMENT_SAFE = re.compile(
    r'\b(?:TODO|FIXME|HACK|NOTE|WARN|WARNING|XXX|IMPORTANT|SECURITY|'
    r'BUG|NOQA|NOQA|TYPE:|PRAGMA|PYLINT|MYPY)\b',
    re.IGNORECASE,
)
_PY_DEF = re.compile(r'^\s*(?:async\s+)?def\s+(\w+)')
_JS_DEF = re.compile(r'^\s*(?:function|async function|const|let|var)\s+(\w+)')
_CLASS_DEF = re.compile(r'^\s*(?:class|interface|type)\s+(\w+)')


def _tokenize_name(name: str) -> set[str]:
    """Split identifier into lowercase tokens: camelCase and snake_case."""
    parts = re.findall(r'[a-z]+', re.sub(r'([A-Z])', r'_\1', name).lower())
    return {p for p in parts if len(p) > 1}


def _strip_redundant_code_comments(code_block: str) -> str:
    """Pass 6: strip # / // comments where content mirrors next function signature."""
    lines = code_block.split('\n')
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Single-line Python comment (not shebang, not type hints)
        is_py_comment = stripped.startswith('#') and not stripped.startswith('#!')
        # Single-line JS comment
        is_js_comment = stripped.startswith('//') and not stripped.startswith('///')
        if is_py_comment or is_js_comment:
            # Never strip safe comments
            if _COMMENT_SAFE.search(stripped):
                result.append(line)
                i += 1
                continue
            comment_text = stripped[1:].strip() if is_py_comment else stripped[2:].strip()
            # Find next non-empty, non-comment line
            next_def_line = None
            for j in range(i + 1, min(i + 4, len(lines))):
                nl = lines[j].strip()
                if nl and not nl.startswith('#') and not nl.startswith('//'):
                    next_def_line = lines[j]
                    break
            if next_def_line is not None:
                # Check if it's a function/class definition
                m = (_PY_DEF.match(next_def_line) or
                     _JS_DEF.match(next_def_line) or
                     _CLASS_DEF.match(next_def_line))
                if m:
                    func_tokens = _tokenize_name(m.group(1))
                    comment_tokens = set(re.findall(r'[a-z]{2,}', comment_text.lower()))
                    if func_tokens and comment_tokens:
                        overlap = len(func_tokens & comment_tokens) / len(func_tokens)
                        if overlap >= 0.70:
                            i += 1
                            continue  # drop this comment
        result.append(line)
        i += 1
    return '\n'.join(result)


# ---------------------------------------------------------------------------
# Core compression
# ---------------------------------------------------------------------------

def _compress(text: str) -> tuple[str, int]:
    """6-pass compression. Code blocks treated separately for Pass 6."""
    segments = re.split(r"(```[\s\S]*?```)", text)

    # Pass 4 trigger: compute ratio from raw text
    code_lines = sum(
        len([l for l in s.splitlines() if l.strip()])
        for i, s in enumerate(segments) if i % 2 == 1
    )
    prose_lines = sum(
        len([l for l in s.splitlines() if l.strip()])
        for i, s in enumerate(segments) if i % 2 == 0
    )
    heavy_explanation = (code_lines > 0 and prose_lines > code_lines * 2) or (
        code_lines == 0 and prose_lines > 10
    )

    result_parts: list[str] = []
    for i, seg in enumerate(segments):
        if i % 2 == 1:
            # Code block: Pass 6 only
            result_parts.append(_strip_redundant_code_comments(seg))
        else:
            # Pass 1: strip full filler lines
            seg = _strip_prose(seg)
            # Pass 5: strip tool success messages
            seg = _strip_tool_success(seg)
            # Pass 2: collapse post-code explanation paragraphs
            if i > 0:
                prev_code = segments[i - 1]
                self_doc = _is_self_documenting(prev_code)
                seg = _collapse_post_code_prose(seg, self_doc)
            # Pass 3: strip inline restatement sentences
            seg = _strip_inline_restatements(seg)
            # Pass 4: repeated reasoning compression
            if heavy_explanation:
                seg = _compress_heavy_explanation(seg)
            result_parts.append(seg)

    compressed = "".join(result_parts)
    return compressed, len(text) - len(compressed)


# ---------------------------------------------------------------------------
# Payload parsing + main
# ---------------------------------------------------------------------------

def _extract_output(payload: dict) -> str:
    """Extract text output from PostToolUse payload."""
    tr = payload.get("tool_response", {})
    if isinstance(tr, str):
        return tr
    if isinstance(tr, dict):
        out = tr.get("output", "") or tr.get("content", "")
        if isinstance(out, str):
            return out
        if isinstance(out, list):
            return " ".join(
                block.get("text", "") for block in out
                if isinstance(block, dict)
            )
    return ""


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        payload = json.loads(raw)

        if payload.get("hook_event_name") not in ("PostToolUse", None, ""):
            sys.exit(0)

        output_text = _extract_output(payload)
        if not output_text or len(output_text) < _MIN_COMPRESS_LEN:
            sys.exit(0)

        compressed, chars_removed = _compress(output_text)
        if chars_removed <= 0:
            sys.exit(0)

        # Only emit if savings are meaningful (>20 chars or >5%)
        if chars_removed < 20 and chars_removed / len(output_text) < 0.05:
            sys.exit(0)

        if os.environ.get("OP_DEBUG"):
            context = f"[OPTIMUSPRIME output-compressor: removed {chars_removed} chars of filler]\n" + compressed
        else:
            context = compressed

        # Log compression ratio and event
        _log_compression(len(output_text), len(compressed))
        _log_compression_event(payload.get("tool_name", ""))

        print(json.dumps({"additionalContext": context}))
        sys.exit(0)

    except Exception:
        sys.exit(0)


def _log_compression(chars_before: int, chars_after: int) -> None:
    """Append compression ratio to .optimusprime/compression-log.json."""
    try:
        import datetime
        ratio = (chars_before - chars_after) / chars_before * 100 if chars_before > 0 else 0.0
        entry = {
            "timestamp": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "chars_before": chars_before,
            "chars_after": chars_after,
            "ratio": round(ratio, 2),
        }
        # Find .optimusprime/ by walking up
        current = Path(__file__).resolve()
        op_dir = None
        for _ in range(12):
            candidate = current / ".optimusprime"
            if candidate.is_dir():
                op_dir = candidate
                break
            parent = current.parent
            if parent == current:
                break
            current = parent
        # Also try cwd walk
        if op_dir is None:
            current = Path.cwd()
            for _ in range(10):
                candidate = current / ".optimusprime"
                if candidate.is_dir():
                    op_dir = candidate
                    break
                parent = current.parent
                if parent == current:
                    break
                current = parent
        if op_dir is None:
            return
        log_path = op_dir / "compression-log.json"
        entries: list = []
        if log_path.is_file():
            try:
                entries = json.loads(log_path.read_text(encoding="utf-8"))
                if not isinstance(entries, list):
                    entries = []
            except Exception:
                entries = []
        entries.append(entry)
        # Keep last 100 entries
        if len(entries) > 100:
            entries = entries[-100:]
        import tempfile
        tmp = log_path.parent / f".compression-log.tmp.{os.getpid()}"
        tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        tmp.replace(log_path)
    except Exception:
        pass


def _log_compression_event(tool_name: str) -> None:
    """Append PostToolUse compressed event to events.jsonl."""
    try:
        current = Path(__file__).resolve()
        op_dir = None
        for _ in range(12):
            candidate = current / ".optimusprime"
            if candidate.is_dir():
                op_dir = candidate
                break
            parent = current.parent
            if parent == current:
                break
            current = parent
        if op_dir is None:
            current = Path.cwd()
            for _ in range(10):
                candidate = current / ".optimusprime"
                if candidate.is_dir():
                    op_dir = candidate
                    break
                parent = current.parent
                if parent == current:
                    break
                current = parent
        if op_dir is None or not op_dir.is_dir():
            return
        import datetime
        entry = json.dumps({
            "ts": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "event": "PostToolUse",
            "tool": tool_name,
            "file": "",
            "action": "compressed",
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


if __name__ == "__main__":
    main()
