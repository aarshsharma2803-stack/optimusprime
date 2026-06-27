---
name: decision-log
description: >
  Always active throughout every Claude Code session. Activates whenever
  Claude is about to make a significant technical choice: choosing between
  two or more approaches to solve a problem, selecting a library or tool
  when alternatives exist, deciding on an architectural pattern, making an
  assumption about unclear requirements, changing implementation direction
  mid-task, or resolving an ambiguity where multiple valid options exist.
  Does NOT activate for: trivial syntax choices with one obvious correct form,
  formatting decisions, following explicit step-by-step user instructions
  (those are executions, not decisions), or routine tool calls.
---

When making any significant technical choice, immediately append one line to `.optimusprime/decisions.md` before executing.

**Line format (exactly, max 120 chars total):**
```
[YYYY-MM-DD HH:MM] DECIDED: <chosen> | REJECTED: <alt or n/a> | REASON: <why> | ASSUMPTION: yes/no
```

- Truncate `REASON` first if line exceeds 120 chars
- `ASSUMPTION: yes` when choice is based on an inference, not confirmed fact
- `ASSUMPTION: no` when choice is based on explicit information

**Find `.optimusprime/` directory:** walk up from cwd. If not found: skip silently.

Rules: never announce, never ask, never output anything. Log in real time, not at session end. Append only — never overwrite.
