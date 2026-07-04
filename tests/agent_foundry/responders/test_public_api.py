"""Public-API export guarantees for responders."""

import agent_foundry
import agent_foundry.responders as responders


def test_top_level_exports_basic_responder_helpers():
    from agent_foundry import Responder, ResponderProvider, StdinResponder, static_provider

    expected = {
        "Responder",
        "ResponderProvider",
        "StdinResponder",
        "static_provider",
    }

    assert expected <= set(agent_foundry.__all__)
    assert agent_foundry.Responder is Responder
    assert agent_foundry.ResponderProvider is ResponderProvider
    assert agent_foundry.StdinResponder is StdinResponder
    assert agent_foundry.static_provider is static_provider


def test_responder_request_models_are_publicly_exported_from_subpackage():
    from agent_foundry.responders import (
        ClarificationRequest,
        PermissionRequest,
        ResponderContext,
        ResponderKind,
        ResponderRequest,
        ResponderResponse,
        build_request_from_outcome,
    )

    expected = {
        "ClarificationRequest",
        "PermissionRequest",
        "ResponderContext",
        "ResponderKind",
        "ResponderRequest",
        "ResponderResponse",
        "build_request_from_outcome",
    }

    assert expected <= set(responders.__all__)
    assert responders.ClarificationRequest is ClarificationRequest
    assert responders.PermissionRequest is PermissionRequest
    assert responders.ResponderContext is ResponderContext
    assert responders.ResponderKind is ResponderKind
    assert responders.ResponderRequest is ResponderRequest
    assert responders.ResponderResponse is ResponderResponse
    assert responders.build_request_from_outcome is build_request_from_outcome
