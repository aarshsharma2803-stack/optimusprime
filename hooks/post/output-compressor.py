#!/usr/bin/env python3
"""PostToolUse hook: strips preamble/postamble/filler from tool response text.

Zero overhead when nothing to strip — exits 0 immediately.
Never modifies content inside ``` code blocks.
Outputs compressed text via additionalContext field.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

# Minimum output length before we bother compressing (short outputs aren't worth it)
_MIN_COMPRESS_LEN = 200

# Filler patterns — each is (compiled_regex, replacement)
# Order matters: preambles first, then postambles, restatements, transitions
_PROSE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Preambles — "Here's the implementation:", "Let me create...", "I'll now..."
    (re.compile(
        r"^(?:Here(?:'s| is) (?:the |my |an? )?(?:implementation|solution|code|file|update(?:d)?(?: (?:file|version))?|change|modification)[:\.]?)\s*$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Let me (?:create|write|implement|update|modify|fix|add|show|walk you through|break down)[^\n]{0,80})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:I(?:'ll| will)(?: now)? (?:create|write|implement|update|modify|fix|add|show|walk you through)[^\n]{0,80})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Sure[!,]?\s+(?:I(?:'ll| will|'d be happy to)|Let me|Here(?:'s| is))[^\n]{0,80})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Of course[!,]?\s+[^\n]{0,80})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Certainly[!,]?\s+[^\n]{0,80})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    # Postambles — "I've created the file above", "The above code..."
    (re.compile(
        r"^(?:I(?:'ve| have) (?:created|written|implemented|updated|modified|added)[^\n]{0,100}(?:above|file|implementation|code)[^\n]{0,60})$",
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
    # Restatements — "As you asked me to", "Per your request"
    (re.compile(
        r"^(?:As you (?:asked|requested)[^\n]{0,80})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Following your (?:instructions?|request)[^\n]{0,80})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Per your (?:instructions?|request)[^\n]{0,80})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    # Filler transitions — "Now let's", "Next, I'll", "Moving on to"
    (re.compile(
        r"^(?:Now let(?:'s|'s|s) [^\n]{0,80})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Next,? I(?:'ll| will) [^\n]{0,80})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
    (re.compile(
        r"^(?:Moving on to [^\n]{0,80})$",
        re.MULTILINE | re.IGNORECASE,
    ), ""),
]

_MULTI_BLANK = re.compile(r"\n{3,}")


def _strip_prose(text: str) -> str:
    for pattern, replacement in _PROSE_PATTERNS:
        text = pattern.sub(replacement, text)
    return _MULTI_BLANK.sub("\n\n", text)


def _compress(text: str) -> tuple[str, int]:
    """Compress text, skipping code blocks. Returns (compressed, chars_removed)."""
    # Split on fenced code blocks — odd indices are inside code blocks
    segments = re.split(r"(```[\s\S]*?```)", text)
    result_parts: list[str] = []
    for i, seg in enumerate(segments):
        if i % 2 == 1:  # inside code block — untouched
            result_parts.append(seg)
        else:
            result_parts.append(_strip_prose(seg))
    compressed = "".join(result_parts)
    return compressed, len(text) - len(compressed)


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
            # Some tools return list of content blocks
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

        # Only PostToolUse fires this hook
        if payload.get("hook_event_name") not in ("PostToolUse", None, ""):
            sys.exit(0)

        output_text = _extract_output(payload)
        if not output_text or len(output_text) < _MIN_COMPRESS_LEN:
            sys.exit(0)

        compressed, chars_removed = _compress(output_text)
        if chars_removed <= 0:
            sys.exit(0)

        # Only output if we saved something meaningful (>20 chars or >5%)
        if chars_removed < 20 and chars_removed / len(output_text) < 0.05:
            sys.exit(0)

        print(json.dumps({
            "additionalContext": (
                f"[OPTIMUSPRIME output-compressor: removed {chars_removed} chars of filler]\n"
                + compressed
            )
        }))
        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
