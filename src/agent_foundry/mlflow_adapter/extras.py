"""Optional-dependency import guard for the MLflow adapter.

Raises a helpful ImportError when the ``[mlflow]`` extra is not installed.
The adapter's other modules import from this file so the error surfaces
uniformly regardless of which entry point the user hit first.
"""

from __future__ import annotations

try:
    import mlflow  # noqa: F401
except ImportError as exc:
    raise ImportError(
        "agent_foundry.mlflow_adapter requires the [mlflow] extra. "
        "Install with: pip install agent-foundry[mlflow]"
    ) from exc
