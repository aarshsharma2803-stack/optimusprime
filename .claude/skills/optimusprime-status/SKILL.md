---
name: optimusprime-status
description: >
  Quick OptimusPrime status — tokens, decisions, loop streak, compression,
  active Auto Bots. One-line summary of what's running.
  Trigger: /optimusprime-status, user asks "op status", "what's active", "how are we doing"
---

Show OptimusPrime status. Find `.optimusprime/` by walking up from cwd.

Read and display:

```
⚡ OP STATUS
━━━━━━━━━━━━━━━━━━━━━━━
Tokens:      [cost-log.json → last token_estimate]k
Decisions:   [decisions.md → count DECIDED lines]
Loop streak: [loop-state.json → len(consecutive_failures)] [⚠️ if ≥2]
Compression: [compression-log.json → avg ratio]%
Bots active: [skills.json → mode=auto skills → bot_name from registry.json]
Hooks:       [count hooks in ~/.claude/settings.json with op scripts] firing
━━━━━━━━━━━━━━━━━━━━━━━
```

If `.optimusprime/` not found: create it and say "Initialized."
