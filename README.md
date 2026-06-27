# OptimusPrime

**The session state protocol for AI coding.**

Claude is stateless. Your project isn't. OptimusPrime bridges the gap.

---

## What it does

Every Claude Code session starts from zero — no memory of decisions, no knowledge of what failed, no scope enforcement. OptimusPrime fixes that at the hook level, before execution, not after.

- **Scope enforcement** — blocks out-of-bounds writes before they happen
- **Decision logging** — every architectural choice captured, silently
- **Loop detection** — stops Claude retrying what already failed
- **Session bridging** — one snapshot file restores full context next session
- **Compaction recovery** — snapshot written before context compresses

---

## Architecture

```
Layer 1 — Foundation    hook-level enforcement, repo-local data, zero external deps
Layer 2 — Protocol      .optimusprime/ directory: contract, decisions, snapshot, attempts
Layer 3 — Hooks         Python 3 stdlib-only: scope-guard, loop-detector, session-logger
Layer 4 — Skills        SKILL.md files: scope-guard, decision-log, context-restorer
Layer 5 — MCP Server    queryable tools over .optimusprime/ data
Layer 6 — CLI           `op` command: decision search, snapshot, resume, cost
Layer 7 — Integrations  Superpowers, gstack, Cursor, Codex — any agent reads .optimusprime/
Layer 8 — Ecosystem     curated community skills hub with semver auto-updates
```

## Protocol directory

`.optimusprime/` is committed to your repo. Every component reads from here. No parallel state.

| File | Purpose |
|------|---------|
| `contract.json` | Session scope contract |
| `decisions.md` | Append-only decision log |
| `session-snapshot.md` | Human-readable session bridge |
| `attempts.md` | Failed attempt log for loop detection |
| `resume.json` | Structured session bridge |
| `skills.json` | Installed ecosystem skills |
| `todos.md` | New TODOs requiring resolution |
| `cost-log.json` | Token and cost tracking |

See [`schema/protocol.md`](schema/protocol.md) for full field-level specification.

---

## Install

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/your-org/optimusprime/main/install.sh | bash

# Windows
irm https://raw.githubusercontent.com/your-org/optimusprime/main/install.ps1 | iex
```

> Full install docs in Session 9.

## Requirements

- Python 3.8+
- Claude Code (hooks API)
- No pip deps required for hooks (stdlib only)

---

*Full documentation, benchmarks, and multi-agent adapter configs coming in Session 9.*
