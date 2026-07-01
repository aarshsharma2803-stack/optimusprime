"""Token counting: tiktoken if available, word×1.3 fallback."""
from __future__ import annotations


class TokenCounter:
    """Count tokens. Uses tiktoken when installed, word estimate otherwise."""

    def __init__(self) -> None:
        self._encoder = None
        self._load_encoder()

    def _load_encoder(self) -> None:
        try:
            import tiktoken
            self._encoder = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            self._encoder = None

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._encoder is not None:
            return len(self._encoder.encode(text))
        return int(len(text.split()) * 1.3)

    @property
    def backend(self) -> str:
        return "tiktoken" if self._encoder is not None else "word_estimate"

    def estimate_cost(self, tokens: int, model: str = "claude-sonnet-4-6") -> float:
        rates = {
            "claude-sonnet-4-6": 3.00,
            "claude-opus-4-6": 15.00,
            "claude-haiku-4-5": 0.80,
        }
        rate = rates.get(model, 3.00)
        return (tokens / 1_000_000) * rate
