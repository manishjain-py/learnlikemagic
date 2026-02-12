"""
Message Models

Models for conversation messages, WebSocket protocol, and DTOs.
"""

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class Message(BaseModel):
    """Individual message in a conversation."""

    role: Literal["student", "teacher"] = Field(description="Role of the message sender")
    content: str = Field(description="Message content text")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="When the message was created")
    message_id: Optional[str] = Field(default=None, description="Unique message identifier")


class StudentContext(BaseModel):
    """Student context for session initialization."""

    grade: int = Field(ge=1, le=12, description="Student's grade level")
    board: str = Field(default="CBSE", description="Educational board")
    language_level: Literal["simple", "standard", "advanced"] = Field(
        default="simple", description="Language complexity preference"
    )
    preferred_examples: list[str] = Field(
        default_factory=lambda: ["food", "sports", "games"],
        description="Preferred example topics",
    )


# WebSocket Protocol

class ClientMessagePayload(BaseModel):
    message: Optional[str] = None
    topic_id: Optional[str] = None
    student_context: Optional[StudentContext] = None


class ClientMessage(BaseModel):
    type: Literal["chat", "start_session", "get_state"] = Field(description="Type of client message")
    payload: ClientMessagePayload = Field(default_factory=ClientMessagePayload)


class SessionStateDTO(BaseModel):
    """Data transfer object for session state."""

    session_id: str
    current_step: int
    total_steps: int
    current_concept: Optional[str]
    progress_percentage: float
    mastery_estimates: dict[str, float]
    is_complete: bool


class StudyPlanStepDTO(BaseModel):
    step_id: int
    type: str
    concept: str
    content_hint: Optional[str] = None
    question_type: Optional[str] = None
    question_count: Optional[int] = None
    is_current: bool = False
    is_completed: bool = False


class StudyPlanDTO(BaseModel):
    total_steps: int
    steps: list[StudyPlanStepDTO]


class TopicDTO(BaseModel):
    topic_id: str
    topic_name: str
    subject: str
    grade_level: int
    learning_objectives: list[str]
    common_misconceptions: list[str]


class StudentProfileDTO(BaseModel):
    grade: int
    board: str
    language_level: str
    preferred_examples: list[str]
    pace_preference: str


class MasteryItemDTO(BaseModel):
    concept: str
    score: float
    level: str


class MisconceptionDTO(BaseModel):
    concept: str
    description: str
    detected_at: str
    resolved: bool


class QuestionDTO(BaseModel):
    question_text: str
    expected_answer: str
    concept: str
    hints_available: int
    hints_used: int


class SessionSummaryDTO(BaseModel):
    turn_timeline: list[str]
    concepts_taught: list[str]
    examples_used: list[str]
    analogies_used: list[str]
    stuck_points: list[str]
    what_helped: list[str]
    progress_trend: str


class BehavioralDTO(BaseModel):
    off_topic_count: int
    warning_count: int
    safety_flags: list[str]


class ConversationMessageDTO(BaseModel):
    role: str
    content: str
    timestamp: str


class DetailedSessionStateDTO(BaseModel):
    """Comprehensive session state for debugging/transparency view."""

    session_id: str
    created_at: str
    updated_at: str
    turn_count: int

    topic: Optional[TopicDTO] = None
    study_plan: Optional[StudyPlanDTO] = None

    current_step: int
    total_steps: int
    progress_percentage: float
    is_complete: bool
    concepts_covered: list[str]
    last_concept_taught: Optional[str] = None

    student_profile: StudentProfileDTO

    awaiting_response: bool
    last_question: Optional[QuestionDTO] = None

    mastery_items: list[MasteryItemDTO]
    overall_mastery: float

    misconceptions: list[MisconceptionDTO]
    weak_areas: list[str]

    session_summary: SessionSummaryDTO
    behavioral: BehavioralDTO
    conversation_history: list[ConversationMessageDTO]


class ServerMessagePayload(BaseModel):
    message: Optional[str] = None
    state: Optional[SessionStateDTO] = None
    error: Optional[str] = None


class ServerMessage(BaseModel):
    type: Literal["assistant", "state_update", "error", "typing"] = Field(description="Type of server message")
    payload: ServerMessagePayload = Field(default_factory=ServerMessagePayload)


# Factory Functions

def create_teacher_message(content: str, message_id: Optional[str] = None) -> Message:
    return Message(role="teacher", content=content, message_id=message_id)


def create_student_message(content: str, message_id: Optional[str] = None) -> Message:
    return Message(role="student", content=content, message_id=message_id)


def create_assistant_response(message: str) -> ServerMessage:
    return ServerMessage(type="assistant", payload=ServerMessagePayload(message=message))


def create_error_response(error: str) -> ServerMessage:
    return ServerMessage(type="error", payload=ServerMessagePayload(error=error))


def create_state_update(state: SessionStateDTO) -> ServerMessage:
    return ServerMessage(type="state_update", payload=ServerMessagePayload(state=state))


def create_typing_indicator() -> ServerMessage:
    return ServerMessage(type="typing", payload=ServerMessagePayload())
