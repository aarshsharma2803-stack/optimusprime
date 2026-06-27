[2026-06-27T00:00:00Z] [agent:main] DECISION: chose hatchling as build backend — standard, zero extra config vs setuptools
[2026-06-27T00:00:01Z] [agent:main] DECISION: chose src/ layout — isolates package from root config files, prevents accidental imports
[2026-06-27T00:00:02Z] [agent:main] DECISION: atomic write via tmp+os.rename() in write_json_safe — prevents corruption on crash
[2026-06-27T00:00:03Z] [agent:main] DECISION: sentence-transformers as optional dep [semantic] — hooks stay stdlib-only per invariant #4
[2026-06-27T00:00:04Z] [agent:main] DECISION: block_response() prints to stderr + returns JSON string — caller prints to stdout, exits 2
[2026-06-27T00:00:05Z] [agent:main] DECISION: find_optimusprime_dir() returns None (not raise) on missing dir — missing dir = no contract = no enforce…
[2026-06-27T00:00:06Z] [agent:main] DECISION: all timestamps use UTC ISO 8601 ending in Z — unambiguous across timezones for multi-agent sessions
[2026-06-27T00:00:07Z] [agent:main] DECISION: MAX_LINE_LENGTH=120 for log files — fits terminal width, grep-friendly, not too aggressive on content
[2026-06-27T00:00:08Z] [agent:main] DECISION: plugin.json uses {plugin_dir} placeholder — installer substitutes real path at install time
[2026-06-27T00:00:09Z] [agent:main] DECISION: complexity_budget fields advisory-only in v0.1 — enforcement deferred to v0.2 after real usage data
[2026-06-27T10:17:45Z] [agent:main] BLOCK: Write to 'secrets/creds.txt' blocked — matches out-of-scope pattern 'secrets…
[2026-06-27T10:17:45Z] [agent:main] BLOCK: Write to 'src/.env' blocked — matches out-of-scope pattern '*.env'
[2026-06-27T10:17:45Z] [agent:main] BLOCK: Bash references out-of-scope path 'secrets/api_key.txt' (pattern 'secrets/*')
[2026-06-27T10:19:20Z] [agent:main] BLOCK: Loop detected — same failure 3 times in a row (tool=Edit, target='src/foo.py…
[2026-06-27T10:19:20Z] [agent:main] BLOCK: Loop detected — same failure 3 times in a row (tool=Edit, target='src/foo.py…
[2026-06-27T00:01:00Z] [agent:main] DECISION: scope-guard uses fnmatch + basename + prefix matching — 3 strategies cover glob, wildcard, dir-prefix patterns
[2026-06-27T00:01:01Z] [agent:main] DECISION: loop-detector reads loop-state.json written by attempt-logger (Session 3) — clean separation of concerns
[2026-06-27T00:01:02Z] [agent:main] DECISION: loop detection uses reversed() tail scan — only consecutive trailing failures count, not total failures
[2026-06-27T00:01:03Z] [agent:main] DECISION: difflib.SequenceMatcher for near-identical errors (0.80 threshold) — catches "line 5/6/7" variations
[2026-06-27T00:01:04Z] [agent:main] DECISION: dependency-analyzer caps at 20 symbols + 8s grep timeout — prevents hanging on huge codebases
[2026-06-27T00:01:05Z] [agent:main] DECISION: breaking-change-detector snapshots on first-touch, warns on removal — never on addition (additions are safe)
[2026-06-27T00:01:06Z] [agent:main] DECISION: snapshot key = sha256[:24] of abs path — stable across renames of op dir, no collisions at project scale
[2026-06-27T00:01:07Z] [agent:main] DECISION: dependency-analyzer + breaking-change-detector use additionalContext field — warn not block
[2026-06-27T00:01:08Z] [agent:main] DECISION: hooks use sys.path.insert(0, PLUGIN_ROOT/src) — portable, no install required, no pip needed
[2026-06-27T00:02:00Z] [agent:main] DECISION: output-compressor works on tool_response.output not transcript — avoids transcript read complexity
[2026-06-27T00:02:01Z] [agent:main] DECISION: code blocks split on ``` before applying filler patterns — never mutate code block content
[2026-06-27T00:02:02Z] [agent:main] DECISION: min compress threshold 200 chars + 20 chars saved — avoids overhead for short/clean outputs
[2026-06-27T00:02:03Z] [agent:main] DECISION: attempt-logger clears loop-state on success via write_json_safe — loop-detector reads this on next PreToolUse
[2026-06-27T00:02:04Z] [agent:main] DECISION: loop-state consecutive_failures capped at 10 — prevents unbounded growth over long sessions
[2026-06-27T00:02:05Z] [agent:main] DECISION: todo-scanner uses git diff HEAD with --unified=0 — extracts + lines only, no context noise
[2026-06-27T00:02:06Z] [agent:main] DECISION: done-checker silent on all-pass — only injects context when something failed, zero noise otherwise
[2026-06-27T00:02:07Z] [agent:main] DECISION: session-logger uses 24h mtime heuristic for decisions.md freshness — git doesn't track .optimusprime/
[2026-06-27T00:02:08Z] [agent:main] DECISION: PreCompact injects full snapshot as additionalContext — snapshot survives compaction in next window
[2026-06-27T00:02:09Z] [agent:main] DECISION: SubagentStop triggers todo-scanner + session-logger — parallel agents each write their own state
