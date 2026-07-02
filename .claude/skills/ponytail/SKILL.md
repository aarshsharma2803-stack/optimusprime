---
name: ponytail
description: >
  Code minimalism — no premature abstractions, no speculative features,
  smallest correct implementation only. Auto-activates when complexity budget
  is minimal or user asks for simpler/smaller code.
  Trigger: complexity_budget:minimal, goal contains refactor/simplify/minimize/clean/slim,
  or user says "keep it simple", "no abstractions", "smaller diff".
---

Write the smallest correct implementation. No extra.

## Rules

- No abstraction until the same logic appears 3+ times in the same codebase
- No optional parameters that nothing calls with a non-default value yet
- No helper function for a single call site — inline it
- No "future-proof" wrapper around something that already works
- No config knob for a value that never actually varies
- Delete more than you write when refactoring
- Three similar lines beats a premature abstraction
- Trust the framework — don't wrap what already works

## Before/after

Not:
```python
class RetryStrategy:
    def __init__(self, max_attempts=3, backoff_fn=None):
        self.max_attempts = max_attempts
        self.backoff_fn = backoff_fn or (lambda i: 2 ** i)

def fetch_with_retry(url, strategy=None):
    strategy = strategy or RetryStrategy()
    for i in range(strategy.max_attempts):
        ...
```

Yes:
```python
def fetch_with_retry(url, max_attempts=3):
    for i in range(max_attempts):
        try:
            return requests.get(url)
        except requests.RequestException:
            if i == max_attempts - 1:
                raise
            time.sleep(2 ** i)
```

Nobody asked for pluggable backoff strategies. When someone does, add it then — with a real second use case in hand, not a hypothetical one.

## When adding code

Ask: "What is the minimum that makes this work?" Write that. Not "what's the minimum that also handles cases nobody has hit yet."

## When reviewing code

Ask: "What can be deleted without breaking anything?" Delete that. Unused parameters, dead branches, config that's always the same value — gone.

## Interaction with other Auto Bots

- If Superpowers is also active (rare — they trigger on opposite complexity signals): Superpowers governs planning rigor, Ponytail governs implementation size. A well-planned small change is not a contradiction.
- Independent of Caveman Bot — Ponytail shapes code, Caveman shapes prose. Both can run at once.

## Persistence

Active for the full session once triggered. Off only: "stop ponytail" or "normal mode".
