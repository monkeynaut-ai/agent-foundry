"""Capability registry: loads and indexes capability specs from a directory."""

import importlib.resources
from pathlib import Path

from agent_foundry.registry.errors import DuplicateCapabilityError
from agent_foundry.registry.spec import CapabilitySpec, load_capability_spec

SPEC_EXTENSIONS = {".yaml", ".yml", ".json"}
BUILTIN_SPECS_PACKAGE = "agent_foundry.capabilities"


def _load_builtin_specs() -> dict[str, CapabilitySpec]:
    """Load built-in specs from agent_foundry.capabilities package data."""
    specs: dict[str, CapabilitySpec] = {}
    files = importlib.resources.files(BUILTIN_SPECS_PACKAGE)
    for item in sorted(files.iterdir(), key=lambda f: f.name):
        if not any(str(item.name).endswith(ext) for ext in SPEC_EXTENSIONS):
            continue
        with importlib.resources.as_file(item) as path:
            spec = load_capability_spec(path)
            specs[spec.name] = spec
    return specs


def _load_directory_specs(directory: Path) -> dict[str, CapabilitySpec]:
    """Load specs from a directory, detecting duplicates within that directory."""
    directory = Path(directory)
    specs: dict[str, CapabilitySpec] = {}
    seen_paths: dict[str, list[Path]] = {}

    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in SPEC_EXTENSIONS:
            continue
        spec = load_capability_spec(path)
        if spec.name in seen_paths:
            seen_paths[spec.name].append(path)
        else:
            seen_paths[spec.name] = [path]
            specs[spec.name] = spec

    for name, paths in seen_paths.items():
        if len(paths) > 1:
            raise DuplicateCapabilityError(
                message=(
                    f"Duplicate capability name '{name}' found in:"
                    f" {', '.join(str(p) for p in paths)}"
                ),
                capability_name=name,
                file_paths=paths,
            )

    return specs


class CapabilityRegistry:
    """In-memory catalog of capability specs, loaded from a directory."""

    def __init__(self, specs: dict[str, CapabilitySpec]):
        self._specs = specs

    @classmethod
    def with_builtins(cls) -> "CapabilityRegistry":
        """Create a registry pre-loaded with Agent Foundry's built-in specs."""
        return cls(_load_builtin_specs())

    @classmethod
    def with_product_specs(cls, product_specs_dir: Path) -> "CapabilityRegistry":
        """Create a registry with builtins + product-specific specs.

        Args:
            product_specs_dir: Directory containing the product's capability
                spec files (YAML/JSON).

        Returns:
            A registry containing both built-in and product specs.

        Raises:
            DuplicateCapabilityError: If a product spec collides with a
                builtin name.
        """
        builtin_specs = _load_builtin_specs()
        product_specs = _load_directory_specs(product_specs_dir)

        for name in product_specs:
            if name in builtin_specs:
                raise DuplicateCapabilityError(
                    message=f"Product spec '{name}' collides with built-in spec",
                    capability_name=name,
                    file_paths=[],
                )

        return cls({**builtin_specs, **product_specs})

    @classmethod
    def from_directory(cls, directory: Path) -> "CapabilityRegistry":
        """Load specs from a single directory (no auto-loading of builtins)."""
        return cls(_load_directory_specs(directory))

    def get(self, name: str) -> CapabilitySpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return list(self._specs.keys())

    def search(self, tags: list[str]) -> list[CapabilitySpec]:
        """Search for capabilities matching all given tags, sorted by name."""
        tag_set = set(tags)
        matches = [spec for spec in self._specs.values() if tag_set.issubset(set(spec.tags))]
        return sorted(matches, key=lambda s: s.name)

    def __len__(self) -> int:
        return len(self._specs)
