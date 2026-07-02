---
name: optimusprime-dashboard
description: >
  Full OptimusPrime dashboard — goal, tokens, decisions, loops, compression,
  active Auto Bots, recent decisions, open TODOs, next action.
  Trigger: /optimusprime-dashboard, user says "show dashboard", "full status", "op dashboard"
---

Show the full OptimusPrime dashboard. Find `.optimusprime/` by walking up from cwd.

Read all files and display:

```
⚡ OPTIMUSPRIME DASHBOARD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 Goal:        [contract.json → goal]
📋 Budget:      [contract.json → complexity_budget]
💬 Tokens:      [cost-log.json]k  (~$[cost])
📝 Decisions:   [count] logged
🔁 Loop streak: [n] [⚠️ if ≥2]
📊 Compression: [avg ratio]%  ([n] sessions)
🤖 Active Bots: [skills.json → auto/always → bot_name]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RECENT DECISIONS (last 5):
[last 5 DECIDED lines from decisions.md]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OPEN TODOS:
[todos.md contents or "none"]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEXT ACTION:
[session-snapshot.md → NEXT line]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Hooks firing: [count from ~/.claude/settings.json op entries]
```

If `.optimusprime/` missing: create it, show dashboard with zeroes, say "Initialized."
