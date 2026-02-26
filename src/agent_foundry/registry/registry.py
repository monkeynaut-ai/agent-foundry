"""Capability registry: loads and indexes capability specs from a directory."""

from pathlib import Path

from agent_foundry.registry.errors import DuplicateCapabilityError
from agent_foundry.registry.spec import CapabilitySpec, load_capability_spec

SPEC_EXTENSIONS = {".yaml", ".yml", ".json"}


class CapabilityRegistry:
    """In-memory catalog of capability specs, loaded from a directory."""

    def __init__(self, specs: dict[str, CapabilitySpec]):
        self._specs = specs

    @classmethod
    def from_directory(cls, directory: Path) -> "CapabilityRegistry":
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
                    message=f"Duplicate capability name '{name}' found in: {', '.join(str(p) for p in paths)}",
                    capability_name=name,
                    file_paths=paths,
                )

        return cls(specs)

    def get(self, name: str) -> CapabilitySpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return list(self._specs.keys())

    def search(self, tags: list[str]) -> list[CapabilitySpec]:
        """Search for capabilities matching all given tags, sorted by name."""
        tag_set = set(tags)
        matches = [
            spec for spec in self._specs.values()
            if tag_set.issubset(set(spec.tags))
        ]
        return sorted(matches, key=lambda s: s.name)

    def __len__(self) -> int:
        return len(self._specs)
