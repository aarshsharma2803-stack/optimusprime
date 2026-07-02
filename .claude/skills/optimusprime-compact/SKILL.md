---
name: optimusprime-compact
description: >
  Compact the current conversation — preserve decisions, requirements, errors,
  architecture, and active task state; strip repeated or low-value content;
  reduce token usage; prepare clean context for Claude.
  Trigger: /optimusprime-compact, user says "compact", "compress conversation",
  "clean up context", "too many tokens", or /compact-conversation.
---

Compact the current conversation immediately. Preserve everything that matters, discard everything that doesn't.

## What to preserve (never discard)

- Project goal and current task
- All architectural decisions and their reasons
- All requirements and constraints
- All known bugs and errors with their context
- All code that was written or modified in this session
- Failed approaches (critical — prevents re-trying what failed)
- Active TODO items
- Current task state (what step, what's done, what's next)

## What to discard

- Repeated explanations of the same concept
- Tool call narration ("I'll now read the file...")
- Success announcements that describe code already shown
- Any content older than 3 exchanges that hasn't been referenced since
- Pleasantries and filler

## Output format

After compacting, output:

```
⚡ OPTIMUSPRIME COMPACT — COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[GOAL] <one sentence>
[TASK] <current subtask + what's done>
[DECISIONS] <bullet list, max 5 most recent>
[CONSTRAINTS] <bullet list>
[KNOWN ERRORS] <bullet list if any>
[FAILED] <what not to retry>
[NEXT] <immediate next action>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tokens saved: continuing from compact context.
```

Also write this summary to `.optimusprime/session-snapshot.md` in the current project.
