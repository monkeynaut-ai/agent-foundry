"""Span emission helper used by the compiler at construct boundaries."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel

from agent_foundry.telemetry import attributes
from agent_foundry.telemetry.config import RedactionPolicy


@dataclass
class SpanHandle:
    """In-band handle returned by ``emit_span`` for setting output and
    LLM-specific attributes mid-execution.
    """

    _span: trace.Span | None  # None when telemetry is off — handle is a no-op
    _redaction: RedactionPolicy | None
    _translations: dict[str, str]  # source-attr → mirror-attr table

    def _set(self, key: str, value: object) -> None:
        """Set ``key`` on the span and mirror to any translated key.

        Mirroring happens before ``span.end()``, so both attributes land
        on the live span — they cannot be lost to OTel's "set-after-end
        is a no-op" rule.
        """
        if self._span is None:
            return
        self._span.set_attribute(key, value)  # type: ignore[arg-type]
        mirror = self._translations.get(key)
        if mirror is not None:
            self._span.set_attribute(mirror, value)  # type: ignore[arg-type]

    def set_output(self, model: BaseModel) -> None:
        if self._span is None:
            return
        if self._redaction is not None and self._redaction.redact_output is not None:
            model = self._redaction.redact_output(model)
            if not isinstance(model, BaseModel):
                raise TypeError(
                    "RedactionPolicy.redact_output must return a Pydantic BaseModel; "
                    f"got {type(model).__name__}"
                )
        self._set(attributes.AF_OUTPUT, model.model_dump_json())

    def set_model_id(self, model_id: str) -> None:
        self._set(attributes.GEN_AI_REQUEST_MODEL, model_id)

    def set_token_usage(self, *, input_tokens: int, output_tokens: int) -> None:
        self._set(attributes.GEN_AI_USAGE_INPUT_TOKENS, input_tokens)
        self._set(attributes.GEN_AI_USAGE_OUTPUT_TOKENS, output_tokens)

    def set_operation_name(self, name: str) -> None:
        """Set the OTel GenAI operation name (e.g. ``"chat"`` for an LLM call).

        Uses the handle's direct span reference rather than
        ``trace.get_current_span()`` so the attribute lands correctly even
        when the caller is on a worker thread (LangGraph dispatches sync
        executors via ``asyncio.to_thread``, and OTel's current-span
        ContextVar may not propagate into that thread).
        """
        self._set(attributes.GEN_AI_OPERATION_NAME, name)


def _resolve_provider_and_translations() -> tuple[SDKTracerProvider | None, dict[str, str]]:
    """Return the active RunContext's TracerProvider and translation table.

    Per-run isolation: provider stored on ``RunContext.telemetry_provider``;
    translation table from ``RunContext.telemetry.attribute_translations``.
    No global state involved.
    """
    from agent_foundry.orchestration.run_context import current_run_context

    ctx = current_run_context.get()
    if ctx is None:
        return None, {}
    provider = ctx.telemetry_provider
    translations = ctx.telemetry.attribute_translations if ctx.telemetry is not None else {}
    return provider, translations


@contextmanager
def emit_span(
    *,
    name: str,
    construct_type: str,
    construct_name: str | None,
    input_model: BaseModel,
    run_id: str | None,
    redaction: RedactionPolicy | None,
) -> Iterator[SpanHandle]:
    """Emit one OTel span for a construct's execution.

    Sets ``agent_foundry.*`` attributes on entry. Exceptions in the body
    are recorded on the span and re-raised. The yielded handle exposes
    ``set_output``, ``set_model_id``, ``set_token_usage``, and
    ``set_operation_name`` so the caller can fill in attributes that are
    only known after execution.

    If no telemetry provider is set on the active ``RunContext`` (telemetry
    is off, or no RunContext is active), yields a no-op ``SpanHandle`` and
    does not call into the OTel SDK at all. The body still runs and
    exceptions still propagate normally — the only effect is that no span
    is emitted.
    """
    provider, translations = _resolve_provider_and_translations()
    if provider is None:
        yield SpanHandle(_span=None, _redaction=redaction, _translations={})
        return

    def _set_with_mirror(span: trace.Span, key: str, value: object) -> None:
        span.set_attribute(key, value)  # type: ignore[arg-type]
        mirror = translations.get(key)
        if mirror is not None:
            span.set_attribute(mirror, value)  # type: ignore[arg-type]

    tracer = provider.get_tracer("agent_foundry")
    with tracer.start_as_current_span(name) as span:
        _set_with_mirror(span, attributes.AF_PRIMITIVE_TYPE, construct_type)
        if construct_name is not None:
            _set_with_mirror(span, attributes.AF_PRIMITIVE_NAME, construct_name)
        if run_id is not None:
            _set_with_mirror(span, attributes.AF_RUN_ID, run_id)

        if redaction is not None and redaction.redact_input is not None:
            redacted_input = redaction.redact_input(input_model)
            if not isinstance(redacted_input, BaseModel):
                raise TypeError(
                    "RedactionPolicy.redact_input must return a Pydantic BaseModel; "
                    f"got {type(redacted_input).__name__}"
                )
            _set_with_mirror(span, attributes.AF_INPUT, redacted_input.model_dump_json())
        else:
            _set_with_mirror(span, attributes.AF_INPUT, input_model.model_dump_json())

        handle = SpanHandle(_span=span, _redaction=redaction, _translations=translations)
        try:
            yield handle
        except BaseException as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        else:
            span.set_status(Status(StatusCode.OK))
