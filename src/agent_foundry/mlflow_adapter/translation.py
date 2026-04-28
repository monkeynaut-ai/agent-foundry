"""Translation table mapping AF span-attribute names to MLflow attribute names.

This module exports a constant ``dict`` rather than a ``SpanProcessor``.
Translation happens at attribute-set time inside ``emit_span`` (see
``agent_foundry/telemetry/spans.py``), not after the span ends — OTel's
SDK makes ``set_attribute`` a no-op on ended spans, so a post-end
SpanProcessor approach silently drops translated attributes under
``BatchSpanProcessor`` (the production pipeline).

Products plug this table into ``TelemetryConfig.attribute_translations``
to opt into MLflow-compatible attribute mirroring. AF core stays
MLflow-agnostic — it just dual-writes per the table.
"""

MLFLOW_TRANSLATIONS: dict[str, str] = {
    "agent_foundry.input": "mlflow.spanInputs",
    "agent_foundry.output": "mlflow.spanOutputs",
}
