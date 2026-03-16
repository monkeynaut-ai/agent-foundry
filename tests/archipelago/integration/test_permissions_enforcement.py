"""Integration tests for ACP permissions enforcement.

These tests exercise the real acp-cc-worker:latest Docker image to verify
that each permission enforcement layer works at runtime — not just that
configuration is passed correctly (which unit tests cover).

Requires: Docker daemon + acp-cc-worker:latest image (pdm docker-base).
"""

import json

import pytest

from tests.archipelago.integration.conftest import (
    _CAP_ADD,
    _CAP_DROP,
    run_in_container,
)

pytestmark = pytest.mark.integration


# ── Layer 1a: Filesystem Lockdown — Hidden Dirs ──


class TestFilesystemLockdownHiddenDirs:
    def test_given_hidden_dir_when_lockdown_runs_then_claude_user_cannot_list_dir(
        self, docker_client, worker_image, container_cleanup
    ):
        script = """
            mkdir -p /workspace/secrets
            echo "top-secret" > /workspace/secrets/key.txt
            export ACP_HIDDEN_DIRS=/workspace/secrets
            . /home/claude/lockdown.sh
            gosu claude sh -c 'ls /workspace/secrets 2>&1'
        """
        exit_code, output = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code != 0
        assert "Permission denied" in output or "cannot" in output.lower()

    def test_given_hidden_dir_when_lockdown_runs_then_claude_user_cannot_read_file_inside(
        self, docker_client, worker_image, container_cleanup
    ):
        script = """
            mkdir -p /workspace/secrets
            echo "api-key-12345" > /workspace/secrets/key.txt
            export ACP_HIDDEN_DIRS=/workspace/secrets
            . /home/claude/lockdown.sh
            gosu claude sh -c 'cat /workspace/secrets/key.txt 2>&1'
        """
        exit_code, output = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code != 0
        assert "api-key-12345" not in output

    def test_given_multiple_hidden_dirs_when_lockdown_runs_then_all_dirs_locked(
        self, docker_client, worker_image, container_cleanup
    ):
        script = """
            mkdir -p /workspace/secrets /workspace/.keys
            echo "s1" > /workspace/secrets/a.txt
            echo "s2" > /workspace/.keys/b.txt
            export ACP_HIDDEN_DIRS=/workspace/secrets,/workspace/.keys
            . /home/claude/lockdown.sh
            FAIL=0
            gosu claude sh -c 'ls /workspace/secrets' 2>/dev/null && FAIL=1
            gosu claude sh -c 'ls /workspace/.keys' 2>/dev/null && FAIL=1
            exit $FAIL
        """
        exit_code, _ = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code == 0

    def test_given_nonexistent_hidden_dir_when_lockdown_runs_then_no_error(
        self, docker_client, worker_image, container_cleanup
    ):
        script = """
            export ACP_HIDDEN_DIRS=/workspace/does-not-exist
            . /home/claude/lockdown.sh
            echo "OK"
        """
        exit_code, output = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code == 0
        assert "OK" in output

    def test_given_unlocked_dir_when_lockdown_runs_then_claude_user_can_read_and_write(
        self, docker_client, worker_image, container_cleanup
    ):
        script = """
            mkdir -p /workspace/secrets /workspace/open
            echo "visible" > /workspace/open/data.txt
            chown -R claude:claude /workspace/open
            export ACP_HIDDEN_DIRS=/workspace/secrets
            . /home/claude/lockdown.sh
            gosu claude sh -c 'cat /workspace/open/data.txt && touch /workspace/open/new.txt && echo "OK"'
        """
        exit_code, output = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code == 0
        assert "visible" in output
        assert "OK" in output


# ── Layer 1b: Filesystem Lockdown — Readonly Dirs ──


class TestFilesystemLockdownReadonlyDirs:
    def test_given_readonly_dir_when_lockdown_runs_then_claude_user_cannot_create_file(
        self, docker_client, worker_image, container_cleanup
    ):
        script = """
            mkdir -p /workspace/config
            echo "setting: true" > /workspace/config/app.yaml
            chown -R claude:claude /workspace/config
            export ACP_READONLY_DIRS=/workspace/config
            . /home/claude/lockdown.sh
            gosu claude sh -c 'touch /workspace/config/new.txt 2>&1'
        """
        exit_code, output = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code != 0
        assert "Permission denied" in output or "Read-only" in output or "cannot" in output.lower()

    def test_given_readonly_dir_when_lockdown_runs_then_claude_user_can_still_read(
        self, docker_client, worker_image, container_cleanup
    ):
        script = """
            mkdir -p /workspace/config
            echo "setting: true" > /workspace/config/app.yaml
            chown -R claude:claude /workspace/config
            export ACP_READONLY_DIRS=/workspace/config
            . /home/claude/lockdown.sh
            gosu claude sh -c 'cat /workspace/config/app.yaml'
        """
        exit_code, output = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code == 0
        assert "setting: true" in output

    def test_given_unlocked_dir_when_readonly_lockdown_runs_then_claude_user_can_read_and_write(
        self, docker_client, worker_image, container_cleanup
    ):
        script = """
            mkdir -p /workspace/config /workspace/writable
            echo "data" > /workspace/writable/file.txt
            chown -R claude:claude /workspace/writable
            export ACP_READONLY_DIRS=/workspace/config
            . /home/claude/lockdown.sh
            gosu claude sh -c 'cat /workspace/writable/file.txt && touch /workspace/writable/new.txt && echo "OK"'
        """
        exit_code, output = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code == 0
        assert "data" in output
        assert "OK" in output


# ── Layer 2: User Drop via gosu ──


class TestUserDrop:
    def test_given_gosu_drop_when_whoami_then_running_as_claude_user(
        self, docker_client, worker_image, container_cleanup
    ):
        script = "gosu claude whoami"
        exit_code, output = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code == 0
        assert output.strip() == "claude"

    def test_given_lockdown_dirs_when_inspected_then_owned_by_root(
        self, docker_client, worker_image, container_cleanup
    ):
        script = """
            mkdir -p /workspace/secrets
            export ACP_HIDDEN_DIRS=/workspace/secrets
            . /home/claude/lockdown.sh
            stat -c '%U' /workspace/secrets
        """
        exit_code, output = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code == 0
        assert "root" in output


# ── Layer 3: Settings.json Verification ──


class TestSettingsPermissions:
    def _read_settings(self, docker_client, worker_image, container_cleanup) -> dict:
        script = "cat /home/claude/.claude/settings.json"
        exit_code, output = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code == 0
        return json.loads(output)

    def test_given_container_when_settings_read_then_allow_contains_expected_tools(
        self, docker_client, worker_image, container_cleanup
    ):
        settings = self._read_settings(docker_client, worker_image, container_cleanup)
        allow = settings["permissions"]["allow"]
        for tool in ["Bash", "Read", "Edit", "Write", "Glob", "Grep"]:
            assert tool in allow

    def test_given_container_when_settings_read_then_deny_blocks_env_files(
        self, docker_client, worker_image, container_cleanup
    ):
        settings = self._read_settings(docker_client, worker_image, container_cleanup)
        deny = settings["permissions"]["deny"]
        assert "Read(./.env)" in deny
        assert "Read(./.env.*)" in deny
        assert "Read(./secrets/**)" in deny

    def test_given_container_when_settings_read_then_sandbox_enabled(
        self, docker_client, worker_image, container_cleanup
    ):
        settings = self._read_settings(docker_client, worker_image, container_cleanup)
        assert settings["sandbox"]["enabled"] is True


# ── Layer 4: Environment Variable Filtering ──


class TestEnvVarFiltering:
    def _create_container_via_manager(self, docker_client, worker_image, container_cleanup, env):
        """Create a container using ContainerManager's env filtering, then exec commands."""
        from agent_foundry.acp.container import ContainerManager

        mgr = ContainerManager(docker_client, default_image=worker_image)
        filtered_env = {k: v for k, v in env.items() if k in mgr._env_allowlist}

        container = docker_client.containers.create(
            worker_image,
            entrypoint="sh",
            command=["-c", "sleep 30"],
            cap_drop=_CAP_DROP,
            cap_add=_CAP_ADD,
            environment=filtered_env,
        )
        container_cleanup.append(container)
        container.start()
        return container

    def test_given_secret_env_on_host_when_container_manager_filters_then_not_visible_inside(
        self, docker_client, worker_image, container_cleanup
    ):
        env = {
            "DATABASE_PASSWORD": "supersecret",
            "ANTHROPIC_API_KEY": "test-key-abc",
        }
        container = self._create_container_via_manager(
            docker_client, worker_image, container_cleanup, env
        )
        exit_code, _ = container.exec_run("printenv DATABASE_PASSWORD")
        assert exit_code != 0

    def test_given_allowlisted_env_when_container_manager_filters_then_visible_inside(
        self, docker_client, worker_image, container_cleanup
    ):
        env = {
            "DATABASE_PASSWORD": "supersecret",
            "ANTHROPIC_API_KEY": "test-key-abc",
        }
        container = self._create_container_via_manager(
            docker_client, worker_image, container_cleanup, env
        )
        exit_code, output = container.exec_run("printenv ANTHROPIC_API_KEY")
        assert exit_code == 0
        assert output.decode().strip() == "test-key-abc"

    def test_given_extra_env_when_container_created_then_visible_inside(
        self, docker_client, worker_image, container_cleanup
    ):
        script = "printenv CUSTOM_VAR"
        exit_code, output = run_in_container(
            docker_client,
            worker_image,
            script,
            env={"CUSTOM_VAR": "hello"},
            cleanup_list=container_cleanup,
        )
        assert exit_code == 0
        assert output.strip() == "hello"


# ── Layer 5: Linux Capability Dropping ──


class TestCapabilityDropping:
    def test_given_cap_drop_all_when_raw_socket_attempted_then_denied(
        self, docker_client, worker_image, container_cleanup
    ):
        script = (
            'python3 -c "'
            "import socket; "
            "socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)"
            '" 2>&1'
        )
        exit_code, output = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code != 0
        assert "Operation not permitted" in output or "PermissionError" in output

    def test_given_cap_add_setuid_when_gosu_used_then_succeeds(
        self, docker_client, worker_image, container_cleanup
    ):
        script = "gosu claude whoami"
        exit_code, output = run_in_container(
            docker_client, worker_image, script, cleanup_list=container_cleanup
        )
        assert exit_code == 0
        assert output.strip() == "claude"
