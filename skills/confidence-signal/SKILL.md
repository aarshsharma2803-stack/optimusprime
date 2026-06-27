---
name: confidence-signal
description: >
  Activates when Claude has internal uncertainty below 70% about whether the
  chosen approach is correct before executing. Triggers on: uncertainty about
  correctness of a complex algorithm with subtle edge cases; uncertainty whether
  a refactor will silently break callers identified by dependency-analyzer;
  requirement ambiguity where two interpretations lead to very different
  implementations and the wrong choice has significant rework cost; an approach
  similar to one in .optimusprime/attempts.md (previously failed this session).
  Does NOT activate for HIGH confidence. Only fires before executing, not after.
---

**When confidence < 70% before executing:**

Output exactly:
```
CONFIDENCE: LOW — [one sentence naming the specific risk] — proceed or clarify?
```

Wait for user response. Do not execute until answered.

**When confidence ≥ 70%:** proceed silently. Never output anything about confidence level.

Rules:
- Never say "CONFIDENCE: HIGH" — silence means high confidence.
- Name the specific risk: "renaming `process()` will break 4 callers in services/" not "I'm unsure".
- After user says "proceed": execute immediately, no further output.
- Threshold is strict: 70%. Mild uncertainty does not qualify.
