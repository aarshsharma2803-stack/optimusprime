---
name: optimusprime
description: >
  Session memory + guardrails for Claude Code. Remembers decisions across sessions,
  blocks repeated failures, compresses output, activates helper bots automatically.
  Subcommands: /optimusprime status|compact|repair|bots|tokens|quality|dashboard.
  Trigger: /optimusprime, /op, "activate optimusprime", "op status", "is op running".
---

One command, seven modes. `/optimusprime` alone = activate + status. `/optimusprime <mode>` = run that mode.

All data lives in `.optimusprime/` — find it by walking up from cwd (10 levels max). If missing anywhere: `mkdir -p .optimusprime`, continue silently. Never ask the user to create folders.

## `/optimusprime` (no args) — activate

**1. Detect session type.** Read `.optimusprime/session-state.json` → `prompt_count`. Over 5 = existing session; otherwise new.

**New session:** show banner, ask for goal, write `contract.json`:

```
⚡ OPTIMUSPRIME ACTIVE
Caveman Bot on · compression on · guardrails armed
Modes: status | compact | repair | bots | tokens | quality | dashboard
What are you working on?
```

**Existing session:** recover context BEFORE anything else. Read `contract.json` (goal), `session-snapshot.md` (last state + next action), `decisions.md` (last 5), `attempts.md` (failed — never retry these), `todos.md`, `loop-state.json`. Show:

```
⚡ CONTEXT RECOVERED
Goal: <goal> · <n> decisions · <n>k tokens · loop <n>
Avoid: <failed approaches or "nothing">
Next: <next action from snapshot>
```

**2. Both flows:** Caveman-style compression active from this response onward — drop articles/filler/pleasantries, fragments OK, all technical substance stays. Persists whole session.

## `/optimusprime status`

One panel: tokens (`cost-log.json`), decisions count (`decisions.md`), loop streak (`loop-state.json`, ⚠️ at 3+), compression avg (`compression-log.json`), active bots (`skills.json`). Nothing else.

## `/optimusprime compact`

Compact conversation now. Keep: goal, decisions + reasons, requirements, errors + context, code written this session, failed approaches, task state. Drop: repeated explanations, narration, filler. Output the compact summary, write it to `.optimusprime/session-snapshot.md`.

## `/optimusprime repair`

Read `loop-state.json` + `attempts.md`. Show: current error, attempt count, what failed. Propose ONE different approach — different strategy, not a retry. Then reset `loop-state.json` to `{"consecutive_failures":[]}`.

## `/optimusprime bots`

Table of 5 bots from `skills.json` × `registry.json`: Caveman (auto, tokens>40k), Superpowers (full-budget builds), UI/UX Pro Max (frontend files), Ponytail (minimal budget), Gstack (deploy/ship goals). Offer mode change → write `skills.json`.

## `/optimusprime tokens`

Session tokens + cost, last 5 sessions trend, compression savings total. Recommendation: <40k healthy · 40-80k caveman auto-on · 80k+ run compact · 150k+ new session with snapshot.

## `/optimusprime quality`

Scan files from `session-snapshot.md` CHANGED list (or ask which). Check: functions >30 lines, duplicate logic, hardcoded secrets, SQL concatenation, eval/exec on user input. Report critical/important/minor. Clean = "✅ passed".

## `/optimusprime dashboard`

status + last 5 decisions + open TODOs + next action, one screen.

## Auto Bot rules (always on once activated)

- tokens > 40k → compress responses harder (caveman full)
- tokens > 80k → maximum compression + suggest `compact`
- loop streak ≥ 3 → suggest `repair`
- frontend files touched → apply UI/UX design rigor
- minimal budget → smallest correct implementation, no abstractions

Off only: "stop optimusprime" / "deactivate op".
