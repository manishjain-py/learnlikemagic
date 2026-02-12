"""
Session State Models

Complete session state model that tracks all aspects of a tutoring session.
"""

from datetime import datetime
from typing import Literal, Optional, Any
from pydantic import BaseModel, Field
import uuid

from tutor.models.messages import Message, StudentContext
from tutor.models.study_plan import Topic, StudyPlan


MasteryLevel = Literal["not_started", "needs_work", "developing", "adequate", "strong", "mastered"]


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
    concepts_covered: list[str] = Field(default_factory=list)
    last_concept_taught: Optional[str] = None

    # Assessment State
    last_question: Optional[Question] = None
    awaiting_response: bool = False

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

    # Memory
    session_summary: SessionSummary = Field(default_factory=SessionSummary)
    conversation_history: list[Message] = Field(default_factory=list)
    full_conversation_log: list[Message] = Field(default_factory=list)

    @property
    def is_complete(self) -> bool:
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
        if self.current_step < self.topic.study_plan.total_steps:
            self.current_step += 1
            self.updated_at = datetime.utcnow()
            return True
        return False

    def set_question(self, question: Question) -> None:
        self.last_question = question
        self.awaiting_response = True
        self.updated_at = datetime.utcnow()

    def clear_question(self) -> None:
        self.awaiting_response = False
        self.updated_at = datetime.utcnow()

    def increment_turn(self) -> None:
        self.turn_count += 1
        self.updated_at = datetime.utcnow()


def create_session(
    topic: Topic,
    student_context: Optional[StudentContext] = None,
) -> SessionState:
    """Create a new session for a topic."""
    concepts = topic.study_plan.get_concepts()
    mastery_estimates = {concept: 0.0 for concept in concepts}

    return SessionState(
        topic=topic,
        student_context=student_context or StudentContext(),
        mastery_estimates=mastery_estimates,
    )
