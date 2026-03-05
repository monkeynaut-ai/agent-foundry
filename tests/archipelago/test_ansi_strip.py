"""ANSI escape code stripping — unit tests."""

from archipelago.docker_worker.ansi import strip_ansi


class TestStripAnsi:
    def test_given_sgr_color_codes_when_stripped_then_text_preserved(self):
        assert strip_ansi("\033[32mPASSED\033[0m") == "PASSED"

    def test_given_cursor_movement_codes_when_stripped_then_text_preserved(self):
        assert strip_ansi("\033[2Ahello\033[1B") == "hello"

    def test_given_no_ansi_codes_when_stripped_then_text_unchanged(self):
        assert strip_ansi("plain text") == "plain text"

    def test_given_empty_string_when_stripped_then_returns_empty(self):
        assert strip_ansi("") == ""

    def test_given_mixed_ansi_and_text_when_stripped_then_only_text_remains(self):
        assert strip_ansi("\033[1;31mERROR\033[0m: \033[33mfile.py\033[0m") == "ERROR: file.py"

    def test_given_osc_title_sequence_when_stripped_then_removed(self):
        assert strip_ansi("\033]0;My Title\x07some text") == "some text"
