"""Tests for _execute_with_quality_controls and _execute_with_timeout internals."""

import time
from typing import Any
from unittest.mock import patch

import pytest

from agent_foundry.registry.errors import CapabilityExecutionError
from agent_foundry.registry.execution import _execute_with_quality_controls, _execute_with_timeout
from agent_foundry.registry.spec import (
    CapabilitySpec,
    ImplementationPointer,
    QualityControls,
)


def _make_spec(timeout_seconds: int = 30, max_retries: int = 0) -> CapabilitySpec:
    return CapabilitySpec(
        name="test_cap",
        description="test",
        version="1.0.0",
        implementation=ImplementationPointer(module="builtins", class_name="dict"),
        inputs_schema={"type": "object", "properties": {}},
        outputs_schema={"type": "object", "properties": {}},
        tags=[],
        quality_controls=QualityControls(timeout_seconds=timeout_seconds, max_retries=max_retries),
    )


# --- Commit 3a: _execute_with_quality_controls ---


class TestExecuteWithQualityControls:
    def test_given_handler_fails_twice_then_succeeds_with_max_retries_2_then_returns_success(self):
        counter = {"n": 0}

        def handler(inputs):
            counter["n"] += 1
            if counter["n"] < 3:
                raise RuntimeError("transient")
            return {"ok": True}

        spec = _make_spec(max_retries=2)
        result = _execute_with_quality_controls(spec, {}, handler)
        assert result == {"ok": True}

    def test_given_handler_always_fails_with_max_retries_2_then_raises_retry_exhausted(self):
        def handler(inputs):
            raise RuntimeError("permanent")

        spec = _make_spec(max_retries=2)
        with pytest.raises(CapabilityExecutionError) as exc_info:
            _execute_with_quality_controls(spec, {}, handler)
        assert exc_info.value.phase == "retry_exhausted"
        assert "3 attempts" in str(exc_info.value)

    def test_given_handler_raises_capability_execution_error_then_re_raises_immediately(self):
        def handler(inputs):
            raise CapabilityExecutionError(
                message="already handled", capability_name="test", phase="timeout"
            )

        spec = _make_spec(max_retries=2)
        with pytest.raises(CapabilityExecutionError) as exc_info:
            _execute_with_quality_controls(spec, {}, handler)
        assert exc_info.value.phase == "timeout"

    def test_given_handler_succeeds_first_try_with_max_retries_3_then_called_once(self):
        counter = {"n": 0}

        def handler(inputs):
            counter["n"] += 1
            return {"ok": True}

        spec = _make_spec(max_retries=3)
        result = _execute_with_quality_controls(spec, {}, handler)
        assert result == {"ok": True}
        assert counter["n"] == 1


# --- Commit 3b: _execute_with_timeout ---


class TestExecuteWithTimeout:
    def test_given_handler_exceeds_timeout_then_raises_timeout_error(self):
        def handler(inputs):
            time.sleep(5)
            return {}

        with pytest.raises(CapabilityExecutionError) as exc_info:
            _execute_with_timeout(handler, {}, timeout=1, capability_name="test")
        assert exc_info.value.phase == "timeout"

    def test_given_handler_completes_within_timeout_then_returns_result(self):
        def handler(inputs):
            return {"done": True}

        result = _execute_with_timeout(handler, {}, timeout=10, capability_name="test")
        assert result == {"done": True}

    def test_given_handler_raises_exception_then_propagates(self):
        def handler(inputs):
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            _execute_with_timeout(handler, {}, timeout=10, capability_name="test")
