"""
Unit tests for message models and factory functions.

Tests factory functions (create_teacher_message, create_student_message,
create_assistant_response, create_error_response, create_state_update,
create_typing_indicator) and all DTO models.
"""

import pytest
from datetime import datetime

from tutor.models.messages import (
    # Core models
    Message,
    StudentContext,
    ServerMessage,
    ServerMessagePayload,
    ClientMessage,
    ClientMessagePayload,
    # Factory functions
    create_teacher_message,
    create_student_message,
    create_assistant_response,
    create_error_response,
    create_state_update,
    create_typing_indicator,
    # DTOs
    SessionStateDTO,
    StudyPlanStepDTO,
    StudyPlanDTO,
    TopicDTO,
    StudentProfileDTO,
    MasteryItemDTO,
    MisconceptionDTO,
    QuestionDTO,
    SessionSummaryDTO,
    BehavioralDTO,
    ConversationMessageDTO,
    DetailedSessionStateDTO,
)


# ---------------------------------------------------------------------------
# Message model
# ---------------------------------------------------------------------------

class TestMessage:
    def test_teacher_role(self):
        msg = Message(role="teacher", content="Hello student")
        assert msg.role == "teacher"
        assert msg.content == "Hello student"
        assert isinstance(msg.timestamp, datetime)

    def test_student_role(self):
        msg = Message(role="student", content="Hi teacher")
        assert msg.role == "student"

    def test_optional_message_id(self):
        msg = Message(role="teacher", content="test")
        assert msg.message_id is None

        msg_with_id = Message(role="teacher", content="test", message_id="msg_123")
        assert msg_with_id.message_id == "msg_123"


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

class TestCreateTeacherMessage:
    def test_creates_teacher_message(self):
        msg = create_teacher_message("Great work!")
        assert isinstance(msg, Message)
        assert msg.role == "teacher"
        assert msg.content == "Great work!"
        assert msg.message_id is None

    def test_with_message_id(self):
        msg = create_teacher_message("Hello", message_id="t_001")
        assert msg.message_id == "t_001"

    def test_has_timestamp(self):
        msg = create_teacher_message("content")
        assert isinstance(msg.timestamp, datetime)


class TestCreateStudentMessage:
    def test_creates_student_message(self):
        msg = create_student_message("I don't understand")
        assert isinstance(msg, Message)
        assert msg.role == "student"
        assert msg.content == "I don't understand"
        assert msg.message_id is None

    def test_with_message_id(self):
        msg = create_student_message("My answer is 5", message_id="s_001")
        assert msg.message_id == "s_001"


class TestCreateAssistantResponse:
    def test_creates_assistant_server_message(self):
        sm = create_assistant_response("Here is my explanation")
        assert isinstance(sm, ServerMessage)
        assert sm.type == "assistant"
        assert sm.payload.message == "Here is my explanation"
        assert sm.payload.error is None
        assert sm.payload.state is None

    def test_empty_message(self):
        sm = create_assistant_response("")
        assert sm.payload.message == ""


class TestCreateErrorResponse:
    def test_creates_error_server_message(self):
        sm = create_error_response("Something went wrong")
        assert isinstance(sm, ServerMessage)
        assert sm.type == "error"
        assert sm.payload.error == "Something went wrong"
        assert sm.payload.message is None


class TestCreateStateUpdate:
    def test_creates_state_update_server_message(self):
        state = SessionStateDTO(
            session_id="sess_123",
            current_step=2,
            total_steps=5,
            current_concept="Fractions",
            progress_percentage=40.0,
            mastery_estimates={"Fractions": 0.6},
            is_complete=False,
        )
        sm = create_state_update(state)
        assert isinstance(sm, ServerMessage)
        assert sm.type == "state_update"
        assert sm.payload.state is not None
        assert sm.payload.state.session_id == "sess_123"
        assert sm.payload.state.current_step == 2


class TestCreateTypingIndicator:
    def test_creates_typing_server_message(self):
        sm = create_typing_indicator()
        assert isinstance(sm, ServerMessage)
        assert sm.type == "typing"
        assert sm.payload.message is None
        assert sm.payload.error is None
        assert sm.payload.state is None


# ---------------------------------------------------------------------------
# StudentContext
# ---------------------------------------------------------------------------

class TestStudentContext:
    def test_default_values(self):
        ctx = StudentContext(grade=5)
        assert ctx.grade == 5
        assert ctx.board == "CBSE"
        assert ctx.language_level == "simple"
        assert isinstance(ctx.preferred_examples, list)

    def test_custom_values(self):
        ctx = StudentContext(
            grade=8,
            board="ICSE",
            language_level="advanced",
            preferred_examples=["science", "technology"],
        )
        assert ctx.grade == 8
        assert ctx.board == "ICSE"
        assert ctx.language_level == "advanced"
        assert ctx.preferred_examples == ["science", "technology"]


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

class TestSessionStateDTO:
    def test_required_fields(self):
        dto = SessionStateDTO(
            session_id="s1",
            current_step=1,
            total_steps=5,
            current_concept="Fractions",
            progress_percentage=20.0,
            mastery_estimates={"Fractions": 0.5},
            is_complete=False,
        )
        assert dto.session_id == "s1"
        assert dto.current_step == 1
        assert dto.total_steps == 5
        assert dto.current_concept == "Fractions"
        assert dto.progress_percentage == 20.0
        assert dto.is_complete is False

    def test_null_concept(self):
        dto = SessionStateDTO(
            session_id="s2",
            current_step=1,
            total_steps=3,
            current_concept=None,
            progress_percentage=0.0,
            mastery_estimates={},
            is_complete=False,
        )
        assert dto.current_concept is None


class TestStudyPlanStepDTO:
    def test_required_fields(self):
        dto = StudyPlanStepDTO(step_id=1, type="explain", concept="Basics")
        assert dto.step_id == 1
        assert dto.type == "explain"
        assert dto.concept == "Basics"
        assert dto.is_current is False
        assert dto.is_completed is False

    def test_optional_fields(self):
        dto = StudyPlanStepDTO(
            step_id=2,
            type="check",
            concept="Fractions",
            content_hint="Use pizza analogy",
            question_type="conceptual",
            question_count=3,
            is_current=True,
            is_completed=False,
        )
        assert dto.content_hint == "Use pizza analogy"
        assert dto.question_type == "conceptual"
        assert dto.question_count == 3
        assert dto.is_current is True


class TestStudyPlanDTO:
    def test_creation(self):
        steps = [
            StudyPlanStepDTO(step_id=1, type="explain", concept="A"),
            StudyPlanStepDTO(step_id=2, type="check", concept="A"),
        ]
        dto = StudyPlanDTO(total_steps=2, steps=steps)
        assert dto.total_steps == 2
        assert len(dto.steps) == 2


class TestTopicDTO:
    def test_creation(self):
        dto = TopicDTO(
            topic_id="t1",
            topic_name="Fractions",
            subject="Math",
            grade_level=3,
            learning_objectives=["Learn fractions"],
            common_misconceptions=["Bigger denominator = bigger fraction"],
        )
        assert dto.topic_id == "t1"
        assert dto.topic_name == "Fractions"
        assert dto.subject == "Math"
        assert dto.grade_level == 3
        assert len(dto.learning_objectives) == 1
        assert len(dto.common_misconceptions) == 1


class TestStudentProfileDTO:
    def test_creation(self):
        dto = StudentProfileDTO(
            grade=3,
            board="CBSE",
            language_level="simple",
            preferred_examples=["food", "sports"],
            pace_preference="normal",
        )
        assert dto.grade == 3
        assert dto.board == "CBSE"
        assert dto.pace_preference == "normal"


class TestMasteryItemDTO:
    def test_creation(self):
        dto = MasteryItemDTO(concept="Fractions", score=0.75, level="adequate")
        assert dto.concept == "Fractions"
        assert dto.score == 0.75
        assert dto.level == "adequate"


class TestMisconceptionDTO:
    def test_creation(self):
        dto = MisconceptionDTO(
            concept="Fractions",
            description="Bigger denominator means bigger fraction",
            detected_at="2026-01-15T10:00:00",
            resolved=False,
        )
        assert dto.concept == "Fractions"
        assert dto.resolved is False


class TestQuestionDTO:
    def test_creation(self):
        dto = QuestionDTO(
            question_text="What is 1/2 + 1/2?",
            expected_answer="1",
            concept="Adding Fractions",
            hints_available=3,
            hints_used=1,
        )
        assert dto.question_text == "What is 1/2 + 1/2?"
        assert dto.expected_answer == "1"
        assert dto.hints_available == 3
        assert dto.hints_used == 1


class TestSessionSummaryDTO:
    def test_creation(self):
        dto = SessionSummaryDTO(
            turn_timeline=["Turn 1: Intro", "Turn 2: Practice"],
            concepts_taught=["Fractions"],
            examples_used=["pizza slices"],
            analogies_used=["pie chart"],
            stuck_points=["denominator confusion"],
            what_helped=["visual aids"],
            progress_trend="improving",
        )
        assert len(dto.turn_timeline) == 2
        assert dto.progress_trend == "improving"


class TestBehavioralDTO:
    def test_creation(self):
        dto = BehavioralDTO(
            off_topic_count=2,
            warning_count=1,
            safety_flags=["mild_language"],
        )
        assert dto.off_topic_count == 2
        assert dto.warning_count == 1
        assert len(dto.safety_flags) == 1


class TestConversationMessageDTO:
    def test_creation(self):
        dto = ConversationMessageDTO(
            role="student",
            content="My answer is 5",
            timestamp="2026-01-15T10:30:00",
        )
        assert dto.role == "student"
        assert dto.content == "My answer is 5"


class TestDetailedSessionStateDTO:
    def test_creation_with_required_fields(self):
        dto = DetailedSessionStateDTO(
            session_id="sess_001",
            created_at="2026-01-15T10:00:00",
            updated_at="2026-01-15T10:30:00",
            turn_count=5,
            current_step=2,
            total_steps=5,
            progress_percentage=40.0,
            is_complete=False,
            concepts_covered=["Basics"],
            student_profile=StudentProfileDTO(
                grade=3,
                board="CBSE",
                language_level="simple",
                preferred_examples=["food"],
                pace_preference="normal",
            ),
            awaiting_response=True,
            mastery_items=[MasteryItemDTO(concept="Basics", score=0.6, level="developing")],
            overall_mastery=0.6,
            misconceptions=[],
            weak_areas=[],
            session_summary=SessionSummaryDTO(
                turn_timeline=["Turn 1: Intro"],
                concepts_taught=["Basics"],
                examples_used=[],
                analogies_used=[],
                stuck_points=[],
                what_helped=[],
                progress_trend="steady",
            ),
            behavioral=BehavioralDTO(
                off_topic_count=0,
                warning_count=0,
                safety_flags=[],
            ),
            conversation_history=[],
        )
        assert dto.session_id == "sess_001"
        assert dto.turn_count == 5
        assert dto.is_complete is False
        assert dto.student_profile.grade == 3
        assert dto.overall_mastery == 0.6

    def test_optional_topic_and_study_plan(self):
        dto = DetailedSessionStateDTO(
            session_id="sess_002",
            created_at="2026-01-15T10:00:00",
            updated_at="2026-01-15T10:00:00",
            turn_count=0,
            current_step=1,
            total_steps=0,
            progress_percentage=0.0,
            is_complete=False,
            concepts_covered=[],
            student_profile=StudentProfileDTO(
                grade=5,
                board="CBSE",
                language_level="standard",
                preferred_examples=[],
                pace_preference="normal",
            ),
            awaiting_response=False,
            mastery_items=[],
            overall_mastery=0.0,
            misconceptions=[],
            weak_areas=[],
            session_summary=SessionSummaryDTO(
                turn_timeline=[],
                concepts_taught=[],
                examples_used=[],
                analogies_used=[],
                stuck_points=[],
                what_helped=[],
                progress_trend="steady",
            ),
            behavioral=BehavioralDTO(
                off_topic_count=0,
                warning_count=0,
                safety_flags=[],
            ),
            conversation_history=[],
        )
        assert dto.topic is None
        assert dto.study_plan is None
        assert dto.last_question is None
        assert dto.last_concept_taught is None


# ---------------------------------------------------------------------------
# ClientMessage / ClientMessagePayload
# ---------------------------------------------------------------------------

class TestClientMessage:
    def test_chat_message(self):
        msg = ClientMessage(
            type="chat",
            payload=ClientMessagePayload(message="Hello"),
        )
        assert msg.type == "chat"
        assert msg.payload.message == "Hello"

    def test_start_session(self):
        msg = ClientMessage(
            type="start_session",
            payload=ClientMessagePayload(
                topic_id="t1",
                student_context=StudentContext(grade=3),
            ),
        )
        assert msg.type == "start_session"
        assert msg.payload.topic_id == "t1"
        assert msg.payload.student_context.grade == 3

    def test_default_payload(self):
        msg = ClientMessage(type="get_state")
        assert msg.payload.message is None
        assert msg.payload.topic_id is None


# ---------------------------------------------------------------------------
# ServerMessage / ServerMessagePayload
# ---------------------------------------------------------------------------

class TestServerMessage:
    def test_assistant_type(self):
        sm = ServerMessage(
            type="assistant",
            payload=ServerMessagePayload(message="Hello"),
        )
        assert sm.type == "assistant"
        assert sm.payload.message == "Hello"

    def test_error_type(self):
        sm = ServerMessage(
            type="error",
            payload=ServerMessagePayload(error="Not found"),
        )
        assert sm.type == "error"
        assert sm.payload.error == "Not found"

    def test_default_payload(self):
        sm = ServerMessage(type="typing")
        assert sm.payload.message is None
        assert sm.payload.error is None
        assert sm.payload.state is None
