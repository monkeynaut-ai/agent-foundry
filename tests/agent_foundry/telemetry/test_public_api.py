"""Public-API export guarantees for telemetry."""

import agent_foundry.telemetry as telemetry


def test_telemetry_config_surface_is_publicly_exported():
    from agent_foundry.telemetry import (
        ArtifactSpec,
        RedactionPolicy,
        RunDefinition,
        RunStats,
        TelemetryConfig,
        attributes,
    )

    expected = {
        "ArtifactSpec",
        "RedactionPolicy",
        "RunDefinition",
        "RunStats",
        "TelemetryConfig",
        "attributes",
    }

    assert expected <= set(telemetry.__all__)
    assert telemetry.ArtifactSpec is ArtifactSpec
    assert telemetry.RedactionPolicy is RedactionPolicy
    assert telemetry.RunDefinition is RunDefinition
    assert telemetry.RunStats is RunStats
    assert telemetry.TelemetryConfig is TelemetryConfig
    assert telemetry.attributes is attributes


def test_low_level_span_helpers_are_not_package_public():
    assert "SpanHandle" not in telemetry.__all__
    assert "build_tracer_provider" not in telemetry.__all__
    assert "emit_span" not in telemetry.__all__
