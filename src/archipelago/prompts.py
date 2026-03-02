"""Prompt templates for each Archipelago pipeline stage."""

STRATEGY_PROMPT = """You are a product strategist. Given the following high-level product idea, \
produce a structured product brief.

Product idea: {product_brief_input}

Return a JSON object with these fields:
- name: A concise product name
- problem_statement: The core problem being solved
- target_personas: A list of target user personas
- success_metrics: A list of measurable success criteria
- constraints: A list of known constraints (can be empty)
"""

ARCHITECTURE_PROMPT = """You are a software architect. Given the following product brief, \
design a feature architecture.

Product Brief:
- Name: {name}
- Problem: {problem_statement}
- Personas: {target_personas}
- Success Metrics: {success_metrics}
- Constraints: {constraints}

Return a JSON object with these fields:
- feature_name: The name of the feature being architected
- components: A list of system components
- data_flow: A description of how data flows through the system
- technology_choices: A list of chosen technologies
- risks: A list of identified risks (can be empty)
"""

SPEC_PROMPT = """You are a technical specification writer. Given the following feature \
architecture, produce a feature specification and test plan.

Architecture:
- Feature: {feature_name}
- Components: {components}
- Data Flow: {data_flow}
- Technologies: {technology_choices}
- Risks: {risks}

Return a JSON object with two top-level keys:
1. "feature_spec" with fields: title, objective, acceptance_criteria (list of strings), \
pr_slices (list of objects with title and commits keys)
2. "test_plan" with fields: feature_name, test_cases (list of objects with name and type keys), \
coverage_targets (list of strings)
"""

DEV_TEST_PROMPT = """You are a TDD developer. Given the following feature spec and test plan, \
implement the feature and run the tests.

Feature Spec:
- Title: {feature_spec_title}
- Objective: {feature_spec_objective}
- Acceptance Criteria: {feature_spec_acceptance_criteria}

Test Plan:
- Feature: {test_plan_feature_name}
- Test Cases: {test_plan_test_cases}
- Coverage Targets: {test_plan_coverage_targets}

Return a JSON object with two top-level keys:
1. "code_patch" with fields: feature_name, files_changed (list of file paths), \
diff_summary, branch_name
2. "test_results" with fields: feature_name, tests_passed (int), tests_failed (int), \
test_output, all_green (boolean)
"""
