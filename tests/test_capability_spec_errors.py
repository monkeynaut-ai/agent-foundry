"""S1.2 — Deterministic errors for invalid specs (missing fields + parse errors).

Tests: missing required fields yield CapabilitySpecValidationError;
       invalid YAML/JSON yields parse error with file path metadata;
       process does not crash.
"""

from pathlib import Path

import pytest

from agent_foundry.registry.errors import (
    CapabilitySpecParseError,
    CapabilitySpecValidationError,
)
from agent_foundry.registry.spec import load_capability_spec

FIXTURES = Path(__file__).parent / "fixtures"


class TestMissingRequiredFields:
    """Missing required fields produce typed validation errors."""

    def test_missing_name_raises_validation_error(self):
        with pytest.raises(CapabilitySpecValidationError) as exc_info:
            load_capability_spec(FIXTURES / "invalid_missing_name.yaml")
        assert "name" in str(exc_info.value)

    def test_validation_error_includes_file_path(self):
        with pytest.raises(CapabilitySpecValidationError) as exc_info:
            load_capability_spec(FIXTURES / "invalid_missing_name.yaml")
        assert exc_info.value.file_path == FIXTURES / "invalid_missing_name.yaml"

    def test_validation_error_lists_missing_fields(self):
        with pytest.raises(CapabilitySpecValidationError) as exc_info:
            load_capability_spec(FIXTURES / "invalid_missing_name.yaml")
        assert "name" in exc_info.value.missing_fields


class TestParseErrors:
    """Malformed YAML/JSON produces typed parse errors with metadata."""

    def test_invalid_yaml_raises_parse_error(self):
        with pytest.raises(CapabilitySpecParseError) as exc_info:
            load_capability_spec(FIXTURES / "invalid_parse_error.yaml")
        assert exc_info.value.file_path == FIXTURES / "invalid_parse_error.yaml"

    def test_invalid_json_raises_parse_error(self):
        with pytest.raises(CapabilitySpecParseError) as exc_info:
            load_capability_spec(FIXTURES / "invalid_parse_error.json")
        assert exc_info.value.file_path == FIXTURES / "invalid_parse_error.json"

    def test_yaml_parse_error_includes_line_info(self):
        with pytest.raises(CapabilitySpecParseError) as exc_info:
            load_capability_spec(FIXTURES / "invalid_parse_error.yaml")
        # YAML errors should include line information when available
        assert exc_info.value.line is not None or exc_info.value.column is not None

    def test_json_parse_error_includes_position(self):
        with pytest.raises(CapabilitySpecParseError) as exc_info:
            load_capability_spec(FIXTURES / "invalid_parse_error.json")
        assert exc_info.value.line is not None or exc_info.value.column is not None

    def test_parse_error_message_is_descriptive(self):
        with pytest.raises(CapabilitySpecParseError) as exc_info:
            load_capability_spec(FIXTURES / "invalid_parse_error.yaml")
        msg = str(exc_info.value)
        assert "invalid_parse_error.yaml" in msg


class TestProcessDoesNotCrash:
    """Invalid specs never cause unhandled exceptions."""

    def test_missing_fields_does_not_crash(self):
        try:
            load_capability_spec(FIXTURES / "invalid_missing_name.yaml")
        except CapabilitySpecValidationError:
            pass  # Expected

    def test_parse_error_does_not_crash(self):
        try:
            load_capability_spec(FIXTURES / "invalid_parse_error.yaml")
        except CapabilitySpecParseError:
            pass  # Expected

    def test_nonexistent_file_raises_parse_error(self):
        with pytest.raises(CapabilitySpecParseError):
            load_capability_spec(FIXTURES / "does_not_exist.yaml")
