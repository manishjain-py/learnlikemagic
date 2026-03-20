"""
Integration test: v2 session plan generation.

Calls generate_session_plan() with real guideline + explanation data from DB.
Validates output has correct step types, card references, and misconceptions.

Run:  cd llm-backend && python -m pytest tests/integration/test_session_plan_v2.py -v -s
"""

import json
import pytest
from database import DatabaseManager
from shared.models.entities import Base, TeachingGuideline
from shared.repositories.explanation_repository import ExplanationRepository
from shared.services.llm_config_service import LLMConfigService
from shared.services.llm_service import LLMService
from shared.prompts import PromptLoader
from study_plans.services.generator_service import StudyPlanGeneratorService
from config import get_settings


@pytest.fixture(scope="module")
def db_session():
    db_manager = DatabaseManager()
    session = db_manager.get_session()
    yield session
    session.close()


@pytest.fixture(scope="module")
def generator(db_session):
    """Build a StudyPlanGeneratorService with real LLM config from DB."""
    settings = get_settings()
    config_svc = LLMConfigService(db_session)
    gen_cfg = config_svc.get_config("study_plan_generator")

    llm_service = LLMService(
        api_key=settings.openai_api_key,
        provider=gen_cfg["provider"],
        model_id=gen_cfg["model_id"],
        gemini_api_key=getattr(settings, "gemini_api_key", None),
        anthropic_api_key=getattr(settings, "anthropic_api_key", None),
    )
    return StudyPlanGeneratorService(llm_service, PromptLoader())


@pytest.fixture(scope="module")
def guideline_with_explanations(db_session):
    """Find a real guideline that has pre-computed explanations."""
    explanation_repo = ExplanationRepository(db_session)

    # Find a guideline with explanations
    guidelines = (
        db_session.query(TeachingGuideline)
        .filter(TeachingGuideline.review_status == "APPROVED")
        .limit(20)
        .all()
    )

    for g in guidelines:
        explanations = explanation_repo.get_by_guideline_id(g.id)
        if explanations:
            # Pick the first variant with a summary
            variant = explanations[0]
            summary = variant.summary_json or {}
            card_titles = [
                c.get("title", "") for c in (variant.cards_json or []) if isinstance(c, dict)
            ]

            print(f"\n--- Test Data ---")
            print(f"Guideline: {g.topic_title or g.topic} (grade {g.grade})")
            print(f"Variant: {variant.variant_key} — {variant.variant_label}")
            print(f"Cards: {len(card_titles)}")
            print(f"Teaching notes: {summary.get('teaching_notes', 'N/A')[:100]}...")
            print(f"Analogies: {summary.get('key_analogies', [])}")

            return {
                "guideline": g,
                "explanation_summaries": [summary],
                "card_titles": card_titles,
                "variants_shown": [variant.variant_key],
            }

    pytest.skip("No guideline with pre-computed explanations found in DB")


VALID_V2_TYPES = {"check_understanding", "guided_practice", "independent_practice", "extend"}


class TestSessionPlanV2Generation:

    def test_generates_valid_plan(self, generator, guideline_with_explanations):
        """generate_session_plan() returns a plan with valid v2 structure."""
        data = guideline_with_explanations

        result = generator.generate_session_plan(
            guideline=data["guideline"],
            explanation_summaries=data["explanation_summaries"],
            card_titles=data["card_titles"],
            variants_shown=data["variants_shown"],
        )

        plan = result["plan"]
        print(f"\n--- Generated Plan ---")
        print(json.dumps(plan, indent=2))

        # Basic structure
        assert "steps" in plan
        assert "metadata" in plan
        assert plan["metadata"]["plan_version"] == 2
        assert plan["metadata"]["variants_shown"] == data["variants_shown"]

    def test_has_3_to_5_steps(self, generator, guideline_with_explanations):
        data = guideline_with_explanations
        result = generator.generate_session_plan(
            guideline=data["guideline"],
            explanation_summaries=data["explanation_summaries"],
            card_titles=data["card_titles"],
            variants_shown=data["variants_shown"],
        )
        steps = result["plan"]["steps"]
        assert 3 <= len(steps) <= 5, f"Expected 3-5 steps, got {len(steps)}"

    def test_all_steps_have_v2_types(self, generator, guideline_with_explanations):
        data = guideline_with_explanations
        result = generator.generate_session_plan(
            guideline=data["guideline"],
            explanation_summaries=data["explanation_summaries"],
            card_titles=data["card_titles"],
            variants_shown=data["variants_shown"],
        )
        for step in result["plan"]["steps"]:
            assert step["type"] in VALID_V2_TYPES, (
                f"Step {step['step_id']} has invalid type '{step['type']}'. "
                f"Valid types: {VALID_V2_TYPES}"
            )

    def test_first_step_is_check_understanding(self, generator, guideline_with_explanations):
        data = guideline_with_explanations
        result = generator.generate_session_plan(
            guideline=data["guideline"],
            explanation_summaries=data["explanation_summaries"],
            card_titles=data["card_titles"],
            variants_shown=data["variants_shown"],
        )
        first = result["plan"]["steps"][0]
        assert first["type"] == "check_understanding", (
            f"First step should be check_understanding, got '{first['type']}'"
        )

    def test_steps_have_card_references(self, generator, guideline_with_explanations):
        data = guideline_with_explanations
        result = generator.generate_session_plan(
            guideline=data["guideline"],
            explanation_summaries=data["explanation_summaries"],
            card_titles=data["card_titles"],
            variants_shown=data["variants_shown"],
        )
        steps_with_refs = [
            s for s in result["plan"]["steps"]
            if s.get("card_references") and len(s["card_references"]) > 0
        ]
        assert len(steps_with_refs) >= 1, (
            "At least one step should reference card content"
        )

    def test_steps_have_misconceptions(self, generator, guideline_with_explanations):
        data = guideline_with_explanations
        result = generator.generate_session_plan(
            guideline=data["guideline"],
            explanation_summaries=data["explanation_summaries"],
            card_titles=data["card_titles"],
            variants_shown=data["variants_shown"],
        )
        steps_with_misconceptions = [
            s for s in result["plan"]["steps"]
            if s.get("misconceptions_to_probe") and len(s["misconceptions_to_probe"]) > 0
        ]
        assert len(steps_with_misconceptions) >= 1, (
            "At least one step should probe for misconceptions"
        )

    def test_steps_have_success_criteria(self, generator, guideline_with_explanations):
        data = guideline_with_explanations
        result = generator.generate_session_plan(
            guideline=data["guideline"],
            explanation_summaries=data["explanation_summaries"],
            card_titles=data["card_titles"],
            variants_shown=data["variants_shown"],
        )
        for step in result["plan"]["steps"]:
            assert step.get("success_criteria"), (
                f"Step {step['step_id']} missing success_criteria"
            )

    def test_progressive_difficulty(self, generator, guideline_with_explanations):
        data = guideline_with_explanations
        result = generator.generate_session_plan(
            guideline=data["guideline"],
            explanation_summaries=data["explanation_summaries"],
            card_titles=data["card_titles"],
            variants_shown=data["variants_shown"],
        )
        difficulties = [s.get("difficulty", "easy") for s in result["plan"]["steps"]]
        difficulty_order = {"easy": 0, "medium": 1, "hard": 2}
        values = [difficulty_order.get(d, 0) for d in difficulties]
        # Should be non-decreasing (progressive)
        assert values == sorted(values), (
            f"Difficulty should progress: got {difficulties}"
        )

    def test_adapter_converts_plan(self, generator, guideline_with_explanations):
        """v2 plan dict converts to StudyPlan model via adapter."""
        from tutor.services.topic_adapter import convert_session_plan_to_study_plan

        data = guideline_with_explanations
        result = generator.generate_session_plan(
            guideline=data["guideline"],
            explanation_summaries=data["explanation_summaries"],
            card_titles=data["card_titles"],
            variants_shown=data["variants_shown"],
        )

        study_plan = convert_session_plan_to_study_plan(result["plan"])
        assert study_plan.total_steps >= 3
        for step in study_plan.steps:
            assert step.type in VALID_V2_TYPES
            assert step.description is not None
