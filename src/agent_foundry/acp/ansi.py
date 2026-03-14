"""ANSI escape code stripping utility."""

import re

_ANSI_ESCAPE = re.compile(r"\x1b\[[\x20-\x3f]*[0-9;]*[\x40-\x7e]|\x1b\].*?\x07|\x1b\(B")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences, preserving spacing from cursor movement.

    Replaces each sequence with a space (cursor-positioning escapes provide
    spacing in Ink TUIs), then collapses runs of whitespace.
    """
    spaced = _ANSI_ESCAPE.sub(" ", text)
    return re.sub(r"  +", " ", spaced).strip()
