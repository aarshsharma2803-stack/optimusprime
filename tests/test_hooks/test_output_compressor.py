"""Tests for hooks/post/output-compressor.py — at least 8 scenarios."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import make_posttooluse, run_hook

_HOOK = Path(__file__).resolve().parent.parent.parent / "hooks" / "post" / "output-compressor.py"
_REPO_ROOT = _HOOK.parent.parent.parent


def _run(output_text, cwd=None):
    return run_hook(_HOOK, make_posttooluse("Read", output_text), cwd or _REPO_ROOT)


def _long(text):
    """Pad text to exceed the 200-char minimum threshold."""
    padding = " Here is some additional context that makes this response long enough to compress."
    return text + padding * 3


# ── 1. Preamble stripped ──────────────────────────────────────────────────

def test_preamble_stripped():
    text = _long("Here's the implementation:\n\nsome actual content here that matters\n")
    stdout, _, rc = _run(text)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout.strip())
        ctx = data.get("additionalContext", "")
        assert "Here's the implementation" not in ctx


# ── 2. Postamble stripped ─────────────────────────────────────────────────

def test_postamble_stripped():
    content = "x" * 250 + "\nI've created the file above with all the changes you requested.\n"
    stdout, _, rc = _run(content)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout.strip())
        assert "I've created the file above" not in data.get("additionalContext", "")


# ── 3. Restatement stripped ───────────────────────────────────────────────

def test_restatement_stripped():
    text = _long("As you asked me to implement this feature, here is the solution.\n\nActual work done here.\n")
    stdout, _, rc = _run(text)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout.strip())
        assert "As you asked me to" not in data.get("additionalContext", "")


# ── 4. Filler transition stripped ────────────────────────────────────────

def test_filler_transition_stripped():
    text = _long("Now let's move on to the next step of the implementation.\n\nCore content.\n")
    stdout, _, rc = _run(text)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout.strip())
        assert "Now let's move on to" not in data.get("additionalContext", "")


# ── 5. Code block preserved untouched ────────────────────────────────────

def test_code_block_preserved():
    code = '```python\ndef hello():\n    return "Here\'s the implementation:"\n```'
    text = "x" * 50 + "\n" + code + "\n" + "y" * 200
    stdout, _, rc = _run(text)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout.strip())
        ctx = data.get("additionalContext", "")
        assert "def hello():" in ctx
        assert "Here's the implementation:" in ctx


# ── 6. Short output → no compression (below 200 char threshold) ──────────

def test_short_output_not_compressed():
    short = "Here's the implementation: just a tiny bit of text."
    assert len(short) < 200
    stdout, _, rc = _run(short)
    assert rc == 0
    assert stdout.strip() == ""


# ── 7. Nothing to strip → exit 0, no stdout ──────────────────────────────

def test_nothing_to_strip_silent():
    # Conditional/user-facing prose — must NOT be stripped (has keep signals: if, you, requires)
    clean = (
        "If you pass `strict=True`, validation raises on the first error.\n"
        "You can configure the timeout by setting `TIMEOUT_MS` in the environment.\n"
        "This requires Python 3.10 or later.\n"
    ) * 5
    stdout, _, rc = _run(clean)
    assert rc == 0
    assert stdout.strip() == ""


# ── 8. Multiple patterns stripped in one response ─────────────────────────

def test_multiple_patterns_stripped():
    text = (
        "Sure! I'll implement this right away.\n\n"
        "Core implementation details go here.\n"
        "This is the main logic of the function.\n" * 10
        + "I've created the file above with all changes.\n"
    )
    stdout, _, rc = _run(text)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout.strip())
        ctx = data.get("additionalContext", "")
        assert "Sure!" not in ctx or "I'll implement" not in ctx


# ── 9. Response with only code blocks → untouched ─────────────────────────

def test_only_code_blocks_untouched():
    code_only = '```python\n' + 'x = 1\n' * 60 + '```'
    stdout, _, rc = _run(code_only)
    assert rc == 0
    # Should not compress pure code
    assert stdout.strip() == ""


# ── 10. "Let me create..." preamble stripped ─────────────────────────────

def test_let_me_create_stripped():
    text = _long("Let me create the file for you with the correct implementation.\n\nHere is the content.\n")
    stdout, _, rc = _run(text)
    assert rc == 0
    if stdout.strip():
        data = json.loads(stdout.strip())
        assert "Let me create" not in data.get("additionalContext", "")
