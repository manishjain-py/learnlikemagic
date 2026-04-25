"""Pydantic API request/response schemas."""
from pydantic import BaseModel, Field
from typing import List, Literal, Dict, Any, Optional

from .domain import Student, Goal, GradingResult


class CreateSessionRequest(BaseModel):
    """Request to create a new learning session."""
    student: Student
    goal: Goal
    mode: Literal["teach_me", "clarify_doubts"] = "teach_me"
    teach_me_mode: Optional[Literal["explain", "baatcheet"]] = None


class CreateSessionResponse(BaseModel):
    """Response with session ID and first teaching turn."""
    session_id: str
    first_turn: Dict[str, Any]
    mode: str = "teach_me"
    teach_me_mode: Optional[Literal["explain", "baatcheet"]] = None
    past_discussions: Optional[list[dict]] = None


# ── Teach Me sub-chooser ──


class TeachMeOptionState(BaseModel):
    """Per-submode availability + in-progress state for the chooser."""
    available: bool
    card_count: Optional[int] = None
    is_stale: bool = False
    in_progress_session_id: Optional[str] = None
    completed_session_id: Optional[str] = None
    current_card_idx: Optional[int] = None
    total_cards: Optional[int] = None
    is_complete: bool = False


class TeachMeOptionsResponse(BaseModel):
    """Response for GET /sessions/teach-me-options — drives the chooser."""
    guideline_id: str
    baatcheet: TeachMeOptionState
    explain: TeachMeOptionState


class CardProgressRequest(BaseModel):
    """Request body for POST /sessions/{id}/card-progress.

    Single endpoint covers fwd/back nav, summary-card completion, and
    optional check-in struggle event sink.
    """
    phase: Literal["card_phase", "dialogue_phase"]
    card_idx: int = Field(..., ge=0, description="0-based card index just navigated to")
    mark_complete: bool = False
    check_in_events: list[Dict[str, Any]] = Field(default_factory=list)


class Personalization(BaseModel):
    """Personalization context surfaced to the frontend on session start.

    Frontend uses these values to substitute `{student_name}` / `{topic_name}`
    in display + audio strings for cards flagged `includes_student_name`.
    """
    student_name: Optional[str] = None
    fallback_student_name: str = "friend"
    topic_name: str


class StepRequest(BaseModel):
    """Request to submit a student's answer."""
    student_reply: str


class StepResponse(BaseModel):
    """Response with next teaching turn and grading info."""
    next_turn: Dict[str, Any]
    routing: str  # "Advance" or "Remediate"
    last_grading: Optional[GradingResult] = None


class SummaryResponse(BaseModel):
    """Session summary with performance metrics."""
    steps_completed: int
    mastery_score: float
    misconceptions_seen: List[str]
    suggestions: List[str]
    concepts_taught: List[str] = []


class GuidelineResponse(BaseModel):
    """Teaching guideline with metadata."""
    id: str
    country: str
    board: str
    grade: int
    subject: str
    chapter: str
    topic: str
    guideline: str
    metadata: Optional["GuidelineMetadata"] = None  # Forward reference
    prior_topics_context: Optional[str] = None


class ChapterInfo(BaseModel):
    """Chapter with summary, sequencing, and topic guideline IDs for progress."""
    chapter: str
    chapter_summary: Optional[str] = None
    chapter_sequence: Optional[int] = None
    topic_count: int = 0
    guideline_ids: List[str] = []
    refresher_guideline_id: Optional[str] = None


class TopicInfo(BaseModel):
    """Topic information with guideline ID, summary, and sequencing."""
    topic: str
    guideline_id: str
    topic_key: Optional[str] = None
    topic_summary: Optional[str] = None
    topic_sequence: Optional[int] = None


class CurriculumResponse(BaseModel):
    """Curriculum discovery response - one of subjects, chapters, or topics."""
    subjects: Optional[List[str]] = None
    chapters: Optional[List[ChapterInfo]] = None
    topics: Optional[List[TopicInfo]] = None


# ── Report Card schemas ──

class ReportCardTopic(BaseModel):
    """Topic-level data for report card."""
    topic: str
    topic_key: str
    guideline_id: Optional[str] = None
    coverage: float                                 # 0-100% from teach_me sessions
    latest_practice_score: Optional[float] = None   # Half-point fractional X in X/Y
    latest_practice_total: Optional[int] = None     # Y in X/Y (usually 10)
    practice_attempt_count: Optional[int] = None    # # of graded attempts for this guideline
    last_studied: Optional[str] = None


class ReportCardChapter(BaseModel):
    """Chapter-level data for report card."""
    chapter: str
    chapter_key: str
    topics: list[ReportCardTopic]


class ReportCardSubject(BaseModel):
    """Subject-level data for report card."""
    subject: str
    chapters: list[ReportCardChapter]


class ReportCardResponse(BaseModel):
    """Complete student report card response."""
    total_sessions: int
    total_chapters_studied: int
    subjects: list[ReportCardSubject]


class ResumableSessionResponse(BaseModel):
    """Response for GET /sessions/resumable."""
    session_id: str
    mode: str = "teach_me"
    teach_me_mode: Optional[Literal["explain", "baatcheet"]] = None
    coverage: float
    current_step: int
    total_steps: int
    concepts_covered: list[str]


class PauseSummary(BaseModel):
    """Response for POST /sessions/{id}/pause."""
    coverage: float
    concepts_covered: list[str]
    message: str


class TopicProgressEntry(BaseModel):
    """Progress for a single topic (used in topic selection indicators)."""
    coverage: float
    session_count: int
    status: str  # "studied" | "not_started"


class TopicProgressResponse(BaseModel):
    """Lightweight topic progress lookup for curriculum picker."""
    user_progress: Dict[str, TopicProgressEntry]


class GuidelineSessionEntry(BaseModel):
    """A session summary for a specific guideline."""
    session_id: str
    mode: str
    teach_me_mode: Optional[Literal["explain", "baatcheet"]] = None
    created_at: Optional[str] = None
    is_complete: bool
    coverage: Optional[float] = None


class GuidelineSessionsResponse(BaseModel):
    """Response for GET /sessions/guideline/{guideline_id}."""
    sessions: list[GuidelineSessionEntry]


# Import GuidelineMetadata for forward reference
from .domain import GuidelineMetadata
GuidelineResponse.model_rebuild()
