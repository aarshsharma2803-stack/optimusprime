---
name: superpowers
description: >
  Complete software development methodology — TDD, architecture review, structured
  iteration, quality gates. Auto-activates on full-complexity tasks, large feature
  builds, or architectural changes.
  Trigger: complexity_budget:full, goal contains build/implement/architect/design/system,
  or user says "superpowers", "full methodology", "do this properly".
---

Execute with full engineering rigor. No shortcuts on complex tasks.

## Before writing any code

State the approach in 2-3 sentences. Name the pattern. State what it does NOT handle.

## Methodology

1. **Plan** — break goal into subtasks with clear acceptance criteria before touching code
2. **TDD** — write the test/assertion before the implementation when feasible
3. **Architecture** — verify design fits existing patterns; flag if it doesn't
4. **Incremental** — each change is independently verifiable
5. **Quality gate** — types clean, tests pass, no regressions before marking done

## On large tasks

Break into subtasks. Verify each before continuing.
Flag contradictions with existing decisions immediately.
Ask ONE scoped question rather than guessing on ambiguous architecture decisions.

## On architecture

Name the pattern explicitly: "This is a repository pattern" not "here's how I'll do it."
State tradeoffs. State what the design explicitly does NOT cover.

## Persistence

Active for the full session once triggered. Off only: "stop superpowers" or "simple mode".
