"""S6.1-S6.4, S6.6-S6.7 — Observability + Evaluation Gates.

S6.1: Tracing spans per node with timestamps, node id, capability, status.
S6.2: Tool and retrieval trace enrichment with redaction.
S6.3: Schema validator gate (generic).
S6.4: Decision eval gates: citation, uncertainty, evidence-first.
S6.6: Compiler enforces gate execution on all paths to final.
S6.7: Non-functional: trace payload size + export latency budgets.
"""

import time
from pathlib import Path
from typing import Any

import pytest

from agent_foundry.observability.tracer import ExecutionTracer, Span
from agent_foundry.observability.gates import (
    schema_validator_gate,
    citation_validator_gate,
    uncertainty_completeness_gate,
    evidence_first_gate,
)
from agent_foundry.registry.registry import CapabilityRegistry

CAPABILITIES_DIR = Path(__file__).parent.parent / "capabilities"


# --- S6.1: Tracing Spans ---

class TestTracingSpans:
    """Node execution emits spans with required fields."""

    def test_span_has_required_fields(self):
        tracer = ExecutionTracer()
        span = tracer.start_span(node_id="n1", capability="rag_retriever")
        tracer.end_span(span, status="success")
        assert span.node_id == "n1"
        assert span.capability == "rag_retriever"
        assert span.status == "success"
        assert span.start_time is not None
        assert span.end_time is not None

    def test_span_timestamps_are_ordered(self):
        tracer = ExecutionTracer()
        span = tracer.start_span(node_id="n1", capability="test")
        time.sleep(0.001)
        tracer.end_span(span, status="success")
        assert span.end_time >= span.start_time

    def test_tracer_collects_all_spans(self):
        tracer = ExecutionTracer()
        s1 = tracer.start_span(node_id="n1", capability="a")
        tracer.end_span(s1, status="success")
        s2 = tracer.start_span(node_id="n2", capability="b")
        tracer.end_span(s2, status="success")
        assert len(tracer.spans) == 2

    def test_span_export(self):
        tracer = ExecutionTracer()
        span = tracer.start_span(node_id="n1", capability="test")
        tracer.end_span(span, status="success")
        exported = tracer.export()
        assert len(exported) == 1
        assert exported[0]["node_id"] == "n1"


# --- S6.2: Tool and Retrieval Trace Enrichment ---

class TestTraceEnrichment:
    """Tool calls and retrievals are captured in traces."""

    def test_tool_trace_redacts_secrets(self):
        tracer = ExecutionTracer()
        span = tracer.start_span(node_id="n1", capability="tool_calling")
        tracer.add_tool_call(span, tool_name="api_call",
                             args={"api_key": "sk-secret-123", "query": "test"},
                             result={"data": "ok"})
        tracer.end_span(span, status="success")
        tool_calls = span.tool_calls
        assert len(tool_calls) == 1
        assert "sk-secret" not in str(tool_calls[0]["args"])
        assert tool_calls[0]["args"]["api_key"] == "[REDACTED]"

    def test_retrieval_trace_includes_metadata(self):
        tracer = ExecutionTracer()
        span = tracer.start_span(node_id="n1", capability="rag_retriever")
        tracer.add_retrieval(span, snippet_ids=["s1", "s2"], ranks=[1, 2])
        tracer.end_span(span, status="success")
        assert span.retrieval_info is not None
        assert span.retrieval_info["snippet_ids"] == ["s1", "s2"]

    def test_tool_trace_redacts_nested_secrets(self):
        tracer = ExecutionTracer()
        span = tracer.start_span(node_id="n1", capability="tool_calling")
        tracer.add_tool_call(
            span,
            tool_name="api_call",
            args={
                "query": "test",
                "headers": {"authorization": "Bearer abc123"},
                "auth": {"token": "tok-xyz"},
            },
            result={"data": "ok"},
        )
        tracer.end_span(span, status="success")

        args = span.tool_calls[0]["args"]
        assert args["headers"]["authorization"] == "[REDACTED]"
        assert args["auth"]["token"] == "[REDACTED]"


# --- S6.3: Schema Validator Gate ---

class TestSchemaValidatorGate:
    """Schema validator gate blocks on invalid output."""

    def test_valid_output_passes(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        result = schema_validator_gate({"name": "test"}, schema)
        assert result["valid"] is True

    def test_invalid_output_fails(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        result = schema_validator_gate({}, schema)
        assert result["valid"] is False
        assert len(result["errors"]) > 0


# --- S6.4: Decision Eval Gates ---

class TestCitationValidatorGate:
    """Citation gate checks evidence ID references."""

    def test_valid_citations_pass(self):
        result = citation_validator_gate(
            evidence_ids=["e1", "e2"],
            retrieved_evidence=[{"id": "e1"}, {"id": "e2"}, {"id": "e3"}],
        )
        assert result["valid"] is True

    def test_missing_citation_fails(self):
        result = citation_validator_gate(
            evidence_ids=["e1", "e999"],
            retrieved_evidence=[{"id": "e1"}, {"id": "e2"}],
        )
        assert result["valid"] is False
        assert "e999" in result["missing_ids"]


class TestUncertaintyGate:
    """Uncertainty gate checks confidence and rationale."""

    def test_complete_uncertainty_passes(self):
        result = uncertainty_completeness_gate(
            uncertainty={"confidence": 0.85, "rationale": "Based on strong evidence"}
        )
        assert result["valid"] is True

    def test_missing_confidence_fails(self):
        result = uncertainty_completeness_gate(
            uncertainty={"rationale": "Some rationale"}
        )
        assert result["valid"] is False
        assert "confidence" in result["missing_fields"]

    def test_missing_rationale_fails(self):
        result = uncertainty_completeness_gate(
            uncertainty={"confidence": 0.5}
        )
        assert result["valid"] is False

    def test_out_of_range_confidence_fails(self):
        result = uncertainty_completeness_gate(
            uncertainty={"confidence": 1.5, "rationale": "test"}
        )
        assert result["valid"] is False


class TestEvidenceFirstGate:
    """Evidence-first contract validator."""

    def test_no_evidence_returns_insufficient(self):
        result = evidence_first_gate(
            retrieved_evidence=[],
            recommendation={"text": "do something"},
        )
        assert result["valid"] is False
        assert result["outcome"] == "insufficient_evidence"

    def test_with_evidence_and_assumptions_passes(self):
        result = evidence_first_gate(
            retrieved_evidence=[{"id": "e1", "text": "evidence"}],
            recommendation={"text": "do something", "assumptions": ["assume X"]},
        )
        assert result["valid"] is True

    def test_missing_assumptions_fails(self):
        result = evidence_first_gate(
            retrieved_evidence=[{"id": "e1", "text": "evidence"}],
            recommendation={"text": "do something"},
        )
        assert result["valid"] is False
