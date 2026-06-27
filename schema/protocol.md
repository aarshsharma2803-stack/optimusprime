# OptimusPrime Protocol — `.optimusprime/` Specification

Version: 0.1.0  
Status: canonical

---

## Overview

`.optimusprime/` is a directory committed to the user's project repo.
It is the single source of truth for all session state.
Any agent (Claude Code, Cursor, Codex) can read it.
No component maintains parallel state outside this directory.

**Discovery rule:** Every hook and CLI tool finds `.optimusprime/` by walking
up the directory tree from `cwd` until it finds the directory or hits filesystem root.
Never assume a fixed path. Never hardcode paths.

---

## Files

### `contract.json` — Scope contract

Written at session start by the `scope-guard` skill. Read by `scope-guard.py` hook
to block out-of-bounds writes.

```json
{
  "version": "0.1.0",
  "agent_id": "string — unique per parallel session, e.g. 'main' or 'worker-1'",
  "goal": "string — the session goal extracted from first user message",
  "in_scope": ["list of file globs or paths explicitly in scope"],
  "out_of_scope": ["list of file globs or paths explicitly excluded"],
  "complexity_budget": {
    "files_max": 10,
    "tokens_max": 50000
  },
  "created_at": "ISO 8601 timestamp",
  "session_id": "string — uuid4, unique per session"
}
```

**Constraints:**
- `agent_id` must be unique across parallel sessions. Defaults to `"main"`.
- `in_scope` and `out_of_scope` support glob patterns (`**/*.py`, `src/auth/*`).
- Missing file = no contract = scope-guard exits 0 (no blocking).
- Malformed JSON = scope-guard exits 0 (silent failure, never crash Claude Code).
- `complexity_budget` fields are advisory only in v0.1; enforcement added in v0.2.

---

### `decisions.md` — Append-only decision log

Written by the `decision-log` skill and any hook that makes a blocking decision.
Never overwritten. Only appended to.

**Format:**

```
[2026-06-27T14:32:00Z] [agent:main] DECISION: chose atomic write (tmp+rename) for write_json_safe — prevents corruption on crash
[2026-06-27T14:33:10Z] [agent:main] BLOCK: scope-guard blocked write to src/auth/token.py — out of scope per contract
[2026-06-27T14:45:00Z] [agent:main] DECISION: deferred semantic search impl to Session 6 — stdlib TF-IDF sufficient for MVP
```

**Constraints:**
- Max 120 chars per line (enforced by `append_to_file()`; longer lines are truncated with `…`).
- Timestamp must be ISO 8601 UTC.
- Prefix must be one of: `DECISION:`, `BLOCK:`, `ATTEMPT:`, `TODO:`, `COST:`.
- Never delete lines. This is an append-only log.
- File may not exist at session start; hooks create it on first write.

---

### `session-snapshot.md` — Session bridge

Written by `session-logger.py` at Stop and PreCompact events.
Users paste this into a new session to restore context instantly.

**Format:**

```markdown
# Session Snapshot
Generated: 2026-06-27T18:00:00Z
Agent: main
Session: <uuid>

## Goal
<extracted goal from contract.json>

## Changed Files
- src/optimusprime/utils.py (created)
- hooks/pre/scope-guard.py (created)

## Key Decisions
- [2026-06-27T14:32:00Z] chose atomic write for write_json_safe
- [2026-06-27T14:45:00Z] deferred semantic search to Session 6

## Failed Attempts
- tried stdlib `ast` for breaking-change detection — too slow on large files

## Open Threads
- [ ] breaking-change-detector.py needs type annotation extraction
- [ ] done-checker.py DoD checklist format TBD

## Next Action
Implement loop-detector.py — tracks error signatures, blocks after N repeated failures
```

**Constraints:**
- `## Changed Files` sourced from git diff against session start commit.
- `## Key Decisions` = last 10 lines from `decisions.md`.
- `## Failed Attempts` = all entries from `attempts.md` in current session.
- File is overwritten on each Stop/PreCompact (not append-only).

---

### `attempts.md` — Failed attempts log

Written by `attempt-logger.py` PostToolUse when exit code is non-zero.
Read by `loop-detector.py` to detect repeated failure signatures.

**Format:**

```
[2026-06-27T14:50:00Z] [session:<uuid>] FAIL tool=Edit file=hooks/pre/scope-guard.py error="SyntaxError line 42"
[2026-06-27T14:52:00Z] [session:<uuid>] FAIL tool=Bash cmd="python hooks/pre/scope-guard.py" error="ModuleNotFoundError"
```

**Constraints:**
- Max 120 chars per line (same as decisions.md).
- `error=` value is the first line of stderr or stdout, quoted, max 80 chars.
- Loop detector hashes `(tool, file/cmd, error_prefix)` as signature.
- After 3 identical signatures in one session, `loop-detector.py` exits 2 (block).
- Cleared at session start (new session = new session_id; old entries from prior sessions remain but are ignored by loop-detector when session_id differs).

---

### `resume.json` — Interruption recovery

Written by `session-logger.py` at Stop and PreCompact.
Structured data version of session-snapshot.md for programmatic use.

```json
{
  "version": "0.1.0",
  "session_id": "uuid4",
  "agent_id": "main",
  "goal": "string",
  "created_at": "ISO 8601",
  "updated_at": "ISO 8601",
  "changed_files": ["src/optimusprime/utils.py"],
  "decisions": [
    {"timestamp": "ISO 8601", "prefix": "DECISION", "body": "string"}
  ],
  "attempts": [
    {"timestamp": "ISO 8601", "tool": "Edit", "target": "string", "error": "string"}
  ],
  "open_threads": ["string"],
  "next_action": "string"
}
```

**Constraints:**
- Written atomically (temp + rename via `write_json_safe()`).
- `decisions` array = last 20 entries from decisions.md.
- `attempts` array = all entries from current session_id in attempts.md.

---

### `skills.json` — Installed ecosystem skills

Written by `op skills install` / `op skills update`. Read by the contextual activator.

```json
{
  "version": "0.1.0",
  "installed": {
    "superpowers": {
      "source": "github:obra/superpowers",
      "installed_version": "2.3.1",
      "installed_at": "ISO 8601",
      "update_policy": "auto",
      "activation": "contextual",
      "path": "~/.claude/skills/superpowers/SKILL.md"
    }
  },
  "last_checked": "ISO 8601"
}
```

**Constraints:**
- `update_policy`: `"auto"` (patch+minor silent), `"notify"` (major only), `"pin"` (never).
- `activation`: `"contextual"` (activator decides), `"always"`, `"manual"`.
- Never modify skill files directly. Install from source, run from source.

---

### `todos.md` — New TODOs requiring resolution

Written by `todo-scanner.py` PostToolUse when new TODO/FIXME comments are detected.

**Format:**

```
[2026-06-27T15:00:00Z] [session:<uuid>] TODO src/optimusprime/utils.py:42 "TODO: handle symlink loops in find_optimusprime_dir"
[2026-06-27T15:01:00Z] [session:<uuid>] FIXME hooks/pre/scope-guard.py:18 "FIXME: glob matching is case-sensitive on Linux"
```

**Constraints:**
- One line per TODO. Max 120 chars.
- Each TODO must be either resolved (line deleted after fix) or explicitly deferred
  by adding `[deferred: reason]` suffix.
- `done-checker.py` blocks Stop if unresolved TODOs exist without deferral.

---

### `cost-log.json` — Token and cost tracking

Written by `cost-awareness` skill. Appended to each session.

```json
{
  "version": "0.1.0",
  "sessions": [
    {
      "session_id": "uuid4",
      "agent_id": "main",
      "started_at": "ISO 8601",
      "ended_at": "ISO 8601",
      "input_tokens": 12500,
      "output_tokens": 4200,
      "cache_read_tokens": 8000,
      "cache_write_tokens": 3000,
      "estimated_cost_usd": 0.042
    }
  ]
}
```

**Constraints:**
- Written atomically. Never partially written.
- `estimated_cost_usd` is best-effort based on current model pricing; may be 0 if unavailable.
- Sessions array is append-only.

---

## Directory layout

```
.optimusprime/
├── contract.json          # scope contract — written at session start
├── decisions.md           # append-only decision log
├── session-snapshot.md    # human-readable session bridge
├── attempts.md            # failed attempts within sessions
├── resume.json            # structured session bridge
├── skills.json            # installed ecosystem skills
├── todos.md               # new TODOs requiring resolution
└── cost-log.json          # token/cost tracking
```

---

## Invariants

1. Every file operation is defensive. Missing files → create or skip. Malformed JSON → exit 0.
2. No hook ever crashes Claude Code. All hooks wrap in `try/except`, exit 0 on unexpected error.
3. Hooks are silent when nothing to do. No stdout when no action taken.
4. Atomic writes only. Never write directly to target; use temp file + `os.rename()`.
5. `.optimusprime/` is found by walking up the tree. Never hardcoded paths.
6. All timestamps are ISO 8601 UTC. `datetime.utcnow().isoformat() + "Z"`.
7. All log lines ≤ 120 chars. Longer lines truncated with `…` before write.
8. Hook block decisions output JSON to stdout: `{"decision": "block", "reason": "OPTIMUSPRIME: ..."}`.
   Also write human-readable reason to stderr.
   Exit code 2 = block, 0 = approve.
