"""Standalone, reproducible demo: run one large realistic verbose Claude
response through the real output-compressor and print the true result.

No dependencies beyond stdlib. Run directly:
    python3 benchmarks/demo_big_sample.py

This sample is written the way Claude actually over-explains in practice —
preamble, a real feature-sized function, a long restating explanation that
uses natural language (including words that legitimately block aggressive
compression, like "if" and "you"), and a closing pleasantry. Nothing in the
wording is chosen to dodge the compressor's keep-signal detection.
"""

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "output_compressor", _REPO_ROOT / "hooks" / "post" / "output-compressor.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

BIG_SAMPLE = (
    "Sure! I'd be happy to help you add rate limiting to your API. Let me "
    "walk you through the implementation.\n\n"
    "First, I'll create a token bucket rate limiter that you can attach to "
    "any endpoint. This is a common approach because it allows short bursts "
    "of traffic while still enforcing a steady average rate over time.\n\n"
    "```python\n"
    "import time\n"
    "import threading\n\n"
    "class RateLimiter:\n"
    "    def __init__(self, rate, capacity):\n"
    "        self.rate = rate\n"
    "        self.capacity = capacity\n"
    "        self.tokens = capacity\n"
    "        self.last_refill = time.monotonic()\n"
    "        self.lock = threading.Lock()\n\n"
    "    def allow(self):\n"
    "        with self.lock:\n"
    "            now = time.monotonic()\n"
    "            elapsed = now - self.last_refill\n"
    "            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)\n"
    "            self.last_refill = now\n"
    "            if self.tokens < 1:\n"
    "                return False\n"
    "            self.tokens -= 1\n"
    "            return True\n"
    "```\n\n"
    "Let me explain how this works in detail. The RateLimiter class "
    "implements what's known as a token bucket algorithm. When you create "
    "an instance, you specify a rate (tokens added per second) and a "
    "capacity (the maximum burst size the bucket can hold). Every time you "
    "call allow(), the limiter first calculates how much time has elapsed "
    "since the last refill and adds that many tokens back to the bucket, "
    "capped at the maximum capacity so it never overflows. If there's at "
    "least one token available, the call consumes one token and returns "
    "True, meaning the request should proceed. If there are no tokens left, "
    "it returns False, meaning you should reject or delay the request. The "
    "lock ensures this is safe if you're calling allow() from multiple "
    "threads at once, which is important in a real web server handling "
    "concurrent requests. You'll want to create one RateLimiter instance "
    "per client or per API key rather than sharing a single instance "
    "globally, otherwise one client could exhaust the bucket for everyone "
    "else. A typical configuration might be a rate of 10 tokens per second "
    "with a capacity of 20, which allows short bursts of up to 20 requests "
    "while settling to a sustained 10 requests per second afterward. This "
    "pattern is used widely in production API gateways because it's simple "
    "to reason about and cheap to compute on every request.\n\n"
    "I've successfully implemented the rate limiter for you! It's thread-safe "
    "and ready to use. Let me know if you'd like me to also add a decorator "
    "wrapper so you can apply this directly to your route handlers, or if "
    "you'd like a Redis-backed version for rate limiting across multiple "
    "server instances instead of just one process.\n"
)


def main() -> None:
    compressed, removed = _mod._compress(BIG_SAMPLE)
    before = len(BIG_SAMPLE)
    after = before - removed
    ratio = 100 * removed / before

    print(f"BEFORE: {before} chars")
    print(f"AFTER:  {after} chars")
    print(f"REDUCTION: {ratio:.1f}%")
    print()
    print("--- compressed output ---")
    print(compressed)


if __name__ == "__main__":
    main()
