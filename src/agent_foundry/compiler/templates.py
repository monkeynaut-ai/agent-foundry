"""Template library for expanding named patterns into subgraph node definitions."""

_TEMPLATES: dict[str, list[dict]] = {
    "draft_review_revise_loop": [
        {"id": "draft", "capability": "structured_output_pydantic", "config": {}},
        {"id": "review", "capability": "schema_validator", "config": {}},
        {"id": "revise", "capability": "structured_output_pydantic", "config": {"role": "reviser"}},
    ],
    "gather_verify_analyze_recommend": [
        {"id": "gather", "capability": "rag_retriever", "config": {}},
        {"id": "verify", "capability": "citation_validator", "config": {}},
        {
            "id": "analyze",
            "capability": "structured_output_pydantic",
            "config": {"role": "analyzer"},
        },
        {"id": "recommend", "capability": "evidence_first_contract", "config": {}},
    ],
    "plan_execute_test_fix_retest": [
        {"id": "plan", "capability": "structured_output_pydantic", "config": {"role": "planner"}},
        {"id": "execute", "capability": "tool_calling", "config": {}},
        {"id": "test", "capability": "schema_validator", "config": {}},
        {"id": "fix", "capability": "structured_output_pydantic", "config": {"role": "fixer"}},
        {"id": "retest", "capability": "schema_validator", "config": {"role": "retester"}},
    ],
}


def expand_template(template_name: str) -> list[dict]:
    """Expand a named template into a list of node definitions.

    Args:
        template_name: The template identifier.

    Returns:
        List of node definition dicts.

    Raises:
        ValueError: If the template is not found.
    """
    if template_name not in _TEMPLATES:
        raise ValueError(f"Unknown template: {template_name}")
    # Return deep copy to prevent mutation
    import copy

    return copy.deepcopy(_TEMPLATES[template_name])
