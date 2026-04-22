"""Public API contract for archetype.templating."""

from __future__ import annotations

import archetype.templating as templating_pkg


class TestPublicExports:
    """The public surface matches __all__ exactly."""

    def test_all_exports_are_importable(self):
        for name in templating_pkg.__all__:
            assert hasattr(templating_pkg, name), (
                f"archetype.templating.__all__ lists {name!r} but it is not exported."
            )

    def test_expected_names_present(self):
        expected = {"build_environment", "resolve"}
        assert set(templating_pkg.__all__) == expected
