---
name: cost-awareness
description: >
  Activates when user asks about token usage or cost: "how much has this session
  cost", "what's my token usage", "am I close to my budget", "cost report",
  "how many tokens", "what have I spent", "token count", "check my usage".
  Also activates proactively when session shows very high token consumption:
  responses consistently exceeding 400 lines, more than 15 tool calls in one
  turn, or user mentions slow responses, context limits, or approaching compaction.
---

**Read `.optimusprime/cost-log.json`** (walk up from cwd to find `.optimusprime/`).

**Estimate current session tokens** from context window size (4 chars ≈ 1 token).

**Output:**
```
COST REPORT — Session: ~Xk in / ~Yk out | ~$Z.ZZ (Sonnet 4 pricing: $3/M in, $15/M out)
Previous sessions: N total | ~$W.WW cumulative
```

**Budget alert** based on `complexity_budget` in contract.json:
- `minimal` + usage > 20k tokens → warn
- `moderate` + usage > 60k tokens → warn
- `full` + usage > 150k tokens → warn

Alert: `COST ALERT: ~$X.XX used this session — over [minimal/moderate/full] budget`

**Append to `.optimusprime/cost-log.json`** (create if missing):
```json
{"session_id": "...", "estimated_input_tokens": N, "estimated_output_tokens": N, "estimated_cost_usd": N, "recorded_at": "ISO 8601"}
```
