"""Canonical artifact models for the Archipelago pipeline."""

from typing import Any

from pydantic import BaseModel


class ProductBrief(BaseModel):
    name: str
    problem_statement: str
    target_personas: list[str]
    success_metrics: list[str]
    constraints: list[str] = []


class FeatureArchitecture(BaseModel):
    feature_name: str
    components: list[str]
    data_flow: str
    technology_choices: list[str]
    risks: list[str] = []


class FeatureSpec(BaseModel):
    title: str
    objective: str
    acceptance_criteria: list[str]
    pr_slices: list[dict[str, Any]]


class TestPlan(BaseModel):
    __test__ = False

    feature_name: str
    test_cases: list[dict[str, Any]]
    coverage_targets: list[str]


class CodePatch(BaseModel):
    feature_name: str
    files_changed: list[str]
    diff_summary: str
    branch_name: str


class TestResults(BaseModel):
    __test__ = False

    feature_name: str
    tests_passed: int
    tests_failed: int
    test_output: str
    all_green: bool
