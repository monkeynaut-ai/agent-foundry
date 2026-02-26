"""Evaluation gates: validators that block final output on failure."""

from typing import Any

import jsonschema

FF_EVAL_GATES = True
FF_DOMAIN_GATES = False


def schema_validator_gate(data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Validate data against a JSON schema.

    Returns:
        Dict with 'valid' bool and 'errors' list.
    """
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(data))
    return {
        "valid": len(errors) == 0,
        "errors": [{"message": e.message, "path": list(e.absolute_path)} for e in errors],
    }


def citation_validator_gate(
    evidence_ids: list[str],
    retrieved_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate that all cited evidence IDs exist in retrieved evidence.

    Returns:
        Dict with 'valid' bool and 'missing_ids' list.
    """
    available_ids = {e.get("id", "") for e in retrieved_evidence}
    missing = [eid for eid in evidence_ids if eid not in available_ids]
    return {
        "valid": len(missing) == 0,
        "missing_ids": missing,
    }


def uncertainty_completeness_gate(
    uncertainty: dict[str, Any],
) -> dict[str, Any]:
    """Validate uncertainty fields: confidence in [0,1] and rationale present.

    Returns:
        Dict with 'valid' bool and 'missing_fields' list.
    """
    missing_fields = []
    confidence = uncertainty.get("confidence")
    rationale = uncertainty.get("rationale")

    if confidence is None:
        missing_fields.append("confidence")
    elif not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
        missing_fields.append("confidence (must be in [0, 1])")

    if not rationale:
        missing_fields.append("rationale")

    return {
        "valid": len(missing_fields) == 0,
        "missing_fields": missing_fields,
    }


def evidence_first_gate(
    retrieved_evidence: list[dict[str, Any]],
    recommendation: dict[str, Any],
) -> dict[str, Any]:
    """Enforce evidence-first policy.

    If no evidence, return insufficient_evidence outcome.
    Recommendation must list assumptions explicitly.

    Returns:
        Dict with 'valid' bool and 'outcome' string.
    """
    if not retrieved_evidence:
        return {
            "valid": False,
            "outcome": "insufficient_evidence",
        }

    assumptions = recommendation.get("assumptions")
    if not assumptions:
        return {
            "valid": False,
            "outcome": "missing_assumptions",
        }

    return {
        "valid": True,
        "outcome": "recommendation_valid",
    }
