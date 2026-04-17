"""Tests for Agent Container Protocol error types."""

from agent_foundry.agents.errors import (
    AdapterError,
    ContainerCreationError,
    ContainerLifecycleError,
    ProtocolError,
    SessionError,
)


class TestContainerCreationError:
    def test_given_container_creation_error_when_constructed_with_image_then_image_attribute_stored(
        self,
    ):
        err = ContainerCreationError("pull failed", image="my-image:latest")
        assert err.image == "my-image:latest"
        assert "pull failed" in str(err)

    def test_given_container_creation_error_when_constructed_without_image_then_image_is_none(
        self,
    ):
        err = ContainerCreationError("generic failure")
        assert err.image is None


class TestContainerLifecycleError:
    def test_given_container_lifecycle_error_when_constructed_with_container_id_then_container_id_attribute_stored(
        self,
    ):
        err = ContainerLifecycleError("stop failed", container_id="abc123")
        assert err.container_id == "abc123"
        assert "stop failed" in str(err)

    def test_given_container_lifecycle_error_when_constructed_without_container_id_then_container_id_is_none(
        self,
    ):
        err = ContainerLifecycleError("generic failure")
        assert err.container_id is None


class TestSessionError:
    def test_given_session_error_when_constructed_with_container_id_then_container_id_attribute_stored(
        self,
    ):
        err = SessionError("exec failed", container_id="def456")
        assert err.container_id == "def456"
        assert "exec failed" in str(err)


class TestAdapterError:
    def test_given_adapter_error_when_constructed_with_message_then_message_preserved(
        self,
    ):
        err = AdapterError("connection lost")
        assert "connection lost" in str(err)
        assert isinstance(err, Exception)


class TestProtocolError:
    def test_given_protocol_error_when_constructed_with_message_then_message_preserved(
        self,
    ):
        err = ProtocolError("invalid JSON")
        assert "invalid JSON" in str(err)
        assert isinstance(err, Exception)


class TestErrorHierarchy:
    def test_given_all_error_types_when_checked_then_all_are_exception_subclasses(
        self,
    ):
        error_types = [
            ContainerCreationError,
            ContainerLifecycleError,
            SessionError,
            AdapterError,
            ProtocolError,
        ]
        for cls in error_types:
            assert issubclass(cls, Exception)
