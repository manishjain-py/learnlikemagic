"""Data models - re-exports for backward compatibility."""

# SQLAlchemy ORM models
from .database import Base, Session, Event, Content, TeachingGuideline

# Domain models (business logic)
from .domain import (
    StudentPrefs,
    Student,
    Goal,
    HistoryEntry,
    GradingResult,
    TutorState,
    RAGSnippet,
    GuidelineMetadata
)

# API request/response schemas
from .schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    StepRequest,
    StepResponse,
    SummaryResponse,
    GuidelineResponse,
    SubtopicInfo,
    CurriculumResponse
)

__all__ = [
    # Database models
    "Base",
    "Session",
    "Event",
    "Content",
    "TeachingGuideline",
    # Domain models
    "StudentPrefs",
    "Student",
    "Goal",
    "HistoryEntry",
    "GradingResult",
    "TutorState",
    "RAGSnippet",
    "GuidelineMetadata",
    # API schemas
    "CreateSessionRequest",
    "CreateSessionResponse",
    "StepRequest",
    "StepResponse",
    "SummaryResponse",
    "GuidelineResponse",
    "SubtopicInfo",
    "CurriculumResponse"
]
