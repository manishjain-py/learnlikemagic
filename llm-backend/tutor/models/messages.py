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
    audio_text: Optional[str] = Field(default=None, description="Hinglish spoken version for TTS (teacher messages only)")
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
    # Personalization fields (populated from user profile when authenticated)
    student_name: Optional[str] = Field(default=None, description="Student's name")
    student_age: Optional[int] = Field(default=None, description="Student's age")
    about_me: Optional[str] = Field(default=None, description="Student's self-description")
    text_language_preference: str = Field(default="en", description="Language for text responses: en, hi, hinglish")
    audio_language_preference: str = Field(default="en", description="Language for audio/TTS: en, hi, hinglish")
    # Kid personality (derived from enrichment profile via LLM)
    tutor_brief: Optional[str] = Field(default=None, description="Compact prose personality for system prompt")
    personality_json: Optional[dict] = Field(default=None, description="Full structured personality (for exam gen)")
    attention_span: Optional[str] = Field(default=None, description="short/medium/long from enrichment profile")


# WebSocket Protocol

class ClientMessagePayload(BaseModel):
    message: Optional[str] = None
    topic_id: Optional[str] = None
    student_context: Optional[StudentContext] = None
    card_idx: Optional[int] = None


class ClientMessage(BaseModel):
    type: Literal["chat", "start_session", "get_state", "card_navigate"] = Field(description="Type of client message")
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
    mode: str = "teach_me"
    coverage: float = 0.0
    concepts_discussed: list[str] = Field(default_factory=list)
    is_paused: bool = False


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


# ─── Card Phase DTOs ─────

class ExplanationLineDTO(BaseModel):
    """Per-line display+audio pair for frontend rendering."""
    display: str
    audio: str
    audio_url: Optional[str] = None  # S3 URL for pre-computed TTS MP3


class ExplanationCardDTO(BaseModel):
    """Explanation card for frontend rendering."""
    card_idx: int
    card_type: Literal["concept", "example", "visual", "analogy", "summary", "simplification", "welcome"]
    title: str
    lines: list[ExplanationLineDTO] = []
    content: str
    visual: Optional[str] = None


class CheckInEventDTO(BaseModel):
    """Check-in struggle data sent from frontend at phase transition."""
    card_idx: int
    card_title: Optional[str] = None
    activity_type: str = "match_pairs"
    wrong_count: int = 0
    hints_shown: int = 0
    confused_pairs: list[dict] = Field(default_factory=list)  # [{left, right, wrong_count, wrong_picks}]
    auto_revealed: int = 0


class CardActionRequest(BaseModel):
    """Request body for card phase actions."""
    action: Literal["clear", "explain_differently"]
    check_in_events: Optional[list[CheckInEventDTO]] = None


class SimplifyCardRequest(BaseModel):
    """Request body for per-card simplification."""
    card_idx: int = Field(description="Index of the card to simplify (0-based)")
    reason: str = Field(default="simplify", description="Simplification reason (default: general simplify)")


class CardPhaseDTO(BaseModel):
    """Card phase state summary for frontend."""
    current_variant_key: str
    current_card_idx: int
    total_cards: int
    available_variants: int


class ServerMessagePayload(BaseModel):
    message: Optional[str] = None
    audio_text: Optional[str] = None
    state: Optional[SessionStateDTO] = None
    error: Optional[str] = None


class ServerMessage(BaseModel):
    type: Literal["assistant", "state_update", "error", "typing", "token"] = Field(description="Type of server message")
    payload: ServerMessagePayload = Field(default_factory=ServerMessagePayload)


# Factory Functions

def create_teacher_message(content: str, message_id: Optional[str] = None, audio_text: Optional[str] = None) -> Message:
    return Message(role="teacher", content=content, message_id=message_id, audio_text=audio_text)


def create_student_message(content: str, message_id: Optional[str] = None) -> Message:
    return Message(role="student", content=content, message_id=message_id)


def create_assistant_response(message: str, audio_text: str | None = None) -> ServerMessage:
    return ServerMessage(type="assistant", payload=ServerMessagePayload(message=message, audio_text=audio_text))


def create_error_response(error: str) -> ServerMessage:
    return ServerMessage(type="error", payload=ServerMessagePayload(error=error))


def create_state_update(state: SessionStateDTO) -> ServerMessage:
    return ServerMessage(type="state_update", payload=ServerMessagePayload(state=state))


def create_token_message(text: str) -> ServerMessage:
    return ServerMessage(type="token", payload=ServerMessagePayload(message=text))


def create_typing_indicator() -> ServerMessage:
    return ServerMessage(type="typing", payload=ServerMessagePayload())
