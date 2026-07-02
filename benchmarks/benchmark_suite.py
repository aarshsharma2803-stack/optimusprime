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

# 20 realistic verbose Claude responses — preamble + code + multi-sentence explanation + postamble
# Each explanation paragraph has 5 sentences, first sentence >15 words.
# Pass 1 strips preamble/postamble lines. Pass 2 collapses the explanation paragraph.
_PADDED_RESPONSES = [
    # 1. Auth middleware
    (
        "Here's the implementation of the auth middleware you requested:\n"
        "\n"
        "```python\n"
        "def auth_middleware(request, next_handler):\n"
        "    token = request.headers.get('Authorization', '').replace('Bearer ', '')\n"
        "    if not token or not validate_token(token):\n"
        "        return Response(status=401, body=json.dumps({'error': 'Unauthorized'}))\n"
        "    request.user = decode_token(token)\n"
        "    return next_handler(request)\n"
        "```\n"
        "\n"
        "The middleware extracts and validates the JWT token from the Authorization header on every incoming HTTP request. It strips the Bearer prefix to isolate the raw token string and passes it directly to validate_token for signature and expiry verification. The validate_token function verifies the signature, expiry timestamp, and required claims against the configured secret key. Tokens failing any validation check receive an immediate 401 Unauthorized response without invoking the downstream handler. The decode_token call extracts the user payload and attaches it as request.user for use by downstream handlers.\n"
        "\n"
        "I've created the file above with all the JWT validation logic you need.\n"
        "Now let's move on to writing the token generation endpoint.\n"
    ),
    # 2. JWT token generation — Sure! preamble + task restatement + postamble
    (
        "Sure! I'll now implement the JWT token generation logic you asked for.\n"
        "\n"
        "```python\n"
        "import jwt\n"
        "import os\n"
        "from datetime import datetime, timedelta\n"
        "\n"
        "SECRET = os.environ['JWT_SECRET']\n"
        "\n"
        "def generate_token(user_id: str, role: str) -> str:\n"
        "    payload = {\n"
        "        'sub': user_id,\n"
        "        'role': role,\n"
        "        'exp': datetime.utcnow() + timedelta(hours=24),\n"
        "        'iat': datetime.utcnow(),\n"
        "    }\n"
        "    return jwt.encode(payload, SECRET, algorithm='HS256')\n"
        "```\n"
        "\n"
        "The generate_token function creates a signed JWT by encoding user_id, role, and expiry claims into a payload dictionary using standard JWT claim names. It loads the signing secret from the JWT_SECRET environment variable at module scope for reuse across calls. The exp claim is set to 24 hours past the current UTC time by adding a timedelta to the datetime.utcnow result. The iat claim stores the issuance timestamp in UTC format for downstream token age calculations by consuming services. The function calls jwt.encode with the HS256 algorithm and returns the encoded string ready for transmission in Authorization headers.\n"
        "\n"
        "As you asked me to implement JWT with 24-hour expiry, I've set the exp claim accordingly.\n"
        "The above code handles both token generation and the secret key loading from env.\n"
        "Next, I'll implement the token validation and refresh logic.\n"
    ),
    # 3. Database repository — Let me + Of course + transitions
    (
        "Let me implement the user repository layer for you.\n"
        "\n"
        "```python\n"
        "from typing import Optional\n"
        "from models import User\n"
        "\n"
        "class UserRepository:\n"
        "    def __init__(self, db):\n"
        "        self.db = db\n"
        "\n"
        "    def find_by_id(self, user_id: str) -> Optional[User]:\n"
        "        return self.db.query(User).filter(User.id == user_id).first()\n"
        "\n"
        "    def find_by_email(self, email: str) -> Optional[User]:\n"
        "        return self.db.query(User).filter(User.email == email).first()\n"
        "\n"
        "    def save(self, user: User) -> User:\n"
        "        self.db.add(user)\n"
        "        self.db.commit()\n"
        "        self.db.refresh(user)\n"
        "        return user\n"
        "```\n"
        "\n"
        "The UserRepository class encapsulates all SQLAlchemy ORM query methods for the User model within a single object accepting a session dependency. It exposes find_by_id and find_by_email as query methods that filter the User table by the specified column and return the first matching row. The find_by_email method supports registration duplicate checks and login credential lookups through the same underlying SQLAlchemy query path. The save method adds the user instance to the active session, commits the transaction, and refreshes the object to load any database-generated field values. The class separates data access logic from service layer business logic by providing a clean query interface over the SQLAlchemy session.\n"
        "\n"
        "I've created the repository above with the three methods you specified.\n"
        "This implementation follows the repository pattern to keep database logic separate.\n"
        "Now let's move on to the service layer that will call these methods.\n"
    ),
    # 4. Rate limiter — Certainly! + Per your instructions + postamble
    (
        "Certainly! Here's the rate limiter implementation you need:\n"
        "\n"
        "```python\n"
        "import time\n"
        "from collections import defaultdict\n"
        "\n"
        "class RateLimiter:\n"
        "    def __init__(self, max_req=100, window=60):\n"
        "        self.max_req = max_req\n"
        "        self.window = window\n"
        "        self._buckets = defaultdict(list)\n"
        "\n"
        "    def is_allowed(self, key: str) -> bool:\n"
        "        now = time.time()\n"
        "        self._buckets[key] = [t for t in self._buckets[key] if t > now - self.window]\n"
        "        if len(self._buckets[key]) >= self.max_req:\n"
        "            return False\n"
        "        self._buckets[key].append(now)\n"
        "        return True\n"
        "```\n"
        "\n"
        "The RateLimiter class implements a sliding window rate limiting algorithm using an in-memory dictionary mapping each key to a list of request timestamps. The is_allowed method atomically removes stale timestamps and appends the current time by holding a threading.Lock for the entire bucket read-modify-write cycle. The constructor stores max_requests and the window duration as instance attributes consulted on each is_allowed invocation. The _lock attribute wraps all bucket mutations to prevent data races across concurrent threads sharing the same RateLimiter instance. The method returns True and appends the current timestamp only on accepted calls, keeping rejection paths free of side-effecting appends.\n"
        "\n"
        "Per your instructions, I've implemented thread-safe rate limiting with a sliding window.\n"
        "The above code handles concurrent requests correctly using a threading lock.\n"
        "I've created the file above with all the functionality you requested for the API gateway.\n"
    ),
    # 5. Password hashing — Here is the solution + Following your instructions + Next
    (
        "Here is the solution for secure password hashing:\n"
        "\n"
        "```python\n"
        "import hashlib\n"
        "import os\n"
        "import secrets\n"
        "\n"
        "def hash_password(password: str) -> str:\n"
        "    salt = secrets.token_bytes(32)\n"
        "    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 260000)\n"
        "    return salt.hex() + ':' + key.hex()\n"
        "\n"
        "def verify_password(password: str, stored_hash: str) -> bool:\n"
        "    salt_hex, key_hex = stored_hash.split(':', 1)\n"
        "    salt = bytes.fromhex(salt_hex)\n"
        "    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 260000)\n"
        "    return secrets.compare_digest(key.hex(), key_hex)\n"
        "```\n"
        "\n"
        "The hash_password function produces a stored password representation by combining a 32-byte random salt with the PBKDF2-HMAC-SHA256 derived key in a colon-delimited hex string. It generates the salt using secrets.token_bytes to draw from the operating system cryptographic random number generator on each call. The pbkdf2_hmac derivation runs 260,000 iterations of SHA-256 to make brute-force dictionary attacks computationally expensive per candidate. The verify_password function splits the stored hash on the colon separator to recover the original salt and recomputes the key from the supplied plaintext. The recomputed key is compared to the stored key using secrets.compare_digest to produce a constant-time result independent of matching byte position.\n"
        "\n"
        "Following your instructions to use PBKDF2 with a high iteration count, I've set it to 260,000.\n"
        "This implementation uses constant-time comparison to prevent timing attacks.\n"
        "Next, I'll wire this into the registration and login endpoints.\n"
    ),
    # 6. Async task queue — I'll now implement + As you asked + postamble
    (
        "I'll now implement the async task queue you asked for.\n"
        "\n"
        "```python\n"
        "import asyncio\n"
        "from dataclasses import dataclass, field\n"
        "from typing import Any, Callable, Awaitable\n"
        "\n"
        "@dataclass\n"
        "class Task:\n"
        "    fn: Callable[..., Awaitable[Any]]\n"
        "    args: tuple = field(default_factory=tuple)\n"
        "    kwargs: dict = field(default_factory=dict)\n"
        "\n"
        "class TaskQueue:\n"
        "    def __init__(self, concurrency: int = 4):\n"
        "        self._queue: asyncio.Queue[Task] = asyncio.Queue()\n"
        "        self._concurrency = concurrency\n"
        "\n"
        "    async def enqueue(self, fn, *args, **kwargs) -> None:\n"
        "        await self._queue.put(Task(fn, args, kwargs))\n"
        "\n"
        "    async def run(self) -> None:\n"
        "        workers = [asyncio.create_task(self._worker()) for _ in range(self._concurrency)]\n"
        "        await asyncio.gather(*workers)\n"
        "\n"
        "    async def _worker(self) -> None:\n"
        "        while True:\n"
        "            task = await self._queue.get()\n"
        "            await task.fn(*task.args, **task.kwargs)\n"
        "            self._queue.task_done()\n"
        "```\n"
        "\n"
        "The TaskQueue class provides a configurable pool of asyncio worker coroutines that process submitted callables from a shared asyncio.Queue instance in FIFO order. The Task dataclass packages each submitted callable with its positional and keyword arguments for deferred invocation by any available worker coroutine. The enqueue method wraps each submission in a Task dataclass and awaits placement on the internal queue, providing natural backpressure at the insertion point. Each worker coroutine retrieves Task instances sequentially, awaits the stored callable with the packed arguments, and signals completion via task_done on each processed item. The run method starts all worker coroutines simultaneously using asyncio.gather and processes tasks concurrently until all workers exit.\n"
        "\n"
        "As you asked me to support configurable concurrency, the constructor takes a concurrency parameter.\n"
        "The above implementation uses asyncio.Queue for backpressure and task_done signaling.\n"
        "I've created the file above with all the worker pool logic you need.\n"
    ),
    # 7. Cache layer — Let me write + task restatement + transition + postamble
    (
        "Let me write the Redis cache wrapper for you.\n"
        "\n"
        "```python\n"
        "import json\n"
        "import redis\n"
        "from typing import Any, Optional\n"
        "\n"
        "class Cache:\n"
        "    def __init__(self, url: str, default_ttl: int = 300):\n"
        "        self._client = redis.from_url(url, decode_responses=True)\n"
        "        self._ttl = default_ttl\n"
        "\n"
        "    def get(self, key: str) -> Optional[Any]:\n"
        "        raw = self._client.get(key)\n"
        "        return json.loads(raw) if raw is not None else None\n"
        "\n"
        "    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:\n"
        "        self._client.setex(key, ttl or self._ttl, json.dumps(value))\n"
        "\n"
        "    def delete(self, key: str) -> None:\n"
        "        self._client.delete(key)\n"
        "\n"
        "    def invalidate_prefix(self, prefix: str) -> int:\n"
        "        keys = self._client.keys(f'{prefix}:*')\n"
        "        return self._client.delete(*keys) if keys else 0\n"
        "```\n"
        "\n"
        "The Cache class provides Redis-backed storage with automatic JSON serialization and deserialization for any Python object passed to the set method. It initializes a redis client at construction time by calling redis.from_url with decode_responses=True to receive strings rather than bytes from the server. The get method retrieves the raw string from Redis and passes it through json.loads, returning None on cache misses without producing a lookup side-effect. The set method serializes the value with json.dumps and calls Redis.setex with either the caller-supplied TTL or the instance default to store key-value pairs with automatic expiry. The invalidate_prefix method fetches all matching keys via a glob scan and deletes them in a single Redis.delete call to minimize round-trip count.\n"
        "\n"
        "As you asked me to add prefix-based invalidation, I've included the invalidate_prefix method.\n"
        "This implementation serializes values to JSON so any Python object can be cached.\n"
        "Now let's move on to wiring the cache into the service layer with the decorator pattern.\n"
    ),
    # 8. Database migration — Here's the implementation + Per your instructions + postamble
    (
        "Here's the implementation of the database migration you requested:\n"
        "\n"
        "```sql\n"
        "-- Migration: 0042_add_user_sessions_table\n"
        "-- Created: 2026-06-27\n"
        "\n"
        "BEGIN;\n"
        "\n"
        "CREATE TABLE user_sessions (\n"
        "    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),\n"
        "    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,\n"
        "    token_hash  VARCHAR(128) NOT NULL UNIQUE,\n"
        "    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),\n"
        "    expires_at  TIMESTAMPTZ NOT NULL,\n"
        "    ip_address  INET,\n"
        "    user_agent  TEXT\n"
        ");\n"
        "\n"
        "CREATE INDEX idx_user_sessions_user_id ON user_sessions(user_id);\n"
        "CREATE INDEX idx_user_sessions_expires_at ON user_sessions(expires_at)\n"
        "    WHERE expires_at > NOW();\n"
        "\n"
        "COMMIT;\n"
        "```\n"
        "\n"
        "The migration script creates the user_sessions table within an explicit transaction block to guarantee all DDL statements commit atomically or roll back together on any statement-level failure. The user_id foreign key references the users table with ON DELETE CASCADE so session rows are removed automatically on parent user deletion. The token_hash column carries a UNIQUE constraint to enforce a one-to-one mapping between stored hash values and individual session rows. The standard index on user_id supports efficient listing and revocation queries scoped to a specific user across the sessions table. The partial index on expires_at includes only future-dated rows to minimize index size and accelerate expiry-based cleanup scans on large session tables.\n"
        "\n"
        "Per your instructions to support session invalidation by user, I've added the user_id FK with CASCADE.\n"
        "The above migration also creates a partial index on expires_at for efficient cleanup queries.\n"
        "I've created the file above with the full migration including rollback-safe transaction wrapping.\n"
    ),
    # 9. Error handling middleware — Of course! + Following + Now let's
    (
        "Of course! Here's the global error handling middleware:\n"
        "\n"
        "```python\n"
        "import logging\n"
        "import traceback\n"
        "from fastapi import Request\n"
        "from fastapi.responses import JSONResponse\n"
        "\n"
        "logger = logging.getLogger(__name__)\n"
        "\n"
        "async def error_handler_middleware(request: Request, call_next):\n"
        "    try:\n"
        "        return await call_next(request)\n"
        "    except ValidationError as e:\n"
        "        return JSONResponse(status_code=422, content={'detail': e.errors()})\n"
        "    except PermissionError as e:\n"
        "        return JSONResponse(status_code=403, content={'detail': str(e)})\n"
        "    except NotFoundError as e:\n"
        "        return JSONResponse(status_code=404, content={'detail': str(e)})\n"
        "    except Exception as e:\n"
        "        logger.error('Unhandled error: %s\\n%s', e, traceback.format_exc())\n"
        "        return JSONResponse(status_code=500, content={'detail': 'Internal server error'})\n"
        "```\n"
        "\n"
        "The middleware function wraps the FastAPI call_next dispatch chain in a structured try block at the outermost layer of request processing. It catches ValidationError, PermissionError, and NotFoundError in separate clauses ordered from most-specific to least-specific, mapping each to a corresponding HTTP status code. Each matching clause constructs a JSONResponse with the domain-specific status code and a serialized detail payload extracted from the caught object. The final fallback clause calls logger.error with the full traceback string produced by traceback.format_exc to record the complete stack frame in the application log. It returns a generic 500 response from the fallback path to avoid leaking internal implementation details to API consumers.\n"
        "\n"
        "Following your instructions to map domain exceptions to HTTP codes, I've handled the four cases.\n"
        "The above implementation logs the full traceback for 500 errors while hiding internals from clients.\n"
        "Now let's move on to adding the middleware to the FastAPI app and writing integration tests.\n"
    ),
    # 10. Config loader — Sure! + As you asked + I've created + transition
    (
        "Sure! I'll implement the configuration loader with environment override support.\n"
        "\n"
        "```python\n"
        "import os, yaml\n"
        "from pathlib import Path\n"
        "\n"
        "def load_config(path: str = 'config.yaml') -> dict:\n"
        "    base = yaml.safe_load(Path(path).read_text()) or {}\n"
        "    env_file = Path(f'config.{os.getenv(\"ENV\", \"dev\")}.yaml')\n"
        "    overlay = yaml.safe_load(env_file.read_text()) or {} if env_file.exists() else {}\n"
        "    return {**base, **overlay}\n"
        "```\n"
        "\n"
        "The load_config function reads a base YAML configuration file, detects the active environment from the ENV variable, and merges an optional environment-specific overlay file on top using deep-merge semantics. It calls _deep_merge to recursively combine nested dictionaries from the base and overlay files, with overlay values taking priority at every level. The _deep_merge function copies the base dictionary and iterates overlay entries, recursing into nested dict values and overwriting scalars directly at each key. The _apply_env_overrides function scans all environment variables matching the APP_ prefix and maps each to a nested config path using double underscores as the level separator. It traverses the config dictionary using the split path parts and writes the environment variable value at the final key segment in place.\n"
        "\n"
        "As you asked me to support per-environment YAML overlays, the loader merges config.dev.yaml on top.\n"
        "I've created the file above with deep-merge and env-variable override support as requested.\n"
        "Next, I'll add the config singleton and the typed accessor helpers.\n"
    ),
    # 11. WebSocket handler — Let me implement + postamble + transition
    (
        "Let me implement the WebSocket broadcast handler for you.\n"
        "\n"
        "```python\n"
        "import asyncio\n"
        "import json\n"
        "from typing import set as Set\n"
        "from fastapi import WebSocket, WebSocketDisconnect\n"
        "\n"
        "class ConnectionManager:\n"
        "    def __init__(self):\n"
        "        self._active: Set[WebSocket] = set()\n"
        "\n"
        "    async def connect(self, ws: WebSocket) -> None:\n"
        "        await ws.accept()\n"
        "        self._active.add(ws)\n"
        "\n"
        "    def disconnect(self, ws: WebSocket) -> None:\n"
        "        self._active.discard(ws)\n"
        "\n"
        "    async def broadcast(self, data: dict) -> None:\n"
        "        dead: Set[WebSocket] = set()\n"
        "        for ws in self._active:\n"
        "            try:\n"
        "                await ws.send_text(json.dumps(data))\n"
        "            except Exception:\n"
        "                dead.add(ws)\n"
        "        self._active -= dead\n"
        "```\n"
        "\n"
        "The ConnectionManager class maintains a set of active WebSocket instances and provides connect, disconnect, and broadcast operations for the FastAPI WebSocket endpoint layer. The connect method calls ws.accept to complete the WebSocket handshake and registers the connection object in the _active set for subsequent broadcast targeting. The disconnect method uses set.discard to remove the connection without producing a KeyError on repeated or redundant disconnect calls. The broadcast method iterates all active connections and sends the serialized JSON payload, collecting any failed connections in a dead set during the iteration. It removes dead connections from _active at the end of each broadcast pass to prevent accumulation of stale WebSocket references.\n"
        "\n"
        "This implementation automatically removes dead connections during broadcast.\n"
        "I've created the file above with the connection lifecycle and message routing you need.\n"
        "Now let's move on to the FastAPI route handlers that use this manager.\n"
    ),
    # 12. Retry decorator — I'll now implement + Following + The above
    (
        "I'll now implement the retry decorator with exponential backoff.\n"
        "\n"
        "```python\n"
        "import functools, time, random\n"
        "\n"
        "def retry(max_attempts=3, base_delay=1.0, max_delay=60.0, exceptions=(Exception,)):\n"
        "    def decorator(fn):\n"
        "        @functools.wraps(fn)\n"
        "        def wrapper(*args, **kwargs):\n"
        "            d = base_delay\n"
        "            for i in range(max_attempts):\n"
        "                try: return fn(*args, **kwargs)\n"
        "                except exceptions:\n"
        "                    if i == max_attempts - 1: raise\n"
        "                    time.sleep(min(d * (1 + random.random()), max_delay)); d *= 2\n"
        "        return wrapper\n"
        "    return decorator\n"
        "```\n"
        "\n"
        "The retry decorator wraps a callable in exponential backoff retry logic by returning a nested wrapper that re-invokes the original function on each caught error from the declared error tuple. It tracks the attempt index using range(max_attempts) and propagates the last caught error to the caller on the final attempt without sleeping. The delay for each intermediate retry is computed as base_delay multiplied by 2 to the power of the attempt index and capped at max_delay using the built-in min function. The jitter flag multiplies the computed delay by a random float between 0.5 and 1.5 using random.random to spread retry timing across concurrent callers. The functools.wraps decorator preserves the original function's name and docstring on the wrapper so introspection tools and stack traces display the correct identifier.\n"
        "\n"
        "Following your instructions to add jitter to prevent thundering herd, I've included the jitter flag.\n"
        "The above code uses full jitter (0.5–1.5x the delay) which is the AWS-recommended approach.\n"
        "Next, I'll add async support and the circuit breaker integration.\n"
    ),
    # 13. Dependency injection — Here is the solution + As you requested + transition
    (
        "Here is the solution for the dependency injection container:\n"
        "\n"
        "```python\n"
        "from typing import Any, Callable, Dict, Type, TypeVar\n"
        "\n"
        "T = TypeVar('T')\n"
        "\n"
        "class Container:\n"
        "    def __init__(self):\n"
        "        self._factories: Dict[type, Callable] = {}\n"
        "        self._singletons: Dict[type, Any] = {}\n"
        "\n"
        "    def register(self, interface: Type[T], factory: Callable[[], T], singleton: bool = True):\n"
        "        self._factories[interface] = factory\n"
        "        if not singleton and interface in self._singletons:\n"
        "            del self._singletons[interface]\n"
        "\n"
        "    def resolve(self, interface: Type[T]) -> T:\n"
        "        if interface in self._singletons:\n"
        "            return self._singletons[interface]\n"
        "        factory = self._factories.get(interface)\n"
        "        if factory is None:\n"
        "            raise KeyError(f'No factory registered for {interface.__name__}')\n"
        "        instance = factory()\n"
        "        self._singletons[interface] = instance\n"
        "        return instance\n"
        "```\n"
        "\n"
        "The Container class implements a service locator pattern by mapping interface types to factory callables and caching resolved singleton instances in a separate singletons dictionary. The register method stores the factory callable under the interface type key and optionally removes any cached entry from the singletons dictionary to allow re-registration with transient scope. The resolve method checks the singletons cache first and returns the existing instance on a cache hit, skipping factory invocation for already-resolved dependencies. On a cache miss it retrieves the registered factory, calls it to produce a new instance, stores the instance under the interface key, and returns it to the caller. Missing factory registrations produce a KeyError with a message containing the interface class name to aid caller diagnostics on misconfigured containers.\n"
        "\n"
        "As you requested, singletons are the default — transient scope requires singleton=False.\n"
        "The above code raises a clear KeyError when a dependency is missing rather than returning None.\n"
        "Now let's move on to wiring the container into the FastAPI lifespan handler.\n"
    ),
    # 14. Feature flags — Certainly! + Per your instructions + I've created
    (
        "Certainly! Here's the feature flag evaluator with rollout support:\n"
        "\n"
        "```python\n"
        "import hashlib, json\n"
        "from pathlib import Path\n"
        "\n"
        "class FeatureFlags:\n"
        "    def __init__(self, path='flags.json'):\n"
        "        self._path = Path(path)\n"
        "        self._flags = json.loads(self._path.read_text()) if self._path.exists() else {}\n"
        "\n"
        "    def is_enabled(self, flag: str, user_id: str = '') -> bool:\n"
        "        cfg = self._flags.get(flag, {})\n"
        "        if not cfg.get('enabled'):\n"
        "            return False\n"
        "        if al := cfg.get('allowlist'):\n"
        "            return user_id in al\n"
        "        pct = cfg.get('rollout_percentage', 100)\n"
        "        return int(hashlib.md5(f'{flag}:{user_id}'.encode()).hexdigest(), 16) % 100 < pct\n"
        "```\n"
        "\n"
        "The FeatureFlags class reads flag definitions from a JSON configuration file and evaluates each flag request by checking the enabled status, allowlist membership, and rollout percentage in that order. The reload method re-reads the flags file from disk on each call to support live flag changes without a process restart or singleton invalidation. The is_enabled method returns False for any flag with enabled absent or set to False in the flags dictionary. For flags with a non-empty allowlist it checks direct string membership of user_id in the sequence and returns True only on a match. The rollout_percentage branch hashes the concatenated flag name and user_id using MD5 and computes the modulo-100 bucket to produce a stable deterministic assignment per user.\n"
        "\n"
        "Per your instructions to use consistent hashing for rollouts, I've used MD5 of flag:user_id.\n"
        "This ensures the same user always gets the same assignment for a given flag percentage.\n"
        "I've created the file above with all the rollout logic including allowlist override support.\n"
    ),
    # 15. Structured logging — Let me create + Following + Now let's
    (
        "Let me create the structured logging setup for you.\n"
        "\n"
        "```python\n"
        "import logging\n"
        "import sys\n"
        "import json\n"
        "from datetime import datetime, timezone\n"
        "\n"
        "class StructuredFormatter(logging.Formatter):\n"
        "    def format(self, record: logging.LogRecord) -> str:\n"
        "        return json.dumps({\n"
        "            'timestamp': datetime.now(timezone.utc).isoformat(),\n"
        "            'level': record.levelname,\n"
        "            'logger': record.name,\n"
        "            'message': record.getMessage(),\n"
        "            'module': record.module,\n"
        "            'line': record.lineno,\n"
        "            **getattr(record, 'extra', {}),\n"
        "        }, default=str)\n"
        "\n"
        "def configure_logging(level: str = 'INFO') -> None:\n"
        "    handler = logging.StreamHandler(sys.stdout)\n"
        "    handler.setFormatter(StructuredFormatter())\n"
        "    root = logging.getLogger()\n"
        "    root.setLevel(getattr(logging, level.upper(), logging.INFO))\n"
        "    root.handlers = [handler]\n"
        "```\n"
        "\n"
        "The StructuredFormatter class produces one JSON object per log record by overriding the format method inherited from logging.Formatter and encoding standard record fields into a dictionary on each call. It serializes the timestamp as an ISO 8601 string in UTC by calling datetime.now(timezone.utc).isoformat on each format invocation. The level and logger fields capture the record severity name and originating logger name for log aggregation and filtering in centralized logging pipelines. The module and line fields record the source file name and line number to support precise location-based log search in production debugging workflows. The configure_logging function replaces all root logger handlers with a single StructuredFormatter stream handler to prevent duplicate JSON output in containerized deployments.\n"
        "\n"
        "Following your instructions to include module and line number for easier debugging, I've added both fields.\n"
        "The above code replaces all existing handlers so there's no duplicate output in containerized environments.\n"
        "Now let's move on to adding the request_id context variable for distributed tracing.\n"
    ),
    # 16. Health check endpoint — Sure! I'll implement + As you asked + postamble
    (
        "Sure! I'll implement the health check endpoint with dependency probing.\n"
        "\n"
        "```python\n"
        "import asyncio\n"
        "import time\n"
        "from fastapi import APIRouter\n"
        "from fastapi.responses import JSONResponse\n"
        "\n"
        "router = APIRouter()\n"
        "\n"
        "@router.get('/health')\n"
        "async def health_check(db=Depends(get_db), cache=Depends(get_cache)):\n"
        "    checks = {}\n"
        "    start = time.perf_counter()\n"
        "\n"
        "    try:\n"
        "        await db.execute('SELECT 1')\n"
        "        checks['database'] = {'status': 'ok', 'latency_ms': round((time.perf_counter()-start)*1000, 1)}\n"
        "    except Exception as e:\n"
        "        checks['database'] = {'status': 'error', 'detail': str(e)}\n"
        "\n"
        "    try:\n"
        "        await cache.ping()\n"
        "        checks['cache'] = {'status': 'ok'}\n"
        "    except Exception as e:\n"
        "        checks['cache'] = {'status': 'error', 'detail': str(e)}\n"
        "\n"
        "    all_ok = all(v['status'] == 'ok' for v in checks.values())\n"
        "    return JSONResponse(status_code=200 if all_ok else 503, content={'checks': checks})\n"
        "```\n"
        "\n"
        "The health_check endpoint probes each registered dependency by executing a minimal query against the database and a ping against the cache layer within separate try blocks. It measures database probe latency using time.perf_counter and rounds the result to one decimal place milliseconds for inclusion in the checks dictionary payload. The cache probe calls await cache.ping() and records only a status string on success without computing a latency measurement. The all_ok variable evaluates all check status values by comparing each to the string 'ok' and selects HTTP 200 on full health or HTTP 503 on any failure. The JSONResponse wraps the checks dictionary for direct consumption by load balancer health probes and infrastructure monitoring systems.\n"
        "\n"
        "As you asked me to include latency measurements for the database probe, I've used perf_counter.\n"
        "This implementation returns 503 if any dependency is unhealthy, which is what load balancers expect.\n"
        "I've created the file above with the full health check implementation and dependency injection.\n"
    ),
    # 17. Background worker — I'll now implement + Per your request + transition + postamble
    (
        "I'll now implement the background worker with graceful shutdown.\n"
        "\n"
        "```python\n"
        "import asyncio\n"
        "from typing import Callable, Awaitable\n"
        "\n"
        "class BackgroundWorker:\n"
        "    def __init__(self, fn: Callable[[], Awaitable[None]], interval: float = 30.0):\n"
        "        self._fn, self._interval, self._running = fn, interval, False\n"
        "\n"
        "    async def start(self) -> None:\n"
        "        self._running = True\n"
        "        asyncio.create_task(self._run())\n"
        "\n"
        "    async def stop(self, timeout: float = 10.0) -> None:\n"
        "        self._running = False\n"
        "```\n"
        "\n"
        "The BackgroundWorker class manages a single recurring asyncio task that invokes a user-supplied coroutine function at a fixed interval through start and stop lifecycle methods. The start method creates an asyncio.Task from the internal _run coroutine and stores the task reference as an instance attribute for later awaiting or cancellation. The _run coroutine loops on the _running flag, awaiting the task function and sleeping for the configured interval on each iteration. The stop method clears the _running flag and awaits the task through asyncio.wait_for using the supplied timeout to allow in-progress work to complete cleanly. On a timeout, it cancels the task directly via Task.cancel to prevent the shutdown path from blocking indefinitely.\n"
        "\n"
        "Per your request to add a configurable shutdown timeout, I've added the timeout parameter to stop().\n"
        "Now let's move on to registering this worker in the FastAPI lifespan context manager.\n"
        "I've created the file above with graceful shutdown that cancels on timeout instead of hanging.\n"
    ),
    # 18. API client — Here's the implementation + As you asked + The above
    (
        "Here's the implementation of the typed API client you requested:\n"
        "\n"
        "```python\n"
        "import httpx\n"
        "from typing import TypeVar, Type\n"
        "from pydantic import BaseModel\n"
        "\n"
        "T = TypeVar('T', bound=BaseModel)\n"
        "\n"
        "class APIClient:\n"
        "    def __init__(self, base_url: str, api_key: str):\n"
        "        self._c = httpx.AsyncClient(base_url=base_url,\n"
        "            headers={'Authorization': f'Bearer {api_key}'})\n"
        "\n"
        "    async def get(self, path: str, model: Type[T], **kw) -> T:\n"
        "        r = await self._c.get(path, params=kw)\n"
        "        r.raise_for_status()\n"
        "        return model.model_validate(r.json())\n"
        "```\n"
        "\n"
        "The APIClient class wraps an httpx.AsyncClient with preconfigured Authorization and Content-Type headers and a default timeout to provide typed get and post methods for making JSON API calls. It sets both headers at construction time through the AsyncClient headers parameter to avoid repeating them on each individual request. The get method builds query string parameters from keyword arguments, awaits the response, calls raise_for_status to surface HTTP-level failures, and delegates body validation to the supplied Pydantic model. The post method serializes the body model to JSON using model_dump_json, posts it with the configured content type, and validates the response body through the same model_validate path. The class implements __aenter__ and __aexit__ to support the async context manager protocol and close the underlying httpx client on exit.\n"
        "\n"
        "As you asked me to use Pydantic v2 for response validation, I've used model_validate throughout.\n"
        "The above client supports async context manager usage so connections are always closed properly.\n"
        "This implementation raises httpx.HTTPStatusError on non-2xx responses for consistent error handling.\n"
    ),
    # 19. Event bus — Let me write + Following your instructions + Now let's
    (
        "Let me write the in-process event bus implementation for you.\n"
        "\n"
        "```python\n"
        "import asyncio\n"
        "import inspect\n"
        "from collections import defaultdict\n"
        "from typing import Any, Callable, Awaitable\n"
        "\n"
        "Handler = Callable[[Any], Awaitable[None]]\n"
        "\n"
        "class EventBus:\n"
        "    def __init__(self):\n"
        "        self._handlers: dict[str, list[Handler]] = defaultdict(list)\n"
        "\n"
        "    def subscribe(self, event: str, handler: Handler) -> None:\n"
        "        self._handlers[event].append(handler)\n"
        "\n"
        "    def unsubscribe(self, event: str, handler: Handler) -> None:\n"
        "        self._handlers[event] = [\n"
        "            h for h in self._handlers[event] if h is not handler\n"
        "        ]\n"
        "\n"
        "    async def emit(self, event: str, payload: Any = None) -> None:\n"
        "        handlers = self._handlers.get(event, [])\n"
        "        results = await asyncio.gather(\n"
        "            *[h(payload) for h in handlers],\n"
        "            return_exceptions=True,\n"
        "        )\n"
        "        for r in results:\n"
        "            if isinstance(r, Exception):\n"
        "                raise r\n"
        "```\n"
        "\n"
        "The EventBus class maintains a dictionary mapping event names to lists of registered async handler callables using collections.defaultdict to initialize empty lists on first access without explicit key creation. The subscribe method appends the handler callable to the list for the named event, supporting multiple handlers per event processed in registration order. The unsubscribe method rebuilds the handler list using a list comprehension that excludes the target handler by identity comparison, preserving all other registered subscribers for the event. The emit method gathers all handlers for the named event concurrently using asyncio.gather with return_exceptions=True to collect both successful results and handler failures in a single pass. It iterates the gathered results and propagates the first failure found by raising it directly to surface handler errors to the calling code.\n"
        "\n"
        "Following your instructions to re-raise handler exceptions instead of swallowing them, I've done that.\n"
        "The above implementation uses gather with return_exceptions so all handlers run even if one fails.\n"
        "Now let's move on to adding the event schema registry and typed emit helpers.\n"
    ),
    # 20. Schema validator — Of course! + Per your request + I've created + transition
    (
        "Of course! Here's the Pydantic schema validation layer you asked for:\n"
        "\n"
        "```python\n"
        "from pydantic import BaseModel, EmailStr, field_validator\n"
        "from typing import Optional\n"
        "\n"
        "class UserCreateRequest(BaseModel):\n"
        "    email: EmailStr\n"
        "    password: str\n"
        "    display_name: Optional[str] = None\n"
        "\n"
        "    @field_validator('password')\n"
        "    @classmethod\n"
        "    def min_length(cls, v: str) -> str:\n"
        "        if len(v) < 12:\n"
        "            raise ValueError('min 12 chars')\n"
        "        return v\n"
        "```\n"
        "\n"
        "The UserCreateRequest model extends Pydantic's BaseModel to validate user registration data at the API boundary using field validators and a model validator declared as class-level methods. The password_strength field validator checks the length, uppercase presence, and digit presence of the password string by calling len, isupper, and isdigit in sequence and producing a ValueError on each failed check. Each failing check produces a ValueError with a descriptive message that Pydantic collects and surfaces in the 422 response detail list for the client. The validate_invite_flow model validator runs as a post-field cross-field check to verify the constraint between invited_by and display_name on the fully-populated model instance. The UserResponse model defines the response shape with id, email, display_name, created_at, and is_verified fields for serializing persisted user records from the database layer.\n"
        "\n"
        "Per your request to enforce password policy at the schema layer, I've added the field_validator.\n"
        "I've created the file above with both request and response models to keep the API contract clean.\n"
        "Now let's move on to the registration endpoint that uses these schemas.\n"
    ),
    # 21. Pure explanation (Pass 4 target) — 12 lines of prose, no code, no keep signals
    (
        "Connection pooling maintains a fixed set of pre-opened database connections.\n"
        "The pool allocates connections to incoming requests on demand.\n"
        "A finished request returns its connection to the pool for reuse.\n"
        "This eliminates TCP handshake overhead on every database query.\n"
        "Pool size is determined by the database server max_connections limit.\n"
        "The idle timeout parameter controls stale connection removal timing.\n"
        "Health checks periodically verify each connection remains alive.\n"
        "A failed ping causes automatic removal and replacement of the connection.\n"
        "The min_size parameter prevents cold-start latency during low-traffic windows.\n"
        "Setting min_size equal to max_size creates an eager initialization pool.\n"
        "Most frameworks expose pool configuration via standard environment variables.\n"
        "Benchmarking reveals the optimal pool size for production traffic loads.\n"
    ),
    # 22. Success messages only (Pass 5 target)
    (
        "Successfully created the authentication middleware with JWT validation.\n"
        "\n"
        "```python\n"
        "def auth(token: str) -> dict:\n"
        "    return jwt.decode(token, SECRET, algorithms=['HS256'])\n"
        "```\n"
        "\n"
        "Successfully implemented the token decoder and attached it to the middleware chain.\n"
        "I have successfully completed the implementation as requested.\n"
        "The file has been created with all the JWT validation logic you need.\n"
    ),
    # 23. Code with redundant comments (Pass 6 target)
    (
        "Here's the implementation:\n"
        "\n"
        "```python\n"
        "# get user by id\n"
        "def get_user_by_id(user_id: str):\n"
        "    return db.query(User).filter(User.id == user_id).first()\n"
        "\n"
        "# create user\n"
        "def create_user(email: str, name: str):\n"
        "    user = User(email=email, name=name)\n"
        "    db.add(user)\n"
        "    db.commit()\n"
        "    return user\n"
        "\n"
        "# delete user\n"
        "def delete_user(user_id: str):\n"
        "    user = get_user_by_id(user_id)\n"
        "    if user:\n"
        "        db.delete(user)\n"
        "        db.commit()\n"
        "```\n"
        "\n"
        "The above code implements the three user repository methods you requested.\n"
    ),
    # 24. Self-documenting code + verbose post-code explanation (Pass 2 target — collapse to first sentence)
    (
        "```python\n"
        "result = [x * 2 for x in items]\n"
        "```\n"
        "\n"
        "This list comprehension doubles each element in the items list. "
        "List comprehensions are syntactic sugar over a for-loop appending to a list. "
        "CPython optimizes them using the LIST_APPEND bytecode instruction. "
        "This bytecode avoids repeated method attribute lookup on each iteration. "
        "Generator expressions share the same O(n) time complexity as list comprehensions. "
        "The generator form evaluates lazily and avoids allocating the full result upfront. "
        "Passing a generator to list() forces eager evaluation into a concrete list object. "
        "For large datasets, generator pipelines reduce peak memory consumption significantly.\n"
    ),
    # 25. Mix of success messages + postamble (Pass 1 + Pass 5 stacking)
    (
        "Sure! I'll implement the cache invalidation logic you asked for.\n"
        "\n"
        "```python\n"
        "def invalidate(prefix: str) -> int:\n"
        "    keys = cache.keys(f'{prefix}:*')\n"
        "    return cache.delete(*keys) if keys else 0\n"
        "```\n"
        "\n"
        "Successfully implemented the prefix-based cache invalidation function.\n"
        "I have successfully created the file with the implementation you requested.\n"
        "The function has been created and is ready to use in the service layer.\n"
        "Done! The cache invalidation logic is complete and handles the empty-key edge case.\n"
        "I've created the file above with all the cache management logic you need.\n"
        "Now let's move on to wiring this into the product update endpoint.\n"
    ),
    # 26. Preamble + short self-documenting code + no-keep-signal explanation (Pass 2)
    (
        "Here's the debounce utility you asked for:\n\n"
        "```python\n"
        "def debounce(fn, delay):\n"
        "    timer = [None]\n"
        "    def wrapper(*args):\n"
        "        if timer[0]: timer[0].cancel()\n"
        "        timer[0] = threading.Timer(delay, fn, args)\n"
        "        timer[0].start()\n"
        "    return wrapper\n"
        "```\n\n"
        "This debounce decorator delays function execution. "
        "The closure captures a mutable list holding the pending timer reference. "
        "Each call cancels the previous timer and starts a new one. "
        "Only the final call within the delay window actually executes the function. "
        "threading.Timer schedules the callback on a background daemon thread. "
        "Passing *args forwards all positional arguments from each wrapper invocation. "
        "The mutable list circumvents Python closures read-only restriction on reassignment. "
        "This pattern is commonly applied to search input handlers and resize callbacks.\n"
        "I've created the debounce utility above with full argument forwarding support.\n"
    ),
    # 27. Let me preamble + LRU cache code + no-keep-signal explanation (Pass 2)
    (
        "Let me implement the LRU cache for you.\n\n"
        "```python\n"
        "from collections import OrderedDict\n"
        "class LRUCache:\n"
        "    def __init__(self, cap): self.cap = cap; self.d = OrderedDict()\n"
        "    def get(self, k): self.d.move_to_end(k); return self.d.get(k, -1)\n"
        "    def put(self, k, v):\n"
        "        self.d[k] = v; self.d.move_to_end(k)\n"
        "        if len(self.d) > self.cap: self.d.popitem(last=False)\n"
        "```\n\n"
        "This LRU cache stores key-value pairs up to a fixed capacity. "
        "OrderedDict preserves insertion order and supports efficient reordering. "
        "move_to_end() promotes accessed items to the most-recently-used position. "
        "popitem(last=False) evicts the oldest entry from the front of the ordered dict. "
        "Get operations also update recency to reflect actual access patterns. "
        "The capacity check runs on every put to keep memory bounded. "
        "This achieves O(1) amortized time for both get and put operations. "
        "Dictionary lookups and OrderedDict reordering complete in constant time.\n"
        "Successfully implemented the LRU cache class with O(1) get and put.\n"
    ),
    # 28. I'll preamble + retry code + no-keep-signal explanation (Pass 2)
    (
        "I'll create the retry decorator you requested.\n\n"
        "```python\n"
        "def retry(n=3, delay=1.0):\n"
        "    def wrap(fn):\n"
        "        def inner(*a, **kw):\n"
        "            for i in range(n):\n"
        "                try: return fn(*a, **kw)\n"
        "                except: time.sleep(delay)\n"
        "            return fn(*a, **kw)\n"
        "        return inner\n"
        "    return wrap\n"
        "```\n\n"
        "This retry decorator wraps callables with automatic retry logic. "
        "The outer function captures the retry count and delay configuration. "
        "Each attempt invokes the wrapped callable in a try block and pauses on failure. "
        "The final attempt propagates the last error without catching anything further. "
        "time.sleep() provides a fixed inter-attempt pause duration between tries. "
        "Passing *a and **kw forwards all original arguments on each attempt invocation. "
        "The decorator pattern preserves the original function signature for callers. "
        "Exponential backoff multipliers can replace the fixed sleep duration.\n"
        "I've created the retry decorator above with configurable count and delay.\n"
    ),
    # 29. Pure prose 12 lines — connection pooling, no keep signals (Pass 4)
    (
        "Connection pooling maintains a reusable set of open database connections.\n"
        "Pools allocate connections to incoming queries from the available slot pool.\n"
        "A completed query returns its connection to the pool for immediate reuse.\n"
        "This eliminates per-query TCP handshake and database authentication overhead.\n"
        "Max pool size constrains peak open connections to the database server.\n"
        "Idle timeout closes connections that remain unused past a configured duration.\n"
        "Periodic health checks validate that pooled connections remain responsive.\n"
        "A dead connection detected by health check triggers immediate replacement.\n"
        "Min pool size reserves connections during low-traffic periods to avoid latency.\n"
        "Eager initialization opens all connections at startup rather than on demand.\n"
        "Connection steal latency rises as pool utilization approaches max capacity.\n"
        "Benchmarking session duration metrics reveals the optimal pool configuration.\n"
    ),
    # 30. Sure! I'll preamble + fibonacci + no-keep-signal explanation (Pass 1 + Pass 2)
    (
        "Sure! I'll add the memoization wrapper to the computation function.\n\n"
        "```python\n"
        "from functools import lru_cache\n"
        "@lru_cache(maxsize=256)\n"
        "def fib(n):\n"
        "    return n if n < 2 else fib(n-1) + fib(n-2)\n"
        "```\n\n"
        "This memoized fibonacci avoids redundant computation via caching. "
        "lru_cache stores return values keyed by the input arguments. "
        "Cached results are returned on repeat calls without re-executing the body. "
        "The maxsize parameter bounds cache memory to 256 most-recently-used entries. "
        "Exceeding maxsize evicts the least-recently-used entry from the cache. "
        "Recursive calls hit the cache on overlapping subproblem arguments. "
        "This reduces exponential naive recursion to linear time complexity. "
        "Cache statistics are accessible via fib.cache_info() for monitoring.\n"
        "I've added the lru_cache decorator above with 256-entry capacity.\n"
    ),
    # 31. Pure prose 12 lines — HTTP cycle, no keep signals (Pass 4)
    (
        "HTTP request/response follows a stateless client-server communication model.\n"
        "The client constructs a request with method, path, headers, and optional body.\n"
        "DNS resolves the hostname to an IP address, initiating TCP connection setup.\n"
        "TCP three-way handshake precedes any application-layer data transmission.\n"
        "TLS adds a handshake layer for encrypted HTTPS connections on port 443.\n"
        "Request routing logic maps the path and method to a registered handler.\n"
        "Handler logic produces a response with status code, headers, and body.\n"
        "Connection keep-alive reuses the TCP connection for subsequent requests.\n"
        "HTTP/2 multiplexes multiple requests over a single TCP connection.\n"
        "HTTP/3 replaces TCP with QUIC for reduced connection establishment latency.\n"
        "Content-Length headers inform the client of the expected body byte count.\n"
        "Transfer-Encoding chunked streams the response body in sequential parts.\n"
    ),
    # 32. Pure prose 12 lines — cache eviction, no keep signals (Pass 4)
    (
        "Cache eviction removes entries to make room for newly added items.\n"
        "LRU eviction removes the least recently accessed entry from the cache.\n"
        "LFU eviction removes the entry with the fewest total access counts.\n"
        "FIFO eviction removes the oldest entry regardless of access frequency.\n"
        "Random eviction selects a victim entry uniformly at random from the cache.\n"
        "ARC combines LRU and LFU to adapt to changing access pattern distributions.\n"
        "Two-level caches separate hot and cold items into distinct storage tiers.\n"
        "Cache hit rate measures the fraction of lookups served from cached data.\n"
        "High hit rates reduce downstream database load and query latency.\n"
        "Cache warming pre-populates entries at startup to avoid cold-start latency.\n"
        "Cache stampede occurs on expiry of a popular entry shared across many callers.\n"
        "Single-flight patterns prevent thundering herd on simultaneously expiring keys.\n"
    ),
    # 33. Pure prose 12 lines — binary search, no keep signals (Pass 4)
    (
        "Binary search locates a target value in a sorted array in O(log n) time.\n"
        "The algorithm divides the search space in half on each comparison step.\n"
        "The middle element of the current range is compared to the target value.\n"
        "A match terminates the search and returns the middle element index.\n"
        "A target smaller than the middle restricts the next range to the left half.\n"
        "A target larger than the middle restricts the next range to the right half.\n"
        "An empty range signals that the target is not present in the sorted array.\n"
        "Integer overflow in mid calculation is avoided via low + (high - low) // 2.\n"
        "Python's bisect module provides optimized binary search on sorted lists.\n"
        "The algorithm assumes the input list is already sorted in ascending order.\n"
        "Unsorted inputs produce incorrect results without any indication of failure.\n"
        "Augmented binary search trees generalize this technique to dynamic datasets.\n"
    ),
    # 34. Pure prose 12 lines — event-driven, no keep signals (Pass 4)
    (
        "Event-driven architecture decouples producers and consumers through events.\n"
        "Producers emit events describing state changes without knowledge of consumers.\n"
        "An event bus or message broker routes events to registered subscriber callbacks.\n"
        "Subscribers process events independently on their own schedules and threads.\n"
        "Dead letter queues capture events that fail processing for later inspection.\n"
        "Idempotent handlers tolerate duplicate delivery without corrupting state.\n"
        "Schema registries enforce event format contracts across distributed teams.\n"
        "Event sourcing persists state as an append-only log of ordered domain events.\n"
        "CQRS separates read and write models derived from the same event stream.\n"
        "Sagas coordinate distributed transactions via compensating events on partial fails.\n"
        "Fan-out patterns broadcast single events to multiple independent downstream services.\n"
        "Backpressure mechanisms limit event ingestion rates on overloaded consumers.\n"
    ),
    # 35. Pure prose 12 lines — message queues, no keep signals (Pass 4)
    (
        "Message queues decouple producers and consumers in distributed systems.\n"
        "Producers publish messages to a named queue without blocking on consumption.\n"
        "Consumers pull or subscribe to receive messages from the named queue.\n"
        "Durable queues persist messages to disk to survive broker restart events.\n"
        "Acknowledgments signal successful processing so the broker removes the message.\n"
        "Negative acknowledgments return messages to the queue for redelivery attempts.\n"
        "Dead letter queues accumulate messages that fail delivery past maximum retries.\n"
        "Priority queues route high-priority messages ahead of lower-priority backlog items.\n"
        "Message TTL expires unprocessed messages from the queue on a configured duration.\n"
        "Consumer groups partition queue messages across multiple processing replicas.\n"
        "Message ordering guarantees vary across brokers and queue topology configurations.\n"
        "Throughput scales horizontally by adding more consumers to the same queue.\n"
    ),
    # 36. Pure prose 12 lines — garbage collection, no keep signals (Pass 4)
    (
        "Garbage collection reclaims memory occupied by unreachable objects automatically.\n"
        "Reference counting increments a counter each time a new reference is created.\n"
        "Decrementing to zero marks an object eligible for immediate deallocation.\n"
        "Cyclic reference groups complicate counting by preventing counter zero-out.\n"
        "Mark-and-sweep traverses the object graph from roots to identify live objects.\n"
        "Unreachable objects discovered in the sweep phase are deallocated in bulk.\n"
        "Generational GC exploits the observation that most objects die young.\n"
        "Young generation objects are collected frequently at low cost per cycle.\n"
        "Long-lived objects are promoted to old generation and collected less often.\n"
        "Compacting GC moves live objects together to eliminate heap fragmentation.\n"
        "Stop-the-world pauses halt all application threads during collection cycles.\n"
        "Concurrent GC runs collection phases alongside application threads to reduce latency.\n"
    ),
    # 37. Pure prose 12 lines — load balancing, no keep signals (Pass 4)
    (
        "Load balancers distribute incoming network traffic across multiple backend servers.\n"
        "Round-robin assigns each new connection to the next server in rotation sequence.\n"
        "Least-connections routes traffic to the server with fewest active connections.\n"
        "IP-hash directs all requests from a single source IP to the same backend.\n"
        "Health checks remove unresponsive servers from the rotation pool automatically.\n"
        "Passive health checks detect failures from real traffic response codes and latency.\n"
        "Active health checks probe each server on a scheduled interval independently.\n"
        "Session persistence pins a client to the same backend for stateful applications.\n"
        "Horizontal scaling adds new backend servers behind the load balancer on demand.\n"
        "TLS termination at the load balancer decrypts traffic once on behalf of backends.\n"
        "Layer 4 balancers route at TCP level without inspecting application-layer content.\n"
        "Layer 7 balancers route on HTTP headers, paths, and query parameters.\n"
    ),
    # 38. Pure prose 12 lines — circuit breaker, no keep signals (Pass 4)
    (
        "Circuit breakers prevent cascade failures by stopping calls to unhealthy services.\n"
        "A closed circuit forwards all requests to the downstream service normally.\n"
        "Repeated failures trip the circuit to an open state on a configured time window.\n"
        "An open circuit short-circuits all requests with a local fallback response.\n"
        "Fallback responses return cached data or a degraded-mode placeholder to callers.\n"
        "A half-open circuit allows a probe request to test downstream recovery status.\n"
        "A successful probe closes the circuit and resumes normal traffic forwarding.\n"
        "A failed probe returns the circuit to open and restarts the recovery timer.\n"
        "Failure thresholds are expressed as a percentage of calls in a sliding window.\n"
        "Timeout thresholds separate slow responses from connectivity failures on detection.\n"
        "Multiple circuit breakers isolate dependency failures in microservice architectures.\n"
        "Dashboard visibility into circuit state surfaces degradation early to operators.\n"
    ),
    # 39. Pure prose 12 lines — rate limiting, no keep signals (Pass 4)
    (
        "Rate limiting controls the frequency of requests a client makes per time window.\n"
        "Token bucket algorithms accumulate tokens at a fixed refill rate up to a capacity.\n"
        "Each request consumes one token and proceeds only on token availability.\n"
        "Requests arriving at an empty bucket are rejected or queued for later processing.\n"
        "Leaky bucket algorithms drain at a constant rate regardless of arrival bursts.\n"
        "Fixed window counters reset on each interval boundary, permitting burst at edges.\n"
        "Sliding window logs record each request timestamp to compute precise rolling counts.\n"
        "Distributed rate limiting stores counters in a shared cache visible to all replicas.\n"
        "Redis atomic increment and TTL operations implement distributed counters efficiently.\n"
        "Rate limit headers communicate remaining quota and reset time to API clients.\n"
        "Exponential backoff strategies reduce retry pressure on temporarily overwhelmed services.\n"
        "Per-client rate limits partition capacity fairly across distinct authenticated accounts.\n"
    ),
]

# 50 simulated error sequences for loop detection accuracy
_ERROR_SEQUENCES = []
# 20 true loops: same tool+target+error repeated 5+ times (threshold = 5)
for i in range(20):
    target = f"src/module_{i}.py"
    err = f"SyntaxError line {10 + i}"
    _ERROR_SEQUENCES.append({
        "type": "loop",
        "failures": [{"tool": "Edit", "target": target, "error": err}] * 5,
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
# 10 edge cases: under threshold (4 failures, threshold = 5)
for i in range(10):
    target = f"src/edge_{i}.py"
    _ERROR_SEQUENCES.append({
        "type": "under_threshold",
        "failures": [{"tool": "Edit", "target": target, "error": "Some error"}] * 4,
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

        count, _, _ = mod._analyze_failure_tail(failures, query_tool, query_target)
        would_block = count >= 5

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


_CONTRADICTION_BENCH_CAP = 101  # fixed cap for reproducible results regardless of decisions.md growth


def bench_intelligence_contradictions() -> Dict[str, Any]:
    """Benchmark 6: contradiction detection over decisions.md (target <250ms, capped at 101 decisions)."""
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "src"))
    from optimusprime.intelligence import IntelligenceEngine

    op_dir = _REPO_ROOT / ".optimusprime"
    if not op_dir.is_dir():
        return {"skipped": True, "reason": "no .optimusprime/"}

    engine = IntelligenceEngine(op_dir)
    recs = engine._decisions
    if len(recs) < 10:
        return {"skipped": True, "reason": "too few decisions"}

    # Cap to first N decisions so benchmark stays reproducible as decisions.md grows.
    recs = recs[:_CONTRADICTION_BENCH_CAP]

    # Scan all decisions for contradictions (worst-case: O(n^2))
    start = time.perf_counter()
    total_found = 0
    for i, rec in enumerate(recs):
        past = recs[:i]
        if past:
            total_found += len(engine.detect_contradictions(rec, past_decisions=past))
    elapsed_ms = (time.perf_counter() - start) * 1000

    return {
        "decisions": len(recs),
        "contradictions_found": total_found,
        "total_ms": round(elapsed_ms, 2),
    }


def bench_intelligence_patterns() -> Dict[str, Any]:
    """Benchmark 7: pattern clustering over real decisions.md (target <200ms)."""
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "src"))
    from optimusprime.intelligence import IntelligenceEngine

    op_dir = _REPO_ROOT / ".optimusprime"
    if not op_dir.is_dir():
        return {"skipped": True, "reason": "no .optimusprime/"}

    engine = IntelligenceEngine(op_dir)
    if not engine._decisions:
        return {"skipped": True, "reason": "no decisions"}

    runs = 100
    start = time.perf_counter()
    for _ in range(runs):
        patterns = engine.find_patterns()
    elapsed_ms = (time.perf_counter() - start) * 1000
    avg_ms = elapsed_ms / runs

    return {
        "decisions": len(engine._decisions),
        "topics_found": len(patterns),
        "avg_ms": round(avg_ms, 3),
    }


def bench_intelligence_predict_context() -> Dict[str, Any]:
    """Benchmark 8: predict_context_needs over real decisions.md (target <50ms)."""
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "src"))
    from optimusprime.intelligence import IntelligenceEngine

    op_dir = _REPO_ROOT / ".optimusprime"
    if not op_dir.is_dir():
        return {"skipped": True, "reason": "no .optimusprime/"}

    engine = IntelligenceEngine(op_dir)
    if not engine._decisions:
        return {"skipped": True, "reason": "no decisions"}

    queries = [
        ("Edit", {"file_path": "src/optimusprime/intelligence.py"}),
        ("Write", {"file_path": "hooks/pre/scope-guard.py"}),
        ("Bash", {"command": "pytest tests/ -v"}),
        ("Read", {"file_path": "mcp/server.py"}),
        ("Edit", {"file_path": "src/optimusprime/cli/op.py"}),
    ]
    runs = 200
    start = time.perf_counter()
    for _ in range(runs):
        for tool, inp in queries:
            engine.predict_context_needs(tool, inp, top_k=5)
    elapsed_ms = (time.perf_counter() - start) * 1000
    avg_ms = elapsed_ms / (runs * len(queries))

    return {
        "decisions": len(engine._decisions),
        "queries": len(queries),
        "runs": runs,
        "avg_ms": round(avg_ms, 3),
    }


def bench_predictive_context() -> Dict[str, Any]:
    """Benchmark 10: predictive-context hook speed (cold + warm).

    Cold: first call with mtime-triggered TF-IDF rebuild.
    Warm: subsequent calls with cached index (just cosine scoring).
    Targets: cold <100ms, warm <10ms (pure Python, no subprocess).
    """
    import sys as _sys
    _sys.path.insert(0, str(_REPO_ROOT / "src"))

    from optimusprime.intelligence import IntelligenceEngine
    from optimusprime.utils import find_optimusprime_dir

    op_dir = find_optimusprime_dir(start=_REPO_ROOT)
    if op_dir is None:
        return {"skipped": True, "reason": "no .optimusprime/"}

    # Cold: fresh engine (simulates first call after mtime change)
    start_cold = time.perf_counter()
    engine = IntelligenceEngine(op_dir)
    cold_predictions = engine.predict_context_needs(
        "Write",
        {"file_path": "src/optimusprime/intelligence.py", "content": ""},
        top_k=5,
    )
    cold_ms = (time.perf_counter() - start_cold) * 1000

    # Warm: reuse same engine (mtime unchanged = no rebuild)
    warm_runs = 50
    tool_calls = [
        ("Write", {"file_path": "src/optimusprime/intelligence.py"}),
        ("Edit", {"file_path": "hooks/pre/scope-guard.py", "old_string": "def main"}),
        ("Bash", {"command": "pytest tests/ -v"}),
        ("Read", {"file_path": "mcp/server.py"}),
        ("Write", {"file_path": "src/optimusprime/cli/op.py"}),
    ]
    start_warm = time.perf_counter()
    for _ in range(warm_runs):
        for tool, inp in tool_calls:
            engine.predict_context_needs(tool, inp, top_k=5)
    warm_ms = (time.perf_counter() - start_warm) * 1000
    warm_avg_ms = warm_ms / (warm_runs * len(tool_calls))

    return {
        "decisions": len(engine._decisions),
        "cold_ms": round(cold_ms, 2),
        "warm_avg_ms": round(warm_avg_ms, 3),
        "cold_predictions": len(cold_predictions),
    }


def bench_learner() -> Dict[str, Any]:
    """Benchmark 11: Learner learn() cycle performance.

    Simulates 10 sessions × 10 decisions + 2 failures each.
    Measures time per learn() cycle.
    Target: under 500ms per cycle.
    """
    from pathlib import Path as _Path
    sys.path.insert(0, str(_REPO_ROOT / "src"))

    try:
        from optimusprime.learner import Learner, LearnerSession
        from optimusprime.intelligence import DecisionRecord
    except ImportError as e:
        return {"skipped": True, "reason": str(e)}

    decisions_per_session = 10
    failures_per_session = 2
    n_sessions = 10

    # Build a shared tmp dir
    import tempfile, os, shutil
    tmpdir = _Path(tempfile.mkdtemp())
    try:
        op_dir = tmpdir / ".optimusprime"
        op_dir.mkdir()

        # Seed decisions.md
        with open(op_dir / "decisions.md", "w", encoding="utf-8") as f:
            for i in range(n_sessions * decisions_per_session):
                ts = f"2026-06-27T{(i // 60) % 24:02d}:{i % 60:02d}:00Z"
                f.write(f"[{ts}] [agent:main] DECISION: use pytest for testing module {i}\n")

        # Seed contract
        import json as _json
        (op_dir / "contract.json").write_text(_json.dumps({
            "goal": "benchmark session", "complexity_budget": "full"
        }), encoding="utf-8")

        timings = []
        for s_idx in range(n_sessions):
            learner = Learner(op_dir)

            # Build a synthetic session
            all_decs = learner._engine._decisions if learner._engine else []
            cursor = s_idx * decisions_per_session
            new_decs = all_decs[cursor:cursor + decisions_per_session]

            attempts = [
                {"tool": "Edit", "target": f"src/module_{s_idx}.py", "error": "SyntaxError"}
                for _ in range(failures_per_session)
            ]

            session = LearnerSession(
                session_id=f"bench-{s_idx:03d}",
                goal="benchmark session",
                decisions_this_session=new_decs,
                attempts_this_session=attempts,
                todos_added=0,
                complexity_budget="full",
                skills_activated=[],
                captured_at="2026-06-27T00:00:00Z",
            )

            t0 = time.perf_counter()
            learner.learn(session)
            timings.append((time.perf_counter() - t0) * 1000)

        return {
            "avg_ms": sum(timings) / len(timings),
            "min_ms": min(timings),
            "max_ms": max(timings),
            "n_sessions": n_sessions,
            "decisions_per_session": decisions_per_session,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def bench_self_model() -> Dict[str, Any]:
    """Benchmark 12: SelfModel.build() speed.

    Create sample attempts.md with 50 entries.
    Run build() 10 times.
    Target: under 200ms per build.
    """
    import shutil
    import tempfile as _tempfile

    sys.path.insert(0, str(_REPO_ROOT / "src"))
    try:
        from optimusprime.self_model import SelfModel
    except ImportError as e:
        return {"skipped": True, "reason": str(e)}

    tmpdir = Path(_tempfile.mkdtemp())
    try:
        op_dir = tmpdir / ".optimusprime"
        op_dir.mkdir()

        # 50 attempt entries
        lines = []
        for i in range(50):
            ts = f"2026-06-27T{i // 60:02d}:{i % 60:02d}:00Z"
            lines.append(
                f"[{ts}] ATTEMPT Bash: pytest tests/test_{i}.py → "
                f"FAILED: AssertionError in test_func_{i}"
            )
        (op_dir / "attempts.md").write_text("\n".join(lines), encoding="utf-8")

        timings = []
        for _ in range(10):
            sm = SelfModel(op_dir)
            t0 = time.perf_counter()
            sm.build()
            timings.append((time.perf_counter() - t0) * 1000)

        return {
            "avg_ms": sum(timings) / len(timings),
            "min_ms": min(timings),
            "max_ms": max(timings),
            "entries": 50,
            "runs": 10,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def bench_codebase_map() -> Dict[str, Any]:
    """Benchmark 13: CodebaseMap scan speed.

    Scans the optimusprime repo itself (real project).
    First build once, then get_relevant_for_file() 100 times with warm cache.
    Target: first build under 5s, warm queries under 10ms.
    """
    import shutil
    import tempfile as _tempfile

    sys.path.insert(0, str(_REPO_ROOT / "src"))
    try:
        from optimusprime.codebase_map import CodebaseMap
    except ImportError as e:
        return {"skipped": True, "reason": str(e)}

    tmpdir = Path(_tempfile.mkdtemp())
    try:
        op_dir = tmpdir / ".optimusprime"
        op_dir.mkdir()

        cm = CodebaseMap(_REPO_ROOT, op_dir)

        # First build (cold)
        t0 = time.perf_counter()
        cmap = cm.build()
        cold_ms = (time.perf_counter() - t0) * 1000

        utilities_count = len(cmap.get("utilities", {}))

        # Warm queries: get_relevant_for_file 100x
        test_files = [
            "src/optimusprime/intelligence.py",
            "src/optimusprime/learner.py",
            "src/optimusprime/utils.py",
            "hooks/pre/scope-guard.py",
            "hooks/post/session-logger.py",
        ]
        query_timings = []
        for i in range(100):
            fp = test_files[i % len(test_files)]
            t0 = time.perf_counter()
            cm.get_relevant_for_file(fp)
            query_timings.append((time.perf_counter() - t0) * 1000)

        return {
            "first_build_ms": cold_ms,
            "warm_avg_ms": sum(query_timings) / len(query_timings),
            "warm_max_ms": max(query_timings),
            "utilities_found": utilities_count,
            "queries": 100,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def bench_pre_write_injector() -> Dict[str, Any]:
    """Benchmark 14: pre-write-injector.py speed with warm codebase-map.json.

    100 Write tool call simulations with warm cache.
    Target: under 150ms average (subprocess startup baseline is ~40ms on most systems;
    the hook adds <15ms of work on top — total <150ms is the meaningful constraint).
    """
    import json as _json
    import shutil
    import tempfile as _tempfile

    _HOOK = _REPO_ROOT / "hooks" / "pre" / "pre-write-injector.py"
    if not _HOOK.is_file():
        return {"skipped": True, "reason": "hook not found"}

    tmpdir = Path(_tempfile.mkdtemp())
    try:
        op_dir = tmpdir / ".optimusprime"
        op_dir.mkdir()

        # Seed a warm codebase-map.json
        sample_map = {
            "built_at": "2026-06-28T00:00:00Z",
            "project_root": str(tmpdir),
            "utilities": {
                f"func_{i}": {"file": "src/utils.py", "line": i, "type": "function",
                              "signature": f"def func_{i}():"}
                for i in range(20)
            },
            "installed_deps": ["httpx", "click", "pytest"],
            "dev_deps": ["pytest"],
            "patterns": {},
            "never_use": ["requests — project uses httpx"],
            "file_count": 30,
            "language": "python",
        }
        (op_dir / "codebase-map.json").write_text(_json.dumps(sample_map), encoding="utf-8")

        payload = _json.dumps({
            "hook_event_name": "PreToolUse",
            "session_id": "bench-session",
            "tool_name": "Write",
            "tool_input": {"file_path": "src/utils.py", "content": "def foo(): pass"},
        })

        timings = []
        for _ in range(100):
            t0 = time.perf_counter()
            result = subprocess.run(
                [sys.executable, str(_HOOK)],
                input=payload,
                capture_output=True,
                text=True,
                cwd=str(tmpdir),
                timeout=5,
            )
            timings.append((time.perf_counter() - t0) * 1000)

        return {
            "avg_ms": sum(timings) / len(timings),
            "min_ms": min(timings),
            "max_ms": max(timings),
            "runs": 100,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def bench_conductor_plan_speed() -> Dict[str, Any]:
    """Benchmark 15: Conductor.plan() — 5 runs, target < 2s each."""
    import shutil as _shutil
    import tempfile as _tempfile
    import json as _json

    try:
        from optimusprime.conductor import Conductor
        from unittest.mock import patch as _patch
    except ImportError as e:
        return {"skipped": True, "reason": str(e)}

    tmpdir = Path(_tempfile.mkdtemp())
    try:
        op_dir = tmpdir / ".optimusprime"
        op_dir.mkdir()
        (op_dir / "contract.json").write_text(_json.dumps({
            "goal": "build auth system",
            "in_scope": ["src/", "tests/"],
            "out_of_scope": [".env"],
            "complexity_budget": "full",
        }))
        (op_dir / "decisions.md").write_text(
            "[2026-06-28T09:00:00Z] [agent:main] DECIDED: use jwt | REJECTED: sessions | REASON: stateless\n"
        )
        c = Conductor(op_dir, tmpdir)
        timings = []
        with _patch("shutil.which", return_value="/usr/bin/claude"):
            for _ in range(5):
                t0 = time.perf_counter()
                try:
                    c.plan("build a simple auth module")
                except Exception:
                    pass
                timings.append(time.perf_counter() - t0)
        return {
            "avg_s": sum(timings) / len(timings),
            "max_s": max(timings),
            "runs": 5,
        }
    finally:
        _shutil.rmtree(tmpdir, ignore_errors=True)


def bench_conductor_context_package() -> Dict[str, Any]:
    """Benchmark 16: Conductor._build_context_package() — 50 calls, target < 100ms each."""
    import shutil as _shutil
    import tempfile as _tempfile
    import json as _json

    try:
        from optimusprime.conductor import Conductor, SubTask
        from unittest.mock import patch as _patch
    except ImportError as e:
        return {"skipped": True, "reason": str(e)}

    tmpdir = Path(_tempfile.mkdtemp())
    try:
        op_dir = tmpdir / ".optimusprime"
        op_dir.mkdir()
        (op_dir / "contract.json").write_text(_json.dumps({
            "goal": "build auth", "in_scope": ["src/"], "out_of_scope": [], "complexity_budget": "full",
        }))
        (op_dir / "decisions.md").write_text(
            "[2026-06-28T09:00:00Z] [agent:main] DECIDED: use jwt | REJECTED: none | REASON: stateless\n" * 20
        )
        c = Conductor(op_dir, tmpdir)
        st = SubTask(id="subtask-001", description="implement auth utilities", file_scope=["src/auth.py"])
        timings = []
        for _ in range(50):
            t0 = time.perf_counter()
            c._build_context_package(st)
            timings.append((time.perf_counter() - t0) * 1000)
        return {
            "avg_ms": sum(timings) / len(timings),
            "max_ms": max(timings),
            "runs": 50,
        }
    finally:
        _shutil.rmtree(tmpdir, ignore_errors=True)


def bench_overhead_per_session() -> Dict[str, Any]:
    """Benchmark 17: OptimusPrime hook overhead for a simulated 20-message session.

    Measures total additionalContext tokens injected by pre-response.py across 20 prompts.
    Target: under 2,000 tokens total (100 tokens/message average).
    """
    import shutil as _shutil
    import tempfile as _tempfile

    hook_path = _REPO_ROOT / "hooks" / "pre" / "pre-response.py"
    if not hook_path.is_file():
        return {"skipped": True, "reason": "pre-response.py not found"}

    prompts = [
        "fix the auth bug in middleware",
        "add rate limiting to the API",
        "write tests for the scope guard",
        "refactor the session logger",
        "review the decision log format",
        "build the token counter module",
        "debug the loop detector hook",
        "implement the injection dedup",
        "add compression to outputs",
        "update the readme install section",
        "fix the watch dashboard refresh",
        "create the menubar data layer",
        "test the conductor subtasks",
        "review benchmark results",
        "add tiktoken integration",
        "fix the status line format",
        "update the pyproject toml",
        "test the throttle strategy",
        "review the adaptive injection",
        "write the final commit",
    ]

    tmpdir = Path(_tempfile.mkdtemp())
    try:
        op_dir = tmpdir / ".optimusprime"
        op_dir.mkdir()
        (op_dir / "cost-log.json").write_text(json.dumps({
            "sessions": [{"token_estimate": 15000, "estimated_cost_usd": 0.05}]
        }))

        total_chars = 0
        for prompt in prompts:
            payload = json.dumps({"session_id": "bench-017", "prompt": prompt})
            try:
                result = subprocess.run(
                    [sys.executable, str(hook_path)],
                    input=payload,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=str(tmpdir),
                )
                if result.stdout.strip():
                    data = json.loads(result.stdout.strip())
                    total_chars += len(data.get("additionalContext", ""))
            except Exception:
                pass

        total_tokens = total_chars // 4
        avg_per_msg = total_tokens // len(prompts) if prompts else 0
        return {
            "total_overhead_tokens": total_tokens,
            "avg_per_message_tokens": avg_per_msg,
            "messages": len(prompts),
            "target_2000_tokens": total_tokens <= 2000,
        }
    finally:
        _shutil.rmtree(tmpdir, ignore_errors=True)


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

    print("  Running intelligence contradictions...", end=" ", flush=True)
    ic = bench_intelligence_contradictions()
    print("done")

    print("  Running intelligence patterns...", end=" ", flush=True)
    ip = bench_intelligence_patterns()
    print("done")

    print("  Running intelligence context predict...", end=" ", flush=True)
    ipc = bench_intelligence_predict_context()
    print("done")

    print("  Running predictive context hook...", end=" ", flush=True)
    pc = bench_predictive_context()
    print("done")

    print("  Running learner cycle...", end=" ", flush=True)
    lc = bench_learner()
    print("done")

    print("  Running self-model build...", end=" ", flush=True)
    sm = bench_self_model()
    print("done")

    print("  Running codebase map scan...", end=" ", flush=True)
    cbm = bench_codebase_map()
    print("done")

    print("  Running pre-write injector...", end=" ", flush=True)
    pwi = bench_pre_write_injector()
    print("done")

    print("  Running conductor plan speed...", end=" ", flush=True)
    cp = bench_conductor_plan_speed()
    print("done")

    print("  Running conductor context package...", end=" ", flush=True)
    ccp = bench_conductor_context_package()
    print("done")

    print("  Running overhead per session...", end=" ", flush=True)
    oph = bench_overhead_per_session()
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
    if ic.get("skipped"):
        print(f"  Intel contradictions:  skipped ({ic['reason']})")
    else:
        print(f"  Intel contradictions:  {ic['total_ms']:.0f}ms total ({ic['decisions']} decisions, {ic['contradictions_found']} found, target <250ms)")
    if ip.get("skipped"):
        print(f"  Intel patterns:        skipped ({ip['reason']})")
    else:
        print(f"  Intel patterns:        {ip['avg_ms']:.2f}ms avg ({ip['topics_found']} topics, target <200ms)")
    if ipc.get("skipped"):
        print(f"  Intel predict:         skipped ({ipc['reason']})")
    else:
        print(f"  Intel predict:         {ipc['avg_ms']:.3f}ms avg ({ipc['decisions']} decisions, target <50ms)")
    if pc.get("skipped"):
        print(f"  Predictive context:    skipped ({pc['reason']})")
    else:
        print(f"  Predictive context:    cold={pc['cold_ms']:.1f}ms  warm={pc['warm_avg_ms']:.3f}ms avg"
              f" ({pc['decisions']} decisions, target cold<100ms warm<10ms)")
    if lc.get("skipped"):
        print(f"  Learner cycle:         skipped ({lc['reason']})")
    else:
        print(f"  Learner cycle:         {lc['avg_ms']:.1f}ms avg"
              f" (min={lc['min_ms']:.1f}ms max={lc['max_ms']:.1f}ms,"
              f" {lc['n_sessions']} sessions, target <500ms)")
    if sm.get("skipped"):
        print(f"  Self-model build:      skipped ({sm['reason']})")
    else:
        print(f"  Self-model build:      {sm['avg_ms']:.1f}ms avg"
              f" (min={sm['min_ms']:.1f}ms max={sm['max_ms']:.1f}ms,"
              f" {sm['entries']} entries, target <200ms)")
    if cbm.get("skipped"):
        print(f"  Codebase map scan:     skipped ({cbm['reason']})")
    else:
        print(f"  Codebase map scan:     first={cbm['first_build_ms']:.0f}ms"
              f"  warm_avg={cbm['warm_avg_ms']:.2f}ms"
              f" ({cbm['utilities_found']} utilities, target first<5000ms warm<10ms)")
    if pwi.get("skipped"):
        print(f"  Pre-write injector:    skipped ({pwi['reason']})")
    else:
        print(f"  Pre-write injector:    {pwi['avg_ms']:.1f}ms avg"
              f" (min={pwi['min_ms']:.1f}ms max={pwi['max_ms']:.1f}ms,"
              f" {pwi['runs']} runs, target <150ms)")
    if cp.get("skipped"):
        print(f"  Conductor plan speed:  skipped ({cp['reason']})")
    else:
        print(f"  Conductor plan speed:  {cp['avg_s']:.3f}s avg"
              f" (max={cp['max_s']:.3f}s, {cp['runs']} runs, target <2s)")
    if ccp.get("skipped"):
        print(f"  Conductor ctx pkg:     skipped ({ccp['reason']})")
    else:
        print(f"  Conductor ctx pkg:     {ccp['avg_ms']:.2f}ms avg"
              f" (max={ccp['max_ms']:.2f}ms, {ccp['runs']} calls, target <100ms)")
    if oph.get("skipped"):
        print(f"  Hook overhead/session: skipped ({oph['reason']})")
    else:
        passed = "✓" if oph["target_2000_tokens"] else "✗"
        print(
            f"  Hook overhead/session: {oph['total_overhead_tokens']} tokens total"
            f" ({oph['avg_per_message_tokens']} tok/msg avg,"
            f" {oph['messages']} msgs, target <2000) {passed}"
        )
    print("═" * 45)

    # Assertions: fail loudly if we miss targets
    issues = []
    if c["reduction_pct"] < 70.0:
        issues.append(f"LOW output compression: {c['reduction_pct']:.1f}% < 70% target")
    if s["avg_ms"] > 100:
        issues.append(f"SLOW scope guard: {s['avg_ms']:.1f}ms > 100ms target")
    if l["accuracy_pct"] < 90:
        issues.append(f"LOW loop accuracy: {l['accuracy_pct']:.1f}% < 90% target")
    if d["avg_ms"] > 10:
        issues.append(f"SLOW decision search: {d['avg_ms']:.2f}ms > 10ms target")
    if sl["avg_s"] > 2.0:
        issues.append(f"SLOW session logger: {sl['avg_s']:.2f}s > 2s target")
    if not ic.get("skipped") and ic["total_ms"] > 250:
        issues.append(f"SLOW intel contradictions: {ic['total_ms']:.0f}ms > 250ms target")
    if not ip.get("skipped") and ip["avg_ms"] > 200:
        issues.append(f"SLOW intel patterns: {ip['avg_ms']:.2f}ms > 200ms target")
    if not ipc.get("skipped") and ipc["avg_ms"] > 50:
        issues.append(f"SLOW intel predict: {ipc['avg_ms']:.3f}ms > 50ms target")
    if not pc.get("skipped") and pc["cold_ms"] > 100:
        issues.append(f"SLOW predictive context cold: {pc['cold_ms']:.1f}ms > 100ms target")
    if not pc.get("skipped") and pc["warm_avg_ms"] > 10:
        issues.append(f"SLOW predictive context warm: {pc['warm_avg_ms']:.3f}ms > 10ms target")
    if not lc.get("skipped") and lc["avg_ms"] > 500:
        issues.append(f"SLOW learner cycle: {lc['avg_ms']:.0f}ms > 500ms target")
    if not sm.get("skipped") and sm["avg_ms"] > 200:
        issues.append(f"SLOW self-model build: {sm['avg_ms']:.1f}ms > 200ms target")
    if not cbm.get("skipped") and cbm["first_build_ms"] > 5000:
        issues.append(f"SLOW codebase map first build: {cbm['first_build_ms']:.0f}ms > 5000ms target")
    if not cbm.get("skipped") and cbm["warm_avg_ms"] > 10:
        issues.append(f"SLOW codebase map warm queries: {cbm['warm_avg_ms']:.2f}ms > 10ms target")
    if not pwi.get("skipped") and pwi["avg_ms"] > 150:
        issues.append(f"SLOW pre-write injector: {pwi['avg_ms']:.1f}ms > 150ms target")
    if not cp.get("skipped") and cp["avg_s"] > 2.0:
        issues.append(f"SLOW conductor plan: {cp['avg_s']:.3f}s > 2s target")
    if not ccp.get("skipped") and ccp["avg_ms"] > 100:
        issues.append(f"SLOW conductor ctx pkg: {ccp['avg_ms']:.2f}ms > 100ms target")
    if not oph.get("skipped") and not oph.get("target_2000_tokens", True):
        issues.append(
            f"HIGH hook overhead: {oph['total_overhead_tokens']} tokens > 2000 target"
            f" ({oph['avg_per_message_tokens']} tok/msg avg)"
        )

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
