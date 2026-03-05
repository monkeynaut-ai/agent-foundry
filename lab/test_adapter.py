"""Tests for PTY adapter using cat/echo as mock subprocesses."""

import pexpect


class TestPtySpawn:
    """Given a command, when spawned via pexpect, then the child process is alive."""

    def test_given_command_when_spawned_then_child_process_alive(self):
        child = pexpect.spawn("cat", encoding="utf-8", timeout=5)
        try:
            assert child.isalive()
        finally:
            child.terminate()
            child.wait()


class TestPtyEcho:
    """Given input sent to a PTY child, when read back, then it matches."""

    def test_given_input_when_sent_then_echoed_back(self):
        child = pexpect.spawn("cat", encoding="utf-8", timeout=5)
        try:
            child.sendline("hello world")
            child.expect("hello world", timeout=5)
        finally:
            child.terminate()
            child.wait()


class TestPtyEof:
    """Given EOF on stdin, when sent to child, then child exits cleanly."""

    def test_given_eof_when_stdin_closes_then_child_exits(self):
        child = pexpect.spawn("cat", encoding="utf-8", timeout=5)
        child.sendeof()
        child.expect(pexpect.EOF, timeout=5)
        child.wait()
        assert not child.isalive()


class TestPtyCr:
    """Given an interactive command, when CR is sent, then submit works."""

    def test_given_interactive_command_when_cr_sent_then_submit_works(self):
        child = pexpect.spawn("cat", encoding="utf-8", timeout=5)
        try:
            child.send("test line\r")
            child.expect("test line", timeout=5)
        finally:
            child.terminate()
            child.wait()
