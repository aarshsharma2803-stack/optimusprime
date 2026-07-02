---
name: optimusprime
description: >
  OptimusPrime main activation command. In a NEW session: initializes environment,
  activates core Auto Bots, starts compression. In an EXISTING session: recovers
  full context first, then activates. Always: Caveman Bot + OP compression run
  from this point forward.
  Trigger: /optimusprime, /op, user says "activate optimusprime", "start op",
  "initialize op", "is optimusprime running", "op status", "show op status"
---

## Detect session type

**Check if this is a new or existing session:**

Find `.optimusprime/` by walking up from cwd (up to 10 parent levels).

Read `.optimusprime/session-state.json`:
- If `prompt_count` > 5 → **EXISTING SESSION** → go to Existing Session Flow
- If `prompt_count` ≤ 5 OR file missing → **NEW SESSION** → go to New Session Flow

If `.optimusprime/` not found anywhere: run `mkdir -p .optimusprime` in cwd, then go to New Session Flow.

---

## NEW SESSION FLOW

### Step 1: Initialize

Create or verify these files exist in `.optimusprime/`:
- `decisions.md` (touch if missing)
- `attempts.md` (touch if missing)
- `todos.md` (touch if missing)

Write `.optimusprime/skills.json` if missing:
```json
{
  "installed": {
    "caveman": {"mode": "auto", "version": "2.0.0", "trigger": "tokens>40000"},
    "superpowers": {"mode": "contextual", "version": "1.0.0", "trigger": "complexity_budget:full"},
    "ui-ux-pro-max": {"mode": "contextual", "version": "1.0.0", "trigger": "frontend_files"},
    "ponytail": {"mode": "contextual", "version": "1.0.0", "trigger": "complexity_budget:minimal"},
    "gstack": {"mode": "contextual", "version": "1.0.0", "trigger": "goal:deploy,ship,pr"}
  }
}
```

### Step 2: Activate core Auto Bots

**Caveman Bot — ACTIVE NOW:**
Respond terse like smart caveman from this point forward. Drop articles/filler/pleasantries. Fragments OK. Keep all technical substance intact. This persists for the entire session.

**OP Compression — ACTIVE NOW:**
The output-compressor.py hook is running on every response, stripping preamble/postamble/over-explanation automatically.

**Superpowers Bot — STANDBY:**
Will activate if goal is complex (complexity_budget: full) or task involves build/implement/architect.

**UI/UX Pro Max Bot — STANDBY:**
Will activate if files touched include .tsx/.jsx/.css/.vue/.html or goal involves design/frontend/UI.

**Ponytail Bot — STANDBY:**
Will activate if complexity_budget is minimal or user asks for simpler code.

### Step 3: Show initialization banner

```
⚡ OPTIMUSPRIME — INITIALIZED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Environment ready
✅ Caveman Bot ACTIVE (compression on)
✅ OP Compression ACTIVE (hook running)
⏸  Superpowers Bot — standby
⏸  UI/UX Pro Max Bot — standby
⏸  Ponytail Bot — standby
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Commands available:
  /optimusprime-compact     — compact conversation
  /optimusprime-status      — quick status check
  /optimusprime-dashboard   — full dashboard
  /optimusprime-autobots    — manage Auto Bots
  /optimusprime-repair      — escape repair loops
  /optimusprime-token-report — token usage report
  /optimusprime-quality-check — code quality scan
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ready. What are you working on?
```

Ask the user for their session goal. When they answer, write it to `.optimusprime/contract.json`.

---

## EXISTING SESSION FLOW

### Step 1: Recover context

Read these files and build a context package:

1. `.optimusprime/contract.json` → goal, scope, budget
2. `.optimusprime/session-snapshot.md` → what happened last, open threads, next action
3. `.optimusprime/decisions.md` → last 5 decisions
4. `.optimusprime/attempts.md` → failed approaches (must not retry)
5. `.optimusprime/todos.md` → open TODOs
6. `.optimusprime/loop-state.json` → current repair loop streak
7. `.optimusprime/cost-log.json` → tokens used
8. `.optimusprime/compression-log.json` → compression ratio
9. `.optimusprime/skills.json` → which Auto Bots are configured

### Step 2: Show context recovery

```
⚡ OPTIMUSPRIME — CONTEXT RECOVERED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 Goal:          [goal]
📋 Budget:        [complexity_budget]
💬 Tokens used:   [n]k  (~$[cost])
📝 Decisions:     [n] logged
🔁 Loop streak:   [n] [⚠️ if ≥2]
📊 Compression:   [avg ratio]%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LAST SESSION STATE:
[session-snapshot.md → OPEN and NEXT lines]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RECENT DECISIONS:
[last 3 from decisions.md]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DO NOT RETRY (failed approaches):
[attempts.md contents or "none"]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OPEN TODOS:
[todos.md or "none"]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 3: Activate Auto Bots for existing session

**Caveman Bot — ACTIVE NOW** (same as new session).

**Token-based activation:**
- If tokens > 40k: Caveman already active
- If tokens > 80k: Add "Maximum compression — single-word answers when possible"

**Context-based activation:**
- If loop_streak ≥ 2: say "⚠️ Repair loop detected — run /optimusprime-repair"
- If complexity_budget = full AND goal suggests build/implement: note Superpowers standby

### Step 4: Confirm ready

```
✅ Context recovery complete. All session history loaded.
Commands available: /optimusprime-compact | /optimusprime-status | /optimusprime-repair
Continuing from: [NEXT line from snapshot]
```

Then continue. Do NOT restart or re-introduce the session. Pick up from where it left off.

---

## ALWAYS ON (both flows)

From the moment `/optimusprime` is activated:
- Caveman Bot runs on every response for this session
- OP output compressor runs via hook on every tool response
- Pre-response hook injects status line before every prompt
- Session logger will write snapshot at session end
