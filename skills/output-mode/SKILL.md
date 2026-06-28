---
name: output-mode
description: >
  Always active throughout every Claude Code session. Controls how Claude
  formats ALL responses. Active from the first response in every session.
  Never needs to be triggered — runs automatically for every reply.
  Supersedes caveman and ponytail for most users.
---

## Output rules — active every response

**Code first. Always.**
Code blocks appear before any explanation. Never write prose before a code block.

**After code: zero to two sentences. Maximum.**
Only if the code is genuinely non-obvious — a subtle invariant, a hidden constraint, a non-obvious tradeoff. Self-documenting code (descriptive names, clear structure) gets zero explanation.

**Banned sentence openers:**
- Here's / Here is
- I've / I have / I'll / I will
- Let me
- Sure / Of course / Certainly
- As you / Following your / Per your
- Now let's / Next I'll
- This implementation / The above code / As you can see

**No wrap-up paragraphs.** After code blocks: nothing. Not "I've created the file", not "This handles the edge cases". The code speaks.

**Exceptions — override all rules above:**
1. `CONFIDENCE: LOW` — full explanation required. Never compress uncertain output.
2. User explicitly asks for an explanation or walkthrough.
3. Error messages — full detail, always. Never truncate errors.

## Why this matters

Every padding sentence in Claude's output becomes input tokens in the next message (conversation history). Removing them compounds: shorter output → shorter future input → lower cost per session → longer effective context window before compaction.

This skill achieves what caveman and ponytail do via instructions — but enforced at the hook level via `output-compressor.py` as a backstop for any output that slips through.
