"""Tests for ``agent_foundry.evals.api.config``."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_foundry.evals.api.config import (
    DEFAULT_CONFIG_FILENAME,
    ApiBindingConfig,
    ConfigNotFoundError,
    EvalApiConfig,
    load_config,
)


def test_load_config_from_explicit_path(tmp_path: Path) -> None:
    config_file = tmp_path / "agent_foundry.config"
    config_file.write_text(
        'registry = "archipelago.evals.eval_registration:EVAL_REGISTRY"\n'
        "\n"
        "[api]\n"
        'host = "0.0.0.0"\n'
        "port = 9000\n"
    )

    cfg = load_config(config_file)

    assert isinstance(cfg, EvalApiConfig)
    assert cfg.registry == "archipelago.evals.eval_registration:EVAL_REGISTRY"
    assert cfg.api.host == "0.0.0.0"
    assert cfg.api.port == 9000


def test_load_config_applies_api_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "agent_foundry.config"
    config_file.write_text('registry = "app.evals:REGISTRY"\n')

    cfg = load_config(config_file)

    assert cfg.registry == "app.evals:REGISTRY"
    assert cfg.api.host == "127.0.0.1"
    assert cfg.api.port == 8000


def test_load_config_from_cwd_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / DEFAULT_CONFIG_FILENAME
    config_file.write_text('registry = "app.evals:REGISTRY"\n')
    monkeypatch.chdir(tmp_path)

    cfg = load_config()

    assert cfg.registry == "app.evals:REGISTRY"


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "agent_foundry.config"
    with pytest.raises(ConfigNotFoundError) as exc_info:
        load_config(missing)
    assert str(missing) in str(exc_info.value)


def test_load_config_missing_registry_raises(tmp_path: Path) -> None:
    config_file = tmp_path / "agent_foundry.config"
    config_file.write_text("[api]\nport = 8000\n")

    with pytest.raises(ValidationError):
        load_config(config_file)


def test_load_config_rejects_unknown_top_level_keys(tmp_path: Path) -> None:
    config_file = tmp_path / "agent_foundry.config"
    config_file.write_text('registry = "app.evals:REGISTRY"\nunknown_key = "oops"\n')

    with pytest.raises(ValidationError):
        load_config(config_file)


def test_load_config_rejects_unknown_api_keys(tmp_path: Path) -> None:
    config_file = tmp_path / "agent_foundry.config"
    config_file.write_text('registry = "app.evals:REGISTRY"\n\n[api]\nunknown_key = "oops"\n')

    with pytest.raises(ValidationError):
        load_config(config_file)


def test_load_config_rejects_malformed_toml(tmp_path: Path) -> None:
    import tomllib

    config_file = tmp_path / "agent_foundry.config"
    config_file.write_text('registry = "missing closing quote\n')

    with pytest.raises(tomllib.TOMLDecodeError):
        load_config(config_file)


def test_api_binding_config_validates_port_range() -> None:
    with pytest.raises(ValidationError):
        ApiBindingConfig(port=0)
    with pytest.raises(ValidationError):
        ApiBindingConfig(port=70000)
