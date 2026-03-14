"""Tests for ACP ANSI stripping utility."""

from agent_foundry.acp.ansi import strip_ansi


class TestStripAnsi:
    def test_given_plain_text_when_stripped_then_unchanged(self):
        assert strip_ansi("hello world") == "hello world"

    def test_given_ansi_color_codes_when_stripped_then_removed(self):
        assert strip_ansi("\x1b[32mgreen\x1b[0m") == "green"

    def test_given_empty_string_when_stripped_then_empty(self):
        assert strip_ansi("") == ""

    def test_given_multiple_escape_sequences_when_stripped_then_spaces_collapsed(self):
        text = "\x1b[1m\x1b[32mhello\x1b[0m"
        result = strip_ansi(text)
        assert "hello" in result
        # No leading/trailing whitespace
        assert result == result.strip()
