"""Docker worker recovery — workspace persistence and session restore tests."""

import json
from unittest.mock import MagicMock

from archipelago.docker_worker.container import ContainerHandle, ContainerManager
from archipelago.docker_worker.models import ResumePoint
from archipelago.docker_worker.recovery import (
    persist_workspace_state,
    recover_session,
)
from archipelago.docker_worker.session import SessionHandle, SessionManager


class TestPersistWorkspaceState:
    def test_given_workspace_with_git_repo_when_persisted_then_snapshot_contains_commit_sha(
        self, tmp_path
    ):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        output = tmp_path / "output"

        def git_runner(cmd, *args, cwd=None):
            if cmd == "rev-parse":
                return "abc123def"
            return ""

        snapshot = persist_workspace_state(workspace, output, git_runner=git_runner)
        assert snapshot.commit_sha == "abc123def"

    def test_given_workspace_with_uncommitted_changes_when_persisted_then_diff_captured(
        self, tmp_path
    ):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        output = tmp_path / "output"

        def git_runner(cmd, *args, cwd=None):
            if cmd == "rev-parse":
                return "abc123"
            if cmd == "diff":
                return "+added line\n-removed line"
            return ""

        snapshot = persist_workspace_state(workspace, output, git_runner=git_runner)
        assert "+added line" in snapshot.working_tree_diff

    def test_given_workspace_with_progress_file_when_persisted_then_events_included(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        output = tmp_path / "output"

        event = {
            "type": "commit_green",
            "pr_id": "pr1",
            "commit_id": "c1",
            "status": "ok",
            "timestamp": 1.0,
        }
        (workspace / "progress.jsonl").write_text(json.dumps(event))

        def git_runner(cmd, *args, cwd=None):
            return "abc"

        snapshot = persist_workspace_state(workspace, output, git_runner=git_runner)
        assert len(snapshot.progress_events) == 1
        assert snapshot.progress_events[0].pr_id == "pr1"

    def test_given_container_when_persist_called_then_git_state_read_via_exec(self, tmp_path):
        output = tmp_path / "output"

        container_mgr = MagicMock(spec=ContainerManager)
        container_handle = ContainerHandle(container_id="c1", workspace_path="/workspace")
        container_handle._container = MagicMock()
        container_handle._container.exec_run.side_effect = [
            (0, b"abc123def\n"),  # git rev-parse HEAD
            (0, b"+added line\n"),  # git diff
        ]
        container_mgr.read_file_from_container.return_value = None  # no progress file

        snapshot = persist_workspace_state(
            workspace_path=None,
            output_path=output,
            container_mgr=container_mgr,
            container_handle=container_handle,
        )
        assert snapshot.commit_sha == "abc123def"
        assert "+added line" in snapshot.working_tree_diff
        assert container_handle._container.exec_run.call_count == 2

    def test_given_container_when_persist_called_then_progress_read_via_api(self, tmp_path):
        output = tmp_path / "output"

        container_mgr = MagicMock(spec=ContainerManager)
        container_handle = ContainerHandle(container_id="c1", workspace_path="/workspace")
        container_handle._container = MagicMock()
        container_handle._container.exec_run.side_effect = [
            (0, b"abc123\n"),
            (0, b""),
        ]
        progress_line = (
            '{"type":"commit_green","pr_id":"pr1","commit_id":"c1","status":"ok","timestamp":1.0}'
        )
        container_mgr.read_file_from_container.return_value = progress_line
        container_mgr.copy_from_container.return_value = True

        snapshot = persist_workspace_state(
            workspace_path=None,
            output_path=output,
            container_mgr=container_mgr,
            container_handle=container_handle,
        )
        assert len(snapshot.progress_events) == 1
        assert snapshot.progress_events[0].pr_id == "pr1"


class TestRecoverSession:
    def test_given_crashed_session_when_recovered_then_fresh_container_created(self):
        container_mgr = MagicMock(spec=ContainerManager)
        session_mgr = MagicMock(spec=SessionManager)

        mock_handle = ContainerHandle(container_id="new-c", status="created")
        container_mgr.create_container.return_value = mock_handle
        session_mgr.launch_session.return_value = SessionHandle(exec_id="e1", container_id="new-c")

        _container, _session = recover_session(
            container_mgr, session_mgr, "vol-1", {"title": "test"}
        )
        container_mgr.create_container.assert_called_once()
        container_mgr.start.assert_called_once()

    def test_given_crashed_session_when_recovered_then_workspace_volume_remounted(self):
        container_mgr = MagicMock(spec=ContainerManager)
        session_mgr = MagicMock(spec=SessionManager)

        mock_handle = ContainerHandle(container_id="new-c", status="created")
        container_mgr.create_container.return_value = mock_handle
        session_mgr.launch_session.return_value = SessionHandle(exec_id="e1", container_id="new-c")

        recover_session(container_mgr, session_mgr, "vol-workspace", {"title": "test"})
        call_kwargs = container_mgr.create_container.call_args
        assert call_kwargs.kwargs["workspace_volume"] == "vol-workspace"

    def test_given_crashed_session_when_recovered_then_cc_launched_with_resume_context(
        self,
    ):
        container_mgr = MagicMock(spec=ContainerManager)
        session_mgr = MagicMock(spec=SessionManager)

        mock_handle = ContainerHandle(container_id="new-c", status="created")
        container_mgr.create_container.return_value = mock_handle
        session_mgr.launch_session.return_value = SessionHandle(exec_id="e1", container_id="new-c")

        recover_session(container_mgr, session_mgr, "vol-1", {"title": "test"})
        session_mgr.launch_session.assert_called_once()

    def test_given_feature_spec_when_recovered_then_spec_written_inside_container(self):
        container_mgr = MagicMock(spec=ContainerManager)
        session_mgr = MagicMock(spec=SessionManager)

        mock_handle = ContainerHandle(
            container_id="new-c", status="created", workspace_path="/workspace"
        )
        container_mgr.create_container.return_value = mock_handle
        session_mgr.launch_session.return_value = SessionHandle(exec_id="e1", container_id="new-c")

        recover_session(container_mgr, session_mgr, "vol-1", {"title": "test-spec"})
        container_mgr.write_file_to_container.assert_called_once()
        call_args = container_mgr.write_file_to_container.call_args
        assert call_args.args[1] == "/workspace/feature_spec.json"
        assert "test-spec" in call_args.args[2]

    def test_given_resume_point_at_pr2_c1_when_recovered_then_cc_starts_from_pr2_c1(
        self,
    ):
        container_mgr = MagicMock(spec=ContainerManager)
        session_mgr = MagicMock(spec=SessionManager)

        mock_handle = ContainerHandle(container_id="new-c", status="created")
        container_mgr.create_container.return_value = mock_handle
        session_mgr.launch_session.return_value = SessionHandle(exec_id="e1", container_id="new-c")

        resume_point = ResumePoint(pr_id="pr2", commit_id="c1", status="blocked")
        recover_session(
            container_mgr,
            session_mgr,
            "vol-1",
            {"title": "test"},
            last_checkpoint=resume_point,
        )

        call_args = session_mgr.launch_session.call_args
        command = call_args.args[1]
        assert "pr2/c1" in command
