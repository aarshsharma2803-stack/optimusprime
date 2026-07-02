---
name: optimusprime-repair
description: >
  Diagnose and escape a repair loop — shows current error, how many times
  it's been tried, what failed before, and suggests a different approach.
  Trigger: /optimusprime-repair, user says "stuck", "loop", "keep failing",
  "same error", "help me fix this"
---

Diagnose the current repair loop and escape it.

## Step 1: Read the loop state

Find `.optimusprime/` by walking up from cwd. Read:
- `loop-state.json` → consecutive_failures list (error text, tool, target)
- `attempts.md` → all failed attempts this session

## Step 2: Diagnose

Show:
```
🔁 REPAIR LOOP DIAGNOSIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Error:    [most recent error text]
Attempts: [n] — same error pattern
Tool:     [Write/Edit/Bash]
Target:   [file or command]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Failed approaches (do not retry):
[list from attempts.md]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Step 3: Escape strategy

Based on the error pattern, suggest ONE different approach:
- If same file edit failing: try a different edit strategy or rewrite the section
- If tool failing: try a different tool
- If logic error: step back and re-read the target file before editing
- If dependency error: check what the file imports and fix the root cause first

## Step 4: Reset loop state

After proposing the escape strategy, clear `.optimusprime/loop-state.json` to `{"consecutive_failures":[]}` so the detector starts fresh.

If `.optimusprime/` missing: say "No loop state found — no active repair loop detected."
