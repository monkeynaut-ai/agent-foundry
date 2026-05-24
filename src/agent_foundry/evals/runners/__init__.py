"""Execution backends for the eval system.

Each module in this package is one runner implementation. They are the
only places allowed to import a third-party eval library — an
``import-linter`` contract enforces this.

Callers do not statically import backends from this package. Instead,
they resolve a runner at startup via
:func:`agent_foundry.evals.runner_loader.load_runner`, which takes a
``module:Class`` spec and instantiates the backend dynamically. That
indirection is what lets us add new backends here without changing
any caller, and what keeps the rest of agent-foundry free of static
references to a specific backend.
"""
