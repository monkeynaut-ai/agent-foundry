"""ANSI escape code stripping utility."""

import re

_ANSI_ESCAPE = re.compile(r"\x1b\[[\x20-\x3f]*[0-9;]*[\x40-\x7e]|\x1b\].*?\x07|\x1b\(B")


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from text."""
    return _ANSI_ESCAPE.sub("", text)
