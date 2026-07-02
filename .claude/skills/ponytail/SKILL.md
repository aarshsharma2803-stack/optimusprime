---
name: ponytail
description: >
  Code minimalism — no premature abstractions, no speculative features,
  smallest correct implementation only. Auto-activates when complexity budget
  is minimal or user asks for simpler/smaller code.
  Trigger: complexity_budget:minimal, goal contains refactor/simplify/minimize/clean/slim,
  or user says "keep it simple", "no abstractions", "ponytail".
---

Write the smallest correct implementation. No extra.

## Rules

- No abstraction until needed 3+ times in the same codebase
- No optional parameters that aren't used right now
- No helper functions for single-call sites
- No "future-proof" wrappers around things that work fine today
- No config for things that aren't variable
- Delete more than you write when refactoring
- Three similar lines beats a premature abstraction
- Trust the framework — don't wrap what already works

## When adding code

Ask: "What is the minimum that makes this work?" Write that.

## When reviewing code

Ask: "What can be deleted without breaking anything?" Delete that.

## Persistence

Active for the full session once triggered. Off only: "stop ponytail" or "normal mode".
