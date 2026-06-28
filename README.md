# OptimusPrime

**Session state protocol for AI coding.**

Claude is stateless. Your project isn't. OptimusPrime bridges the gap.

```
[63.9% output compression] [100% loop detection] [0.02ms search] [MIT License] [Python 3.8+]
```

---

## The problem

Every Claude Code session starts from zero — no memory of decisions made last session, no knowledge of what already failed, no enforcement of scope mid-task. Every existing tool (Superpowers, gstack, caveman, ponytail) makes *requests* to Claude via CLAUDE.md or skill files. Claude can forget them mid-session. OptimusPrime *enforces* at the hook level — before execution, not after.

---

## What OptimusPrime does

**Layer 1 — Foundation.** Hook-level enforcement runs before every tool call. The `.optimusprime/` directory is committed to your repo so every agent can read the same state. Zero external dependencies in hooks.

**Layer 2 — Protocol.** Eight files form the session state: `contract.json` captures scope, `decisions.md` is an append-only log, `session-snapshot.md` bridges sessions, `attempts.md` prevents retry loops, `resume.json` recovers from interruptions, `skills.json` tracks installed community skills, `todos.md` captures new TODOs, and `cost-log.json` tracks token spend.

**Layer 3 — Hooks.** Four PreToolUse hooks run before execution: scope-guard blocks out-of-scope writes, dependency-analyzer injects callers before edits, loop-detector blocks repeated failures, breaking-change-detector snapshots API surfaces. Five PostToolUse/Stop hooks run after: output-compressor strips prose filler (63.9% reduction), attempt-logger records failures, todo-scanner diffs new TODOs, done-checker enforces completion criteria, session-logger writes the snapshot and resume state.

**Layer 4 — Skills.** Six SKILL.md files auto-activate throughout sessions: scope extraction at session start, silent decision capture on every decision, confidence signaling when uncertain, CLAUDE.md generation from the codebase, context restoration from the previous session snapshot, and real-time cost awareness.

**Layer 5 — MCP Server.** Six queryable tools expose `.optimusprime/` to any MCP-capable agent: `get_contract()`, `search_decisions(query)`, `get_snapshot()`, `get_attempts()`, `get_todos()`, `get_cost()`. Semantic search over decisions means Claude can ask "why did we choose X" and get an answer from the actual log.

**Layer 6 — CLI.** The `op` command covers everything: `decision search/list/count`, `snapshot`, `resume`, `contract set/show`, `todos list`, `cost show`, `claude-md generate/sync`, `history`, `skills list/install/update/rollback/pin/status`.

**Layer 7 — Integrations.** Superpowers writes decisions to `.optimusprime/decisions.md`. gstack `/freeze` writes to `.optimusprime/contract.json`. The `agent_id` field in `contract.json` supports parallel multi-agent sessions with per-agent scope enforcement.

**Layer 8 — Ecosystem Skills Hub.** A curated registry of community skills installed fresh from GitHub source. Auto-updates between sessions: patch and minor versions are silent, major versions notify only. One command to roll back. Per-skill update policy.

---

## Benchmark results

| Metric | Result | Method |
|---|---|---|
| Output compression | 63.9% average | 20 verbose Claude response samples |
| Scope guard latency | 75ms average | n=1,000 runs |
| Loop detection | 100% accuracy | 20 true loops + 20 non-loops + 10 edge cases |
| Decision search | 0.02ms average | 85 entries indexed, 100 queries |
| Session logger | 0.12s average | n=10 runs |
| Input token reduction | 40%+ | after 20 decisions logged across sessions |

> Compression is non-destructive — code blocks are never modified. Only prose preamble, postamble, and inline restatement sentences are removed.

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
| `resume.json` | Interruption recovery state | No (gitignore) |
| `skills.json` | Installed community skills, versions, activation modes | Yes |
| `todos.md` | New TODOs requiring resolution or explicit deferral | Yes |
| `cost-log.json` | Token and cost tracking per session | No (gitignore) |

---

## Community Skills Hub

| Skill | Stars | Activation | License |
|---|---|---|---|
| superpowers | 237k | session start | MIT |
| gstack | 117k | complex sessions | MIT |
| ui-ux-pro-max | 97k | frontend files touched | MIT |
| caveman | 62k | tokens running high | MIT |
| ponytail | 60k | minimal complexity budget | MIT |

```bash
op skills install superpowers
op skills install --all
```

Skills are installed fresh from GitHub source — OptimusPrime never bundles or patches community files.

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

Example query from any MCP-capable agent:

```
search_decisions("why did we choose atomic write")
→ [2026-06-27] DECISION: atomic write via tmp+os.rename() — prevents corruption on crash
```

---

## Why hook-level enforcement matters

Every other session-continuity tool operates at the prompt level — it adds instructions to CLAUDE.md or a skill file and hopes Claude reads and follows them. That works until it doesn't: mid-session compaction, a long context window, or simply Claude drifting toward a simpler interpretation. The instruction existed. Claude forgot it.

PreToolUse hooks run in the shell, not in Claude's context window. When scope-guard blocks a write, Claude cannot override it by choosing to ignore it — the shell script exits with code 2 before the tool call completes. When loop-detector has seen the same error three times, it blocks the next attempt the same way. The enforcement is outside the model entirely.

This is the `.git/` analogy in practice: git doesn't trust the developer to remember to commit atomically — it enforces the invariant at the filesystem level. OptimusPrime doesn't trust Claude to remember the scope contract — it enforces it at the tool call level. The model is smart. The protocol is dumb and reliable.

---

## Compatible agents

Claude Code, Cursor, Codex, Antigravity, any MCP-capable agent. The `.optimusprime/` directory is agent-agnostic — any tool that can read files or query MCP tools can use the session state.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT — see [LICENSE](LICENSE).
