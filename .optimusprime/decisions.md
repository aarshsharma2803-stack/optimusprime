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
