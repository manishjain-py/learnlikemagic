"""Domain models for business logic."""
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class StudentPrefs(BaseModel):
    """Student preferences."""
    style: Optional[str] = "standard"  # simple, standard, challenge
    lang: Optional[str] = "en"


class Student(BaseModel):
    """Student profile."""
    id: str
    grade: int
    prefs: Optional[StudentPrefs] = None


class Goal(BaseModel):
    """Learning goal for a session."""
    topic: str
    syllabus: str  # e.g., "CBSE Grade 3 Math"
    learning_objectives: List[str]
    guideline_id: Optional[str] = None  # Reference to TeachingGuideline


class HistoryEntry(BaseModel):
    """Conversation history entry."""
    role: str  # "teacher" or "student"
    msg: str
    meta: Optional[Dict[str, Any]] = None


class GradingResult(BaseModel):
    """Grading result from check node."""
    score: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    labels: List[str] = Field(default_factory=list)  # misconception labels
    confidence: float = Field(..., ge=0.0, le=1.0)


class TutorState(BaseModel):
    """Complete tutor state - the core domain model."""
    session_id: str
    student: Student
    goal: Goal
    step_idx: int = 0
    history: List[HistoryEntry] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)  # misconceptions collected
    mastery_score: float = 0.0
    last_grading: Optional[GradingResult] = None
    next_action: Optional[str] = None  # "present", "check", etc.

    class Config:
        arbitrary_types_allowed = True


class RAGSnippet(BaseModel):
    """Represents a retrieved content snippet."""
    id: str
    text: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class GuidelineMetadata(BaseModel):
    """Metadata for teaching guidelines."""
    learning_objectives: List[str] = Field(default_factory=list)
    depth_level: str = "intermediate"  # basic, intermediate, advanced
    prerequisites: List[str] = Field(default_factory=list)
    common_misconceptions: List[str] = Field(default_factory=list)
    scaffolding_strategies: List[str] = Field(default_factory=list)
    assessment_criteria: Dict[str, str] = Field(default_factory=dict)
