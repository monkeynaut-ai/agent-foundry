"""Tests for ACP adapter interface."""

import pytest

from agent_foundry.acp.adapter import AdapterBase, TurnResult


class TestTurnResult:
    def test_given_turn_result_when_constructed_then_fields_stored(self):
        result = TurnResult(
            agent_session_id="sess-1",
            exit_code=0,
            task_complete=True,
        )
        assert result.agent_session_id == "sess-1"
        assert result.exit_code == 0
        assert result.task_complete is True

    def test_given_turn_result_with_defaults_when_constructed_then_defaults_applied(self):
        result = TurnResult()
        assert result.agent_session_id is None
        assert result.exit_code == -1
        assert result.task_complete is False


class TestAdapterBase:
    def test_given_adapter_base_when_instantiated_directly_then_raises_type_error(self):
        with pytest.raises(TypeError):
            AdapterBase()

    def test_given_concrete_adapter_when_run_turn_called_then_returns_turn_result(self):
        class StubAdapter(AdapterBase):
            def run_turn(self, prompt, ws, protocol_session_id, **kwargs):
                return TurnResult(agent_session_id="s1", exit_code=0)

            def run(self, initial_prompt, ws_url, protocol_session_id, **kwargs):
                return 0

        adapter = StubAdapter()
        result = adapter.run_turn("do something", None, "p1")
        assert isinstance(result, TurnResult)
        assert result.agent_session_id == "s1"

    def test_given_concrete_adapter_when_run_called_then_returns_exit_code(self):
        class StubAdapter(AdapterBase):
            def run_turn(self, prompt, ws, protocol_session_id, **kwargs):
                return TurnResult()

            def run(self, initial_prompt, ws_url, protocol_session_id, **kwargs):
                return 42

        adapter = StubAdapter()
        assert adapter.run("prompt", "ws://host", "p1") == 42
