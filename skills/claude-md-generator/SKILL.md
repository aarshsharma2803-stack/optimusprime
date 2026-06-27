---
name: claude-md-generator
description: >
  Activates when user requests CLAUDE.md generation or update: "generate
  CLAUDE.md", "update CLAUDE.md", "my CLAUDE.md is outdated", "create project
  context file", "claude-md generate", "regenerate project instructions",
  "write CLAUDE.md". Also activates when CLAUDE.md is missing from a project
  root containing package.json, pyproject.toml, Cargo.toml, or go.mod and the
  user appears to be starting work on that project.
---

**Read before writing:**
1. `package.json` / `pyproject.toml` / `Cargo.toml` → stack, framework, key deps
2. Sample 3–5 test files → testing patterns, assertion style
3. `git log --oneline -20` → commit conventions
4. `.optimusprime/decisions.md` → all `DECIDED:` lines
5. Top-level directory scan → project shape

**Write `CLAUDE.md` with:**
- What this project is (1 sentence)
- Tech stack: language, framework, key dependencies
- Conventions: naming patterns, file structure, import style
- Architectural decisions from `decisions.md` (up to 5, ≤1 line each)
- Testing approach: framework, what gets tested, where tests live
- Things Claude must never do in this repo

**Staleness check:** if existing CLAUDE.md predates the newest entry in `decisions.md` by >30 days, note: `Note: existing CLAUDE.md was stale — regenerated.`

**Output:** `CLAUDE.md generated — X decisions incorporated`
