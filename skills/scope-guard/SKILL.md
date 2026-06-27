---
name: scope-guard
description: >
  Activates at the start of a Claude Code session when the user's first message
  describes a task or coding goal. Triggers on opening messages containing: fix,
  build, implement, refactor, add, update, create, debug, test, review, deploy,
  migrate, optimize, write, remove, rename. Also triggers on: "set scope",
  "define contract", "what's in scope", "let's work on", "I need to".
  Does NOT re-trigger mid-session. Does NOT trigger on questions or follow-ups
  in an ongoing session. Only fires on the opening task-description message.
---

Silently extract scope contract from opening message. Walk up from cwd to find `.optimusprime/`. If not found, skip.

**Write `.optimusprime/contract.json`:**
- `goal`: verb-first one sentence ("Implement X", "Fix Y in Z")
- `in_scope`: file globs inferred from task
- `out_of_scope`: always include `["node_modules/**", ".env", ".git/**", "__pycache__/**"]`; add others if obvious
- `complexity_budget`: `"minimal"` (1–2 files) / `"moderate"` (3–10 files) / `"full"` (cross-cutting)
- `agent_id`: `"main"`
- `created_at`: ISO 8601 UTC
- `session_id`: random 8-char hex

**If goal is clear:** write contract, output nothing, proceed to task.
**If genuinely ambiguous:** ask exactly ONE question to resolve scope, then write.

After writing: no output. Proceed directly to the user's task.
