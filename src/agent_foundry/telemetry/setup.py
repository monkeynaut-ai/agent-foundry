"""Construct an OpenTelemetry TracerProvider from a TelemetryConfig."""

from __future__ import annotations

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from agent_foundry.telemetry.config import TelemetryConfig


def build_tracer_provider(config: TelemetryConfig) -> TracerProvider:
    """Build a TracerProvider with a BatchSpanProcessor exporting to the
    configured OTLP/HTTP endpoint. Caller is responsible for installing the
    provider on the OTel SDK and calling ``shutdown()`` for clean flush.
    """
    resource = Resource.create({"service.name": config.service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=config.otlp_endpoint,
        headers=config.otlp_headers,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider
