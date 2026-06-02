"""Tests for the shared ``TokenUsage`` payload."""

from __future__ import annotations

from agent_foundry.models.usage import TokenUsage


def test_from_mapping_pulls_all_four_buckets() -> None:
    usage = TokenUsage.from_mapping(
        {
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_creation_input_tokens": 3,
            "cache_read_input_tokens": 4,
        }
    )
    assert usage is not None
    assert usage.input_tokens == 10
    assert usage.output_tokens == 20
    assert usage.cache_creation_input_tokens == 3
    assert usage.cache_read_input_tokens == 4
    assert usage.total_tokens() == 37


def test_from_mapping_missing_keys_stay_none() -> None:
    usage = TokenUsage.from_mapping({"input_tokens": 5})
    assert usage is not None
    assert usage.input_tokens == 5
    assert usage.output_tokens is None
    assert usage.total_tokens() == 5


def test_from_mapping_non_dict_returns_none() -> None:
    assert TokenUsage.from_mapping(None) is None
    assert TokenUsage.from_mapping("nope") is None
    assert TokenUsage.from_mapping(42) is None


def test_total_tokens_all_none_is_none() -> None:
    assert TokenUsage().total_tokens() is None


def test_from_mapping_ignores_non_int_values() -> None:
    usage = TokenUsage.from_mapping({"input_tokens": "x", "output_tokens": 7})
    assert usage is not None
    assert usage.input_tokens is None
    assert usage.output_tokens == 7
