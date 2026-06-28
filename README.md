# OptimusPrime

**Claude is stateless. Your project isn't.**

OptimusPrime is the first hook-level session state protocol for AI coding. Runtime enforcement that fires before execution. Cross-session memory that compounds over time. Intelligence that gets smarter every session.

```
[63.9% output compression] [100% loop detection] [0.02ms search] [145 tests] [MIT License] [Python 3.8+]
```

---

## The problem

Every Claude Code session starts from zero — no memory of decisions made last session, no knowledge of what already failed, no enforcement of scope mid-task. Every existing tool (Superpowers, gstack, caveman, ponytail) makes *requests* to Claude via CLAUDE.md or skill files. Claude can forget them mid-session. OptimusPrime *enforces* at the hook level — before execution, not after.

---

## What's in v1.0.0

**9 hooks** — scope enforcement, loop detection, dependency analysis, breaking change detection, predictive context injection, output compression, attempt logging, TODO accountability, done checking, session snapshots + cross-session learner

**7 skills** — scope contract extraction, decision logging, confidence signaling, CLAUDE.md generation, context restoration, cost awareness, production output mode

**Intelligence layer** — contradiction detection across decisions, topic clustering, predictive context injection ranked by relevance not recency, cross-session learning engine that adapts to your actual usage patterns

**MCP server** — 9 tools including `reason_about()`, `get_contradictions()`, `get_patterns()` exposing full project intelligence to any MCP-capable agent

**CLI** — `op` command with 9 command groups including `op intel ask`, `op intel patterns`, `op intel learned`, `op intel session-history`

**Ecosystem Skills Hub** — one-command install for Superpowers, gstack, UI/UX Pro Max, caveman, ponytail. Auto-updates. Contextual activation. Learns your real activation thresholds from usage.

---

## Architecture — 8 layers

**Layer 1 — Foundation.** Hook-level enforcement runs before every tool call. The `.optimusprime/` directory is committed to your repo so every agent can read the same state. Zero external dependencies in hooks.

**Layer 2 — Protocol.** Eight files form the session state: `contract.json` captures scope, `decisions.md` is an append-only log, `session-snapshot.md` bridges sessions, `attempts.md` prevents retry loops, `resume.json` recovers from interruptions, `skills.json` tracks installed community skills, `todos.md` captures new TODOs, `cost-log.json` tracks token spend. Two derived files: `patterns.json` (learned cross-session patterns) and `scope-guard-log.json` (blocked file history).

**Layer 3 — Hooks.** Five PreToolUse hooks run before execution: `predictive-context` injects semantically relevant decisions by relevance score, `scope-guard` blocks out-of-scope writes, `dependency-analyzer` injects callers before edits, `loop-detector` blocks repeated failures, `breaking-change-detector` snapshots API surfaces. Five PostToolUse/Stop hooks run after: `output-compressor` strips prose filler (63.9% reduction), `attempt-logger` records failures, `todo-scanner` diffs new TODOs, `done-checker` enforces completion criteria, `session-logger` writes the snapshot and resume state. One Stop-only hook: `learner-hook` runs after session-logger to update `patterns.json`.

**Layer 4 — Skills.** Seven SKILL.md files auto-activate: scope extraction at session start, silent decision capture on every decision, confidence signaling when uncertain, CLAUDE.md generation from the codebase, context restoration from the previous session snapshot, cost awareness, and production output mode.

**Layer 5 — MCP Server.** Nine queryable tools expose `.optimusprime/` to any MCP-capable agent: `get_contract()`, `search_decisions(query)`, `get_snapshot()`, `get_attempts()`, `get_todos()`, `get_cost()`, `reason_about(question)`, `get_contradictions(severity)`, `get_patterns()`. Semantic TF-IDF search over decisions means Claude can ask "why did we choose X" and get an answer from the actual log.

**Layer 6 — CLI.** The `op` command covers everything across 9 command groups. See [CLI reference](#cli-reference).

**Layer 7 — Integrations.** Superpowers writes decisions to `.optimusprime/decisions.md`. gstack `/freeze` writes to `.optimusprime/contract.json`. The `agent_id` field supports parallel multi-agent sessions with per-agent scope enforcement.

**Layer 8 — Ecosystem Skills Hub.** A curated registry of community skills installed fresh from GitHub source. Auto-updates between sessions: patch and minor versions are silent, major versions notify only. One command to roll back. Per-skill update policy.

---

## Intelligence layer

Session 50 is exactly as smart as session 1 with other tools. After OptimusPrime, it isn't.

**Predictive context** (`hooks/pre/predictive-context.py`) — before every tool call, extracts signals from the tool name, target file, and function names. Scores all past decisions by TF-IDF similarity to the current context. Injects the top-5 ranked decisions as `additionalContext`. File-path and function-name boosts surface the most relevant decisions, not the most recent.

**Contradiction detection** (`op intel contradictions`) — scans decisions.md for hard contradictions (explicit REJECTED list conflicts) and soft contradictions (same topic bucket, different choices). Hybrid TF-IDF + topic clustering handles both large-corpus and small-corpus scenarios.

**Cross-session learner** (`hooks/post/learner-hook.py`, `src/optimusprime/learner.py`) — after every session ends, analyzes what happened and updates `patterns.json`:

- **Skill thresholds**: if caveman auto-activated at 30k tokens for 3 sessions instead of the default 60k, it learns your real threshold and updates the activation signal
- **Failure patterns**: indexes every failed tool call by file. Marks resolved when a subsequent decision mentions the same file
- **User preferences**: running averages of decisions per session, failure rate, complexity distribution, preferred and avoided libraries from DECIDED/REJECTED lines
- **Topic patterns**: velocity and stability metrics per topic; unstable areas flagged when velocity > 3.0 across multiple sessions
- **Scope suggestions**: if a file is blocked 3+ times, surfaces it as a scope contract review candidate
- **Session history**: last 20 sessions with goal, decisions, failures, topics, activated skills

---

## Benchmark results

| Metric | Result | Method |
|---|---|---|
| Output compression | 63.9% average | 20 verbose Claude response samples |
| Scope guard latency | 75ms average | n=1,000 runs |
| Loop detection | 100% accuracy | 20 true loops + 20 non-loops + 10 edge cases |
| Decision search | 0.02ms average | 112 entries indexed, 100 queries |
| Session logger | 0.12s average | n=10 runs |
| Input token reduction | 40%+ | after 20 decisions logged across sessions |
| Contradiction detection | 163ms total | O(n²) full history scan, 112 decisions |
| Context prediction | 0.77ms avg | per tool call, 112 decisions indexed |
| Learning cycle | 1.8ms avg | 10 sessions × 10 decisions each |

Compression is non-destructive — code blocks are never modified. Only prose preamble, postamble, and inline restatement sentences are removed.

---

## Install

### macOS / Linux

```bash
git clone https://github.com/aarshsharma2803-stack/optimusprime
cd optimusprime
bash install.sh
```

### Windows

```powershell
git clone https://github.com/aarshsharma2803-stack/optimusprime
cd optimusprime
.\install.ps1
```

### Requirements

- Python 3.8+ (hooks and CLI)
- Python 3.10+ (MCP server — installed automatically if available)
- Claude Code with hook support

---

## The `.optimusprime/` directory

| File | Purpose | Commit to repo? |
|---|---|---|
| `contract.json` | Scope contract: goal, in-scope files, out-of-scope patterns, complexity budget, agent_id | Yes |
| `decisions.md` | Append-only decision log, 120 char/line, timestamped | Yes |
| `session-snapshot.md` | Session bridge: goal, changed files, decisions, open threads, next action | Yes |
| `attempts.md` | Failed attempts log — prevents Claude retrying what already failed | Yes |
| `patterns.json` | Cross-session learned patterns: skill thresholds, failure history, user preferences, topic velocity | Yes |
| `resume.json` | Interruption recovery state | No (gitignore) |
| `skills.json` | Installed community skills, versions, activation modes | Yes |
| `todos.md` | New TODOs requiring resolution or explicit deferral | Yes |
| `cost-log.json` | Token and cost tracking per session | No (gitignore) |
| `scope-guard-log.json` | Blocked file history for learner scope suggestions | No (gitignore) |

---

## Community Skills Hub

| Skill | Stars | Activation | License |
|---|---|---|---|
| superpowers | 237k | session start | MIT |
| gstack | 117k | complex sessions | MIT |
| ui-ux-pro-max | 97k | frontend files touched | MIT |
| caveman | 62k | tokens running high (learned per user) | MIT |
| ponytail | 60k | minimal complexity budget | MIT |

```bash
op skills install superpowers
op skills install --all
```

Skills are installed fresh from GitHub source — OptimusPrime never bundles or patches community files. After 3 sessions, skill activation thresholds adapt to your actual token usage patterns instead of registry defaults.

---

## CLI reference

| Command | What it does |
|---|---|
| `op decision search <query>` | Semantic search over decisions.md |
| `op decision list [--last N] [--all]` | List recent or all decisions |
| `op decision count` | Count decisions and blocks by type |
| `op snapshot` | Show current session snapshot |
| `op resume` | Print resume.json for pasting into new session |
| `op contract show` | Display current scope contract |
| `op contract set --goal "..."` | Set session goal |
| `op todos list` | List unresolved TODOs |
| `op cost show` | Show token usage and estimated cost |
| `op claude-md generate` | Generate CLAUDE.md from codebase analysis |
| `op claude-md sync` | Sync CLAUDE.md with current .optimusprime/ state |
| `op history` | Show full session history |
| `op skills list` | List available and installed community skills |
| `op skills install <name>` | Install a skill from the registry |
| `op skills update [<name>]` | Update one or all skills |
| `op skills rollback <name>` | Roll back a skill to previous version |
| `op skills pin <name> <version>` | Pin a skill to a specific version |
| `op skills status` | Show update policy and version for each skill |
| `op intel ask <question>` | Answer a question using structured decision analysis |
| `op intel contradictions [--all]` | Scan for hard (and soft with --all) contradictions |
| `op intel patterns` | Show decision clusters by topic with velocity metrics |
| `op intel summary` | Cross-topic overview: topics, velocity, contradiction count |
| `op intel learned` | Show what patterns.json has accumulated across sessions |
| `op intel session-history [--all]` | Table of past sessions: goal, decisions, failures, topics |

---

## MCP Server

Register in Claude Code (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "optimusprime": {
      "command": "python3",
      "args": ["/path/to/optimusprime/mcp/server.py"]
    }
  }
}
```

Register in Cursor (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "optimusprime": {
      "command": "python3",
      "args": ["/path/to/optimusprime/mcp/server.py"]
    }
  }
}
```

Available tools:

| Tool | What it returns |
|---|---|
| `get_contract()` | Current scope contract |
| `search_decisions(query)` | TF-IDF ranked decisions matching query |
| `get_snapshot()` | Current session snapshot |
| `get_attempts()` | Recent failed attempts |
| `get_todos()` | Unresolved TODOs |
| `get_cost()` | Token usage and cost estimate |
| `reason_about(question)` | Structured multi-section answer with Confidence level |
| `get_contradictions(severity)` | All hard/soft contradictions in decision history |
| `get_patterns()` | Topic clusters with velocity and stability metrics |

---

## Why hook-level enforcement matters

Every other session-continuity tool operates at the prompt level — it adds instructions to CLAUDE.md or a skill file and hopes Claude reads and follows them. That works until it doesn't: mid-session compaction, a long context window, or simply Claude drifting toward a simpler interpretation. The instruction existed. Claude forgot it.

PreToolUse hooks run in the shell, not in Claude's context window. When scope-guard blocks a write, Claude cannot override it by choosing to ignore it — the shell script exits with code 2 before the tool call completes. When loop-detector has seen the same error three times, it blocks the next attempt the same way. The enforcement is outside the model entirely.

This is the `.git/` analogy in practice: git doesn't trust the developer to remember to commit atomically — it enforces the invariant at the filesystem level. OptimusPrime doesn't trust Claude to remember the scope contract — it enforces it at the tool call level. The model is smart. The protocol is dumb and reliable.

---

## How it compounds

OptimusPrime was built across 12 sessions using itself. 123 decisions are logged in `.optimusprime/decisions.md`. The intelligence layer answered questions about architectural choices made in session 3 while working in session 11. The learner adapted the output compressor's behavior to the project's actual prose density. Scope guard blocked 3 accidental writes to config files that would have been silent without it.

We ate our own cooking through the entire build.

---

## Compatible agents

Claude Code · Antigravity · Cursor · Codex · Any MCP agent

The `.optimusprime/` directory is agent-agnostic — any tool that can read files or query MCP tools can use the session state.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT — see [LICENSE](LICENSE).
