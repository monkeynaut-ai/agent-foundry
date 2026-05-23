"""App-side registration of AICalls exposed to Agent Foundry's eval system.

Lab stand-in for the equivalent module a real application would ship
(e.g., ``archipelago.evals.registration``). Instantiates an
``AICallRegistry`` and registers each AICall the lab wants to expose
as an evaluation target.
"""

from lab.eval_tests.ai_call.design_review import design_review

from agent_foundry.evals.registry import AICallRegistry

EVAL_REGISTRY = AICallRegistry()
EVAL_REGISTRY.register("design_review", design_review)
