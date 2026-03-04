"""Tests for _make_router closure in the compiler."""

from langgraph.graph import END

from agent_foundry.compiler.compiler import _make_router


class TestMakeRouter:
    def test_given_route_map_with_two_conditions_when_state_matches_first_then_returns_first_target(self):
        router = _make_router({"cond_a": "target_a", "cond_b": "target_b"}, "default", "src")
        result = router({"cond_a": True})
        assert result == "target_a"

    def test_given_no_conditions_match_then_returns_default_target(self):
        router = _make_router({"cond_a": "target_a"}, "default", "src")
        result = router({})
        assert result == "default"

    def test_given_state_has_loop_exhausted_then_returns_end(self):
        router = _make_router({"cond_a": "target_a"}, "default", "src")
        result = router({"_loop_exhausted": True})
        assert result == END

    def test_given_multiple_conditions_true_then_deterministic_first_sorted(self):
        router = _make_router({"b_cond": "target_b", "a_cond": "target_a"}, "default", "src")
        result = router({"a_cond": True, "b_cond": True})
        assert result == "target_a"  # "a_cond" sorts before "b_cond"
