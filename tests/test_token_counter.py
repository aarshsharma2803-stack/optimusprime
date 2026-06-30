"""Tests for TokenCounter."""
from __future__ import annotations

from optimusprime.token_counter import TokenCounter


def test_count_returns_int():
    tc = TokenCounter()
    result = tc.count("hello world")
    assert isinstance(result, int)


def test_count_empty_string():
    tc = TokenCounter()
    assert tc.count("") == 0


def test_count_nonempty_returns_positive():
    tc = TokenCounter()
    assert tc.count("hello world foo bar baz") > 0


def test_backend_is_valid_string():
    tc = TokenCounter()
    assert tc.backend in ("tiktoken", "word_estimate")


def test_estimate_cost_sonnet():
    tc = TokenCounter()
    cost = tc.estimate_cost(1_000_000, "claude-sonnet-4-6")
    assert abs(cost - 3.00) < 0.001


def test_estimate_cost_opus():
    tc = TokenCounter()
    cost = tc.estimate_cost(1_000_000, "claude-opus-4-6")
    assert abs(cost - 15.00) < 0.001


def test_estimate_cost_haiku():
    tc = TokenCounter()
    cost = tc.estimate_cost(1_000_000, "claude-haiku-4-5")
    assert abs(cost - 0.80) < 0.001


def test_estimate_cost_unknown_model_uses_sonnet_rate():
    tc = TokenCounter()
    cost = tc.estimate_cost(1_000_000, "claude-unknown-xyz")
    assert abs(cost - 3.00) < 0.001
