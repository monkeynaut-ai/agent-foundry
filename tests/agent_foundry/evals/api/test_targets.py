"""Tests for the ``/targets`` HTTP routes."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from agent_foundry.ai_models.inference import InferenceParameters
from agent_foundry.ai_models.model import ModelCapabilities, ModelEntry
from agent_foundry.constructs.ai_call import AICall, ModelInput
from agent_foundry.evals.api.app import create_app
from agent_foundry.evals.registry import AICallRegistry


class _Input(BaseModel):
    text: str


class _Output(BaseModel):
    result: str


def _make_ai_call() -> AICall[_Input, _Output]:
    entry = ModelEntry(
        model_id="claude-haiku-4-5-20251001",
        provider=object(),  # type: ignore[arg-type]  # not invoked in route tests
        capabilities=ModelCapabilities(context_window=1000, max_output_tokens=100),
    )
    return AICall[_Input, _Output](
        model_input=ModelInput[_Input](instructions="i", prompt="p"),
        parameters=InferenceParameters(max_tokens=128),
        model=entry,
    )


@pytest.fixture()
def app_with_two_targets() -> FastAPI:
    registry = AICallRegistry()
    registry.register("design_review", _make_ai_call())
    registry.register("work_router", _make_ai_call())
    return create_app(registry)


@pytest.fixture()
def app_with_empty_registry() -> FastAPI:
    return create_app(AICallRegistry())


# --- GET /targets ---


def test_list_targets_returns_all_registered(app_with_two_targets: FastAPI) -> None:
    client = TestClient(app_with_two_targets)

    response = client.get("/targets")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    names = {entry["name"] for entry in body}
    assert names == {"design_review", "work_router"}


def test_list_targets_empty_registry_returns_empty_list(
    app_with_empty_registry: FastAPI,
) -> None:
    client = TestClient(app_with_empty_registry)

    response = client.get("/targets")

    assert response.status_code == 200
    assert response.json() == []


def test_list_targets_entries_carry_kind_and_schemas(app_with_two_targets: FastAPI) -> None:
    client = TestClient(app_with_two_targets)

    response = client.get("/targets")

    body = response.json()
    entry = next(e for e in body if e["name"] == "design_review")
    assert entry["kind"] == "ai_call"
    assert isinstance(entry["input_schema"], dict)
    assert isinstance(entry["output_schema"], dict)
    assert "properties" in entry["input_schema"]


# --- GET /targets/{name} ---


def test_get_target_returns_registered_target(app_with_two_targets: FastAPI) -> None:
    client = TestClient(app_with_two_targets)

    response = client.get("/targets/design_review")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "design_review"
    assert body["kind"] == "ai_call"
    assert "text" in body["input_schema"]["properties"]
    assert "result" in body["output_schema"]["properties"]


def test_get_target_404_on_unknown_name(app_with_two_targets: FastAPI) -> None:
    client = TestClient(app_with_two_targets)

    response = client.get("/targets/does_not_exist")

    assert response.status_code == 404
    assert "does_not_exist" in response.json()["detail"]


def test_get_target_404_on_empty_registry(app_with_empty_registry: FastAPI) -> None:
    client = TestClient(app_with_empty_registry)

    response = client.get("/targets/anything")

    assert response.status_code == 404
