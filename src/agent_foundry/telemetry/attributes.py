"""Canonical attribute names for AF telemetry spans.

These are the names AF emits on every span. Two namespaces:

- ``agent_foundry.*`` — AF-internal concepts that no external standard
  covers cleanly. The MLflow adapter translates these additively to
  ``mlflow.*`` without removing originals.
- ``gen_ai.*`` — OpenTelemetry GenAI semantic conventions, used as-is.
  Recognised natively by MLflow's OTLP translator (renders typed spans
  without remapping) and by other OTel-compatible backends.

This module is the contract surface. Changes to constants are breaking
changes — downstream consumers (translators, dashboards, queries) depend
on them.
"""

AF_INPUT = "agent_foundry.input"
"""JSON-serialised input model (post-redaction)."""

AF_OUTPUT = "agent_foundry.output"
"""JSON-serialised output model (post-redaction)."""

AF_PRIMITIVE_TYPE = "agent_foundry.primitive_type"
"""The Python class name of the primitive emitting this span,
e.g. ``"AgentAction"``."""

AF_PRIMITIVE_NAME = "agent_foundry.primitive_name"
"""The primitive's diagnostic ``name`` field if set; otherwise absent."""

AF_RUN_ID = "agent_foundry.run_id"
"""The active ``RunContext.run_id`` for cross-referencing spans to runs."""

GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
"""OTel GenAI operation name, e.g. ``"chat"`` for an LLM chat completion."""

GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
"""OTel GenAI model identifier reported by the executor."""

GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
"""OTel GenAI input-token usage if reported."""

GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
"""OTel GenAI output-token usage if reported."""
