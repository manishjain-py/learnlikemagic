"""Unit tests for tutor/services/session_service.py — SessionService."""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from types import SimpleNamespace

from shared.models.domain import Student, Goal, GradingResult
from shared.models.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    StepRequest,
    StepResponse,
    SummaryResponse,
)
from shared.utils.exceptions import SessionNotFoundException, GuidelineNotFoundException
from tutor.models.session_state import SessionState, ExamQuestion, ExamFeedback, create_session, Misconception
from tutor.models.study_plan import (
    Topic,
    TopicGuidelines,
    StudyPlan,
    StudyPlanStep,
)
from tutor.models.messages import StudentContext


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_topic() -> Topic:
    return Topic(
        topic_id="math_fractions_basics",
        topic_name="Fractions - Basics",
        subject="Mathematics",
        grade_level=3,
        guidelines=TopicGuidelines(
            learning_objectives=["Understand fractions"],
            common_misconceptions=["Denominator confusion"],
            teaching_approach="Use visuals",
        ),
        study_plan=StudyPlan(
            steps=[
                StudyPlanStep(step_id=1, type="explain", concept="What is a fraction", content_hint="Pizza example"),
                StudyPlanStep(step_id=2, type="check", concept="What is a fraction", question_type="conceptual"),
                StudyPlanStep(step_id=3, type="practice", concept="What is a fraction", question_count=2),
            ]
        ),
    )


def _make_session_state() -> SessionState:
    topic = _make_topic()
    ctx = StudentContext(grade=3, board="CBSE", language_level="simple")
    session = create_session(topic=topic, student_context=ctx)
    session.session_id = "test-session-123"
    return session


def _make_guideline_response():
    """Return a mock that looks like a DB guideline row."""
    g = MagicMock()
    g.id = "guideline-1"
    g.topic = "Fractions"
    g.topic_title = "Fractions"
    g.subtopic = "Basics"
    g.subtopic_title = "Basics"
    g.subject = "Mathematics"
    g.grade = 3
    g.guideline = "Teach fractions using pizza examples."
    g.description = "Teach fractions"
    g.metadata = None
    g.metadata_json = None
    g.country = "India"
    g.board = "CBSE"
    return g


def _create_request() -> CreateSessionRequest:
    return CreateSessionRequest(
        student=Student(id="student-1", grade=3),
        goal=Goal(
            topic="Fractions",
            syllabus="CBSE Grade 3 Math",
            learning_objectives=["Understand fractions"],
            guideline_id="guideline-1",
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSessionServiceCreateNewSession:
    """Tests for SessionService.create_new_session."""

    @patch("tutor.services.session_service.get_settings")
    def test_create_session_raises_guideline_not_found(self, mock_settings):
        mock_settings.return_value = MagicMock(
            openai_api_key="fake",
            gemini_api_key=None,
            anthropic_api_key=None,
        )

        from tutor.services.session_service import SessionService

        db = MagicMock()
        svc = SessionService.__new__(SessionService)
        svc.db = db
        svc.session_repo = MagicMock()
        svc.event_repo = MagicMock()
        svc.guideline_repo = MagicMock()
        svc.orchestrator = MagicMock()
        svc.llm_service = MagicMock()

        svc.guideline_repo.get_guideline_by_id.return_value = None

        request = _create_request()
        with pytest.raises(GuidelineNotFoundException):
            svc.create_new_session(request)

    @patch("tutor.services.session_service.get_settings")
    @patch("tutor.services.session_service.convert_guideline_to_topic")
    def test_create_session_success(self, mock_convert, mock_settings):
        mock_settings.return_value = MagicMock(
            openai_api_key="fake",
            gemini_api_key=None,
            anthropic_api_key=None,
        )
        mock_convert.return_value = _make_topic()

        from tutor.services.session_service import SessionService

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()
        svc.session_repo = MagicMock()
        svc.event_repo = MagicMock()
        svc.guideline_repo = MagicMock()
        svc.llm_service = MagicMock()
        svc.orchestrator = MagicMock()

        # guideline found
        svc.guideline_repo.get_guideline_by_id.return_value = _make_guideline_response()
        # no existing study plan
        svc.db.query.return_value.filter.return_value.first.return_value = None
        # orchestrator returns welcome
        svc.orchestrator.generate_welcome_message = AsyncMock(return_value="Hello! Let's learn fractions!")

        request = _create_request()

        with patch("asyncio.run", return_value="Hello! Let's learn fractions!"):
            response = svc.create_new_session(request)

        assert isinstance(response, CreateSessionResponse)
        assert response.session_id is not None
        assert response.first_turn["message"] == "Hello! Let's learn fractions!"
        svc.db.add.assert_called_once()
        svc.db.commit.assert_called_once()
        svc.event_repo.log.assert_called_once()


class TestSessionServiceProcessStep:
    """Tests for SessionService.process_step."""

    @patch("tutor.services.session_service.get_settings")
    def test_process_step_session_not_found(self, mock_settings):
        mock_settings.return_value = MagicMock(
            openai_api_key="fake",
            gemini_api_key=None,
            anthropic_api_key=None,
        )

        from tutor.services.session_service import SessionService

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()
        svc.session_repo = MagicMock()
        svc.event_repo = MagicMock()
        svc.guideline_repo = MagicMock()
        svc.llm_service = MagicMock()
        svc.orchestrator = MagicMock()

        svc.session_repo.get_by_id.return_value = None

        with pytest.raises(SessionNotFoundException):
            svc.process_step("nonexistent", StepRequest(student_reply="42"))

    @patch("tutor.services.session_service.get_settings")
    def test_process_step_success(self, mock_settings):
        mock_settings.return_value = MagicMock(
            openai_api_key="fake",
            gemini_api_key=None,
            anthropic_api_key=None,
        )

        from tutor.services.session_service import SessionService
        from tutor.orchestration.orchestrator import TurnResult

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()
        svc.session_repo = MagicMock()
        svc.event_repo = MagicMock()
        svc.guideline_repo = MagicMock()
        svc.llm_service = MagicMock()
        svc.orchestrator = MagicMock()

        session_state = _make_session_state()
        db_row = MagicMock()
        db_row.state_json = session_state.model_dump_json()
        svc.session_repo.get_by_id.return_value = db_row

        turn_result = TurnResult(
            response="Good answer!",
            intent="answer",
            specialists_called=["master_tutor"],
            state_changed=True,
        )
        svc.orchestrator.agent_logs = MagicMock()
        svc.orchestrator.agent_logs.get_recent_logs.return_value = []

        with patch("asyncio.run", return_value=turn_result):
            resp = svc.process_step("test-session-123", StepRequest(student_reply="3/4"))

        assert isinstance(resp, StepResponse)
        assert resp.next_turn["message"] == "Good answer!"
        svc.event_repo.log.assert_called_once()

    @patch("tutor.services.session_service.get_settings")
    def test_process_step_exam_completion_returns_only_final_feedback(self, mock_settings):
        mock_settings.return_value = MagicMock(
            openai_api_key="fake",
            gemini_api_key=None,
            anthropic_api_key=None,
        )

        from tutor.services.session_service import SessionService
        from tutor.orchestration.orchestrator import TurnResult

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()
        svc.session_repo = MagicMock()
        svc.event_repo = MagicMock()
        svc.guideline_repo = MagicMock()
        svc.llm_service = MagicMock()
        svc.orchestrator = MagicMock()

        session_state = _make_session_state()
        session_state.mode = "exam"
        session_state.exam_questions = [
            ExamQuestion(
                question_idx=0,
                question_text="Q1?",
                concept="Basics",
                difficulty="easy",
                question_type="conceptual",
                expected_answer="A1",
                student_answer="A1",
                result="correct",
            )
        ]
        session_state.exam_current_question_idx = 1
        session_state.exam_finished = True
        session_state.exam_total_correct = 1
        session_state.exam_feedback = ExamFeedback(
            score=1,
            total=1,
            percentage=100.0,
            strengths=["Basics"],
            weak_areas=[],
            patterns=["Overall strong performance"],
            next_steps=["Great job! Try a harder topic or retake to aim for a perfect score."],
        )

        db_row = MagicMock()
        db_row.state_json = session_state.model_dump_json()
        svc.session_repo.get_by_id.return_value = db_row

        turn_result = TurnResult(
            response="✅ Exam complete! Here are your final results.",
            intent="exam_answer",
            specialists_called=["master_tutor"],
            state_changed=True,
        )
        svc.orchestrator.agent_logs = MagicMock()
        svc.orchestrator.agent_logs.get_recent_logs.return_value = []

        with patch("asyncio.run", return_value=turn_result):
            resp = svc.process_step("test-session-123", StepRequest(student_reply="A1"))

        assert resp.next_turn["is_complete"] is True
        assert resp.next_turn["exam_feedback"]["percentage"] == 100.0
        assert len(resp.next_turn["exam_results"]) == 1
        assert resp.last_grading is None


class TestSessionServiceGetSummary:
    """Tests for SessionService.get_summary."""

    @patch("tutor.services.session_service.get_settings")
    def test_get_summary_not_found(self, mock_settings):
        mock_settings.return_value = MagicMock(
            openai_api_key="fake",
            gemini_api_key=None,
            anthropic_api_key=None,
        )

        from tutor.services.session_service import SessionService

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()
        svc.session_repo = MagicMock()
        svc.event_repo = MagicMock()
        svc.guideline_repo = MagicMock()
        svc.llm_service = MagicMock()
        svc.orchestrator = MagicMock()

        svc.session_repo.get_by_id.return_value = None

        with pytest.raises(SessionNotFoundException):
            svc.get_summary("nonexistent")

    @patch("tutor.services.session_service.get_settings")
    def test_get_summary_success_high_mastery(self, mock_settings):
        mock_settings.return_value = MagicMock(
            openai_api_key="fake",
            gemini_api_key=None,
            anthropic_api_key=None,
        )

        from tutor.services.session_service import SessionService

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()
        svc.session_repo = MagicMock()
        svc.event_repo = MagicMock()
        svc.guideline_repo = MagicMock()
        svc.llm_service = MagicMock()
        svc.orchestrator = MagicMock()

        session = _make_session_state()
        session.mastery_estimates = {"What is a fraction": 0.9}
        session.current_step = 4  # past last step

        db_row = MagicMock()
        db_row.state_json = session.model_dump_json()
        svc.session_repo.get_by_id.return_value = db_row

        resp = svc.get_summary("test-session-123")

        assert isinstance(resp, SummaryResponse)
        assert resp.mastery_score == 0.9
        assert "Excellent work" in resp.suggestions[0]

    @patch("tutor.services.session_service.get_settings")
    def test_get_summary_with_misconceptions(self, mock_settings):
        mock_settings.return_value = MagicMock(
            openai_api_key="fake",
            gemini_api_key=None,
            anthropic_api_key=None,
        )

        from tutor.services.session_service import SessionService

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()
        svc.session_repo = MagicMock()
        svc.event_repo = MagicMock()
        svc.guideline_repo = MagicMock()
        svc.llm_service = MagicMock()
        svc.orchestrator = MagicMock()

        session = _make_session_state()
        session.mastery_estimates = {"What is a fraction": 0.5}
        session.misconceptions = [
            Misconception(concept="fractions", description="Thinks numerator is always bigger"),
        ]

        db_row = MagicMock()
        db_row.state_json = session.model_dump_json()
        svc.session_repo.get_by_id.return_value = db_row

        resp = svc.get_summary("test-session-123")
        assert any("Work on understanding" in s for s in resp.suggestions)
        assert len(resp.misconceptions_seen) == 1


class TestGenerateSuggestions:
    """Tests for SessionService._generate_suggestions."""

    @patch("tutor.services.session_service.get_settings")
    def test_low_mastery_suggestions(self, mock_settings):
        mock_settings.return_value = MagicMock(
            openai_api_key="fake",
            gemini_api_key=None,
            anthropic_api_key=None,
        )

        from tutor.services.session_service import SessionService

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()
        svc.session_repo = MagicMock()
        svc.event_repo = MagicMock()
        svc.guideline_repo = MagicMock()
        svc.llm_service = MagicMock()
        svc.orchestrator = MagicMock()

        session = _make_session_state()
        session.mastery_estimates = {"What is a fraction": 0.3}

        suggestions = svc._generate_suggestions(session, [])
        assert any("Keep practicing" in s for s in suggestions)

    @patch("tutor.services.session_service.get_settings")
    def test_medium_mastery_suggestions(self, mock_settings):
        mock_settings.return_value = MagicMock(
            openai_api_key="fake",
            gemini_api_key=None,
            anthropic_api_key=None,
        )

        from tutor.services.session_service import SessionService

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()
        svc.session_repo = MagicMock()
        svc.event_repo = MagicMock()
        svc.guideline_repo = MagicMock()
        svc.llm_service = MagicMock()
        svc.orchestrator = MagicMock()

        session = _make_session_state()
        session.mastery_estimates = {"What is a fraction": 0.75}

        suggestions = svc._generate_suggestions(session, [])
        assert any("Good progress" in s for s in suggestions)
