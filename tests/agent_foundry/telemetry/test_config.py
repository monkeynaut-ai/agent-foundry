"""Tests for the telemetry config Pydantic models."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from agent_foundry.telemetry.config import (
    ArtifactSpec,
    RedactionPolicy,
    RunDefinition,
    RunStats,
    TelemetryConfig,
)


class _Input(BaseModel):
    ticket_id: str
    kind: str = "bug"


class _Output(BaseModel):
    success: bool


# -- TelemetryConfig --


def test_telemetry_config_minimum_fields() -> None:
    config = TelemetryConfig(
        otlp_endpoint="http://localhost:5000/v1/traces",
        otlp_headers={},
        service_name="archipelago",
    )
    assert config.otlp_endpoint == "http://localhost:5000/v1/traces"
    assert config.otlp_headers == {}
    assert config.service_name == "archipelago"
    assert config.redaction is None
    assert config.run_definition is None


def test_telemetry_config_requires_endpoint() -> None:
    with pytest.raises(ValidationError):
        TelemetryConfig(  # type: ignore[call-arg]
            otlp_headers={},
            service_name="archipelago",
        )


def test_telemetry_config_requires_service_name() -> None:
    with pytest.raises(ValidationError):
        TelemetryConfig(  # type: ignore[call-arg]
            otlp_endpoint="http://localhost:5000/v1/traces",
            otlp_headers={},
        )


# -- RunDefinition --


def test_run_definition_evaluates_callables() -> None:
    rd = RunDefinition(
        name=lambda inp: f"ticket-{inp.ticket_id}",
        params=lambda inp: {"ticket_id": inp.ticket_id, "kind": inp.kind},
        tags={"product": "archipelago"},
        metrics=lambda out, stats: {
            "success": float(out.success),
            "duration_ms": stats.duration_ms,
        },
    )
    sample = _Input(ticket_id="42", kind="feature")
    assert rd.name(sample) == "ticket-42"
    assert rd.params(sample) == {"ticket_id": "42", "kind": "feature"}


def test_run_definition_metrics_callable_consumes_output_and_stats() -> None:
    rd = RunDefinition(
        name=lambda _: "n",
        params=lambda _: {},
        tags={},
        metrics=lambda out, stats: {"success": float(out.success)},
    )
    out = _Output(success=True)
    stats = RunStats()
    assert rd.metrics(out, stats) == {"success": 1.0}


def test_run_definition_tags_can_be_callable() -> None:
    rd = RunDefinition(
        name=lambda _: "n",
        params=lambda _: {},
        tags=lambda inp: {"kind": inp.kind},
        metrics=lambda _out, _s: {},
    )
    sample = _Input(ticket_id="1", kind="bug")
    assert callable(rd.tags)
    assert rd.tags(sample) == {"kind": "bug"}


def test_run_definition_artifacts_default_empty() -> None:
    rd = RunDefinition(
        name=lambda _: "n",
        params=lambda _: {},
        tags={},
        metrics=lambda _out, _stats: {},
    )
    assert rd.artifacts == []


# -- ArtifactSpec --


def test_artifact_spec_path_required(tmp_path: Path) -> None:
    spec = ArtifactSpec(path=tmp_path / "result.json")
    assert spec.path == tmp_path / "result.json"
    assert spec.artifact_path is None


def test_artifact_spec_optional_artifact_path(tmp_path: Path) -> None:
    spec = ArtifactSpec(path=tmp_path / "x.json", artifact_path="folder/x.json")
    assert spec.artifact_path == "folder/x.json"


# -- RedactionPolicy --


def test_redaction_policy_defaults_to_none() -> None:
    policy = RedactionPolicy()
    assert policy.redact_input is None
    assert policy.redact_output is None


def test_redaction_policy_accepts_callables() -> None:
    def red_in(m: _Input) -> _Input:
        return _Input(ticket_id="REDACTED", kind=m.kind)

    policy = RedactionPolicy(redact_input=red_in)
    assert policy.redact_input is red_in
    assert policy.redact_output is None


# -- RunStats --


def test_run_stats_zero_defaults() -> None:
    stats = RunStats()
    assert stats.duration_ms == 0.0
    assert stats.span_count == 0
    assert stats.error_count == 0
    assert stats.total_input_tokens == 0
    assert stats.total_output_tokens == 0


def test_run_stats_explicit_values() -> None:
    stats = RunStats(
        duration_ms=123.4,
        span_count=5,
        error_count=1,
        total_input_tokens=100,
        total_output_tokens=200,
    )
    assert stats.duration_ms == 123.4
    assert stats.span_count == 5
    assert stats.error_count == 1
    assert stats.total_input_tokens == 100
    assert stats.total_output_tokens == 200
