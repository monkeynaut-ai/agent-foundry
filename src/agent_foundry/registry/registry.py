"""Role registry: loads and indexes role specs from a directory."""

import importlib.resources
from pathlib import Path

from agent_foundry.registry.errors import DuplicateRoleError
from agent_foundry.registry.spec import RoleSpec, load_role_spec

SPEC_EXTENSIONS = {".yaml", ".yml", ".json"}
BUILTIN_SPECS_PACKAGE = "agent_foundry.roles"


def _load_builtin_specs() -> dict[str, RoleSpec]:
    """Load built-in specs from agent_foundry.roles package data."""
    specs: dict[str, RoleSpec] = {}
    files = importlib.resources.files(BUILTIN_SPECS_PACKAGE)
    for item in sorted(files.iterdir(), key=lambda f: f.name):
        if not any(str(item.name).endswith(ext) for ext in SPEC_EXTENSIONS):
            continue
        with importlib.resources.as_file(item) as path:
            spec = load_role_spec(path)
            specs[spec.name] = spec
    return specs


def _load_directory_specs(directory: Path) -> dict[str, RoleSpec]:
    """Load specs from a directory, detecting duplicates within that directory."""
    directory = Path(directory)
    specs: dict[str, RoleSpec] = {}
    seen_paths: dict[str, list[Path]] = {}

    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in SPEC_EXTENSIONS:
            continue
        spec = load_role_spec(path)
        if spec.name in seen_paths:
            seen_paths[spec.name].append(path)
        else:
            seen_paths[spec.name] = [path]
            specs[spec.name] = spec

    for name, paths in seen_paths.items():
        if len(paths) > 1:
            raise DuplicateRoleError(
                message=(
                    f"Duplicate role name '{name}' found in:"
                    f" {', '.join(str(p) for p in paths)}"
                ),
                role_name=name,
                file_paths=paths,
            )

    return specs


class RoleRegistry:
    """In-memory catalog of role specs, loaded from a directory."""

    def __init__(self, specs: dict[str, RoleSpec]):
        self._specs = specs

    @classmethod
    def with_builtins(cls) -> "RoleRegistry":
        """Create a registry pre-loaded with Agent Foundry's built-in specs."""
        return cls(_load_builtin_specs())

    @classmethod
    def with_product_specs(cls, product_specs_dir: Path) -> "RoleRegistry":
        """Create a registry with builtins + product-specific specs.

        Args:
            product_specs_dir: Directory containing the product's role
                spec files (YAML/JSON).

        Returns:
            A registry containing both built-in and product specs.

        Raises:
            DuplicateRoleError: If a product spec collides with a
                builtin name.
        """
        builtin_specs = _load_builtin_specs()
        product_specs = _load_directory_specs(product_specs_dir)

        for name in product_specs:
            if name in builtin_specs:
                raise DuplicateRoleError(
                    message=f"Product spec '{name}' collides with built-in spec",
                    role_name=name,
                    file_paths=[],
                )

        return cls({**builtin_specs, **product_specs})

    @classmethod
    def from_directory(cls, directory: Path) -> "RoleRegistry":
        """Load specs from a single directory (no auto-loading of builtins)."""
        return cls(_load_directory_specs(directory))

    def get(self, name: str) -> RoleSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return list(self._specs.keys())

    def search(self, tags: list[str]) -> list[RoleSpec]:
        """Search for roles matching all given tags, sorted by name."""
        tag_set = set(tags)
        matches = [spec for spec in self._specs.values() if tag_set.issubset(set(spec.tags))]
        return sorted(matches, key=lambda s: s.name)

    def __len__(self) -> int:
        return len(self._specs)
