#!/usr/bin/env python3
"""PostToolUse hook: 3-pass compression of tool response text.

Pass 1: strip full preamble/postamble/filler lines (existing)
Pass 2: collapse multi-sentence explanation paragraphs after code blocks
Pass 3: remove inline technical restatement sentences from mixed paragraphs

Zero overhead when nothing to strip — exits 0 immediately.
Code blocks are never touched.
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
    """Pass 2: collapse multi-sentence explanation blocks that follow a code block."""
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
        # Keep paragraphs with user-facing language (warnings, conditionals, you/your)
        if _KEEP_SIGNALS.search(stripped):
            result.append(chunk)
            continue
        # Collapse: self-documenting code → drop entirely (or keep ≤15-word first sentence)
        # Non-self-documenting → keep first sentence only
        first = sentences[0].strip()
        if is_self_doc:
            if len(first.split()) <= 15:
                trailing = '\n' if chunk.endswith('\n') else ''
                result.append(first + trailing)
            # else: drop paragraph entirely (append nothing)
        else:
            trailing = '\n' if chunk.endswith('\n') else ''
            result.append(first + trailing)
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
# Core compression
# ---------------------------------------------------------------------------

def _compress(text: str) -> tuple[str, int]:
    """3-pass compression. Code blocks (```...```) are always untouched."""
    segments = re.split(r"(```[\s\S]*?```)", text)
    result_parts: list[str] = []

    for i, seg in enumerate(segments):
        if i % 2 == 1:
            # Inside code block — untouched
            result_parts.append(seg)
        else:
            # Pass 1: strip full filler lines
            seg = _strip_prose(seg)
            # Pass 2: collapse post-code explanation paragraphs
            if i > 0:
                prev_code = segments[i - 1]
                self_doc = _is_self_documenting(prev_code)
                seg = _collapse_post_code_prose(seg, self_doc)
            # Pass 3: strip inline restatement sentences from mixed paragraphs
            seg = _strip_inline_restatements(seg)
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
        print(json.dumps({"additionalContext": context}))
        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
