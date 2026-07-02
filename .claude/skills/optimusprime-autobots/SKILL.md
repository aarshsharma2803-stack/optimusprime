---
name: optimusprime-autobots
description: >
  Show and manage all OptimusPrime Auto Bots — which are active, which are on
  standby, and which triggers activate each one.
  Trigger: /optimusprime-autobots, user asks "show autobots", "which bots are active",
  "list bots", "manage autobots"
---

Show the Auto Bot status and allow activation/deactivation.

Read `.optimusprime/skills.json` from the current project (walk up from cwd). Cross-reference with `ecosystem/registry.json` in the OptimusPrime install directory for bot metadata.

Display:

```
🤖 OPTIMUSPRIME AUTO BOTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bot                  Status      Trigger
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Caveman Bot          [mode]      tokens > 40k
Superpowers Bot      [mode]      complexity = full
UI/UX Pro Max Bot    [mode]      frontend files touched
Ponytail Bot         [mode]      complexity = minimal
Gstack Bot           [mode]      goal contains deploy/ship/pr
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Mode: auto=always fires | contextual=fires when triggered | off=disabled
```

Then ask: "Would you like to change any bot's mode? (auto/contextual/off)"

If yes, update `.optimusprime/skills.json` with the new mode and confirm.

If `.optimusprime/` missing: create it with default skills.json (caveman=auto, others=contextual).
