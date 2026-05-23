"""Session-level guards for the main test suite.

Tests under ``tests/`` must run without loading heavyweight
eval-framework dependencies (e.g. ``pydantic_evals``). Tests that need
those dependencies live under ``tests-evals/`` and run via
``pdm test-evals``.

Two checks enforce the separation:

1. A ``sys.modules`` snapshot at conftest load time — if
   ``pydantic_evals`` is already present (e.g. a pytest plugin loaded
   it before conftest ran), raise immediately so the silent breach is
   visible.
2. A ``sys.meta_path`` finder installed at conftest load time that
   raises ``ImportError`` on any subsequent attempt to import
   ``pydantic_evals`` in this worker — directly or transitively, at
   collection time or during test execution. The ImportError fires
   inside the test stack and surfaces as a normal test failure
   (propagates cleanly under xdist).
"""

from __future__ import annotations

import sys
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec


class _PydanticEvalsBlocker(MetaPathFinder):
    """Prevent ``pydantic_evals`` from loading in this worker process."""

    def find_spec(
        self,
        name: str,
        path: object | None = None,
        target: object | None = None,
    ) -> ModuleSpec | None:
        if name == "pydantic_evals" or name.startswith("pydantic_evals."):
            raise ImportError(
                f"Test under tests/ attempted to import {name!r}. "
                "Tests under tests/ must not load pydantic_evals — "
                "move this test to tests-evals/."
            )
        return None


# Fail loud if something already loaded pydantic_evals before this hook
# was installed (e.g., a pytest plugin); the finder can only block
# imports that happen after it is in place.
if "pydantic_evals" in sys.modules:
    raise RuntimeError(
        "pydantic_evals was already in sys.modules when tests/ conftest "
        "loaded; the blocker installed too late to be effective."
    )

sys.meta_path.insert(0, _PydanticEvalsBlocker())
