---
name: optimusprime-token-report
description: >
  Token usage report — current session tokens, cost, trend across sessions,
  compression savings, and recommendations to reduce usage.
  Trigger: /optimusprime-token-report, user asks "how many tokens", "token usage",
  "cost report", "am I running out of context"
---

Show the full token usage report. Find `.optimusprime/` by walking up from cwd.

Read `cost-log.json` (all sessions) and `compression-log.json` (all entries).

Display:

```
💬 TOKEN USAGE REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Current session:  [last session token_estimate]k tokens  (~$[cost])
Context limit:    ~200k tokens (Claude)
Usage:            [n]%  [▓▓▓░░░░░░░] 
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Last 5 sessions:
  [date]  [n]k  $[cost]
  [date]  [n]k  $[cost]
  ...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Compression savings:
  Sessions compressed:  [n]
  Avg reduction:        [avg ratio]%
  Chars saved (total):  [sum chars_before - chars_after]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RECOMMENDATIONS:
```

Then add recommendations based on current token level:
- < 40k: "Usage healthy. No action needed."
- 40k–80k: "Caveman Bot should activate automatically. Run /optimusprime-compact if context feels noisy."
- 80k–150k: "Run /optimusprime-compact now. Consider /compact for built-in compaction."
- > 150k: "Critical — run /compact immediately or start a new session. Paste session-snapshot.md as first message."

If `.optimusprime/` missing: create it and say "No token history yet — first session."
