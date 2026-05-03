"""Unit tests for the coherent session experience feature.

Covers:
1. teaching_notes propagation in explanation summary
2. Precomputed summary preference for teaching_notes vs fallback
3. BaseAgent._execute_with_prompt existence
4. Master tutor welcome/bridge sanitization
5. Orchestrator welcome/bridge fallback
6. Card-aware pacing directive
7. card_covered_concepts serialization round-trip
"""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from tutor.agents.base_agent import BaseAgent
from tutor.agents.master_tutor import MasterTutorAgent, TutorTurnOutput
from tutor.models.session_state import SessionState, CardPhaseState
from tutor.models.study_plan import StudyPlan, StudyPlanStep, Topic, TopicGuidelines
from tutor.models.messages import StudentContext
from book_ingestion_v2.services.explanation_generator_service import (
    ExplanationSummaryOutput,
    GenerationOutput,
    ExplanationCardOutput,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(**overrides):
    topic = Topic(
        topic_id="t1",
        topic_name="Fractions",
        subject="Math",
        grade_level=5,
        guidelines=TopicGuidelines(learning_objectives=["Understand fractions"]),
        study_plan=StudyPlan(steps=[
            StudyPlanStep(step_id=1, type="explain", concept="fractions"),
            StudyPlanStep(step_id=2, type="check", concept="fractions"),
        ]),
    )
    defaults = dict(
        student_context=StudentContext(grade=5),
        topic=topic,
    )
    defaults.update(overrides)
    return SessionState(**defaults)


def _make_generation_output(teaching_notes="Cards taught fractions via pizza analogy."):
    def _line(text, audio):
        # ExplanationCardOutput now stores content as a list of ExplanationLineOutput
        # (display + audio pair) rather than flat content/audio_text strings.
        return {"display": text, "audio": audio}

    return GenerationOutput(
        cards=[
            ExplanationCardOutput(
                card_idx=1, card_type="concept", title="What is a fraction?",
                lines=[_line("A fraction is a part of a whole.", "A fraction is a part of a whole.")],
            ),
            ExplanationCardOutput(
                card_idx=2, card_type="example", title="Pizza slices",
                lines=[_line("If you cut a pizza into 4 slices and eat 1, you ate 1/4.", "If you cut a pizza into four slices and eat one, you ate one quarter.")],
            ),
            ExplanationCardOutput(
                card_idx=3, card_type="summary", title="Recap",
                lines=[_line("Fractions show parts of a whole.", "Fractions show parts of a whole.")],
            ),
        ],
        summary=ExplanationSummaryOutput(
            key_analogies=["pizza slices"],
            key_examples=["1/4 of a pizza"],
            teaching_notes=teaching_notes,
        ),
    )


def _make_tutor_output(**overrides):
    defaults = dict(
        response="Hello!",
        audio_text="Hello!",
        intent="continuation",
        turn_summary="Greeted student",
        session_complete=True,
        advance_to_step=3,
        mastery_updates=[{"concept": "fractions", "score": 0.9}],
    )
    defaults.update(overrides)
    return TutorTurnOutput(**defaults)


# ===========================================================================
# 1. teaching_notes in explanation summary
# ===========================================================================

def test_teaching_notes_in_summary():
    """_build_summary() propagates teaching_notes from GenerationOutput."""
    from book_ingestion_v2.services.explanation_generator_service import ExplanationGeneratorService

    gen_output = _make_generation_output(teaching_notes="Fractions explained via pizza analogy.")
    variant_config = {"key": "A", "label": "Everyday Analogies", "approach": "analogy-driven"}

    # _build_summary is an instance method; create a minimal instance
    service = ExplanationGeneratorService.__new__(ExplanationGeneratorService)
    result = service._build_summary(gen_output, variant_config)

    assert "teaching_notes" in result
    assert result["teaching_notes"] == "Fractions explained via pizza analogy."


# ===========================================================================
# 2. precomputed summary uses teaching_notes
# ===========================================================================

def test_precomputed_summary_uses_teaching_notes():
    """_build_precomputed_summary() prefers teaching_notes when available."""
    from tutor.services.session_service import SessionService

    session = _make_session(
        card_phase=CardPhaseState(
            guideline_id="g1",
            active=False,
            variants_shown=["A"],
            available_variant_keys=["A", "B"],
        ),
    )

    mock_explanation = MagicMock()
    mock_explanation.summary_json = {
        "approach_label": "Everyday Analogies",
        "teaching_notes": "Fractions explained via pizza.",
        "card_titles": ["What is a fraction?"],
        "key_analogies": ["pizza"],
        "key_examples": ["1/4"],
    }

    mock_repo = MagicMock()
    mock_repo.get_variant.return_value = mock_explanation

    svc = SessionService.__new__(SessionService)
    with patch("tutor.services.session_service.ExplanationRepository", return_value=mock_repo):
        svc.db = MagicMock()
        result = svc._build_precomputed_summary(session)

    assert "Fractions explained via pizza." in result
    # Should NOT contain fallback structured labels when teaching_notes present
    assert "Topics covered:" not in result


# ===========================================================================
# 3. precomputed summary fallback
# ===========================================================================

def test_precomputed_summary_fallback():
    """Falls back to structured labels when teaching_notes is absent."""
    from tutor.services.session_service import SessionService

    session = _make_session(
        card_phase=CardPhaseState(
            guideline_id="g1",
            active=False,
            variants_shown=["A"],
            available_variant_keys=["A", "B"],
        ),
    )

    mock_explanation = MagicMock()
    mock_explanation.summary_json = {
        "approach_label": "Everyday Analogies",
        "teaching_notes": "",
        "card_titles": ["What is a fraction?"],
        "key_analogies": ["pizza"],
        "key_examples": ["1/4"],
    }

    mock_repo = MagicMock()
    mock_repo.get_variant.return_value = mock_explanation

    svc = SessionService.__new__(SessionService)
    with patch("tutor.services.session_service.ExplanationRepository", return_value=mock_repo):
        svc.db = MagicMock()
        result = svc._build_precomputed_summary(session)

    assert "Topics covered:" in result
    assert "Analogies used:" in result


# ===========================================================================
# 4. BaseAgent._execute_with_prompt exists
# ===========================================================================

def test_execute_with_prompt_exists():
    """BaseAgent has _execute_with_prompt method."""
    assert hasattr(BaseAgent, "_execute_with_prompt")
    assert callable(getattr(BaseAgent, "_execute_with_prompt"))


# ===========================================================================
# 5. Master tutor welcome sanitization
# ===========================================================================

@pytest.mark.asyncio
async def test_master_tutor_welcome_sanitizes_output():
    """generate_welcome() zeroes session_complete, advance_to_step, mastery_updates."""
    mock_llm = MagicMock()
    agent = MasterTutorAgent(llm_service=mock_llm)

    raw_output = _make_tutor_output(
        session_complete=True,
        advance_to_step=3,
        mastery_updates=[{"concept": "fractions", "score": 0.9}],
    )

    with patch.object(agent, "_execute_with_prompt", new_callable=AsyncMock, return_value=raw_output):
        session = _make_session()
        output = await agent.generate_welcome(session)

    assert output.session_complete is False
    assert output.advance_to_step is None
    assert output.mastery_updates == []


# ===========================================================================
# 6. Master tutor bridge sanitization
# ===========================================================================

@pytest.mark.asyncio
async def test_master_tutor_bridge_sanitizes_output():
    """generate_bridge() zeroes dangerous fields."""
    mock_llm = MagicMock()
    agent = MasterTutorAgent(llm_service=mock_llm)

    raw_output = _make_tutor_output(
        session_complete=True,
        advance_to_step=5,
        mastery_updates=[{"concept": "fractions", "score": 0.8}],
    )

    with patch.object(agent, "_execute_with_prompt", new_callable=AsyncMock, return_value=raw_output):
        session = _make_session()
        output = await agent.generate_bridge(session, bridge_type="understood")

    assert output.session_complete is False
    assert output.advance_to_step is None
    assert output.mastery_updates == []


# ===========================================================================
# 7. Orchestrator welcome fallback
# ===========================================================================

@pytest.mark.asyncio
async def test_welcome_fallback_on_error():
    """Orchestrator returns hardcoded welcome when master tutor fails."""
    from tutor.orchestration.orchestrator import TeacherOrchestrator

    mock_llm = MagicMock()
    orchestrator = TeacherOrchestrator(llm_service=mock_llm)

    orchestrator.master_tutor = MagicMock()
    orchestrator.master_tutor.set_session = MagicMock()
    orchestrator.master_tutor.generate_welcome = AsyncMock(side_effect=Exception("LLM failed"))

    session = _make_session()
    result_text, result_audio = await orchestrator.generate_tutor_welcome(session)

    assert isinstance(result_text, str)
    assert len(result_text) > 0


# ===========================================================================
# 8. Orchestrator bridge fallback
# ===========================================================================

@pytest.mark.asyncio
async def test_bridge_fallback_on_error():
    """Orchestrator returns hardcoded bridge when master tutor fails."""
    from tutor.orchestration.orchestrator import TeacherOrchestrator

    mock_llm = MagicMock()
    orchestrator = TeacherOrchestrator(llm_service=mock_llm)

    orchestrator.master_tutor = MagicMock()
    orchestrator.master_tutor.set_session = MagicMock()
    orchestrator.master_tutor.generate_bridge = AsyncMock(side_effect=Exception("LLM failed"))

    session = _make_session()
    result = await orchestrator.generate_bridge_turn(session, bridge_type="understood")

    assert isinstance(result.response, str)
    assert len(result.response) > 0


# ===========================================================================
# 9. Card-aware pacing per concept
# ===========================================================================

def test_card_aware_pacing_per_concept():
    """QUICK-CHECK pacing when concept in card_covered_concepts."""
    mock_llm = MagicMock()
    agent = MasterTutorAgent(llm_service=mock_llm)

    session = _make_session(
        card_covered_concepts={"fractions"},
        turn_count=2,
        current_step=1,
    )

    result = agent._compute_pacing_directive(session)

    assert "QUICK-CHECK" in result


# ===========================================================================
# 10. No quick-check for uncovered concept
# ===========================================================================

def test_pacing_no_quickcheck_uncovered_concept():
    """Normal explain pacing when concept NOT in card_covered_concepts."""
    mock_llm = MagicMock()
    agent = MasterTutorAgent(llm_service=mock_llm)

    session = _make_session(
        card_covered_concepts={"fractions"},
        turn_count=2,
        current_step=1,
    )
    # Change the explain step's concept to something NOT in card_covered_concepts
    session.topic.study_plan.steps[0].concept = "addition"

    result = agent._compute_pacing_directive(session)

    assert "QUICK-CHECK" not in result


# ===========================================================================
# 11. card_covered_concepts serialization round-trip
# ===========================================================================

def test_card_covered_concepts_round_trip():
    """card_covered_concepts survives JSON round-trip."""
    session = _make_session(card_covered_concepts={"fractions", "decimals"})

    serialized = session.model_dump_json()
    restored = SessionState.model_validate_json(serialized)

    assert restored.card_covered_concepts == {"fractions", "decimals"}
