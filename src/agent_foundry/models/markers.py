"""Annotated metadata markers for agent-foundry boundary models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

PLATFORM_DEFAULT_MAX_FILE_BYTES: Final[int] = 10_000_000


@dataclass(frozen=True)
class AgentFilePath:
    """Annotated metadata marker for fields that contain agent-written file paths.

    Attach via typing.Annotated:

        class ReviewerOutput(BaseModel):
            review_path: Annotated[str, AgentFilePath()]
            transcript_path: Annotated[str, AgentFilePath(max_size_bytes=50_000_000)]

    At runtime, the Plan 2 executor walks the JSON schema for fields
    carrying ``x-agent-file-path`` extensions and verifies the declared
    paths exist in the container and are within the declared size limit.
    """

    max_size_bytes: int = PLATFORM_DEFAULT_MAX_FILE_BYTES

    def __get_pydantic_json_schema__(self, core_schema: Any, handler: Any) -> Any:
        schema = handler(core_schema)
        schema["x-agent-file-path"] = {"max_size_bytes": self.max_size_bytes}
        return schema


@dataclass(frozen=True)
class FilePathFieldSpec:
    """A discovered AgentFilePath field: its JSON pointer and declared size limit."""

    json_pointer: str
    max_size_bytes: int


def walk_file_path_fields(schema: dict[str, Any]) -> list[FilePathFieldSpec]:
    """Walk a JSON schema; return every field that carries ``x-agent-file-path``.

    Handles nested objects, arrays (per-item), and ``$defs``/``$ref`` (resolved).
    Pointer format: ``/field`` for object properties, ``*`` for any array index
    (e.g., ``/paths/*``).
    """
    defs = schema.get("$defs", {})
    specs: list[FilePathFieldSpec] = []
    _walk(schema, "", defs, specs, set())
    return specs


def _resolve_ref(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if not isinstance(ref, str):
        return node
    # "#/$defs/Name"
    prefix = "#/$defs/"
    if ref.startswith(prefix):
        name = ref[len(prefix) :]
        target = defs.get(name)
        if isinstance(target, dict):
            return target
    return node


def _walk(
    node: Any,
    pointer: str,
    defs: dict[str, Any],
    specs: list[FilePathFieldSpec],
    visited: set[str],
) -> None:
    if not isinstance(node, dict):
        return

    # Resolve $ref before anything else.
    ref = node.get("$ref")
    if isinstance(ref, str):
        if ref in visited:
            return
        visited = visited | {ref}
        node = _resolve_ref(node, defs)

    # Record marker at the current node.
    marker = node.get("x-agent-file-path")
    if isinstance(marker, dict) and "max_size_bytes" in marker:
        specs.append(
            FilePathFieldSpec(
                json_pointer=pointer,
                max_size_bytes=int(marker["max_size_bytes"]),
            )
        )

    # Recurse into object properties.
    props = node.get("properties")
    if isinstance(props, dict):
        for field_name, field_schema in props.items():
            _walk(field_schema, f"{pointer}/{field_name}", defs, specs, visited)

    # Recurse into array items.
    items = node.get("items")
    if isinstance(items, dict):
        _walk(items, f"{pointer}/*", defs, specs, visited)


def extract_paths(output: dict[str, Any], specs: list[FilePathFieldSpec]) -> list[tuple[str, int]]:
    """Resolve each spec's JSON pointer against ``output``.

    Returns a list of ``(path, max_size_bytes)`` tuples. Missing optional
    nodes are silently skipped.
    """
    results: list[tuple[str, int]] = []
    for spec in specs:
        _resolve_pointer(output, spec.json_pointer, spec.max_size_bytes, results)
    return results


def _resolve_pointer(
    node: Any, pointer: str, max_size_bytes: int, results: list[tuple[str, int]]
) -> None:
    if not pointer:
        if isinstance(node, str):
            results.append((node, max_size_bytes))
        return

    # pointer starts with "/"
    assert pointer.startswith("/"), f"invalid pointer: {pointer!r}"
    rest = pointer[1:]
    if "/" in rest:
        segment, remainder = rest.split("/", 1)
        remainder_pointer = f"/{remainder}"
    else:
        segment, remainder_pointer = rest, ""

    if segment == "*":
        if not isinstance(node, list):
            return
        for item in node:
            _resolve_pointer(item, remainder_pointer, max_size_bytes, results)
        return

    if not isinstance(node, dict):
        return
    if segment not in node:
        return
    _resolve_pointer(node[segment], remainder_pointer, max_size_bytes, results)
