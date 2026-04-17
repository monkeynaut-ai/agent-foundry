"""Tests for ACP generic workspace recovery."""

from unittest.mock import MagicMock

from agent_foundry.agents.recovery import WorkspaceSnapshot, capture_workspace_state


class TestWorkspaceSnapshot:
    def test_given_snapshot_when_constructed_then_fields_stored(self):
        snap = WorkspaceSnapshot(
            commit_sha="abc123",
            working_tree_diff="diff --git ...",
            transcript_path="/tmp/transcript.log",
        )
        assert snap.commit_sha == "abc123"
        assert snap.working_tree_diff == "diff --git ..."
        assert snap.transcript_path == "/tmp/transcript.log"

    def test_given_snapshot_without_transcript_then_transcript_is_none(self):
        snap = WorkspaceSnapshot(commit_sha="abc", working_tree_diff="")
        assert snap.transcript_path is None


class TestCaptureWorkspaceStateHost:
    def test_given_workspace_with_git_when_captured_then_sha_and_diff_stored(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        def mock_git_runner(*args, cwd=None):
            if "rev-parse" in args:
                return "deadbeef123"
            if "diff" in args:
                return "diff --git a/file.py ..."
            return ""

        output = tmp_path / "output"
        snap = capture_workspace_state(
            output_path=output,
            workspace_path=workspace,
            git_runner=mock_git_runner,
        )
        assert snap.commit_sha == "deadbeef123"
        assert "diff --git" in snap.working_tree_diff

    def test_given_workspace_with_transcript_when_captured_then_transcript_copied(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "transcript.log").write_text("session log")

        def mock_git_runner(*args, cwd=None):
            return "unknown" if "rev-parse" in args else ""

        output = tmp_path / "output"
        snap = capture_workspace_state(
            output_path=output,
            workspace_path=workspace,
            git_runner=mock_git_runner,
        )
        assert snap.transcript_path is not None
        assert (output / "transcript.log").exists()

    def test_given_workspace_without_transcript_when_captured_then_transcript_none(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        def mock_git_runner(*args, cwd=None):
            return "sha1" if "rev-parse" in args else ""

        output = tmp_path / "output"
        snap = capture_workspace_state(
            output_path=output,
            workspace_path=workspace,
            git_runner=mock_git_runner,
        )
        assert snap.transcript_path is None


class TestCaptureWorkspaceStateContainer:
    def test_given_container_when_captured_then_git_state_from_container(self, tmp_path):
        container_mgr = MagicMock()
        container_handle = MagicMock()
        container_handle.workspace_path = "/workspace"
        container_handle._container.exec_run.side_effect = [
            (0, b"abc123\n"),  # rev-parse HEAD
            (0, b"diff content"),  # git diff
        ]
        container_mgr.copy_from_container.return_value = False  # no transcript

        output = tmp_path / "output"
        snap = capture_workspace_state(
            output_path=output,
            container_mgr=container_mgr,
            container_handle=container_handle,
        )
        assert snap.commit_sha == "abc123"
        assert snap.working_tree_diff == "diff content"

    def test_given_container_with_failed_git_when_captured_then_unknown_sha(self, tmp_path):
        container_mgr = MagicMock()
        container_handle = MagicMock()
        container_handle.workspace_path = "/workspace"
        container_handle._container.exec_run.side_effect = [
            (1, b""),  # rev-parse fails
            (1, b""),  # diff fails
        ]
        container_mgr.copy_from_container.return_value = False

        output = tmp_path / "output"
        snap = capture_workspace_state(
            output_path=output,
            container_mgr=container_mgr,
            container_handle=container_handle,
        )
        assert snap.commit_sha == "unknown"
        assert snap.working_tree_diff == ""
