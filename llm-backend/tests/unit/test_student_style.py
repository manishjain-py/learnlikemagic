"""Tests for MasterTutorAgent._compute_student_style"""

from unittest.mock import MagicMock
from tutor.agents.master_tutor import MasterTutorAgent


def _make_msg(content, role="student"):
    msg = MagicMock()
    msg.content = content
    msg.role = role
    return msg


def _make_session(messages=None):
    session = MagicMock()
    session.conversation_history = messages or []
    return session


def _make_agent():
    return MasterTutorAgent(llm_service=MagicMock())


class TestStudentStyle:
    def test_no_messages(self):
        agent = _make_agent()
        session = _make_session([])
        result = agent._compute_student_style(session)
        assert "Unknown" in result

    def test_quiet_student(self):
        agent = _make_agent()
        session = _make_session([
            _make_msg("yes"),
            _make_msg("ok"),
            _make_msg("4"),
        ])
        result = agent._compute_student_style(session)
        assert "QUIET" in result
        assert "2-3 sentences" in result

    def test_moderate_student(self):
        agent = _make_agent()
        session = _make_session([
            _make_msg("I think the answer is probably around 42"),
            _make_msg("Oh wait let me think about that again"),
        ])
        result = agent._compute_student_style(session)
        assert "Moderate" in result

    def test_expressive_student(self):
        agent = _make_agent()
        session = _make_session([
            _make_msg("Oh wow that's so cool! I never thought about it that way before. "
                      "It's like when my mom makes pizza and cuts it into pieces and each piece "
                      "is a fraction right?"),
        ])
        result = agent._compute_student_style(session)
        assert "Expressive" in result

    def test_asks_questions(self):
        agent = _make_agent()
        session = _make_session([
            _make_msg("What happens if the number has a zero?"),
        ])
        result = agent._compute_student_style(session)
        assert "asks questions" in result

    def test_disengagement_signal(self):
        agent = _make_agent()
        session = _make_session([
            _make_msg("Oh that's really interesting I think I understand now"),  # long
            _make_msg("I see what you mean about that concept"),  # medium
            _make_msg("Yeah I guess so"),  # shorter
            _make_msg("ok"),  # very short — disengaging (< 40% of first, ≤5 words)
        ])
        result = agent._compute_student_style(session)
        assert "disengagement" in result.lower() or "shorter" in result.lower()
