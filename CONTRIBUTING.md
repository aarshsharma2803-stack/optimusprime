# Contributing to OptimusPrime

## How to add a skill to the registry

Community skills are listed in `ecosystem/registry.json`. To propose a new skill:

1. Fork the repo
2. Add an entry to `ecosystem/registry.json` with these required fields:

```json
"skill-name": {
  "display_name": "Human-readable name",
  "source": "github:owner/repo",
  "license": "MIT",
  "default_mode": "auto",
  "activation_signals": ["keyword1", "keyword2"],
  "tags": ["tag1", "tag2"],
  "description": "One-line description of what this skill does.",
  "stars": 0
}
```

Required field notes:
- `source`: must be `github:owner/repo` format
- `license`: MIT license required — non-permissive licenses will not be accepted
- `default_mode`: `auto` (context-triggered), `manual` (user-invoked only), or `always`
- `activation_signals`: keywords that trigger contextual activation when present in session goal or touched files

3. Open a PR with:
   - Skill description and what problem it solves
   - Current star count on the source repo
   - Why it belongs in the OptimusPrime registry (complements existing skills, broad applicability, active maintenance)

Skills with fewer than 1k stars are unlikely to be accepted unless they fill a clear gap.

---

## How to contribute a hook

Hooks in `hooks/pre/` and `hooks/post/` must follow these invariants or they will not be merged:

**Never crash Claude Code.** Every hook wraps `main()` in `try/except Exception: sys.exit(0)`. Silent failure is always better than a crash that blocks the user.

**Exit 0 silently when nothing to do.** No output when the hook has no action to take. The `[op]` prefix is for install script output, not hooks.

**Handle missing `.optimusprime/` gracefully.** Never assume the directory exists. Use `find_optimusprime_dir()` from `src/optimusprime/utils.py` and exit 0 if it returns `None`.

**Stdlib only.** No pip dependencies in hooks. The venv may not be available when Claude Code runs hooks. Use only Python standard library modules.

**Exit 2 + JSON for blocks.** If your hook needs to block a tool call:
```python
print(json.dumps({"decision": "block", "reason": "OPTIMUSPRIME: reason here"}))
print("OPTIMUSPRIME BLOCK: reason here", file=sys.stderr)
sys.exit(2)
```

**Test your hook.** Add tests in `tests/test_hooks/test_<hookname>.py` with a minimum of 5 test cases covering: normal operation, nothing-to-do (silent), malformed input, missing `.optimusprime/`, and your hook's specific block/allow logic.

---

## How to run tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
python benchmarks/benchmark_suite.py
```

All 75+ existing tests must pass. The benchmark suite must still report "All performance targets met."

---

## PR checklist

- [ ] All 75+ existing tests pass (`pytest tests/`)
- [ ] New tests added for new functionality (minimum 5 per hook)
- [ ] No pip dependencies added to hooks (stdlib only)
- [ ] Hook exits 0 silently when nothing to do
- [ ] Hook wraps main() in try/except, exits 0 on any unexpected error
- [ ] `decisions.md` updated with key architectural choices
- [ ] Benchmarks still meet targets (`python benchmarks/benchmark_suite.py`)
- [ ] PR description explains the why, not just the what
