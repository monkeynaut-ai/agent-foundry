"""Schema transformation utilities for Claude Code --json-schema compatibility.

Claude Code's --json-schema flag has two limitations that Pydantic's default
JSON Schema output violates:

1. It cannot resolve `$ref` references. Pydantic generates `$defs` + `$ref`
   for every nested BaseModel. Leaving them in produces
   `error_max_structured_output_retries` after 5 failed attempts.

2. It silently disables schema enforcement when the OpenAPI `discriminator`
   keyword is present. Pydantic emits this for any `Field(discriminator="...")`
   on a discriminated union. The subtype comes back as `success` but
   `structured_output` is absent — the most dangerous failure mode because it
   looks like everything worked.

This module's `to_claude_code_schema` function transforms a Pydantic model's
schema into a standalone, reference-free form that Claude Code accepts.
Discriminated unions remain expressible via plain `oneOf` with `const` kind
discriminators — empirically verified to work correctly, including nested
cases.
"""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel


def _resolve_ref(ref: str, defs: dict[str, Any]) -> dict[str, Any]:
    """Resolve a '#/$defs/Name' reference against a $defs dict."""
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        raise ValueError(f"unsupported $ref shape: {ref!r}")
    name = ref[len(prefix) :]
    if name not in defs:
        raise KeyError(f"missing $def: {name!r}")
    return defs[name]


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    """Walk a JSON Schema node, inlining $refs and stripping keys that
    make Claude Code silently disable structured-output enforcement."""
    if isinstance(node, dict):
        if "$ref" in node and len(node) == 1:
            return _inline(deepcopy(_resolve_ref(node["$ref"], defs)), defs)
        result: dict[str, Any] = {}
        for key, value in node.items():
            if key == "discriminator":
                continue
            if key == "$defs":
                continue
            # Claude Code 2.1.x silently refuses to inject the
            # StructuredOutput tool when the schema carries any `x-*`
            # extension keyword (empirically verified against 2.1.76 with
            # `x-agent-file-path`). Same failure class as `discriminator`:
            # `result.subtype == "success"` but no `structured_output`.
            # Client-side consumers of extensions (e.g. AgentFilePath
            # verification) read them from `model.model_json_schema()`
            # directly, not from this sanitized copy.
            if isinstance(key, str) and key.startswith("x-"):
                continue
            result[key] = _inline(value, defs)
        return result
    if isinstance(node, list):
        return [_inline(item, defs) for item in node]
    return node


def to_claude_code_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic model's JSON schema into a Claude-Code-compatible form.

    Transforms:
        - Inlines all $defs/$ref references (Claude Code cannot resolve them)
        - Strips the OpenAPI `discriminator` keyword (causes silent schema disable)
        - Strips all `x-*` JSON Schema extension keywords (same silent-disable
          failure on Claude Code 2.1.x; `x-agent-file-path` was the smoking gun)

    The returned dict is a standalone JSON Schema document ready to pass to
    `claude --json-schema`.
    """
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    return _inline(raw, defs)
