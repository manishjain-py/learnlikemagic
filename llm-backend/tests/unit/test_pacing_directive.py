"""Tests for MasterTutorAgent._compute_pacing_directive"""

from unittest.mock import MagicMock
from tutor.agents.master_tutor import MasterTutorAgent


def _make_session(turn_count=5, mastery=None, trend="steady", is_complete=False):
    """Create a mock session with specified state."""
    session = MagicMock()
    session.turn_count = turn_count
    session.mastery_estimates = mastery or {"concept1": 0.5}
    session.session_summary.progress_trend = trend
    session.is_complete = is_complete
    return session


def _make_agent():
    agent = MasterTutorAgent(llm_service=MagicMock())
    return agent


class TestPacingDirective:
    def test_first_turn_directive(self):
        agent = _make_agent()
        session = _make_session(turn_count=1)
        result = agent._compute_pacing_directive(session)
        assert "FIRST TURN" in result
        assert "2-3 sentences" in result

    def test_first_turn_not_zero(self):
        """turn_count=0 is pre-increment state, should NOT be first turn."""
        agent = _make_agent()
        session = _make_session(turn_count=0)
        result = agent._compute_pacing_directive(session)
        assert "FIRST TURN" not in result

    def test_accelerate_high_mastery(self):
        agent = _make_agent()
        session = _make_session(mastery={"c1": 0.9, "c2": 0.85}, trend="improving")
        result = agent._compute_pacing_directive(session)
        assert "ACCELERATE" in result

    def test_extend_past_plan(self):
        agent = _make_agent()
        session = _make_session(
            mastery={"c1": 0.9, "c2": 0.85}, trend="improving", is_complete=True
        )
        result = agent._compute_pacing_directive(session)
        assert "EXTEND" in result

    def test_simplify_low_mastery(self):
        agent = _make_agent()
        session = _make_session(mastery={"c1": 0.2, "c2": 0.3})
        result = agent._compute_pacing_directive(session)
        assert "SIMPLIFY" in result

    def test_simplify_struggling_trend(self):
        agent = _make_agent()
        session = _make_session(mastery={"c1": 0.5}, trend="struggling")
        result = agent._compute_pacing_directive(session)
        assert "SIMPLIFY" in result

    def test_steady_default(self):
        agent = _make_agent()
        session = _make_session(mastery={"c1": 0.6}, trend="steady")
        result = agent._compute_pacing_directive(session)
        assert "STEADY" in result
