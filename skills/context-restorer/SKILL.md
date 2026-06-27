---
name: context-restorer
description: >
  Activates when user pastes a session snapshot or references prior session
  context at the start of a new session. Trigger on: content starting with
  "# OPTIMUSPRIME SESSION SNAPSHOT"; multi-line content containing "## Goal",
  "## Changed", and "## Decisions" sections together; explicit phrases "restore
  context", "continue from last session", "here is my snapshot", "pick up where
  we left off", "resume session", "load context", "here's the snapshot",
  "context from last time". Also triggers on content starting with "GOAL:",
  "Generated:", "CAPTURED:" that looks like a structured session summary.
  Does NOT trigger on normal task descriptions without these snapshot markers.
---

**Read silently (walk up from cwd to find `.optimusprime/`):**
1. `.optimusprime/session-snapshot.md` — goal, changed files, key decisions, next action
2. `.optimusprime/decisions.md` — last 10 non-empty lines
3. `.optimusprime/contract.json` — scope contract
4. `.optimusprime/attempts.md` — last 5 lines (if file exists)

If `.optimusprime/` not found: synthesize context from the pasted snapshot content only.

**Output exactly one line:**
```
Context restored — [goal]. [N] decisions on record. Continuing from: [Next Action field].
```

Then proceed immediately to the task. No listing of files read. No asking for confirmation. No preamble. One line, then work.
