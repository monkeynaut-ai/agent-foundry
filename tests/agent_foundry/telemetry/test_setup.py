"""Tests for build_tracer_provider."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider

from agent_foundry.telemetry.config import TelemetryConfig
from agent_foundry.telemetry.setup import build_tracer_provider


def _config(**overrides) -> TelemetryConfig:
    kwargs = dict(
        otlp_endpoint="http://localhost:5000/v1/traces",
        otlp_headers={"x-mlflow-experiment-id": "1"},
        service_name="archipelago",
    )
    kwargs.update(overrides)
    return TelemetryConfig(**kwargs)  # type: ignore[arg-type]


def test_build_tracer_provider_returns_tracer_provider() -> None:
    provider = build_tracer_provider(_config())
    assert isinstance(provider, TracerProvider)
    provider.shutdown()


def test_build_tracer_provider_sets_service_name_resource() -> None:
    provider = build_tracer_provider(_config(service_name="archipelago"))
    assert provider.resource.attributes.get("service.name") == "archipelago"
    provider.shutdown()


def test_build_tracer_provider_emits_to_configured_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behavioural test that the provider's exporter pipeline targets the
    configured endpoint. Avoids reaching into OTel SDK internals — instead
    monkeypatches the OTLP exporter constructor and asserts it was called
    with the right endpoint and headers.
    """
    observed: dict[str, object] = {}

    from agent_foundry.telemetry import setup as setup_mod

    original = setup_mod.OTLPSpanExporter

    def capturing_exporter(*, endpoint: str, headers: dict[str, str]):
        observed["endpoint"] = endpoint
        observed["headers"] = headers
        return original(endpoint=endpoint, headers=headers)

    monkeypatch.setattr(setup_mod, "OTLPSpanExporter", capturing_exporter)
    provider = build_tracer_provider(
        _config(otlp_endpoint="http://example:5000/v1/traces", otlp_headers={"k": "v"})
    )
    assert observed["endpoint"] == "http://example:5000/v1/traces"
    assert observed["headers"] == {"k": "v"}
    provider.shutdown()
