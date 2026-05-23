"""Execution backends for the eval system.

Each module in this package is one runner implementation. They are the
only places allowed to import a third-party eval library — an
``import-linter`` contract enforces this.

Concrete backends are exposed by direct import from their module
(e.g. ``from agent_foundry.evals.runners.pydantic_evals import
PydanticEvalsRunner``); this package does not re-export them, so
adding a new backend doesn't change this file.
"""
