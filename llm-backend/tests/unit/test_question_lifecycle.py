"""Tests for TeacherOrchestrator._handle_question_lifecycle"""

from unittest.mock import MagicMock
from tutor.models.session_state import Question
from tutor.orchestration.orchestrator import TeacherOrchestrator


def _make_output(**kwargs):
    output = MagicMock()
    output.answer_correct = kwargs.get("answer_correct", None)
    output.question_asked = kwargs.get("question_asked", None)
    output.expected_answer = kwargs.get("expected_answer", None)
    output.question_concept = kwargs.get("question_concept", None)
    return output


def _make_session(last_question=None, history=None):
    session = MagicMock()
    session.last_question = last_question
    session.conversation_history = history or []
    session.current_step_data = MagicMock()
    session.current_step_data.concept = "default_concept"
    return session


def _make_student_msg(content):
    msg = MagicMock()
    msg.content = content
    msg.role = "student"
    return msg


def _make_orchestrator():
    orch = TeacherOrchestrator(llm_service=MagicMock())
    return orch


class TestQuestionLifecycle:
    def test_new_question_no_pending(self):
        orch = _make_orchestrator()
        session = _make_session(last_question=None)
        output = _make_output(question_asked="What is 2+2?", expected_answer="4", question_concept="addition")
        result = orch._handle_question_lifecycle(session, output, "addition")
        assert result is True
        session.set_question.assert_called_once()

    def test_wrong_answer_increments_attempts(self):
        q = Question(question_text="What is 2+2?", expected_answer="4", concept="addition")
        session = _make_session(
            last_question=q,
            history=[_make_student_msg("5")]
        )
        orch = _make_orchestrator()
        output = _make_output(answer_correct=False)
        result = orch._handle_question_lifecycle(session, output, "addition")
        assert result is True
        assert q.wrong_attempts == 1

    def test_wrong_answer_preserves_question(self):
        q = Question(question_text="What is 2+2?", expected_answer="4", concept="addition")
        session = _make_session(
            last_question=q,
            history=[_make_student_msg("5")]
        )
        orch = _make_orchestrator()
        output = _make_output(answer_correct=False)
        orch._handle_question_lifecycle(session, output, "addition")
        session.clear_question.assert_not_called()

    def test_wrong_answer_records_student_answer(self):
        q = Question(question_text="What is 2+2?", expected_answer="4", concept="addition")
        session = _make_session(
            last_question=q,
            history=[_make_student_msg("I think it's 5")]
        )
        orch = _make_orchestrator()
        output = _make_output(answer_correct=False)
        orch._handle_question_lifecycle(session, output, "addition")
        assert len(q.previous_student_answers) == 1
        assert "5" in q.previous_student_answers[0]

    def test_phase_progression(self):
        q = Question(question_text="Q?", expected_answer="A", concept="c")
        orch = _make_orchestrator()

        # 1st wrong → probe
        session = _make_session(last_question=q, history=[_make_student_msg("wrong1")])
        orch._handle_question_lifecycle(session, _make_output(answer_correct=False), "c")
        assert q.phase == "probe"
        assert q.wrong_attempts == 1

        # 2nd wrong → hint
        session.conversation_history = [_make_student_msg("wrong2")]
        orch._handle_question_lifecycle(session, _make_output(answer_correct=False), "c")
        assert q.phase == "hint"
        assert q.wrong_attempts == 2

        # 3rd wrong → explain
        session.conversation_history = [_make_student_msg("wrong3")]
        orch._handle_question_lifecycle(session, _make_output(answer_correct=False), "c")
        assert q.phase == "explain"
        assert q.wrong_attempts == 3

    def test_correct_clears_question(self):
        q = Question(question_text="Q?", expected_answer="A", concept="c")
        session = _make_session(last_question=q)
        orch = _make_orchestrator()
        output = _make_output(answer_correct=True)
        result = orch._handle_question_lifecycle(session, output, "c")
        assert result is True
        session.clear_question.assert_called_once()

    def test_followup_same_concept_preserves(self):
        q = Question(question_text="Q?", expected_answer="A", concept="place_value")
        q.wrong_attempts = 2
        session = _make_session(last_question=q)
        orch = _make_orchestrator()
        output = _make_output(
            question_asked="What about this?",
            question_concept="place_value"
        )
        result = orch._handle_question_lifecycle(session, output, "place_value")
        assert result is False  # No change — same concept follow-up
        assert q.wrong_attempts == 2  # Preserved

    def test_new_concept_replaces(self):
        q = Question(question_text="Q?", expected_answer="A", concept="place_value")
        session = _make_session(last_question=q)
        orch = _make_orchestrator()
        output = _make_output(
            question_asked="New Q?",
            expected_answer="B",
            question_concept="expanded_form"
        )
        result = orch._handle_question_lifecycle(session, output, "expanded_form")
        assert result is True
        session.set_question.assert_called_once()

    def test_probing_after_wrong_preserves(self):
        """When tutor asks a follow-up after wrong answer, original question is preserved."""
        q = Question(question_text="Q?", expected_answer="A", concept="c")
        session = _make_session(
            last_question=q,
            history=[_make_student_msg("wrong")]
        )
        orch = _make_orchestrator()
        # Wrong answer + tutor asks follow-up on same concept
        output = _make_output(
            answer_correct=False,
            question_asked="Can you think about why?",
            question_concept="c"
        )
        orch._handle_question_lifecycle(session, output, "c")
        # Should increment attempts but NOT replace question
        assert q.wrong_attempts == 1
        session.set_question.assert_not_called()
