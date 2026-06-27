#!/usr/bin/env python3
"""OptimusPrime Benchmark Suite.

Produces reproducible performance and accuracy numbers.
Run: python benchmarks/benchmark_suite.py

Results go in the README as proof of measurable impact.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT / "ecosystem"))

# ---------------------------------------------------------------------------
# Sample data for benchmarks
# ---------------------------------------------------------------------------

# 20 representative Claude responses with typical padding patterns
_PADDED_RESPONSES = [
    (
        "Here's the implementation:\n\n"
        "def authenticate(user_id: str, token: str) -> bool:\n"
        "    conn = db.connect()\n"
        "    result = conn.execute('SELECT * FROM users WHERE id=?', (user_id,))\n"
        "    return result.fetchone() is not None and verify_token(token)\n\n"
        "I've created the file above with all the authentication logic you requested. "
        "The implementation handles edge cases for None inputs and invalid tokens."
    ),
    (
        "Let me create the configuration file for you.\n\n"
        "[database]\nhost = localhost\nport = 5432\nname = myapp\n\n"
        "The above configuration file sets up the database connection parameters. "
        "You can modify these values as needed for your environment."
    ),
    (
        "Sure! I'll implement the sorting algorithm right away.\n\n"
        "def quicksort(arr):\n    if len(arr) <= 1:\n        return arr\n"
        "    pivot = arr[len(arr) // 2]\n    left = [x for x in arr if x < pivot]\n"
        "    middle = [x for x in arr if x == pivot]\n"
        "    right = [x for x in arr if x > pivot]\n"
        "    return quicksort(left) + middle + quicksort(right)\n\n"
        "This implementation uses the divide-and-conquer approach. "
        "As you asked me to implement a fast sorting algorithm, quicksort is ideal here."
    ),
    (
        "Of course! Moving on to the next part of the implementation.\n\n"
        "class UserRepository:\n    def __init__(self, db):\n        self.db = db\n"
        "    def find_by_id(self, user_id):\n        return self.db.query(User).get(user_id)\n\n"
        "Now let's move on to implementing the service layer that calls this repository."
    ),
    (
        "Following your instructions, I've updated the tests:\n\n"
        "def test_auth():\n    assert authenticate('user1', 'valid_token') is True\n"
        "    assert authenticate('user1', 'bad_token') is False\n\n"
        "I've created the test file above with comprehensive coverage. "
        "The tests verify both the happy path and error cases."
    ),
    (
        "Certainly! Per your request, here is the updated schema:\n\n"
        "CREATE TABLE users (\n    id SERIAL PRIMARY KEY,\n"
        "    email VARCHAR(255) UNIQUE NOT NULL,\n    created_at TIMESTAMP DEFAULT NOW()\n);\n\n"
        "This implementation creates a normalized users table. The above code is ready to run."
    ),
    (
        "Here is the solution:\n\n"
        "import hashlib\n\ndef hash_password(password: str) -> str:\n"
        "    salt = os.urandom(32)\n    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)\n"
        "    return salt.hex() + ':' + key.hex()\n\n"
        "The implementation uses PBKDF2 with SHA-256 for secure password hashing. "
        "Next, I'll implement the verification function."
    ),
    (
        "Let me write the middleware for you.\n\n"
        "def auth_middleware(request, next_handler):\n"
        "    token = request.headers.get('Authorization', '').replace('Bearer ', '')\n"
        "    if not token or not validate_token(token):\n"
        "        return Response(status=401)\n    return next_handler(request)\n\n"
        "This middleware validates JWT tokens on every request. "
        "I've created the file above."
    ),
    (
        "I'll now implement the caching layer.\n\n"
        "class Cache:\n    def __init__(self, ttl=300):\n        self._store = {}\n"
        "        self._ttl = ttl\n    def get(self, key):\n        entry = self._store.get(key)\n"
        "        if entry and time.time() < entry['expires']:\n            return entry['value']\n"
        "        return None\n\n"
        "The cache implementation handles TTL expiration automatically. "
        "Now let's move on to wiring it into the service layer."
    ),
    (
        "As you requested, here is the API endpoint:\n\n"
        "@app.route('/api/users', methods=['GET'])\ndef get_users():\n"
        "    users = UserRepository(db).find_all()\n"
        "    return jsonify([u.to_dict() for u in users])\n\n"
        "The above code implements a RESTful endpoint. "
        "As you asked me to add pagination, I've included limit/offset support."
    ),
    # 10 more without preamble (should see less compression)
    (
        "The function validates email addresses using a regex pattern.\n"
        "Returns True if valid, False otherwise.\n\n"
        "def is_valid_email(email: str) -> bool:\n"
        "    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$'\n"
        "    return bool(re.match(pattern, email))\n"
    ),
    (
        "Database connection pooling reduces overhead by reusing connections.\n"
        "This is critical for high-throughput APIs.\n\n"
        "pool = ConnectionPool(min_size=2, max_size=10, timeout=30)\n"
        "conn = pool.acquire()\ntry:\n    result = conn.execute(query)\nfinally:\n    pool.release(conn)\n"
    ),
    (
        "The logging configuration sets up structured JSON output for production.\n\n"
        "import logging\nimport json\n\nclass JsonFormatter(logging.Formatter):\n"
        "    def format(self, record):\n        return json.dumps({'level': record.levelname, 'msg': record.getMessage()})\n"
    ),
    (
        "Error handling is implemented at the service boundary.\n\n"
        "class ServiceError(Exception):\n    def __init__(self, message, code=500):\n"
        "        super().__init__(message)\n        self.code = code\n\n"
        "def handle_service_error(error):\n    return {'error': str(error), 'code': error.code}, error.code\n"
    ),
    (
        "Rate limiting prevents API abuse by tracking request counts per IP.\n\n"
        "from collections import defaultdict\nfrom datetime import datetime\n\n"
        "requests_per_ip = defaultdict(list)\n\ndef is_rate_limited(ip, limit=100, window=60):\n"
        "    now = datetime.now().timestamp()\n    cutoff = now - window\n"
        "    requests_per_ip[ip] = [t for t in requests_per_ip[ip] if t > cutoff]\n"
        "    if len(requests_per_ip[ip]) >= limit:\n        return True\n"
        "    requests_per_ip[ip].append(now)\n    return False\n"
    ),
    (
        "The migration script adds the new index for improved query performance.\n\n"
        "-- Migration: add_user_email_index\nCREATE INDEX CONCURRENTLY idx_users_email\n"
        "ON users (email) WHERE deleted_at IS NULL;\n\n"
        "ANALYZE users;\n"
    ),
    (
        "WebSocket connection handling for real-time updates.\n\n"
        "async def websocket_handler(websocket, path):\n    clients.add(websocket)\n"
        "    try:\n        async for message in websocket:\n"
        "            await broadcast(message)\n    finally:\n        clients.discard(websocket)\n"
    ),
    (
        "The background job processes pending notifications every 30 seconds.\n\n"
        "def process_notifications():\n    pending = Notification.query.filter_by(sent=False).limit(100).all()\n"
        "    for n in pending:\n        send_notification(n)\n        n.sent = True\n"
        "    db.session.commit()\n    return len(pending)\n"
    ),
    (
        "Retry logic with exponential backoff for network requests.\n\n"
        "import time\n\ndef with_retry(fn, max_attempts=3, base_delay=1.0):\n"
        "    for attempt in range(max_attempts):\n        try:\n            return fn()\n"
        "        except Exception as e:\n            if attempt == max_attempts - 1:\n                raise\n"
        "            time.sleep(base_delay * (2 ** attempt))\n"
    ),
    (
        "Feature flag evaluation reads from a config file or environment.\n\n"
        "def is_feature_enabled(feature: str, user_id: str = None) -> bool:\n"
        "    flags = load_feature_flags()\n    flag = flags.get(feature, {})\n"
        "    if not flag.get('enabled', False):\n        return False\n"
        "    if user_id and 'allowlist' in flag:\n        return user_id in flag['allowlist']\n"
        "    rollout = flag.get('rollout_percentage', 100)\n"
        "    return (hash(user_id or '') % 100) < rollout\n"
    ),
]

# 50 simulated error sequences for loop detection accuracy
_ERROR_SEQUENCES = []
# 20 true loops: same tool+target+error repeated 3+ times
for i in range(20):
    target = f"src/module_{i}.py"
    err = f"SyntaxError line {10 + i}"
    _ERROR_SEQUENCES.append({
        "type": "loop",
        "failures": [
            {"tool": "Edit", "target": target, "error": err},
            {"tool": "Edit", "target": target, "error": err},
            {"tool": "Edit", "target": target, "error": err},
        ],
        "query_tool": "Edit",
        "query_target": target,
        "expect_block": True,
    })
# 20 non-loops: clearly different targets (not just a one-char diff)
_NON_LOOP_TARGETS = [
    ("database/models.py", "api/handlers.py", "ui/components.jsx", "tests/integration.py"),
    ("migrations/001.sql", "scripts/seed.py", "docs/api.md", "benchmarks/run.py"),
    ("config/prod.yaml", "infra/deploy.tf", "monitoring/alerts.py", "tools/lint.sh"),
    ("frontend/app.tsx", "backend/server.go", "proto/service.proto", "k8s/deployment.yaml"),
    ("auth/jwt.py", "payments/stripe.py", "email/templates.html", "sms/twilio.py"),
]
for i in range(20):
    grp = _NON_LOOP_TARGETS[i % len(_NON_LOOP_TARGETS)]
    _ERROR_SEQUENCES.append({
        "type": "non_loop_diff_target",
        "failures": [
            {"tool": "Edit", "target": grp[0], "error": "ImportError: module not found"},
            {"tool": "Edit", "target": grp[1], "error": "TypeError: wrong argument"},
            {"tool": "Edit", "target": grp[2], "error": "KeyError: missing key"},
        ],
        "query_tool": "Edit",
        "query_target": grp[3],
        "expect_block": False,
    })
# 10 edge cases: under threshold (2 failures)
for i in range(10):
    target = f"src/edge_{i}.py"
    _ERROR_SEQUENCES.append({
        "type": "under_threshold",
        "failures": [
            {"tool": "Edit", "target": target, "error": "Some error"},
            {"tool": "Edit", "target": target, "error": "Some error"},
        ],
        "query_tool": "Edit",
        "query_target": target,
        "expect_block": False,
    })


# ---------------------------------------------------------------------------
# Benchmark implementations
# ---------------------------------------------------------------------------


def bench_output_compression() -> Dict[str, Any]:
    """Benchmark 1: measure output-compressor.py compression ratios."""
    hook = _REPO_ROOT / "hooks" / "post" / "output-compressor.py"
    before_total = 0
    after_total = 0
    compressed_count = 0

    for response in _PADDED_RESPONSES:
        payload = {
            "hook_event_name": "PostToolUse",
            "session_id": "bench",
            "tool_name": "Read",
            "tool_input": {},
            "tool_response": {"output": response},
        }
        result = subprocess.run(
            [sys.executable, str(hook)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=5,
        )
        before_total += len(response)
        if result.stdout.strip():
            try:
                data = json.loads(result.stdout.strip())
                ctx = data.get("additionalContext", response)
                after_total += len(ctx)
                compressed_count += 1
            except Exception:
                after_total += len(response)
        else:
            after_total += len(response)

    reduction_pct = 100.0 * (before_total - after_total) / before_total if before_total else 0
    return {
        "samples": len(_PADDED_RESPONSES),
        "compressed": compressed_count,
        "before_chars": before_total,
        "after_chars": after_total,
        "reduction_pct": reduction_pct,
    }


def bench_scope_guard_latency() -> Dict[str, Any]:
    """Benchmark 2: scope-guard.py latency over 1000 runs with contract present."""
    hook = _REPO_ROOT / "hooks" / "pre" / "scope-guard.py"
    runs = 1000

    # Use this repo's own .optimusprime/ as the cwd
    cwd = _REPO_ROOT

    payload = json.dumps({
        "hook_event_name": "PreToolUse",
        "session_id": "bench",
        "tool_name": "Write",
        "tool_input": {"file_path": "src/optimusprime/utils.py"},
    })

    start = time.perf_counter()
    for _ in range(runs):
        subprocess.run(
            [sys.executable, str(hook)],
            input=payload,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=5,
        )
    elapsed = time.perf_counter() - start
    avg_ms = elapsed * 1000 / runs

    return {"runs": runs, "total_s": elapsed, "avg_ms": avg_ms}


def bench_loop_detection() -> Dict[str, Any]:
    """Benchmark 3: loop detector accuracy on 50 sequences."""
    import importlib.util as ilu

    # Load loop detector internals directly (faster than subprocess for accuracy test)
    _PLUGIN_ROOT = _REPO_ROOT
    sys.path.insert(0, str(_PLUGIN_ROOT / "src"))

    spec = ilu.spec_from_file_location(
        "loop_detector_bench", _REPO_ROOT / "hooks" / "pre" / "loop-detector.py"
    )
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)

    true_positives = 0  # correctly blocked real loops
    true_negatives = 0  # correctly passed non-loops
    false_positives = 0  # blocked something that wasn't a loop
    false_negatives = 0  # missed a real loop

    for seq in _ERROR_SEQUENCES:
        failures = seq["failures"]
        query_tool = seq["query_tool"]
        query_target = seq["query_target"]
        expect_block = seq["expect_block"]

        count, _ = mod._count_matching_tail(failures, query_tool, query_target)
        would_block = count >= 3

        if expect_block and would_block:
            true_positives += 1
        elif not expect_block and not would_block:
            true_negatives += 1
        elif not expect_block and would_block:
            false_positives += 1
        else:
            false_negatives += 1

    total = len(_ERROR_SEQUENCES)
    accuracy = 100.0 * (true_positives + true_negatives) / total if total else 0

    return {
        "total": total,
        "true_positives": true_positives,
        "true_negatives": true_negatives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "accuracy_pct": accuracy,
    }


def bench_decision_search() -> Dict[str, Any]:
    """Benchmark 4: TF-IDF search speed over real decisions.md."""
    search_path = _REPO_ROOT / "mcp" / "search.py"
    decisions_path = _REPO_ROOT / ".optimusprime" / "decisions.md"

    spec = importlib.util.spec_from_file_location("op_search_bench", search_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    engine = mod.DecisionSearchEngine()
    engine.index(decisions_path)

    queries = [
        "atomic write", "loop detection", "stdlib", "session", "hook",
        "contract", "python", "scope", "decision", "token",
        "test", "cli", "mcp", "ecosystem", "skill",
        "install", "update", "caveman", "superpowers", "snapshot",
        "error", "fail", "block", "git", "json",
        "cost", "budget", "compress", "resume", "deploy",
        "markdown", "file", "path", "security", "performance",
        "cache", "api", "format", "version", "agent",
        "build", "pipeline", "async", "database", "config",
        "fnmatch", "glob", "regex", "subprocess", "search",
        "semver", "registry", "activator", "installer", "signal",
        "similarity", "threshold", "index", "precompact", "stop",
        "postamble", "preamble", "filler", "restatement", "caveman",
        "ponytail", "gstack", "superpowers", "fastmcp", "urllib",
        "shlex", "difflib", "tempfile", "os.rename", "find_optimusprime",
        "decisions.md", "attempts.md", "session-snapshot", "resume.json", "skills.json",
        "complexity budget", "agent_id", "session_id", "out_of_scope", "in_scope",
        "click", "pytest", "benchmark", "performance", "latency",
        "write hook", "read hook", "edit hook", "bash hook", "tools",
    ]
    # Trim to 100
    queries = (queries * 3)[:100]

    start = time.perf_counter()
    for q in queries:
        engine.search(q, top_k=5)
    elapsed = time.perf_counter() - start
    avg_ms = elapsed * 1000 / len(queries)

    return {
        "indexed": engine.doc_count,
        "queries": len(queries),
        "total_s": elapsed,
        "avg_ms": avg_ms,
    }


def bench_session_logger() -> Dict[str, Any]:
    """Benchmark 5: session-logger.py write time with real .optimusprime/ data."""
    hook = _REPO_ROOT / "hooks" / "post" / "session-logger.py"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        op_dir = tmp / ".optimusprime"
        op_dir.mkdir()

        # Copy real decisions.md
        real_decisions = _REPO_ROOT / ".optimusprime" / "decisions.md"
        if real_decisions.is_file():
            (op_dir / "decisions.md").write_text(
                real_decisions.read_text(encoding="utf-8"), encoding="utf-8"
            )

        # Write a contract
        (op_dir / "contract.json").write_text(json.dumps({
            "goal": "Benchmark session logger performance",
            "agent_id": "main",
            "session_id": "bench-session",
            "in_scope": ["src/**"],
            "out_of_scope": [".env"],
        }), encoding="utf-8")

        payload = json.dumps({"hook_event_name": "Stop", "session_id": "bench-session"})

        runs = 10
        start = time.perf_counter()
        for _ in range(runs):
            subprocess.run(
                [sys.executable, str(hook)],
                input=payload,
                capture_output=True,
                text=True,
                cwd=str(tmp),
                timeout=10,
            )
        elapsed = time.perf_counter() - start
        avg_s = elapsed / runs

    return {"runs": runs, "total_s": elapsed, "avg_s": avg_s}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def run_all() -> None:
    print()
    print("═" * 45)
    print("  OptimusPrime Benchmark Results")
    print("═" * 45)

    print("  Running output compression...", end=" ", flush=True)
    c = bench_output_compression()
    print("done")

    print("  Running scope guard latency...", end=" ", flush=True)
    s = bench_scope_guard_latency()
    print("done")

    print("  Running loop detection accuracy...", end=" ", flush=True)
    l = bench_loop_detection()
    print("done")

    print("  Running decision search speed...", end=" ", flush=True)
    d = bench_decision_search()
    print("done")

    print("  Running session logger speed...", end=" ", flush=True)
    sl = bench_session_logger()
    print("done")

    print()
    print("═" * 45)
    print("  OptimusPrime Benchmark Results")
    print("═" * 45)
    print(f"  Output compression:    -{c['reduction_pct']:.1f}% average reduction")
    print(f"  Scope guard latency:   {s['avg_ms']:.1f}ms average (n={s['runs']}, target <100ms)")
    print(f"  Loop detection:        {l['accuracy_pct']:.1f}% accuracy ({l['true_positives']}TP / {l['false_positives']}FP / {l['false_negatives']}FN)")
    print(f"  Decision search:       {d['avg_ms']:.2f}ms average ({d['indexed']} indexed, {d['queries']} queries)")
    print(f"  Session logger:        {sl['avg_s']:.2f}s average (n={sl['runs']})")
    print("═" * 45)

    # Assertions: fail loudly if we miss targets
    issues = []
    if s["avg_ms"] > 100:
        issues.append(f"SLOW scope guard: {s['avg_ms']:.1f}ms > 100ms target")
    if l["accuracy_pct"] < 90:
        issues.append(f"LOW loop accuracy: {l['accuracy_pct']:.1f}% < 90% target")
    if d["avg_ms"] > 10:
        issues.append(f"SLOW decision search: {d['avg_ms']:.2f}ms > 10ms target")
    if sl["avg_s"] > 2.0:
        issues.append(f"SLOW session logger: {sl['avg_s']:.2f}s > 2s target")

    if issues:
        print()
        print("  PERFORMANCE TARGETS MISSED:")
        for issue in issues:
            print(f"  ✗  {issue}")
        print("═" * 45)
        sys.exit(1)
    else:
        print()
        print("  All performance targets met. ✓")
        print("═" * 45)


if __name__ == "__main__":
    run_all()
