"""
Topic Adapter

Bridges between database models (TeachingGuideline, StudyPlan DB record)
and the new tutor models (Topic, TopicGuidelines, StudyPlan).
"""

import json
import logging
from typing import Optional

from shared.models.schemas import GuidelineResponse
from shared.models.entities import StudyPlan as StudyPlanRecord
from tutor.models.study_plan import (
    Topic,
    TopicGuidelines,
    StudyPlan,
    StudyPlanStep,
)

logger = logging.getLogger("tutor.topic_adapter")


def convert_guideline_to_topic(
    guideline: GuidelineResponse,
    study_plan_record: Optional[StudyPlanRecord] = None,
) -> Topic:
    """
    Convert a DB guideline + study plan into the new Topic model.

    Args:
        guideline: GuidelineResponse from the guideline repository
        study_plan_record: Optional StudyPlan DB record with plan_json

    Returns:
        Topic model ready for the master tutor
    """
    # Build TopicGuidelines from guideline data
    learning_objectives = []
    common_misconceptions = []
    teaching_approach = ""

    if guideline.metadata:
        learning_objectives = guideline.metadata.learning_objectives or []
        common_misconceptions = guideline.metadata.common_misconceptions or []
        teaching_approach = "\n".join(guideline.metadata.scaffolding_strategies or [])

    # If no metadata, extract from guideline text
    if not learning_objectives:
        learning_objectives = [f"Learn about {guideline.subtopic}"]

    if not teaching_approach:
        # Use the full guideline text as teaching approach
        teaching_approach = guideline.guideline[:500] if guideline.guideline else ""

    topic_guidelines = TopicGuidelines(
        learning_objectives=learning_objectives,
        required_depth=guideline.metadata.depth_level if guideline.metadata else "intermediate",
        prerequisite_concepts=guideline.metadata.prerequisites if guideline.metadata else [],
        common_misconceptions=common_misconceptions,
        teaching_approach=teaching_approach,
    )

    # Build StudyPlan from plan_json
    study_plan = _convert_study_plan(study_plan_record, guideline)

    topic_id = f"{guideline.subject}_{guideline.topic}_{guideline.subtopic}".lower().replace(" ", "_")

    return Topic(
        topic_id=guideline.id or topic_id,
        topic_name=f"{guideline.topic} - {guideline.subtopic}",
        subject=guideline.subject,
        grade_level=guideline.grade,
        guidelines=topic_guidelines,
        study_plan=study_plan,
    )


def _convert_study_plan(
    study_plan_record: Optional[StudyPlanRecord],
    guideline: GuidelineResponse,
) -> StudyPlan:
    """Convert DB study plan to new StudyPlan model."""
    if not study_plan_record or not study_plan_record.plan_json:
        # Generate a default study plan
        return _generate_default_plan(guideline)

    try:
        plan_data = json.loads(study_plan_record.plan_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"Failed to parse plan_json for guideline {guideline.id}")
        return _generate_default_plan(guideline)

    # The plan_json format has a "todo_list" with steps
    todo_list = plan_data.get("todo_list", [])
    if not todo_list:
        return _generate_default_plan(guideline)

    steps = []
    for i, item in enumerate(todo_list, start=1):
        # Determine step type from the item's teaching_approach or structure
        step_type = _infer_step_type(item, i, len(todo_list))
        concept = item.get("title", f"Step {i}").strip()
        content_hint = item.get("description", "").strip()

        step = StudyPlanStep(
            step_id=i,
            type=step_type,
            concept=concept,
            content_hint=content_hint if step_type == "explain" else None,
            question_type="conceptual" if step_type == "check" else None,
            question_count=2 if step_type == "practice" else None,
        )
        steps.append(step)

    return StudyPlan(steps=steps)


def _infer_step_type(item: dict, index: int, total: int) -> str:
    """Infer step type from study plan item data."""
    title = item.get("title", "").lower()
    description = item.get("description", "").lower()
    teaching_approach = item.get("teaching_approach", "").lower()

    # Check for explicit type markers
    for text in [title, description, teaching_approach]:
        if any(kw in text for kw in ["practice", "solve", "exercise", "try"]):
            return "practice"
        if any(kw in text for kw in ["check", "quiz", "assess", "test", "verify"]):
            return "check"

    # Pattern: explain, check, explain, check, ... practice at end
    if index == total:
        return "practice"
    elif index % 2 == 0:
        return "check"
    else:
        return "explain"


def _generate_default_plan(guideline: GuidelineResponse) -> StudyPlan:
    """Generate a simple default study plan when no plan exists."""
    subtopic = guideline.subtopic
    return StudyPlan(steps=[
        StudyPlanStep(
            step_id=1,
            type="explain",
            concept=subtopic,
            content_hint=f"Introduce {subtopic} with a concrete example",
        ),
        StudyPlanStep(
            step_id=2,
            type="check",
            concept=subtopic,
            question_type="conceptual",
        ),
        StudyPlanStep(
            step_id=3,
            type="explain",
            concept=subtopic,
            content_hint=f"Deepen understanding of {subtopic}",
        ),
        StudyPlanStep(
            step_id=4,
            type="practice",
            concept=subtopic,
            question_count=2,
        ),
    ])
