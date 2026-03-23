"""Unit tests for study_plans/services — GeneratorService, ReviewerService."""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

from study_plans.services.generator_service import StudyPlanGeneratorService, StudyPlan, StudyPlanStep, StudyPlanMetadata
from study_plans.services.reviewer_service import StudyPlanReviewerService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_guideline():
    """Create a mock TeachingGuideline DB row."""
    g = MagicMock()
    g.id = "g-123"
    g.chapter = "Fractions"
    g.chapter_title = "Fractions"
    g.topic = "Basics"
    g.topic_title = "Basics"
    g.grade = 3
    g.guideline = "Teach fractions with pizza examples."
    g.description = "Teach fractions"
    return g


def _valid_plan_dict():
    return {
        "todo_list": [
            {
                "step_id": "step_1",
                "title": "Pizza Party",
                "description": "Introduce fractions with pizza slices",
                "teaching_approach": "Visual",
                "success_criteria": "Student can identify half",
                "status": "pending",
            },
            {
                "step_id": "step_2",
                "title": "Fraction Quiz",
                "description": "Check understanding",
                "teaching_approach": "Assessment",
                "success_criteria": "Student answers 2/3 correctly",
                "status": "pending",
            },
        ],
        "metadata": {
            "plan_version": 1,
            "estimated_duration_minutes": 30,
            "difficulty_level": "grade-appropriate",
            "is_generic": True,
            "creative_theme": "Food Adventure",
        },
    }


# ---------------------------------------------------------------------------
# Tests — StudyPlanGeneratorService
# ---------------------------------------------------------------------------

class TestStudyPlanGeneratorService:
    def test_generate_plan_success(self):
        llm = MagicMock()
        llm.model_id = "gpt-5.2"
        loader = MagicMock()
        loader.load.return_value = "Generate a plan for {chapter} {topic} grade {grade}. Guidelines: {guideline_text}"

        plan_dict = _valid_plan_dict()
        llm.call.return_value = {
            "output_text": json.dumps(plan_dict),
            "reasoning": None,
        }
        llm.parse_json_response.return_value = plan_dict
        llm.make_schema_strict = MagicMock(return_value={})

        svc = StudyPlanGeneratorService(llm, loader)
        guideline = _make_guideline()

        result = svc.generate_plan(guideline)

        assert "plan" in result
        assert "reasoning" in result
        assert "model" in result
        assert result["model"] == "gpt-5.2"
        assert len(result["plan"]["todo_list"]) == 2
        llm.call.assert_called_once()

    def test_generate_plan_raises_on_llm_error(self):
        llm = MagicMock()
        llm.model_id = "gpt-5.2"
        loader = MagicMock()
        loader.load.return_value = "Generate a plan for {chapter} {topic} grade {grade}. Guidelines: {guideline_text}"
        llm.make_schema_strict = MagicMock(return_value={})
        llm.call.side_effect = RuntimeError("API error")

        svc = StudyPlanGeneratorService(llm, loader)
        guideline = _make_guideline()

        with pytest.raises(RuntimeError, match="API error"):
            svc.generate_plan(guideline)

    def test_validate_plan_schema_rejects_missing_fields(self):
        llm = MagicMock()
        loader = MagicMock()
        llm.make_schema_strict = MagicMock(return_value={})
        svc = StudyPlanGeneratorService(llm, loader)

        with pytest.raises(ValueError, match="Missing required field"):
            svc._validate_plan_schema({"metadata": {}})

    def test_validate_plan_schema_rejects_empty_todo_list(self):
        llm = MagicMock()
        loader = MagicMock()
        llm.make_schema_strict = MagicMock(return_value={})
        svc = StudyPlanGeneratorService(llm, loader)

        with pytest.raises(ValueError, match="cannot be empty"):
            svc._validate_plan_schema({"todo_list": [], "metadata": {}})

    def test_validate_plan_schema_accepts_valid(self):
        llm = MagicMock()
        loader = MagicMock()
        llm.make_schema_strict = MagicMock(return_value={})
        svc = StudyPlanGeneratorService(llm, loader)

        # Should not raise
        svc._validate_plan_schema(_valid_plan_dict())


class TestStudyPlanPydanticModels:
    def test_study_plan_step_model(self):
        step = StudyPlanStep(
            step_id="s1",
            title="Test",
            description="Test desc",
            teaching_approach="Visual",
            success_criteria="Pass",
        )
        assert step.status == "pending"

    def test_study_plan_model(self):
        plan = StudyPlan(
            todo_list=[
                StudyPlanStep(
                    step_id="s1",
                    title="Test",
                    description="Desc",
                    teaching_approach="Visual",
                    success_criteria="Pass",
                )
            ],
            metadata=StudyPlanMetadata(
                estimated_duration_minutes=20,
                difficulty_level="easy",
            ),
        )
        assert len(plan.todo_list) == 1
        assert plan.metadata.plan_version == 1


# ---------------------------------------------------------------------------
# Tests — StudyPlanReviewerService
# ---------------------------------------------------------------------------

class TestStudyPlanReviewerService:
    def test_review_plan_approved(self):
        llm = MagicMock()
        llm.model_id = "gpt-4o"
        loader = MagicMock()
        loader.load.return_value = "Review {chapter} {topic} grade {grade}. Guidelines: {guideline_text}. Plan: {plan_json}"

        review_result = {
            "approved": True,
            "feedback": "Good plan.",
            "suggested_improvements": [],
            "overall_rating": 8,
        }
        llm.call.return_value = {"output_text": json.dumps(review_result), "reasoning": None}
        llm.parse_json_response.return_value = review_result

        svc = StudyPlanReviewerService(llm, loader)
        guideline = _make_guideline()

        result = svc.review_plan(_valid_plan_dict(), guideline)

        assert result["approved"] is True
        assert result["model"] == "gpt-4o"
        assert result["overall_rating"] == 8
        llm.call.assert_called_once()

    def test_review_plan_rejected(self):
        llm = MagicMock()
        loader = MagicMock()
        loader.load.return_value = "Review {chapter} {topic} grade {grade}. Guidelines: {guideline_text}. Plan: {plan_json}"

        review_result = {
            "approved": False,
            "feedback": "Plan is too short.",
            "suggested_improvements": ["Add more steps"],
            "overall_rating": 4,
        }
        llm.call.return_value = {"output_text": json.dumps(review_result), "reasoning": None}
        llm.parse_json_response.return_value = review_result

        svc = StudyPlanReviewerService(llm, loader)
        guideline = _make_guideline()

        result = svc.review_plan(_valid_plan_dict(), guideline)

        assert result["approved"] is False
        assert len(result["suggested_improvements"]) == 1

    def test_review_plan_raises_on_error(self):
        llm = MagicMock()
        loader = MagicMock()
        loader.load.return_value = "Review {chapter} {topic} grade {grade}. Guidelines: {guideline_text}. Plan: {plan_json}"
        llm.call.side_effect = RuntimeError("Review failed")

        svc = StudyPlanReviewerService(llm, loader)
        with pytest.raises(RuntimeError):
            svc.review_plan(_valid_plan_dict(), _make_guideline())


