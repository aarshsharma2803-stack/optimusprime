---
name: superpowers
description: >
  Full engineering rigor for complex work — plan before code, name the pattern,
  verify before marking done. Auto-activates on full-complexity tasks, multi-file
  builds, or architectural changes.
  Trigger: complexity_budget:full, goal contains build/implement/architect/design/system,
  or user says "superpowers", "do this properly", "full methodology".
---

Execute complex work with full rigor. Simple tasks stay simple — this only changes behavior once a task crosses into multi-file or architectural territory.

## Before writing any code

State the approach in 2-3 sentences. Name the pattern if there is one. State what it explicitly does NOT handle. Then write code.

Not: *(silently starts editing five files)*
Yes: "Repository pattern — one `UserRepository` class wrapping the ORM calls. Doesn't handle caching; that's a separate concern if needed later."

## Methodology

1. **Plan** — break the goal into subtasks with a clear acceptance criterion for each, before touching code
2. **TDD where it pays off** — write the failing test/assertion first when the behavior is easy to specify up front; skip it for pure plumbing
3. **Architecture fit** — check the change against existing patterns in the codebase; flag it explicitly if it doesn't fit, don't silently introduce a second pattern
4. **Incremental** — each subtask is independently verifiable; don't bundle five changes into one unverifiable diff
5. **Quality gate before "done"** — types clean, tests pass, no regressions, no dead code left behind

## On large tasks

Break into subtasks with acceptance criteria before executing any of them. Verify each subtask before moving to the next — don't discover three broken assumptions at the end.

Flag contradictions with existing decisions immediately, don't proceed past them silently.

Ambiguous architecture call → ask ONE scoped question. Don't guess on things that are expensive to unwind (schema shape, public API surface, cross-service contracts). Do guess on things that are cheap to change later (variable names, internal helper structure).

## On architecture

Name the pattern explicitly. "This is a repository pattern," not "here's how I'll structure it." Naming it lets the pattern's known tradeoffs apply automatically instead of being re-derived.

State what the design does NOT cover — every design excludes something; say what, so nobody assumes coverage that isn't there.

## Interaction with other Auto Bots

- Runs alongside [[optimusprime]]'s loop-detector and scope-guard — those enforce the floor (don't get stuck, don't touch out-of-scope files), Superpowers raises the ceiling (plan well, verify before done)
- If Caveman Bot is also active (tokens > 40k): keep the terse voice, keep the rigor. Compression changes prose, not process.

## Persistence

Active for the full session once triggered. Off only: "stop superpowers" or "simple mode".
