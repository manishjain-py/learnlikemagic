"""
Session State Models

Complete session state model that tracks all aspects of a tutoring session.
"""

from datetime import datetime
from typing import Literal, Optional, Any
from pydantic import BaseModel, Field, field_validator
import uuid

from tutor.models.messages import Message, StudentContext
from tutor.models.study_plan import Topic, StudyPlan


MasteryLevel = Literal["not_started", "needs_work", "developing", "adequate", "strong", "mastered"]

SessionMode = Literal["teach_me", "clarify_doubts", "exam"]


class Misconception(BaseModel):
    """A detected student misconception."""

    concept: str = Field(description="Related concept")
    description: str = Field(description="Description of the misconception")
    detected_at: datetime = Field(default_factory=datetime.utcnow, description="When misconception was detected")
    resolved: bool = Field(default=False, description="Whether misconception has been addressed")


class Question(BaseModel):
    """A question asked to the student."""

    question_text: str = Field(description="The question asked")
    expected_answer: str = Field(description="Expected/correct answer")
    concept: str = Field(description="Concept being tested")
    rubric: str = Field(default="", description="Evaluation criteria")
    hints: list[str] = Field(default_factory=list, description="Available hints")
    hints_used: int = Field(default=0, description="Number of hints provided")
    wrong_attempts: int = Field(default=0, description="Number of wrong attempts on this question")
    previous_student_answers: list[str] = Field(default_factory=list, description="Student's previous wrong answers")
    phase: str = Field(default="asked", description="Lifecycle phase: asked, probe, hint, explain")


class ExamQuestion(BaseModel):
    """A single exam question with its result."""
    question_idx: int
    question_text: str
    concept: str
    difficulty: Literal["easy", "medium", "hard"]
    question_type: Literal["conceptual", "procedural", "application", "real_world", "error_spotting", "reasoning"]
    expected_answer: str
    student_answer: Optional[str] = None
    result: Optional[Literal["correct", "partial", "incorrect"]] = None
    feedback: str = ""
    score: float = 0.0
    marks_rationale: str = ""


class ExamFeedback(BaseModel):
    """Post-exam evaluation feedback."""
    score: float
    total: int
    percentage: float
    strengths: list[str]
    weak_areas: list[str]
    patterns: list[str]
    next_steps: list[str]


class SessionSummary(BaseModel):
    """Running summary/memory of the session."""

    turn_timeline: list[str] = Field(default_factory=list, description="Compact narrative timeline of each turn")
    concepts_taught: list[str] = Field(default_factory=list, description="Concepts that have been explained")
    depth_reached: dict[str, str] = Field(default_factory=dict, description="Depth reached per concept")
    examples_used: list[str] = Field(default_factory=list, description="Examples used (avoid repetition)")
    analogies_used: list[str] = Field(default_factory=list, description="Analogies used")
    student_responses_summary: list[str] = Field(default_factory=list, description="Summary of key student responses")
    progress_trend: Literal["improving", "steady", "struggling"] = Field(
        default="steady", description="Overall progress trend"
    )
    stuck_points: list[str] = Field(default_factory=list, description="Areas where student struggled")
    what_helped: list[str] = Field(default_factory=list, description="What helped overcome stuck points")
    next_focus: Optional[str] = Field(default=None, description="Recommended next focus area")


class SessionState(BaseModel):
    """Complete session state for a tutoring session."""

    # Identification
    session_id: str = Field(
        default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}",
        description="Unique session identifier",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    turn_count: int = Field(default=0)

    # Topic & Plan
    topic: Optional[Topic] = Field(default=None, description="Topic being taught")

    # Progress Tracking
    current_step: int = Field(default=1, ge=1, description="Current step in study plan (1-indexed)")
    last_concept_taught: Optional[str] = None

    # Assessment State
    last_question: Optional[Question] = None
    awaiting_response: bool = False
    allow_extension: bool = Field(default=True, description="Allow tutor to continue past study plan for advanced students")

    # Mastery Tracking
    mastery_estimates: dict[str, float] = Field(default_factory=dict, description="Mastery score (0-1) per concept")
    misconceptions: list[Misconception] = Field(default_factory=list)
    weak_areas: list[str] = Field(default_factory=list)

    # Personalization
    student_context: StudentContext = Field(default_factory=StudentContext)
    pace_preference: Literal["slow", "normal", "fast"] = "normal"

    # Behavioral Tracking
    off_topic_count: int = 0
    warning_count: int = 0
    safety_flags: list[str] = Field(default_factory=list)

    # Mode and pause state
    mode: SessionMode = Field(default="teach_me", description="Session mode")
    is_paused: bool = Field(default=False, description="Whether this Teach Me session is paused")

    # Coverage tracking
    concepts_covered_set: set[str] = Field(
        default_factory=set,
        description="Set of concept names covered in this session"
    )

    # Exam state
    exam_questions: list[ExamQuestion] = Field(default_factory=list)
    exam_current_question_idx: int = Field(default=0)
    exam_total_correct: int = Field(default=0)
    exam_total_partial: int = Field(default=0)
    exam_total_incorrect: int = Field(default=0)
    exam_finished: bool = Field(default=False)
    exam_feedback: Optional[ExamFeedback] = Field(default=None)

    # Clarify Doubts state
    concepts_discussed: list[str] = Field(
        default_factory=list,
        description="Concepts discussed in this Clarify Doubts session"
    )
    clarify_complete: bool = Field(
        default=False,
        description="Whether this Clarify Doubts session has been ended by the student"
    )

    # Memory
    session_summary: SessionSummary = Field(default_factory=SessionSummary)
    conversation_history: list[Message] = Field(default_factory=list)
    full_conversation_log: list[Message] = Field(default_factory=list)

    @field_validator("concepts_covered_set", mode="before")
    @classmethod
    def _coerce_to_set(cls, v):
        if isinstance(v, list):
            return set(v)
        return v

    @property
    def is_complete(self) -> bool:
        if self.mode == "clarify_doubts":
            return self.clarify_complete
        if not self.topic:
            return False
        return self.current_step > self.topic.study_plan.total_steps

    @property
    def current_step_data(self) -> Optional[Any]:
        if not self.topic:
            return None
        return self.topic.study_plan.get_step(self.current_step)

    @property
    def progress_percentage(self) -> float:
        if not self.topic or self.topic.study_plan.total_steps == 0:
            return 0.0
        return min(100.0, (self.current_step - 1) / self.topic.study_plan.total_steps * 100)

    @property
    def overall_mastery(self) -> float:
        if not self.mastery_estimates:
            return 0.0
        return sum(self.mastery_estimates.values()) / len(self.mastery_estimates)

    @property
    def coverage_percentage(self) -> float:
        if not self.topic or not self.topic.study_plan:
            return 0.0
        all_concepts = self.topic.study_plan.get_concepts()
        if not all_concepts:
            return 0.0
        covered = len(self.concepts_covered_set & set(all_concepts))
        return round(covered / len(all_concepts) * 100, 1)

    def get_current_turn_id(self) -> str:
        return f"turn_{self.turn_count + 1}"

    def add_message(self, message: Message) -> None:
        self.conversation_history.append(message)
        self.full_conversation_log.append(message)
        max_history = 10
        if len(self.conversation_history) > max_history:
            self.conversation_history = self.conversation_history[-max_history:]

    def update_mastery(self, concept: str, score: float) -> None:
        self.mastery_estimates[concept] = max(0.0, min(1.0, score))
        self.updated_at = datetime.utcnow()

    def add_misconception(self, concept: str, description: str) -> None:
        self.misconceptions.append(Misconception(concept=concept, description=description))
        if concept not in self.weak_areas:
            self.weak_areas.append(concept)
        self.updated_at = datetime.utcnow()

    def advance_step(self) -> bool:
        if not self.topic:
            return False
        if self.current_step <= self.topic.study_plan.total_steps:
            self.current_step += 1
            self.updated_at = datetime.utcnow()
            return True
        return False

    def set_question(self, question: Question) -> None:
        self.last_question = question
        self.awaiting_response = True
        self.updated_at = datetime.utcnow()

    def clear_question(self) -> None:
        self.last_question = None
        self.awaiting_response = False
        self.updated_at = datetime.utcnow()

    def increment_turn(self) -> None:
        self.turn_count += 1
        self.updated_at = datetime.utcnow()


def create_session(
    topic: Topic,
    student_context: Optional[StudentContext] = None,
    mode: SessionMode = "teach_me",
) -> SessionState:
    """Create a new session for a topic."""
    concepts = topic.study_plan.get_concepts()
    mastery_estimates = {concept: 0.0 for concept in concepts} if mode == "teach_me" else {}

    return SessionState(
        topic=topic,
        student_context=student_context or StudentContext(),
        mastery_estimates=mastery_estimates,
        mode=mode,
    )
