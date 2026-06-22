"""The attribute namespace contract from the design doc.

These tests pin the exact string values. Changes here are breaking
changes — downstream consumers depend on them.
"""

from __future__ import annotations

from agent_foundry.telemetry import attributes


def test_af_input_constant() -> None:
    assert attributes.AF_INPUT == "agent_foundry.input"


def test_af_output_constant() -> None:
    assert attributes.AF_OUTPUT == "agent_foundry.output"


def test_af_construct_type_constant() -> None:
    assert attributes.AF_PRIMITIVE_TYPE == "agent_foundry.construct_type"


def test_af_construct_name_constant() -> None:
    assert attributes.AF_PRIMITIVE_NAME == "agent_foundry.construct_name"


def test_af_run_id_constant() -> None:
    assert attributes.AF_RUN_ID == "agent_foundry.run_id"


def test_gen_ai_operation_name_constant() -> None:
    assert attributes.GEN_AI_OPERATION_NAME == "gen_ai.operation.name"


def test_gen_ai_request_model_constant() -> None:
    assert attributes.GEN_AI_REQUEST_MODEL == "gen_ai.request.model"


def test_gen_ai_usage_input_tokens_constant() -> None:
    assert attributes.GEN_AI_USAGE_INPUT_TOKENS == "gen_ai.usage.input_tokens"


def test_gen_ai_usage_output_tokens_constant() -> None:
    assert attributes.GEN_AI_USAGE_OUTPUT_TOKENS == "gen_ai.usage.output_tokens"
