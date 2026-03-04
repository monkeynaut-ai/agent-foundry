"""Docker worker interrupt protocol — detection, handling, and resume tests."""

from unittest.mock import MagicMock

from archipelago.docker_worker.interrupts import InterruptDetector, InterruptHandler
from archipelago.docker_worker.models import ClarificationRequest, PermissionRequest
from archipelago.docker_worker.session import SessionHandle, SessionManager

# ── Commit 1: InterruptDetector ──


class TestInterruptDetector:
    def test_given_clarification_line_when_scanned_then_returns_clarification_request(
        self,
    ):
        detector = InterruptDetector()
        line = 'ARCHIPELAGO_NEED_CLARIFICATION {"question": "Which DB?", "options": ["pg"], "default": "pg", "blocking": true}'
        result = detector.scan_line(line)
        assert isinstance(result, ClarificationRequest)

    def test_given_permission_line_when_scanned_then_returns_permission_request(self):
        detector = InterruptDetector()
        line = 'ARCHIPELAGO_NEED_PERMISSION {"action": "install lodash", "risk_level": "low", "why_needed": "transforms"}'
        result = detector.scan_line(line)
        assert isinstance(result, PermissionRequest)

    def test_given_normal_output_line_when_scanned_then_returns_none(self):
        detector = InterruptDetector()
        result = detector.scan_line("Running pytest... 5 passed")
        assert result is None

    def test_given_malformed_json_after_marker_when_scanned_then_returns_none(self):
        detector = InterruptDetector()
        result = detector.scan_line("ARCHIPELAGO_NEED_CLARIFICATION {not valid json}")
        assert result is None

    def test_given_clarification_request_when_parsed_then_all_fields_populated(self):
        detector = InterruptDetector()
        line = 'ARCHIPELAGO_NEED_CLARIFICATION {"question": "Which DB?", "options": ["pg", "mysql"], "default": "pg", "blocking": true}'
        result = detector.scan_line(line)
        assert result.question == "Which DB?"
        assert result.options == ["pg", "mysql"]
        assert result.default == "pg"
        assert result.blocking is True

    def test_given_permission_request_when_parsed_then_risk_level_validated(self):
        detector = InterruptDetector()
        line = 'ARCHIPELAGO_NEED_PERMISSION {"action": "delete prod", "risk_level": "high", "why_needed": "cleanup"}'
        result = detector.scan_line(line)
        assert result.risk_level == "high"


# ── Commit 2: InterruptHandler breakpoint integration ──


class TestInterruptHandler:
    def _make_handler(self, auto_approve=False):
        session_mgr = MagicMock(spec=SessionManager)
        detector = InterruptDetector()
        return InterruptHandler(
            session_mgr, detector, auto_approve_low_risk=auto_approve
        ), session_mgr

    def test_given_blocking_clarification_when_handled_then_session_paused(self):
        handler, session_mgr = self._make_handler()
        request = ClarificationRequest(question="Which DB?", blocking=True)
        session = SessionHandle(exec_id="e1", container_id="c1")
        handler.handle_interrupt(request, session, {})
        session_mgr.pause.assert_called_once_with(session)

    def test_given_blocking_clarification_when_handled_then_breakpoint_payload_set_in_state(
        self,
    ):
        handler, _ = self._make_handler()
        request = ClarificationRequest(question="Which DB?", options=["pg"], blocking=True)
        session = SessionHandle(exec_id="e1", container_id="c1")
        result = handler.handle_interrupt(request, session, {"existing": True})
        assert "breakpoint_payload" in result
        assert result["breakpoint_payload"]["type"] == "clarification"
        assert result["breakpoint_payload"]["question"] == "Which DB?"
        assert result["existing"] is True

    def test_given_high_risk_permission_when_handled_then_session_paused(self):
        handler, session_mgr = self._make_handler()
        request = PermissionRequest(action="delete prod", risk_level="high", why_needed="cleanup")
        session = SessionHandle(exec_id="e1", container_id="c1")
        handler.handle_interrupt(request, session, {})
        session_mgr.pause.assert_called_once_with(session)

    def test_given_low_risk_permission_with_auto_approve_when_handled_then_approval_sent(
        self,
    ):
        handler, session_mgr = self._make_handler(auto_approve=True)
        request = PermissionRequest(
            action="install lodash", risk_level="low", why_needed="transforms"
        )
        session = SessionHandle(exec_id="e1", container_id="c1")
        result = handler.handle_interrupt(request, session, {})
        session_mgr.send_input.assert_called_once_with(session, "yes\n")
        assert "breakpoint_payload" not in result

    def test_given_low_risk_permission_without_auto_approve_when_handled_then_session_paused(
        self,
    ):
        handler, session_mgr = self._make_handler(auto_approve=False)
        request = PermissionRequest(
            action="install lodash", risk_level="low", why_needed="transforms"
        )
        session = SessionHandle(exec_id="e1", container_id="c1")
        result = handler.handle_interrupt(request, session, {})
        session_mgr.pause.assert_called_once()
        assert "breakpoint_payload" in result


# ── Commit 3: Resume after interrupt ──


class TestResumeAfterInterrupt:
    def test_given_paused_session_when_response_provided_then_input_sent_to_pty(self):
        session_mgr = MagicMock(spec=SessionManager)
        handler = InterruptHandler(session_mgr, InterruptDetector())
        session = SessionHandle(exec_id="e1", container_id="c1", status="paused")
        handler.resume_after_response("pg\n", session)
        session_mgr.send_input.assert_called_once_with(session, "pg\n")

    def test_given_paused_session_when_response_provided_then_session_resumed(self):
        session_mgr = MagicMock(spec=SessionManager)
        handler = InterruptHandler(session_mgr, InterruptDetector())
        session = SessionHandle(exec_id="e1", container_id="c1", status="paused")
        handler.resume_after_response("pg\n", session)
        session_mgr.resume.assert_called_once_with(session)

    def test_given_resumed_session_when_cc_continues_then_output_streaming_resumes(self):
        session_mgr = MagicMock(spec=SessionManager)
        handler = InterruptHandler(session_mgr, InterruptDetector())
        session = SessionHandle(exec_id="e1", container_id="c1", status="paused")
        handler.resume_after_response("pg\n", session)
        # After resume_after_response, the session manager's resume() is called
        # which sets status back to "running", confirming output streaming can proceed
        session_mgr.resume.assert_called_once_with(session)
