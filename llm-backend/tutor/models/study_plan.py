"""
Study Plan Models

Models for topic guidelines and study plans used by the master tutor.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class TopicGuidelines(BaseModel):
    """Curriculum scope guidelines for a topic — what to teach and at what depth."""

    learning_objectives: list[str] = Field(description="What the student should learn")
    required_depth: str = Field(default="conceptual + procedural", description="Depth of understanding required")
    prerequisite_concepts: list[str] = Field(default_factory=list, description="Concepts student should already know")
    common_misconceptions: list[str] = Field(default_factory=list, description="Common mistakes students make")
    scope_boundary: str = Field(default="", description="What is in-scope vs out-of-scope for this grade level")
    prior_topics_context: Optional[str] = Field(
        default=None,
        description="Curriculum context: what prior topics in this chapter cover"
    )


class StudyPlanStep(BaseModel):
    """Individual step in a study plan."""

    step_id: int = Field(ge=1, description="Step number (1-indexed)")
    type: Literal["explain", "check", "practice"] = Field(description="Type of learning activity")
    concept: str = Field(description="Concept being taught or assessed")
    content_hint: Optional[str] = Field(default=None, description="Hint for content generation (explain steps)")
    question_type: Optional[Literal["conceptual", "procedural", "application"]] = Field(
        default=None, description="Type of question (check steps)"
    )
    question_count: Optional[int] = Field(default=None, ge=1, description="Number of questions (practice steps)")

    # Explanation sub-plan fields (only used for explain steps)
    explanation_approach: Optional[str] = Field(default=None, description="Teaching method e.g. 'visual analogy', 'storytelling'")
    explanation_building_blocks: Optional[list[str]] = Field(default=None, description="Ordered sub-ideas to cover across turns")
    explanation_analogy: Optional[str] = Field(default=None, description="Suggested real-world connection")
    min_explanation_turns: int = Field(default=4, description="Minimum tutor turns in explanation before advancing")


class StudyPlan(BaseModel):
    """Complete study plan with ordered steps."""

    steps: list[StudyPlanStep] = Field(description="Ordered list of study steps")

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    def get_step(self, step_id: int) -> Optional[StudyPlanStep]:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def get_concepts(self) -> list[str]:
        seen = {}
        for step in self.steps:
            if step.concept not in seen:
                seen[step.concept] = True
        return list(seen.keys())


class Topic(BaseModel):
    """Complete topic data including guidelines and study plan."""

    topic_id: str = Field(description="Unique topic identifier")
    topic_name: str = Field(description="Human-readable topic name")
    subject: str = Field(description="Subject area")
    grade_level: int = Field(ge=1, le=12, description="Target grade level")
    guidelines: TopicGuidelines = Field(description="Teaching guidelines")
    study_plan: StudyPlan = Field(description="Study plan with steps")


# Factory Functions

def create_explain_step(
    step_id: int,
    concept: str,
    content_hint: str,
    explanation_approach: Optional[str] = None,
    explanation_building_blocks: Optional[list[str]] = None,
    explanation_analogy: Optional[str] = None,
) -> StudyPlanStep:
    return StudyPlanStep(
        step_id=step_id,
        type="explain",
        concept=concept,
        content_hint=content_hint,
        explanation_approach=explanation_approach,
        explanation_building_blocks=explanation_building_blocks,
        explanation_analogy=explanation_analogy,
    )


def create_check_step(
    step_id: int,
    concept: str,
    question_type: Literal["conceptual", "procedural", "application"] = "conceptual",
) -> StudyPlanStep:
    return StudyPlanStep(step_id=step_id, type="check", concept=concept, question_type=question_type)


def create_practice_step(step_id: int, concept: str, question_count: int = 2) -> StudyPlanStep:
    return StudyPlanStep(step_id=step_id, type="practice", concept=concept, question_count=question_count)
