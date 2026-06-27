# OptimusPrime — Project Context

## What this is

OptimusPrime is the session state protocol for AI coding.

**One line:** Claude is stateless. Your project isn't. OptimusPrime bridges the gap.

OptimusPrime is NOT a simple plugin. It is a protocol — the `.git/` of AI sessions.
Every component reads from and writes to `.optimusprime/` in the user's repo.
Any agent (Claude Code, Cursor, Codex, Superpowers, gstack) can read this data.

## The problem it solves

Every Claude Code session starts from zero:
- No memory of decisions made last session
- No knowledge of what approaches already failed
- Claude drifts mid-task because nothing enforces scope at runtime
- After compaction, decisions from an hour ago vanish
- New session tomorrow = re-explain everything from scratch

Every existing tool (Superpowers, gstack, caveman, ponytail) makes REQUESTS to Claude
via CLAUDE.md or skill files. Claude can forget them mid-session.
OptimusPrime ENFORCES at the hook level — before execution, not after.

## Architecture — 8 layers

### Layer 1 — Foundation (non-negotiables)
- Hook-level enforcement (PreToolUse blocks before execution)
- Repo-local committed data (.optimusprime/ directory)
- Cross-agent protocol spec (any agent reads it)
- Zero external dependencies

### Layer 2 — Protocol (.optimusprime/ schema)
Files written to user's repo:
- `contract.json` — scope contract (goal, in-scope files, out-of-scope, complexity budget, agent_id)
- `decisions.md` — append-only decision log (120 char/line, timestamped)
- `session-snapshot.md` — session bridge (goal, changed files, decisions, open threads, next action)
- `attempts.md` — failed attempts within session (prevents Claude retrying what already failed)
- `resume.json` — interruption recovery state
- `skills.json` — installed community skills, versions, activation modes
- `todos.md` — newly added TODOs requiring resolution or explicit deferral
- `cost-log.json` — token/cost tracking per session

### Layer 3 — Hooks (Python 3, stdlib only, no pip deps)

PreToolUse (block before execution):
- `scope-guard.py` — reads contract.json, blocks OOB writes. Exit 2 + JSON decision:block
- `dependency-analyzer.py` — injects callers of target function before edit
- `loop-detector.py` — tracks error signatures, blocks after N repeated failures
- `breaking-change-detector.py` — snapshots API surface before edit, flags breaking changes

PostToolUse + Stop:
- `output-compressor.py` — strips preamble/postamble/filler, zero overhead if nothing to strip
- `attempt-logger.py` — logs failed tool calls to attempts.md
- `todo-scanner.py` — diffs session start vs end, extracts new TODOs
- `done-checker.py` — enforces project-defined DoD checklist before Stop
- `session-logger.py` — writes session-snapshot.md and resume.json at Stop/PreCompact

### Layer 4 — Skills (SKILL.md with YAML frontmatter, auto-triggering)
- `scope-guard/SKILL.md` — session start contract extraction, silent
- `decision-log/SKILL.md` — always active, silent decision capture
- `confidence-signal/SKILL.md` — structured uncertainty mechanism
- `claude-md-generator/SKILL.md` — analyzes codebase, generates/maintains CLAUDE.md
- `context-restorer/SKILL.md` — new session context restoration from snapshot
- `cost-awareness/SKILL.md` — real-time token/cost surfacing

### Layer 5 — MCP Server (Python, exposes .optimusprime/ as queryable tools)
Tools: get_contract(), search_decisions(query), get_snapshot(), get_attempts(),
get_todos(), get_cost()
Semantic search over decisions.md so Claude can query "why did we choose X"

### Layer 6 — CLI (`op` command, Python)
Commands: decision search, snapshot, resume, contract, todos, cost,
claude-md generate, claude-md sync, history, skills list/install/update/rollback/pin/status

### Layer 7 — Integrations
- Superpowers writes decisions to .optimusprime/decisions.md
- gstack /freeze writes to .optimusprime/contract.json
- Multi-agent: agent_id in contract.json for parallel session scope enforcement
- Any MCP-capable agent reads .optimusprime/ directly

### Layer 8 — Ecosystem Skills Hub (SEPARATE from core)
Curated registry of community skills. Installed fresh from GitHub source, never bundled.
Auto-updates: patch/minor silently between sessions, major = notification only.
Rollback in one command. Per-skill update policy.

Current registry:
- superpowers (obra/superpowers) — workflow methodology, 237k stars, MIT
- gstack (garrytan/gstack) — engineering team toolkit, 117k stars, MIT
- ui-ux-pro-max (nextlevelbuilder/ui-ux-pro-max-skill) — design intelligence, 97k stars, MIT
- caveman (JuliusBrussee/caveman) — output compression, 62k stars, MIT
- ponytail (DietrichGebert/ponytail) — code minimalism, 60k stars, MIT

Contextual activation: OptimusPrime knows what files are being touched, session goal,
token usage. Maps that to skill suggestions/auto-activation.
- frontend files → suggest ui-ux-pro-max
- tokens running high → activate caveman/ponytail
- complex full session → suggest superpowers
- minimal complexity budget → ponytail auto-activates

## Tech stack

- Language: Python 3.8+ (hooks, MCP server, CLI) — stdlib only for hooks
- CLI framework: Click (for `op` command)
- MCP server: Python MCP SDK
- Semantic search: sentence-transformers or simple TF-IDF (no cloud dependency)
- Testing: pytest with comprehensive coverage
- Supported agents: Claude Code primary, then Cursor, Codex, others
- Supported OS: macOS, Linux, Windows

## Directory structure

```
optimusprime/
├── CLAUDE.md                          # This file
├── README.md
├── .claude-plugin/
│   └── plugin.json                    # Claude Code plugin manifest
├── hooks/
│   ├── hooks.json                     # Hook event → script mapping
│   ├── pre/
│   │   ├── scope-guard.py
│   │   ├── dependency-analyzer.py
│   │   ├── loop-detector.py
│   │   └── breaking-change-detector.py
│   └── post/
│       ├── output-compressor.py
│       ├── attempt-logger.py
│       ├── todo-scanner.py
│       ├── done-checker.py
│       └── session-logger.py
├── skills/
│   ├── scope-guard/SKILL.md
│   ├── decision-log/SKILL.md
│   ├── confidence-signal/SKILL.md
│   ├── claude-md-generator/SKILL.md
│   ├── context-restorer/SKILL.md
│   └── cost-awareness/SKILL.md
├── mcp/
│   ├── server.py                      # MCP server
│   └── search.py                      # Semantic search over decisions.md
├── cli/
│   └── op.py                          # `op` CLI entry point
├── ecosystem/
│   ├── registry.json                  # Curated skill registry
│   ├── installer.py                   # op skills install logic
│   ├── updater.py                     # Auto-update engine
│   └── activator.py                   # Contextual activation engine
├── schema/
│   └── protocol.md                    # .optimusprime/ spec document
├── tests/
│   ├── test_hooks/
│   ├── test_cli/
│   ├── test_mcp/
│   └── test_ecosystem/
├── benchmarks/
│   └── README.md                      # Proving measurable improvements
├── install.sh
├── install.ps1
└── pyproject.toml
```

## Critical rules for every session

1. Hooks NEVER crash Claude Code. Every hook wraps main() in try/except, exits 0 on
   any unexpected error. Silent failure is always better than a crash.

2. Hooks are SILENT when nothing to do. Exit 0 immediately. No output.

3. `.optimusprime/` is the single source of truth. Every component reads from here.
   No component maintains its own parallel state.

4. No pip dependencies in hooks. Python stdlib only. CLI and MCP server can have deps.

5. All file operations are defensive. Missing files = exit 0. Malformed JSON = exit 0.
   Never assume .optimusprime/ exists — find it by walking up the directory tree.

6. Hooks output JSON to stdout for decisions:
   `{"decision": "block", "reason": "OPTIMUSPRIME: reason here"}`
   Also write to stderr for human-readable output.
   Exit code 2 for block, 0 for approve.

7. The ecosystem layer NEVER modifies community skill files. It installs from source,
   runs from source. OptimusPrime does not fork or patch community skills.

8. Auto-updates NEVER happen mid-session. Only at SessionStart, before first tool call.

9. Semver auto-update policy: patch = silent, minor = silent + log, major = notify only.

10. Every decision made during building OptimusPrime itself goes into
    `.optimusprime/decisions.md` in THIS repo. We eat our own cooking.

## Build sequence (sessions)

Session 1: Foundation + Protocol layer
- pyproject.toml, .claude-plugin/plugin.json, README skeleton
- .optimusprime/ schema and protocol.md spec
- Shared utilities: find_optimusprime_dir(), load_contract(), write_json_safe()

Session 2: Core hooks — PreToolUse
- scope-guard.py (most critical, build first)
- loop-detector.py (highest user impact)
- dependency-analyzer.py
- breaking-change-detector.py
- hooks.json wiring

Session 3: Core hooks — PostToolUse + Stop
- output-compressor.py
- attempt-logger.py
- session-logger.py
- todo-scanner.py
- done-checker.py

Session 4: Skills
- All 6 SKILL.md files
- Careful trigger phrase writing so they auto-activate correctly

Session 5: CLI
- op.py with Click
- All 8+ commands
- Shell completion

Session 6: MCP Server
- server.py
- search.py (semantic search over decisions.md)
- Registration in plugin.json

Session 7: Ecosystem Skills Hub
- registry.json
- installer.py
- updater.py (with semver logic)
- activator.py (contextual activation engine)
- skills.json schema

Session 8: Tests + Benchmarks
- Comprehensive pytest coverage for all hooks
- Benchmark suite proving token savings
- Integration tests

Session 9: Installers + Polish
- install.sh (macOS/Linux)
- install.ps1 (Windows)
- Multi-agent adapter configs
- Final README

## What good looks like

A user installs OptimusPrime. They start a Claude Code session. Claude silently
extracts a scope contract from their first message. Through the session, decisions
are logged silently, out-of-scope writes are blocked, loop attempts are caught,
output padding is stripped. Before compaction, a snapshot is written.

Next day, new session. They paste the snapshot. Claude knows everything — the goal,
every decision made, what failed, what's in progress, what to do next. Zero
re-explanation.

Meanwhile, because they're working on a frontend task, UI/UX Pro Max activated
silently. Because they've used 60k tokens, caveman engaged automatically.

That is the experience. Everything else is implementation detail.
