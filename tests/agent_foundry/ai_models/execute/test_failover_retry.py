"""Retry + failover behavior of ``invoke_ai_call``.

Uses scripted fake providers (no network) to exercise the inner retry loop
(transient errors against one model) and the outer failover loop (advance the
fallback chain on persistent failure or exhausted retries).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_foundry.ai_models.execute.invoke import invoke_ai_call
from agent_foundry.ai_models.inference import (
    InferenceParameters,
    InferenceProvider,
    InferenceRequest,
    InferenceResult,
)
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.ai_models.resilience import RetryPolicy
from agent_foundry.constructs.ai_call import AICall, ModelInput


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


class _Transient(Exception):
    pass


class _Persistent(Exception):
    pass


class _ScriptedProvider(InferenceProvider):
    """Raise each queued exception in turn, then return success."""

    def __init__(self, *, fail_with: list[Exception] | None = None, tag: str = "ok") -> None:
        self._queue = list(fail_with or [])
        self._tag = tag
        self.calls = 0

    async def __call__(self, request: InferenceRequest) -> InferenceResult:
        self.calls += 1
        if self._queue:
            raise self._queue.pop(0)
        return InferenceResult(output=_Output(result=self._tag), usage=None)

    async def close(self) -> None:
        pass

    def is_transient(self, exc: Exception) -> bool:
        return isinstance(exc, _Transient)


def _entry(provider: InferenceProvider, *, model_id: str = "m", fallback: ModelEntry | None = None):
    return ModelEntry(
        model_id=model_id,
        provider=provider,
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
        fallback=fallback,
    )


def _call(model: ModelEntry, *, retry: RetryPolicy | None = None, fallbacks=None) -> AICall:
    return AICall[_Input, _Output](
        model_input=ModelInput(instructions="i", prompt="p"),
        model=model,
        parameters=InferenceParameters(),
        retry=retry or RetryPolicy(max_attempts=3, backoff_base_seconds=0.0),
        fallbacks=fallbacks,
    )


_NO_WAIT = RetryPolicy(max_attempts=3, backoff_base_seconds=0.0)


@pytest.mark.asyncio
async def test_transient_then_success_is_retried() -> None:
    provider = _ScriptedProvider(fail_with=[_Transient(), _Transient()], tag="recovered")
    result = await invoke_ai_call(construct=_call(_entry(provider)), model_input=_Input(text="x"))
    assert result.output.result == "recovered"
    assert provider.calls == 3  # 2 failures + 1 success, within max_attempts=3


@pytest.mark.asyncio
async def test_retries_exhausted_without_fallback_raises() -> None:
    provider = _ScriptedProvider(fail_with=[_Transient(), _Transient(), _Transient()])
    construct = _call(
        _entry(provider), retry=RetryPolicy(max_attempts=2, backoff_base_seconds=0.0), fallbacks=[]
    )
    with pytest.raises(_Transient):
        await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    assert provider.calls == 2  # capped at max_attempts; no failover


@pytest.mark.asyncio
async def test_persistent_error_fails_over_without_retry() -> None:
    primary = _ScriptedProvider(fail_with=[_Persistent()])
    fallback = _ScriptedProvider(tag="from-fallback")
    construct = _call(_entry(primary), retry=_NO_WAIT, fallbacks=[_entry(fallback, model_id="fb")])
    result = await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    assert result.output.result == "from-fallback"
    assert primary.calls == 1  # persistent -> no retry on primary
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_failover_after_retries_exhausted() -> None:
    primary = _ScriptedProvider(fail_with=[_Transient(), _Transient()])
    fallback = _ScriptedProvider(tag="from-fallback")
    construct = _call(
        _entry(primary),
        retry=RetryPolicy(max_attempts=2, backoff_base_seconds=0.0),
        fallbacks=[_entry(fallback, model_id="fb")],
    )
    result = await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    assert result.output.result == "from-fallback"
    assert primary.calls == 2  # retried to the cap, then failed over
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_all_candidates_fail_raises_last_error() -> None:
    primary = _ScriptedProvider(fail_with=[_Persistent()])
    fallback = _ScriptedProvider(fail_with=[_Persistent()])
    construct = _call(_entry(primary), retry=_NO_WAIT, fallbacks=[_entry(fallback, model_id="fb")])
    with pytest.raises(_Persistent):
        await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_empty_fallbacks_disables_failover_even_with_model_chain() -> None:
    fallback = _ScriptedProvider(tag="should-not-run")
    primary = _ScriptedProvider(fail_with=[_Persistent()])
    # Model declares a default fallback, but the call disables failover with [].
    primary_entry = _entry(primary, fallback=_entry(fallback, model_id="fb"))
    with pytest.raises(_Persistent):
        await invoke_ai_call(
            construct=_call(primary_entry, retry=_NO_WAIT, fallbacks=[]),
            model_input=_Input(text="x"),
        )
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_none_fallbacks_inherits_model_default_chain() -> None:
    fallback = _ScriptedProvider(tag="from-model-chain")
    primary = _ScriptedProvider(fail_with=[_Persistent()])
    primary_entry = _entry(primary, fallback=_entry(fallback, model_id="fb"))
    # fallbacks unset (None) -> derive chain from ModelEntry.fallback
    construct = _call(primary_entry, retry=_NO_WAIT, fallbacks=None)
    result = await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    assert result.output.result == "from-model-chain"
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_default_retry_policy_used_when_unset() -> None:
    # retry=None -> DEFAULT_RETRY_POLICY (max_attempts=3), so 2 transient then success.
    provider = _ScriptedProvider(fail_with=[_Transient(), _Transient()], tag="ok")
    construct = AICall[_Input, _Output](
        model_input=ModelInput(instructions="i", prompt="p"),
        model=_entry(provider),
        parameters=InferenceParameters(),
        # retry and fallbacks left unset
    )
    result = await invoke_ai_call(construct=construct, model_input=_Input(text="x"))
    assert result.output.result == "ok"
    assert provider.calls == 3
