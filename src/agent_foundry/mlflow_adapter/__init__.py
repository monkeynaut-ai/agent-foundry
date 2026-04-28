"""MLflow adapter for Agent Foundry telemetry.

Translates AF's ``agent_foundry.*`` span attributes additively to MLflow's
``mlflow.*`` namespace, and binds MLflow Run lifecycle to ``RunContext``
open/close hooks.

Optional install — requires the ``[mlflow]`` extra:

    pip install agent-foundry[mlflow]
"""

from __future__ import annotations

# Import-guard (raises actionable ImportError if mlflow isn't installed).
from agent_foundry.mlflow_adapter import extras  # noqa: F401

__all__: list[str] = []
