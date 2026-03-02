"""Interrupt protocol: detect and handle CC clarification/permission requests."""

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from archipelago.docker_worker.models import ClarificationRequest, PermissionRequest
from archipelago.docker_worker.session import SessionHandle, SessionManager

logger = logging.getLogger(__name__)

_INTERRUPT_PATTERN = re.compile(
    r"^ARCHIPELAGO_NEED_(CLARIFICATION|PERMISSION)\s+(\{.*\})$"
)


class InterruptDetector:
    """Scans output lines for interrupt markers and parses them."""

    def __init__(
        self,
        on_clarification: Callable[[ClarificationRequest], None] | None = None,
        on_permission: Callable[[PermissionRequest], None] | None = None,
    ):
        self._on_clarification = on_clarification
        self._on_permission = on_permission

    def scan_line(
        self, line: str
    ) -> ClarificationRequest | PermissionRequest | None:
        """Scan a single line for interrupt markers.

        Returns the parsed request model, or None if no marker found.
        """
        match = _INTERRUPT_PATTERN.match(line.strip())
        if not match:
            return None

        kind = match.group(1)
        payload_str = match.group(2)

        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            logger.warning("Malformed JSON in interrupt marker: %s", line)
            return None

        if kind == "CLARIFICATION":
            try:
                request = ClarificationRequest(**payload)
                if self._on_clarification:
                    self._on_clarification(request)
                return request
            except Exception:
                logger.warning("Invalid ClarificationRequest payload: %s", payload)
                return None
        else:
            try:
                request = PermissionRequest(**payload)
                if self._on_permission:
                    self._on_permission(request)
                return request
            except Exception:
                logger.warning("Invalid PermissionRequest payload: %s", payload)
                return None


class InterruptHandler:
    """Handles detected interrupts by pausing sessions and managing breakpoints."""

    def __init__(
        self,
        session_manager: SessionManager,
        detector: InterruptDetector,
        auto_approve_low_risk: bool = False,
    ):
        self._session_manager = session_manager
        self._detector = detector
        self._auto_approve_low_risk = auto_approve_low_risk

    def handle_interrupt(
        self,
        request: ClarificationRequest | PermissionRequest,
        session_handle: SessionHandle,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle an interrupt, potentially pausing the session.

        Returns updated state dict. If a breakpoint is needed,
        state will contain 'breakpoint_payload'.
        """
        if isinstance(request, ClarificationRequest) and request.blocking:
            self._session_manager.pause(session_handle)
            return {
                **state,
                "breakpoint_payload": {
                    "type": "clarification",
                    "question": request.question,
                    "options": request.options,
                    "default": request.default,
                },
            }

        if isinstance(request, PermissionRequest):
            if request.risk_level == "high":
                self._session_manager.pause(session_handle)
                return {
                    **state,
                    "breakpoint_payload": {
                        "type": "permission",
                        "action": request.action,
                        "risk_level": request.risk_level,
                        "why_needed": request.why_needed,
                    },
                }
            if self._auto_approve_low_risk and request.risk_level == "low":
                self._session_manager.send_input(session_handle, "yes\n")
                return state
            # Medium risk or low without auto-approve
            self._session_manager.pause(session_handle)
            return {
                **state,
                "breakpoint_payload": {
                    "type": "permission",
                    "action": request.action,
                    "risk_level": request.risk_level,
                    "why_needed": request.why_needed,
                },
            }

        return state

    def resume_after_response(
        self, response_text: str, session_handle: SessionHandle
    ) -> None:
        """Send a response and resume the session."""
        self._session_manager.send_input(session_handle, response_text)
        self._session_manager.resume(session_handle)
