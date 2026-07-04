"""Public-API export guarantees for shared model helpers."""

import agent_foundry.models as models


def test_agent_file_path_helpers_are_publicly_exported():
    from agent_foundry.models import (
        PLATFORM_DEFAULT_MAX_FILE_BYTES,
        AgentFilePath,
        FilePathFieldSpec,
        extract_paths,
        walk_file_path_fields,
    )

    expected = {
        "PLATFORM_DEFAULT_MAX_FILE_BYTES",
        "AgentFilePath",
        "FilePathFieldSpec",
        "extract_paths",
        "walk_file_path_fields",
    }

    assert expected <= set(models.__all__)
    assert models.PLATFORM_DEFAULT_MAX_FILE_BYTES is PLATFORM_DEFAULT_MAX_FILE_BYTES
    assert models.AgentFilePath is AgentFilePath
    assert models.FilePathFieldSpec is FilePathFieldSpec
    assert models.extract_paths is extract_paths
    assert models.walk_file_path_fields is walk_file_path_fields
