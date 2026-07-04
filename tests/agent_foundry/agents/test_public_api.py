"""Public-API export guarantees for containerized-agent contracts."""

import agent_foundry.agents as agents


def test_container_configuration_contracts_are_publicly_exported():
    from agent_foundry.agents import ContainerConfig, NetworkMode

    assert {"ContainerConfig", "NetworkMode"} <= set(agents.__all__)
    assert agents.ContainerConfig is ContainerConfig
    assert agents.NetworkMode is NetworkMode


def test_container_backend_contracts_are_publicly_exported():
    from agent_foundry.agents import (
        ContainerHandleBase,
        ContainerManagerBase,
        ExecResult,
        HealthReport,
        HealthStatus,
    )

    expected = {
        "ContainerHandleBase",
        "ContainerManagerBase",
        "ExecResult",
        "HealthReport",
        "HealthStatus",
    }
    assert expected <= set(agents.__all__)
    assert agents.ContainerHandleBase is ContainerHandleBase
    assert agents.ContainerManagerBase is ContainerManagerBase
    assert agents.ExecResult is ExecResult
    assert agents.HealthReport is HealthReport
    assert agents.HealthStatus is HealthStatus


def test_agent_turn_envelope_contracts_are_publicly_exported():
    from agent_foundry.agents import (
        AgentTurnEnvelope,
        ClarificationOutcome,
        FailureOutcome,
        PermissionOutcome,
        SuccessOutcome,
        TurnOutcomeKind,
    )

    expected = {
        "AgentTurnEnvelope",
        "ClarificationOutcome",
        "FailureOutcome",
        "PermissionOutcome",
        "SuccessOutcome",
        "TurnOutcomeKind",
    }
    assert expected <= set(agents.__all__)
    assert agents.AgentTurnEnvelope is AgentTurnEnvelope
    assert agents.ClarificationOutcome is ClarificationOutcome
    assert agents.FailureOutcome is FailureOutcome
    assert agents.PermissionOutcome is PermissionOutcome
    assert agents.SuccessOutcome is SuccessOutcome
    assert agents.TurnOutcomeKind is TurnOutcomeKind
