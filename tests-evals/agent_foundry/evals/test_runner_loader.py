"""Tests for ``agent_foundry.evals.runner_loader``."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from agent_foundry.evals.models import Runner
from agent_foundry.evals.runner_loader import (
    DEFAULT_RUNNER_SPEC,
    InvalidRunnerSpecError,
    RunnerAttributeError,
    RunnerModuleImportError,
    load_runner,
)


@pytest.fixture()
def _make_runner_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Write a Python module that exposes a Runner-conforming class."""

    def _factory(module_name: str, attr_name: str = "MyRunner") -> str:
        module_path = tmp_path / f"{module_name}.py"
        module_path.write_text(
            textwrap.dedent(
                f"""
                class {attr_name}:
                    async def run(self, suite, *, task, max_concurrency=1):
                        return None
                """
            ).lstrip()
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        return f"{module_name}:{attr_name}"

    yield _factory

    for name in list(sys.modules):
        if name.startswith("_runner_loader_test_"):
            del sys.modules[name]


def test_load_runner_default_spec_resolves_pydantic_evals_runner() -> None:
    """The default spec resolves to a Runner-conforming instance."""
    runner = load_runner()
    assert isinstance(runner, Runner)


def test_load_runner_returns_instance_from_explicit_spec(_make_runner_module) -> None:
    spec = _make_runner_module("_runner_loader_test_basic")
    runner = load_runner(spec)
    assert isinstance(runner, Runner)


def test_load_runner_invalid_spec_no_colon() -> None:
    with pytest.raises(InvalidRunnerSpecError, match="module:Class"):
        load_runner("no_colon_here")


def test_load_runner_invalid_spec_empty_module() -> None:
    with pytest.raises(InvalidRunnerSpecError):
        load_runner(":MyRunner")


def test_load_runner_invalid_spec_empty_attr() -> None:
    with pytest.raises(InvalidRunnerSpecError):
        load_runner("module.path:")


def test_load_runner_module_not_found() -> None:
    with pytest.raises(RunnerModuleImportError):
        load_runner("does_not_exist_module_xyz:MyRunner")


def test_load_runner_attribute_missing(_make_runner_module) -> None:
    _make_runner_module("_runner_loader_test_attr_missing", attr_name="MyRunner")
    with pytest.raises(RunnerAttributeError, match="MISSING"):
        load_runner("_runner_loader_test_attr_missing:MISSING")


def test_load_runner_class_missing_run_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_path = tmp_path / "_runner_loader_test_no_run.py"
    module_path.write_text("class NotARunner:\n    pass\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(TypeError, match="Runner Protocol"):
        load_runner("_runner_loader_test_no_run:NotARunner")


def test_default_runner_spec_points_at_pydantic_evals_runner() -> None:
    assert DEFAULT_RUNNER_SPEC == "agent_foundry.evals.runners.pydantic_evals:PydanticEvalsRunner"
