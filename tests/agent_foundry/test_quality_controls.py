"""S1.6 — Quality controls: timeouts + retries.

Tests: slow node times out; flaky node retries up to max then errors.
Feature flag: FF_RETRY_TIMEOUTS (default off until stabilized).
"""

import time
from typing import Any
from unittest.mock import patch

import pytest

from agent_foundry.registry.errors import RoleExecutionError
from agent_foundry.registry.execution import execute_role
from agent_foundry.registry.spec import (
    RoleSpec,
    ImplementationPointer,
    QualityControls,
)


def _make_spec(timeout_seconds: int = 30, max_retries: int = 0) -> RoleSpec:
    return RoleSpec(
        name="test_cap",
        description="test",
        version="1.0.0",
        implementation=ImplementationPointer(module="builtins", class_name="dict"),
        inputs_schema={"type": "object", "properties": {}},
        outputs_schema={"type": "object", "properties": {}},
        tags=[],
        quality_controls=QualityControls(timeout_seconds=timeout_seconds, max_retries=max_retries),
    )


def _slow_handler(inputs: dict[str, Any]) -> dict[str, Any]:
    time.sleep(5)
    return {}


def _make_flaky_handler(fail_until: int):
    counter = {"n": 0}

    def handler(inputs: dict[str, Any]) -> dict[str, Any]:
        counter["n"] += 1
        if counter["n"] < fail_until:
            raise RuntimeError("Transient failure")
        return {}

    return handler


def _always_failing_handler(inputs: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("Permanent failure")


def _ok_handler(inputs: dict[str, Any]) -> dict[str, Any]:
    return {}


class TestTimeout:
    """Slow nodes time out based on quality_controls.timeout_seconds."""

    def test_slow_node_times_out(self):
        spec = _make_spec(timeout_seconds=1)
        with patch("agent_foundry.registry.execution.FF_RETRY_TIMEOUTS", True):
            with pytest.raises(RoleExecutionError) as exc_info:
                execute_role(spec, {}, _slow_handler)
            assert exc_info.value.phase == "timeout"

    def test_fast_node_does_not_timeout(self):
        spec = _make_spec(timeout_seconds=10)
        with patch("agent_foundry.registry.execution.FF_RETRY_TIMEOUTS", True):
            result = execute_role(spec, {}, _ok_handler)
        assert result == {}


class TestRetries:
    """Flaky nodes retry up to max_retries then error."""

    def test_flaky_node_succeeds_after_retries(self):
        spec = _make_spec(max_retries=3)
        with patch("agent_foundry.registry.execution.FF_RETRY_TIMEOUTS", True):
            result = execute_role(spec, {}, _make_flaky_handler(3))
        assert result == {}

    def test_always_failing_node_exhausts_retries(self):
        spec = _make_spec(max_retries=2)
        with patch("agent_foundry.registry.execution.FF_RETRY_TIMEOUTS", True):
            with pytest.raises(RoleExecutionError) as exc_info:
                execute_role(spec, {}, _always_failing_handler)
            assert exc_info.value.phase == "retry_exhausted"

    def test_retry_exhausted_includes_attempt_count(self):
        spec = _make_spec(max_retries=2)
        with patch("agent_foundry.registry.execution.FF_RETRY_TIMEOUTS", True):
            with pytest.raises(RoleExecutionError) as exc_info:
                execute_role(spec, {}, _always_failing_handler)
            assert "3 attempts" in str(exc_info.value)  # 1 initial + 2 retries


class TestFeatureFlag:
    """FF_RETRY_TIMEOUTS off means no timeout/retry enforcement."""

    def test_flag_off_does_not_timeout(self):
        spec = _make_spec(timeout_seconds=1)
        with patch("agent_foundry.registry.execution.FF_RETRY_TIMEOUTS", False):
            # With flag off, handler runs without timeout enforcement
            result = execute_role(spec, {}, _ok_handler)
        assert result == {}

    def test_flag_off_does_not_retry(self):
        spec = _make_spec(max_retries=3)
        with (
            patch("agent_foundry.registry.execution.FF_RETRY_TIMEOUTS", False),
            pytest.raises(RuntimeError),
        ):
            execute_role(spec, {}, _always_failing_handler)
