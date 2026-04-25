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

SessionMode = Literal["teach_me", "clarify_doubts"]

# Submode within Teach Me. Only meaningful when mode == "teach_me".
TeachMeMode = Literal["explain", "baatcheet"]

ExplanationPhaseName = Literal["not_started", "opening", "explaining", "informal_check", "complete"]


class RemedialCard(BaseModel):
    """A dynamically generated simplified explanation card."""
    card_id: str = Field(description="Stable ID, e.g. 'remedial_A_3_1'")
    source_card_idx: int = Field(description="Base card index this simplifies")
    depth: int = Field(description="Simplification depth (1 or 2)")
    card: dict = Field(description="ExplanationCard content dict (title, content, audio_text, card_type)")


class ConfusionEvent(BaseModel):
    """Tracks a student's confusion on a specific card."""
    base_card_idx: int = Field(description="Which card confused the student")
    base_card_title: str = Field(description="Title for human readability")
    depth_reached: int = Field(default=0, description="How many simplifications were tried")
    escalated: bool = Field(default=False, description="Whether it escalated to interactive mode")


class CheckInStruggleEvent(BaseModel):
    """Tracks a student's struggles on a check-in activity."""
    card_idx: int = Field(description="Check-in card index (1-based)")
    card_title: str = Field(description="Check-in title for readability")
    activity_type: str = Field(default="match_pairs", description="Activity type: pick_one, true_false, fill_blank, match_pairs, sort_buckets, sequence")
    wrong_count: int = Field(default=0, description="Total wrong attempts")
    hints_shown: int = Field(default=0, description="Times hint was displayed")
    confused_pairs: list[dict] = Field(
        default_factory=list,
        description="Struggle details: [{left, right, wrong_count, wrong_picks}]"
    )
    auto_revealed: int = Field(default=0, description="Items auto-revealed by safety valve")


class CardPhaseState(BaseModel):
    """Tracks card-based explanation phase for pre-computed explanations."""
    guideline_id: str = Field(description="FK for explanation lookups (NOT topic_id)")
    active: bool = Field(default=True, description="Whether card phase is currently active")
    current_variant_key: str = Field(default="A", description="Current variant being shown")
    current_card_idx: int = Field(default=0, description="Current card index (0-based)")
    total_cards: int = Field(default=0, description="Total cards in current variant")
    variants_shown: list[str] = Field(default_factory=list, description="Variant keys already shown")
    available_variant_keys: list[str] = Field(default_factory=list, description="All available variant keys")
    completed: bool = Field(default=False, description="True when student says 'clear' or exhausts variants")
    remedial_cards: dict[int, list[RemedialCard]] = Field(
        default_factory=dict,
        description="Maps base card_idx to ordered list of generated remedial cards"
    )
    confusion_events: list[ConfusionEvent] = Field(
        default_factory=list,
        description="Per-card confusion tracking for tutor context"
    )
    check_in_struggles: list[CheckInStruggleEvent] = Field(
        default_factory=list,
        description="Per-check-in struggle tracking for tutor context"
    )


class DialoguePhaseState(BaseModel):
    """Tracks card-based dialogue phase for Baatcheet sessions.

    Sibling to CardPhaseState (Explain mode). Kept separate because
    CardPhaseState carries variant-aware fields (current_variant_key,
    variants_shown, remedial_cards) that don't apply to Baatcheet.
    """
    guideline_id: str = Field(description="FK for dialogue lookups")
    active: bool = Field(default=True, description="Whether dialogue phase is currently active")
    current_card_idx: int = Field(default=0, description="Current card index (0-based)")
    total_cards: int = Field(default=0, description="Total cards in dialogue")
    completed: bool = Field(default=False, description="True when student saw the summary card")
    last_visited_at: Optional[datetime] = Field(
        default=None, description="When the student last advanced (used for resume CTA)"
    )
    check_in_struggles: list[CheckInStruggleEvent] = Field(
        default_factory=list,
        description="Per-check-in struggle tracking, mirrors CardPhaseState.check_in_struggles",
    )


class ExplanationPhase(BaseModel):
    """Tracks the explanation lifecycle for a single concept."""

    concept: str = Field(description="Concept being explained")
    step_id: int = Field(description="Study plan step ID for this explanation")
    phase: ExplanationPhaseName = Field(default="not_started", description="Current phase of explanation")
    tutor_turns_in_phase: int = Field(default=0, description="Tutor turns spent in explanation so far")
    building_blocks_covered: list[str] = Field(default_factory=list, description="Building blocks already covered")
    student_engaged: bool = Field(default=False, description="Whether student has shown engagement")
    informal_check_passed: bool = Field(default=False, description="Whether informal understanding check passed")
    skip_reason: Optional[str] = Field(default=None, description="Reason explanation was skipped e.g. 'student_demonstrated_knowledge'")


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
    teach_me_mode: TeachMeMode = Field(
        default="explain",
        description="Submode within Teach Me; only meaningful when mode == 'teach_me'",
    )
    is_paused: bool = Field(default=False, description="Whether this Teach Me session is paused")

    # Coverage tracking
    concepts_covered_set: set[str] = Field(
        default_factory=set,
        description="Set of concept names covered in this session"
    )

    # Clarify Doubts state
    concepts_discussed: list[str] = Field(
        default_factory=list,
        description="Concepts discussed in this Clarify Doubts session"
    )
    clarify_complete: bool = Field(
        default=False,
        description="Whether this Clarify Doubts session has been ended by the student"
    )
    is_refresher: bool = False

    # Card Phase (pre-computed explanations)
    card_phase: Optional[CardPhaseState] = Field(
        default=None, description="Card-based explanation phase state (pre-computed explanations)"
    )
    # Dialogue Phase (Baatcheet) — sibling of card_phase
    dialogue_phase: Optional[DialoguePhaseState] = Field(
        default=None, description="Card-based dialogue phase state (Baatcheet)"
    )
    precomputed_explanation_summary: Optional[str] = Field(
        default=None, description="Summary of pre-computed explanations shown, for tutor context injection"
    )
    card_covered_concepts: set[str] = Field(
        default_factory=set,
        description="Concepts covered during card phase, for cross-phase context"
    )

    # Explanation tracking
    explanation_phases: dict[str, ExplanationPhase] = Field(
        default_factory=dict, description="Per-concept explanation phase tracking (keyed by concept name)"
    )
    current_explanation_concept: Optional[str] = Field(
        default=None, description="Which concept is currently being explained"
    )

    # Memory
    session_summary: SessionSummary = Field(default_factory=SessionSummary)
    conversation_history: list[Message] = Field(default_factory=list)
    full_conversation_log: list[Message] = Field(default_factory=list)

    @field_validator("concepts_covered_set", "card_covered_concepts", mode="before")
    @classmethod
    def _coerce_to_set(cls, v):
        if isinstance(v, list):
            return set(v)
        return v

    @property
    def is_complete(self) -> bool:
        """Single source of truth for session completion across all modes."""
        if self.mode == "clarify_doubts":
            return self.clarify_complete
        # teach_me
        if not self.topic:
            return False
        if self.is_refresher:
            return self.card_phase is not None and self.card_phase.completed
        # Baatcheet submode — completion gated on dialogue_phase
        if self.teach_me_mode == "baatcheet":
            return self.dialogue_phase is not None and self.dialogue_phase.completed
        # Card-based Teach Me (Explain): complete when card phase is done
        if self.card_phase is not None:
            return self.card_phase.completed
        # v1 fallback (non-card sessions, out of scope but preserved for legacy data)
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

    # --- Card phase helpers ---

    def is_in_card_phase(self) -> bool:
        """Check if the session is currently in the card-based explanation phase."""
        return self.card_phase is not None and self.card_phase.active

    def complete_card_phase(self):
        """Mark card phase as completed."""
        if self.card_phase:
            self.card_phase.active = False
            self.card_phase.completed = True
            self.updated_at = datetime.utcnow()

    # --- Dialogue phase helpers (Baatcheet) ---

    def is_in_dialogue_phase(self) -> bool:
        """Check if the session is currently in the dialogue (Baatcheet) phase."""
        return self.dialogue_phase is not None and self.dialogue_phase.active

    def complete_dialogue_phase(self) -> None:
        """Mark dialogue phase as completed."""
        if self.dialogue_phase:
            self.dialogue_phase.active = False
            self.dialogue_phase.completed = True
            self.updated_at = datetime.utcnow()

    # --- Explanation phase helpers ---

    def start_explanation(self, concept: str, step_id: int) -> ExplanationPhase:
        """Initialize explanation tracking for a concept."""
        phase = ExplanationPhase(concept=concept, step_id=step_id, phase="opening")
        self.explanation_phases[concept] = phase
        self.current_explanation_concept = concept
        self.updated_at = datetime.utcnow()
        return phase

    def get_current_explanation(self) -> Optional[ExplanationPhase]:
        """Get the ExplanationPhase for the currently active concept."""
        if not self.current_explanation_concept:
            return None
        return self.explanation_phases.get(self.current_explanation_concept)

    def is_in_explanation_phase(self) -> bool:
        """Check if we are currently in an active explanation."""
        ep = self.get_current_explanation()
        return ep is not None and ep.phase not in ("not_started", "complete")

    def can_advance_past_explanation(self) -> bool:
        """Check if the current explanation is complete enough to advance."""
        ep = self.get_current_explanation()
        if ep is None:
            return True  # no explanation tracking → allow advancement
        if ep.phase == "complete":
            return True
        if ep.skip_reason:
            return True  # student demonstrated prior knowledge
        if ep.informal_check_passed:
            return True
        # Check minimum turns AND building blocks coverage
        step = self.current_step_data
        min_turns = step.min_explanation_turns if step and hasattr(step, 'min_explanation_turns') else 4
        blocks = step.explanation_building_blocks if step and hasattr(step, 'explanation_building_blocks') else None
        blocks_all_covered = not blocks or all(b in ep.building_blocks_covered for b in blocks)
        if ep.tutor_turns_in_phase >= min_turns and ep.phase == "informal_check" and blocks_all_covered:
            return True
        return False


def create_session(
    topic: Topic,
    student_context: Optional[StudentContext] = None,
    mode: SessionMode = "teach_me",
) -> SessionState:
    """Create a new session for a topic."""
    concepts = topic.study_plan.get_concepts()
    # Seed mastery for teach_me which uses per-concept mastery tracking.
    if mode == "teach_me":
        mastery_estimates = {concept: 0.0 for concept in concepts}
    else:
        mastery_estimates = {}

    return SessionState(
        topic=topic,
        student_context=student_context or StudentContext(),
        mastery_estimates=mastery_estimates,
        mode=mode,
    )
