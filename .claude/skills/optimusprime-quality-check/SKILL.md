---
name: optimusprime-quality-check
description: >
  Run a code quality check on recently modified files — SOLID, DRY, KISS, YAGNI,
  security vulnerabilities, SQL injection, hardcoded secrets, overly long functions.
  Trigger: /optimusprime-quality-check, user says "quality check", "code review",
  "check my code", "run quality gate"
---

Run a code quality check on recently modified files.

## Step 1: Find files to check

Find `.optimusprime/` by walking up from cwd. Read `session-snapshot.md` → CHANGED list.
If no snapshot: ask user which files to check.

## Step 2: For each file, check

**SOLID violations:**
- Functions over 30 lines → likely violates Single Responsibility
- Classes doing >3 unrelated things → SRP violation

**DRY violations:**
- Same logic in 3+ places → extract

**Security:**
- Hardcoded credentials: `password = "..."`, `api_key = "..."`, `secret = "..."`
- SQL concatenation: `"SELECT..." + user_input` or `f"SELECT...{var}"`
- Use of `eval()`, `exec()`, `subprocess` with user input

**YAGNI:**
- Unused parameters
- Functions that are defined but never called
- Config options with only one possible value

## Step 3: Report

```
🔍 QUALITY CHECK REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Files checked: [n]
Issues found:  [n]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[file]: [issue] — [fix suggestion]
...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL (fix now): [list security issues]
IMPORTANT (fix soon): [list SOLID/DRY]
MINOR (optional): [list YAGNI]
```

If no issues: "✅ Quality check passed — no issues found."
