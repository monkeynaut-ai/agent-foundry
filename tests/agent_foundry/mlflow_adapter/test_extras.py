"""Tests for the mlflow_adapter import guard."""

from __future__ import annotations

import sys

import pytest


def test_mlflow_adapter_import_succeeds_when_mlflow_is_available() -> None:
    # mlflow is installed via the [mlflow] extra; just confirm the package
    # imports without error.
    import agent_foundry.mlflow_adapter  # noqa: F401


def test_mlflow_adapter_import_raises_helpful_error_when_mlflow_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force ImportError on `import mlflow` and confirm the adapter raises the
    # actionable message.
    mod_name = "agent_foundry.mlflow_adapter"
    sys.modules.pop(mod_name, None)
    sys.modules.pop("agent_foundry.mlflow_adapter.extras", None)
    monkeypatch.setitem(sys.modules, "mlflow", None)

    with pytest.raises(ImportError, match=r"\[mlflow\] extra"):
        __import__(mod_name)
