"""Check local Markdown links.

This intentionally small checker validates repository-local links in Markdown
files and ignores external URLs, mailto links, and same-page anchors.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
IGNORE_PREFIXES = (
    "http://",
    "https://",
    "mailto:",
    "app://",
    "plugin://",
)


def _iter_markdown_files() -> list[Path]:
    ignored_parts = {".git", ".venv", "__pycache__", ".pytest_cache"}
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not ignored_parts.intersection(path.relative_to(ROOT).parts)
    )


def _extract_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    elif " " in target:
        target = target.split(" ", 1)[0]
    return unquote(target)


def _is_external_or_anchor(target: str) -> bool:
    return (
        not target
        or target.startswith("#")
        or target.startswith(IGNORE_PREFIXES)
        or "://" in target
    )


def _target_exists(source: Path, target: str) -> bool:
    path_part = target.split("#", 1)[0]
    if not path_part:
        return True
    candidate = Path(path_part)
    if candidate.is_absolute():
        return candidate.exists()
    return (source.parent / candidate).resolve().exists()


def main() -> int:
    failures: list[str] = []
    for source in _iter_markdown_files():
        text = source.read_text(encoding="utf-8")
        text = FENCED_CODE_RE.sub("", text)
        text = INLINE_CODE_RE.sub("", text)
        for match in LINK_RE.finditer(text):
            target = _extract_target(match.group(1))
            if _is_external_or_anchor(target):
                continue
            if not _target_exists(source, target):
                rel = source.relative_to(ROOT)
                failures.append(f"{rel}: broken link: {target}")

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
