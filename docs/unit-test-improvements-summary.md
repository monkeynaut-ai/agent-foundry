# Unit Test Improvements Summary

Date: 2026-02-27
Branch: `improve-unit-tests`

## Scope
This summary covers all unit test changes made in this branch across these commits:
- `cdb9bb4` — tighten assertions, add missing coverage, replace broad exception assertions
- `bb975c3` — refactor duplicated capability spec tests
- `26a03c0` — make benchmark budgets configurable for slower environments

## 1) False-Positive Reduction (Stricter Assertions)
- Tightened conditional branch behavior checks in `tests/test_compiler_advanced.py`:
  - `test_condition_takes_true_branch` now requires `validated == True` and verifies `citations_checked` is not set for that path.
- Tightened Decision Support gate assertions in `tests/test_decision_support_demo.py`:
  - `test_valid_citations_in_demo` now strictly asserts `citations_valid == True` and no `gate_failure`.
  - `test_demo_has_valid_uncertainty` now strictly asserts `uncertainty_valid == True` and no `gate_failure`.
  - `test_demo_passes_evidence_first` now strictly asserts `evidence_valid == True`, `outcome == recommendation_valid`, and no `gate_failure`.

## 2) Typed Error Assertions
- Replaced overly broad `pytest.raises(Exception)` checks with specific `pydantic.ValidationError` checks in `tests/test_plan_tools_breakpoints_versions.py`:
  - Missing persistence `backend` now checks for `ValidationError` with `backend` in message.
  - Missing persistence `thread_id` now checks for `ValidationError` with `thread_id` in message.

## 3) Planner and Compiler Branch Coverage Additions
- Enhanced high-risk planning assertions in `tests/test_planner_retrieval_tools.py`:
  - `test_high_risk_plan_inserts_breakpoint` now expects exact breakpoint `['tools']`.
  - Added `test_high_risk_plan_adds_human_approval_gate_and_version`.
  - Added `test_empty_registry_raises_value_error` to cover minimal-plan empty-registry failure path.
- Strengthened gate enforcement coverage in `tests/test_gate_enforcement.py`:
  - `test_plan_with_gate_passes` now checks runtime output fields, not only graph existence.
  - Added `test_branching_plan_with_gate_bypass_fails` to enforce failure when any branch can bypass eval gates.

## 4) Spec Loader Coverage Gaps Closed
Added parse/contract edge-case tests in `tests/test_capability_spec_errors.py`:
- Unsupported extension (`.txt`) raises `CapabilitySpecParseError`.
- YAML non-object input raises parse error (`Expected a mapping`).
- JSON non-object input raises parse error (`Expected a mapping`).

## 5) Observability Redaction Coverage Added
- Added nested secret redaction test in `tests/test_observability.py`:
  - Verifies nested `authorization` and `token` keys are redacted to `[REDACTED]`.

## 6) New CLI Unit Tests
Added `tests/test_demo_cli.py` with direct CLI behavior checks:
- JSON output mode (`--json`) with argument forwarding verification.
- Human-readable output formatting checks.
- Non-zero exit (`SystemExit(code=1)`) when `gate_failure` is present.

## 7) Test Duplication Reduction
Refactored `tests/test_capability_spec.py`:
- Consolidated repetitive YAML/JSON field-by-field tests into parameterized cases.
- Added shared assertion helper for field validation.
- Preserved round-trip validation coverage (`model_dump` and JSON serialization round-trip).

## 8) Benchmark Stability Improvements
Made benchmark budgets environment-scalable via `AF_BENCHMARK_SLOW_FACTOR` (default `1.0`):
- `tests/test_registry_benchmark.py`
- `tests/test_retriever_benchmark.py`
- `tests/test_decision_support_demo.py` (DS9 benchmark)

This allows CI/hardware-specific tolerance tuning without weakening default local expectations.

## Validation Results
- Full suite: `pdm run pytest`
  - `209 passed, 3 deselected, 0 failed`
- Benchmarks only: `pdm run pytest -m benchmark`
  - `3 passed, 209 deselected, 0 failed`
- Existing warnings observed: SWIG/FAISS deprecation warnings in retriever benchmark/API paths.

## Outcome
The test suite is now stricter against silent regressions, has improved branch/error-path coverage, includes direct CLI and nested-redaction checks, is less duplicated, and benchmark assertions are more portable across environments.
