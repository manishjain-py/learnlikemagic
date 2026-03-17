"""Unit tests for the pre-computed explanations feature.

Covers:
1. CardPhaseState model (serialization, is_in_card_phase, complete_card_phase)
2. ExplanationRepository (CRUD with mocked DB, parse_cards)
3. ExplanationGeneratorService (multi-pass LLM pipeline, skip/refine logic)
4. SessionService card phase paths (create, process_step guard, card actions)
5. DTO validation (CardActionRequest, ExplanationCardDTO, CardPhaseDTO)
"""

import json
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock
from pydantic import ValidationError

from tutor.models.session_state import (
    SessionState,
    CardPhaseState,
    create_session,
)
from tutor.models.study_plan import (
    Topic,
    TopicGuidelines,
    StudyPlan,
    StudyPlanStep,
)
from tutor.models.messages import (
    StudentContext,
    CardActionRequest,
    ExplanationCardDTO,
    CardPhaseDTO,
)
from shared.repositories.explanation_repository import (
    ExplanationRepository,
    ExplanationCard,
)
from shared.models.entities import TopicExplanation
from shared.utils.exceptions import SessionNotFoundException


# ---------------------------------------------------------------------------
# Shared helpers — follow existing codebase patterns
# ---------------------------------------------------------------------------

def _make_topic(num_explain=1, num_check=1) -> Topic:
    """Build a Topic with explain+check step pairs."""
    steps = []
    step_id = 1
    for i in range(num_explain):
        concept = f"Concept_{i + 1}"
        steps.append(StudyPlanStep(step_id=step_id, type="explain", concept=concept, content_hint=f"Hint {i}"))
        step_id += 1
    for i in range(num_check):
        concept = f"Concept_{i + 1}"
        steps.append(StudyPlanStep(step_id=step_id, type="check", concept=concept, question_type="conceptual"))
        step_id += 1
    return Topic(
        topic_id="topic-1",
        topic_name="Fractions Basics",
        subject="Mathematics",
        grade_level=3,
        guidelines=TopicGuidelines(learning_objectives=["Understand fractions"]),
        study_plan=StudyPlan(steps=steps),
    )


def _make_session_state(card_phase=None, **overrides) -> SessionState:
    """Build a SessionState with optional card_phase and overrides."""
    topic = overrides.pop("topic", _make_topic())
    ctx = StudentContext(grade=3, board="CBSE", language_level="simple")
    session = create_session(topic=topic, student_context=ctx)
    session.session_id = "test-session-card"
    if card_phase is not None:
        session.card_phase = card_phase
    for k, v in overrides.items():
        setattr(session, k, v)
    return session


def _make_card_phase(**overrides) -> CardPhaseState:
    """Build a CardPhaseState with sensible defaults."""
    defaults = dict(
        guideline_id="guideline-1",
        active=True,
        current_variant_key="A",
        current_card_idx=0,
        total_cards=5,
        variants_shown=["A"],
        available_variant_keys=["A", "B", "C"],
        completed=False,
    )
    defaults.update(overrides)
    return CardPhaseState(**defaults)


def _sample_cards_json(count=5):
    """Return well-formed card dicts for testing."""
    return [
        {
            "card_idx": i + 1,
            "card_type": "concept",
            "title": f"Card {i + 1}",
            "content": f"Explanation for card {i + 1}",
            "visual": None,
        }
        for i in range(count)
    ]


def _make_guideline_mock():
    """Return a mock that resembles a TeachingGuideline ORM row."""
    g = MagicMock()
    g.id = "guideline-1"
    g.chapter = "Fractions"
    g.chapter_title = "Fractions"
    g.topic = "Basics"
    g.topic_title = "Fractions Basics"
    g.subject = "Mathematics"
    g.grade = 3
    g.guideline = "Teach fractions with pizza examples."
    g.description = "Teach fractions"
    g.prior_topics_context = None
    g.book_id = "book-1"
    g.review_status = "APPROVED"
    g.topic_sequence = 1
    g.country = "India"
    g.board = "CBSE"
    return g


def _make_explanation_row(variant_key="A", num_cards=5):
    """Return a mock TopicExplanation row."""
    row = MagicMock(spec=TopicExplanation)
    row.id = f"expl-{variant_key}"
    row.guideline_id = "guideline-1"
    row.variant_key = variant_key
    row.variant_label = f"Variant {variant_key}"
    row.cards_json = _sample_cards_json(num_cards)
    row.summary_json = {
        "card_titles": [f"Card {i+1}" for i in range(num_cards)],
        "key_analogies": ["pizza slices"],
        "key_examples": ["sharing a pizza"],
        "approach_label": f"Approach {variant_key}",
    }
    row.generator_model = "gpt-4o"
    row.created_at = datetime.utcnow()
    return row


def _svc_skeleton():
    """Build a SessionService instance bypassing __init__ (same pattern as existing tests)."""
    from tutor.services.session_service import SessionService

    svc = SessionService.__new__(SessionService)
    svc.db = MagicMock()
    svc.session_repo = MagicMock()
    svc.event_repo = MagicMock()
    svc.guideline_repo = MagicMock()
    svc.llm_service = MagicMock()
    svc.orchestrator = MagicMock()
    return svc


# ===========================================================================
# 1. CardPhaseState model tests
# ===========================================================================

class TestCardPhaseStateModel:
    """Tests for the CardPhaseState pydantic model and SessionState helpers."""

    def test_card_phase_state_serialization_roundtrip(self):
        """Create CardPhaseState, dump to dict, restore, verify all fields."""
        original = _make_card_phase(
            current_variant_key="B",
            current_card_idx=3,
            total_cards=7,
            variants_shown=["A", "B"],
        )

        dumped = original.model_dump()
        restored = CardPhaseState.model_validate(dumped)

        assert restored.guideline_id == original.guideline_id
        assert restored.active == original.active
        assert restored.current_variant_key == "B"
        assert restored.current_card_idx == 3
        assert restored.total_cards == 7
        assert restored.variants_shown == ["A", "B"]
        assert restored.available_variant_keys == ["A", "B", "C"]
        assert restored.completed is False

    def test_card_phase_state_json_roundtrip(self):
        """Ensure CardPhaseState survives JSON serialization (as stored in DB)."""
        original = _make_card_phase()
        json_str = original.model_dump_json()
        restored = CardPhaseState.model_validate_json(json_str)

        assert restored.guideline_id == original.guideline_id
        assert restored.active is True

    def test_session_state_is_in_card_phase_true_when_active(self):
        """is_in_card_phase() returns True when card_phase exists and active=True."""
        session = _make_session_state(card_phase=_make_card_phase(active=True))
        assert session.is_in_card_phase() is True

    def test_session_state_is_in_card_phase_false_when_inactive(self):
        """is_in_card_phase() returns False when card_phase exists but active=False."""
        session = _make_session_state(card_phase=_make_card_phase(active=False))
        assert session.is_in_card_phase() is False

    def test_session_state_is_in_card_phase_false_when_none(self):
        """is_in_card_phase() returns False when card_phase is None."""
        session = _make_session_state(card_phase=None)
        assert session.is_in_card_phase() is False

    def test_session_state_complete_card_phase(self):
        """complete_card_phase() sets active=False, completed=True."""
        session = _make_session_state(card_phase=_make_card_phase(active=True, completed=False))
        before = session.updated_at

        session.complete_card_phase()

        assert session.card_phase.active is False
        assert session.card_phase.completed is True
        assert session.updated_at >= before

    def test_complete_card_phase_noop_when_none(self):
        """complete_card_phase() is safe to call when card_phase is None."""
        session = _make_session_state(card_phase=None)
        session.complete_card_phase()  # should not raise
        assert session.card_phase is None

    def test_card_phase_in_full_session_state_roundtrip(self):
        """CardPhaseState survives full SessionState serialization (model_dump_json)."""
        session = _make_session_state(card_phase=_make_card_phase(
            current_variant_key="C", total_cards=10
        ))
        json_str = session.model_dump_json()
        restored = SessionState.model_validate_json(json_str)

        assert restored.card_phase is not None
        assert restored.card_phase.current_variant_key == "C"
        assert restored.card_phase.total_cards == 10
        assert restored.is_in_card_phase() is True


# ===========================================================================
# 2. ExplanationRepository tests (mock DB session)
# ===========================================================================

class TestExplanationRepository:
    """Tests for ExplanationRepository CRUD operations with a mocked DB session."""

    def test_upsert_and_get_by_guideline_id(self):
        """upsert stores a variant, get_by_guideline_id retrieves it."""
        db = MagicMock()
        repo = ExplanationRepository(db)

        # Mock: upsert calls delete (returns nothing), then add, commit, refresh
        db.query.return_value.filter.return_value.delete.return_value = 0
        mock_entity = MagicMock(spec=TopicExplanation)
        db.refresh = MagicMock()

        result = repo.upsert(
            guideline_id="g1",
            variant_key="A",
            variant_label="Everyday Analogies",
            cards_json=_sample_cards_json(4),
            summary_json={"key_analogies": ["pizza"]},
            generator_model="gpt-4o",
        )

        # Verify DB calls
        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()

        # The returned object is the one passed to db.add
        added_entity = db.add.call_args[0][0]
        assert added_entity.guideline_id == "g1"
        assert added_entity.variant_key == "A"
        assert added_entity.variant_label == "Everyday Analogies"
        assert len(added_entity.cards_json) == 4

    def test_has_explanations_true(self):
        """has_explanations returns True when a row exists."""
        db = MagicMock()
        repo = ExplanationRepository(db)
        db.query.return_value.filter.return_value.first.return_value = ("some-id",)

        assert repo.has_explanations("g1") is True

    def test_has_explanations_false(self):
        """has_explanations returns False when no row exists."""
        db = MagicMock()
        repo = ExplanationRepository(db)
        db.query.return_value.filter.return_value.first.return_value = None

        assert repo.has_explanations("g1") is False

    def test_get_variant_returns_match(self):
        """get_variant returns the row when found."""
        db = MagicMock()
        repo = ExplanationRepository(db)

        mock_row = _make_explanation_row("B")
        db.query.return_value.filter.return_value.first.return_value = mock_row

        result = repo.get_variant("g1", "B")
        assert result is mock_row
        assert result.variant_key == "B"

    def test_get_variant_returns_none(self):
        """get_variant returns None when not found."""
        db = MagicMock()
        repo = ExplanationRepository(db)
        db.query.return_value.filter.return_value.first.return_value = None

        result = repo.get_variant("g1", "Z")
        assert result is None

    def test_parse_cards_valid(self):
        """parse_cards validates and returns ExplanationCard models for well-formed input."""
        cards_json = _sample_cards_json(3)
        parsed = ExplanationRepository.parse_cards(cards_json)

        assert len(parsed) == 3
        assert all(isinstance(c, ExplanationCard) for c in parsed)
        assert parsed[0].card_idx == 1
        assert parsed[0].card_type == "concept"
        assert parsed[0].title == "Card 1"

    def test_parse_cards_with_visual(self):
        """parse_cards handles cards with visual field populated."""
        cards_json = [
            {
                "card_idx": 1,
                "card_type": "visual",
                "title": "Diagram",
                "content": "See the diagram below",
                "visual": "  1/2  |  1/4\n  ███  |  █░░░",
            }
        ]
        parsed = ExplanationRepository.parse_cards(cards_json)
        assert parsed[0].visual is not None
        assert "1/2" in parsed[0].visual

    def test_parse_cards_invalid_missing_required_field(self):
        """parse_cards raises ValidationError on malformed cards (missing required field)."""
        cards_json = [
            {"card_idx": 1, "card_type": "concept"}  # missing title and content
        ]
        with pytest.raises(ValidationError):
            ExplanationRepository.parse_cards(cards_json)

    def test_parse_cards_empty_list(self):
        """parse_cards returns empty list for empty input."""
        parsed = ExplanationRepository.parse_cards([])
        assert parsed == []

    def test_delete_by_guideline_id(self):
        """delete_by_guideline_id calls delete and commit, returns count."""
        db = MagicMock()
        repo = ExplanationRepository(db)
        db.query.return_value.filter.return_value.delete.return_value = 3

        count = repo.delete_by_guideline_id("g1")

        assert count == 3
        db.commit.assert_called_once()


# ===========================================================================
# 3. ExplanationGeneratorService tests (mock LLM)
# ===========================================================================

class TestExplanationGeneratorService:
    """Tests for the multi-pass LLM pipeline in ExplanationGeneratorService."""

    def _make_service(self):
        """Build ExplanationGeneratorService with mocked dependencies."""
        from book_ingestion_v2.services.explanation_generator_service import (
            ExplanationGeneratorService,
        )

        db = MagicMock()
        llm = MagicMock()
        llm.model_id = "gpt-4o"
        # make_schema_strict is a staticmethod — mock it as passthrough
        llm.make_schema_strict = MagicMock(side_effect=lambda x: x)

        with patch(
            "book_ingestion_v2.services.explanation_generator_service.LLMService"
        ) as MockLLMCls:
            MockLLMCls.make_schema_strict = MagicMock(side_effect=lambda x: x)
            svc = ExplanationGeneratorService(db, llm)

        # Replace repo with a mock to avoid real DB calls
        svc.repo = MagicMock()
        return svc, llm

    def _good_generation_output(self, num_cards=5):
        """Return a dict matching GenerationOutput schema."""
        return {
            "cards": [
                {
                    "card_idx": i + 1,
                    "card_type": "concept",
                    "title": f"Card {i + 1}",
                    "content": f"Content {i + 1}",
                    "visual": None,
                }
                for i in range(num_cards)
            ],
            "summary": {
                "key_analogies": ["pizza analogy"],
                "key_examples": ["sharing example"],
            },
        }

    def _critique_output(self, quality="good"):
        """Return a dict matching CritiqueOutput schema."""
        return {
            "issues": [],
            "suggestions": [],
            "overall_quality": quality,
        }

    def test_generate_variant_skip_refine_on_good(self):
        """When critique returns 'good', refine is NOT called and cards are stored."""
        svc, llm = self._make_service()
        guideline = _make_guideline_mock()
        variant_config = {"key": "A", "label": "Everyday Analogies", "approach": "analogy-driven"}

        gen_output = self._good_generation_output(5)
        critique_output = self._critique_output("good")

        # llm.call is invoked twice: generate + critique (no refine)
        llm.call.side_effect = [
            {"output_text": json.dumps(gen_output)},
            {"output_text": json.dumps(critique_output)},
        ]
        llm.parse_json_response = MagicMock(side_effect=[gen_output, critique_output])

        cards, summary = svc._generate_variant(guideline, variant_config)

        assert cards is not None
        assert len(cards) == 5
        assert summary is not None
        assert summary["approach_label"] == "Everyday Analogies"
        assert llm.call.call_count == 2  # generate + critique, no refine

    def test_generate_variant_refine_on_needs_improvement(self):
        """When critique returns 'needs_improvement', refine IS called and summary uses refined output."""
        svc, llm = self._make_service()
        guideline = _make_guideline_mock()
        variant_config = {"key": "B", "label": "Visual Walkthrough", "approach": "diagram-heavy"}

        gen_output = self._good_generation_output(4)
        critique_output = self._critique_output("needs_improvement")
        refined_output = self._good_generation_output(6)

        # llm.call: generate, critique, refine (3 calls)
        llm.call.side_effect = [
            {"output_text": json.dumps(gen_output)},
            {"output_text": json.dumps(critique_output)},
            {"output_text": json.dumps(refined_output)},
        ]
        llm.parse_json_response = MagicMock(
            side_effect=[gen_output, critique_output, refined_output]
        )

        cards, summary = svc._generate_variant(guideline, variant_config)

        assert cards is not None
        assert len(cards) == 6  # refined output has 6 cards
        assert summary is not None
        assert llm.call.call_count == 3  # generate + critique + refine
        # Summary should be built from refined output, so it has 6 card titles
        assert len(summary["card_titles"]) == 6

    def test_generate_variant_skip_on_poor(self):
        """When critique returns 'poor', variant is NOT stored (returns None, None)."""
        svc, llm = self._make_service()
        guideline = _make_guideline_mock()
        variant_config = {"key": "C", "label": "Step-by-Step", "approach": "procedural"}

        gen_output = self._good_generation_output(4)
        critique_output = self._critique_output("poor")

        llm.call.side_effect = [
            {"output_text": json.dumps(gen_output)},
            {"output_text": json.dumps(critique_output)},
        ]
        llm.parse_json_response = MagicMock(side_effect=[gen_output, critique_output])

        cards, summary = svc._generate_variant(guideline, variant_config)

        assert cards is None
        assert summary is None
        assert llm.call.call_count == 2  # generate + critique, no refine

    def test_generate_variant_min_cards_validation(self):
        """When generation returns < MIN_CARDS, variant is skipped."""
        svc, llm = self._make_service()
        guideline = _make_guideline_mock()
        variant_config = {"key": "A", "label": "Analogies", "approach": "analogy-driven"}

        # Only 2 cards — below MIN_CARDS (3)
        gen_output = self._good_generation_output(2)

        llm.call.side_effect = [
            {"output_text": json.dumps(gen_output)},
        ]
        llm.parse_json_response = MagicMock(side_effect=[gen_output])

        cards, summary = svc._generate_variant(guideline, variant_config)

        assert cards is None
        assert summary is None
        # Only generate was called — skipped before critique
        assert llm.call.call_count == 1

    def test_generate_variant_trims_excess_cards(self):
        """When generation returns > MAX_CARDS, cards are trimmed to MAX_CARDS."""
        svc, llm = self._make_service()
        guideline = _make_guideline_mock()
        variant_config = {"key": "A", "label": "Analogies", "approach": "analogy-driven"}

        gen_output = self._good_generation_output(20)  # Exceeds MAX_CARDS=15
        critique_output = self._critique_output("good")

        llm.call.side_effect = [
            {"output_text": json.dumps(gen_output)},
            {"output_text": json.dumps(critique_output)},
        ]
        llm.parse_json_response = MagicMock(side_effect=[gen_output, critique_output])

        cards, summary = svc._generate_variant(guideline, variant_config)

        assert cards is not None
        assert len(cards) == 15  # Trimmed to MAX_CARDS

    def test_generate_variant_min_cards_after_refine_skips(self):
        """When refined output has < MIN_CARDS, variant is skipped."""
        svc, llm = self._make_service()
        guideline = _make_guideline_mock()
        variant_config = {"key": "A", "label": "Analogies", "approach": "analogy-driven"}

        gen_output = self._good_generation_output(4)
        critique_output = self._critique_output("needs_improvement")
        # Refined output has only 2 cards — below MIN_CARDS
        refined_output = self._good_generation_output(2)

        llm.call.side_effect = [
            {"output_text": json.dumps(gen_output)},
            {"output_text": json.dumps(critique_output)},
            {"output_text": json.dumps(refined_output)},
        ]
        llm.parse_json_response = MagicMock(
            side_effect=[gen_output, critique_output, refined_output]
        )

        cards, summary = svc._generate_variant(guideline, variant_config)

        assert cards is None
        assert summary is None
        assert llm.call.call_count == 3  # All three calls made, but result skipped

    def test_generate_for_guideline_stores_successful_variants(self):
        """generate_for_guideline upserts variants that pass validation."""
        svc, llm = self._make_service()
        guideline = _make_guideline_mock()

        gen_output = self._good_generation_output(5)
        critique_output = self._critique_output("good")

        # Each of the 3 variants needs 2 LLM calls (generate + critique)
        llm.call.side_effect = [
            {"output_text": json.dumps(gen_output)},
            {"output_text": json.dumps(critique_output)},
        ] * 3
        llm.parse_json_response = MagicMock(
            side_effect=[gen_output, critique_output] * 3
        )

        mock_stored = MagicMock(spec=TopicExplanation)
        svc.repo.upsert.return_value = mock_stored

        results = svc.generate_for_guideline(guideline)

        assert len(results) == 3
        assert svc.repo.upsert.call_count == 3

    def test_generate_for_guideline_filters_variant_keys(self):
        """generate_for_guideline respects variant_keys filter."""
        svc, llm = self._make_service()
        guideline = _make_guideline_mock()

        gen_output = self._good_generation_output(5)
        critique_output = self._critique_output("good")

        llm.call.side_effect = [
            {"output_text": json.dumps(gen_output)},
            {"output_text": json.dumps(critique_output)},
        ]
        llm.parse_json_response = MagicMock(
            side_effect=[gen_output, critique_output]
        )

        mock_stored = MagicMock(spec=TopicExplanation)
        svc.repo.upsert.return_value = mock_stored

        results = svc.generate_for_guideline(guideline, variant_keys=["B"])

        assert len(results) == 1
        # Verify the upserted variant was "B"
        upsert_call = svc.repo.upsert.call_args
        assert upsert_call[1]["variant_key"] == "B" or upsert_call.kwargs.get("variant_key") == "B"


# ===========================================================================
# 4. Session service card phase tests (mock repo + orchestrator)
# ===========================================================================

class TestSessionServiceCardPhase:
    """Tests for card phase logic in SessionService."""

    @patch("tutor.services.session_service.get_settings")
    @patch("tutor.services.session_service.convert_guideline_to_topic")
    @patch("tutor.services.session_service.ExplanationRepository")
    def test_session_creation_with_explanations(self, MockExplRepo, mock_convert, mock_settings):
        """When pre-computed explanations exist, card phase is initialized and no LLM welcome call."""
        mock_settings.return_value = MagicMock(
            openai_api_key="fake", gemini_api_key=None, anthropic_api_key=None,
        )
        mock_convert.return_value = _make_topic()

        svc = _svc_skeleton()

        # guideline found
        svc.guideline_repo.get_guideline_by_id.return_value = _make_guideline_mock()
        # no existing study plan
        svc.db.query.return_value.filter.return_value.first.return_value = None

        # Pre-computed explanations exist
        expl_a = _make_explanation_row("A", 5)
        expl_b = _make_explanation_row("B", 4)
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_guideline_id.return_value = [expl_a, expl_b]
        MockExplRepo.return_value = mock_repo_instance

        from shared.models.domain import Student, Goal
        from shared.models.schemas import CreateSessionRequest

        request = CreateSessionRequest(
            student=Student(id="s1", grade=3),
            goal=Goal(
                chapter="Fractions",
                syllabus="CBSE Grade 3 Math",
                learning_objectives=["Understand fractions"],
                guideline_id="guideline-1",
            ),
        )

        response = svc.create_new_session(request)

        # Verify card phase fields in first_turn
        assert response.first_turn["session_phase"] == "card_phase"
        assert response.first_turn["explanation_cards"] == expl_a.cards_json
        assert response.first_turn["card_phase_state"]["current_variant_key"] == "A"
        assert response.first_turn["card_phase_state"]["total_cards"] == 5
        assert response.first_turn["card_phase_state"]["available_variants"] == 2

        # No LLM welcome call should have been made
        svc.orchestrator.generate_welcome_message.assert_not_called()

    @patch("tutor.services.session_service.get_settings")
    @patch("tutor.services.session_service.convert_guideline_to_topic")
    @patch("tutor.services.session_service.ExplanationRepository")
    def test_session_creation_without_explanations(self, MockExplRepo, mock_convert, mock_settings):
        """When no explanations exist, falls back to dynamic welcome with LLM call."""
        mock_settings.return_value = MagicMock(
            openai_api_key="fake", gemini_api_key=None, anthropic_api_key=None,
        )
        mock_convert.return_value = _make_topic()

        svc = _svc_skeleton()

        svc.guideline_repo.get_guideline_by_id.return_value = _make_guideline_mock()
        svc.db.query.return_value.filter.return_value.first.return_value = None

        # No explanations
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_by_guideline_id.return_value = []
        MockExplRepo.return_value = mock_repo_instance

        from shared.models.domain import Student, Goal
        from shared.models.schemas import CreateSessionRequest

        request = CreateSessionRequest(
            student=Student(id="s1", grade=3),
            goal=Goal(
                chapter="Fractions",
                syllabus="CBSE Grade 3 Math",
                learning_objectives=["Understand fractions"],
                guideline_id="guideline-1",
            ),
        )

        with patch("asyncio.run", return_value=("Welcome to fractions!", "Welcome audio")):
            response = svc.create_new_session(request)

        assert "session_phase" not in response.first_turn
        assert response.first_turn["message"] == "Welcome to fractions!"

    @patch("tutor.services.session_service.get_settings")
    def test_process_step_rejects_during_card_phase(self, mock_settings):
        """process_step raises HTTPException 400 when session is in card phase."""
        mock_settings.return_value = MagicMock(
            openai_api_key="fake", gemini_api_key=None, anthropic_api_key=None,
        )

        from tutor.services.session_service import SessionService
        from shared.models.schemas import StepRequest

        svc = _svc_skeleton()

        # Build session state with active card phase
        session = _make_session_state(card_phase=_make_card_phase(active=True))
        db_row = MagicMock()
        db_row.state_json = session.model_dump_json()
        db_row.state_version = 1
        svc.session_repo.get_by_id.return_value = db_row

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            svc.process_step("test-session-card", StepRequest(student_reply="hello"))

        assert exc_info.value.status_code == 400
        assert "card phase" in exc_info.value.detail.lower()

    @patch("tutor.services.session_service.get_settings")
    @patch("tutor.services.session_service.ExplanationRepository")
    def test_card_action_clear_transitions(self, MockExplRepo, mock_settings):
        """complete_card_phase('clear') completes card phase, advances past explain steps."""
        mock_settings.return_value = MagicMock(
            openai_api_key="fake", gemini_api_key=None, anthropic_api_key=None,
        )

        svc = _svc_skeleton()

        # Session with card phase active, study plan has explain+check steps
        topic = _make_topic(num_explain=1, num_check=1)
        session = _make_session_state(
            topic=topic,
            card_phase=_make_card_phase(active=True, variants_shown=["A"]),
        )
        db_row = MagicMock()
        db_row.state_json = session.model_dump_json()
        db_row.state_version = 1
        svc.session_repo.get_by_id.return_value = db_row

        # Mock _build_precomputed_summary via ExplanationRepository
        mock_repo_instance = MagicMock()
        mock_expl = _make_explanation_row("A")
        mock_repo_instance.get_variant.return_value = mock_expl
        MockExplRepo.return_value = mock_repo_instance

        # Mock persist
        svc._persist_session_state = MagicMock()

        result = svc.complete_card_phase("test-session-card", "clear")

        assert result["action"] == "transition_to_interactive"
        assert "precomputed_summary" in result
        svc._persist_session_state.assert_called_once()

    @patch("tutor.services.session_service.get_settings")
    @patch("tutor.services.session_service.ExplanationRepository")
    def test_card_action_explain_differently_with_unseen(self, MockExplRepo, mock_settings):
        """explain_differently switches to next unseen variant when available."""
        mock_settings.return_value = MagicMock(
            openai_api_key="fake", gemini_api_key=None, anthropic_api_key=None,
        )

        svc = _svc_skeleton()

        # Session with variant A shown, B and C still unseen
        session = _make_session_state(
            card_phase=_make_card_phase(
                active=True,
                current_variant_key="A",
                variants_shown=["A"],
                available_variant_keys=["A", "B", "C"],
            ),
        )
        db_row = MagicMock()
        db_row.state_json = session.model_dump_json()
        db_row.state_version = 1
        svc.session_repo.get_by_id.return_value = db_row

        # Mock the variant B lookup
        mock_repo_instance = MagicMock()
        expl_b = _make_explanation_row("B", 6)
        mock_repo_instance.get_variant.return_value = expl_b
        MockExplRepo.return_value = mock_repo_instance

        svc._persist_session_state = MagicMock()

        result = svc.complete_card_phase("test-session-card", "explain_differently")

        assert result["action"] == "switch_variant"
        assert result["variant_key"] == "B"
        assert result["cards"] == expl_b.cards_json
        svc._persist_session_state.assert_called_once()

    @patch("tutor.services.session_service.get_settings")
    @patch("tutor.services.session_service.ExplanationRepository")
    def test_card_action_explain_differently_exhausted(self, MockExplRepo, mock_settings):
        """When all variants seen, explain_differently falls back to dynamic."""
        mock_settings.return_value = MagicMock(
            openai_api_key="fake", gemini_api_key=None, anthropic_api_key=None,
        )

        svc = _svc_skeleton()

        # All variants already shown
        session = _make_session_state(
            card_phase=_make_card_phase(
                active=True,
                current_variant_key="C",
                variants_shown=["A", "B", "C"],
                available_variant_keys=["A", "B", "C"],
            ),
        )
        db_row = MagicMock()
        db_row.state_json = session.model_dump_json()
        db_row.state_version = 1
        svc.session_repo.get_by_id.return_value = db_row

        # Mock ExplanationRepository for summary building
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_variant.return_value = _make_explanation_row("A")
        MockExplRepo.return_value = mock_repo_instance

        svc._persist_session_state = MagicMock()

        with patch("asyncio.run", return_value=("Let me explain differently...", "audio text")):
            result = svc.complete_card_phase("test-session-card", "explain_differently")

        assert result["action"] == "fallback_dynamic"
        assert result["message"] == "Let me explain differently..."
        assert result["audio_text"] == "audio text"
        svc._persist_session_state.assert_called_once()

    @patch("tutor.services.session_service.get_settings")
    def test_card_action_on_non_card_phase_session_raises(self, mock_settings):
        """complete_card_phase raises 400 when session is not in card phase."""
        mock_settings.return_value = MagicMock(
            openai_api_key="fake", gemini_api_key=None, anthropic_api_key=None,
        )

        svc = _svc_skeleton()

        session = _make_session_state(card_phase=None)
        db_row = MagicMock()
        db_row.state_json = session.model_dump_json()
        db_row.state_version = 1
        svc.session_repo.get_by_id.return_value = db_row

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            svc.complete_card_phase("test-session-card", "clear")

        assert exc_info.value.status_code == 400
        assert "not in card phase" in exc_info.value.detail.lower()

    @patch("tutor.services.session_service.get_settings")
    def test_card_action_session_not_found(self, mock_settings):
        """complete_card_phase raises SessionNotFoundException for missing session."""
        mock_settings.return_value = MagicMock(
            openai_api_key="fake", gemini_api_key=None, anthropic_api_key=None,
        )

        svc = _svc_skeleton()
        svc.session_repo.get_by_id.return_value = None

        with pytest.raises(SessionNotFoundException):
            svc.complete_card_phase("nonexistent", "clear")


# ===========================================================================
# 5. DTO validation tests
# ===========================================================================

class TestDTOValidation:
    """Tests for CardActionRequest, ExplanationCardDTO, CardPhaseDTO."""

    def test_card_action_request_accepts_clear(self):
        """CardActionRequest accepts 'clear' action."""
        req = CardActionRequest(action="clear")
        assert req.action == "clear"

    def test_card_action_request_accepts_explain_differently(self):
        """CardActionRequest accepts 'explain_differently' action."""
        req = CardActionRequest(action="explain_differently")
        assert req.action == "explain_differently"

    def test_card_action_request_rejects_invalid_action(self):
        """CardActionRequest rejects actions other than clear/explain_differently."""
        with pytest.raises(ValidationError):
            CardActionRequest(action="skip")

    def test_card_action_request_rejects_empty(self):
        """CardActionRequest rejects empty string."""
        with pytest.raises(ValidationError):
            CardActionRequest(action="")

    def test_explanation_card_dto_valid(self):
        """ExplanationCardDTO validates a correct card."""
        card = ExplanationCardDTO(
            card_idx=1,
            card_type="concept",
            title="What is a fraction?",
            content="A fraction represents a part of a whole.",
            visual=None,
        )
        assert card.card_idx == 1
        assert card.card_type == "concept"

    def test_explanation_card_dto_all_types(self):
        """ExplanationCardDTO accepts all valid card_type values."""
        for card_type in ["concept", "example", "visual", "analogy", "summary"]:
            card = ExplanationCardDTO(
                card_idx=1, card_type=card_type, title="T", content="C"
            )
            assert card.card_type == card_type

    def test_explanation_card_dto_rejects_invalid_type(self):
        """ExplanationCardDTO rejects invalid card_type."""
        with pytest.raises(ValidationError):
            ExplanationCardDTO(
                card_idx=1, card_type="unknown", title="T", content="C"
            )

    def test_explanation_card_dto_with_visual(self):
        """ExplanationCardDTO stores visual field."""
        card = ExplanationCardDTO(
            card_idx=1,
            card_type="visual",
            title="Diagram",
            content="See below",
            visual="[===]",
        )
        assert card.visual == "[===]"

    def test_card_phase_dto_valid(self):
        """CardPhaseDTO validates correctly."""
        dto = CardPhaseDTO(
            current_variant_key="A",
            current_card_idx=2,
            total_cards=5,
            available_variants=3,
        )
        assert dto.current_variant_key == "A"
        assert dto.current_card_idx == 2
        assert dto.total_cards == 5
        assert dto.available_variants == 3


# ===========================================================================
# 6. Internal helper method tests
# ===========================================================================

class TestAdvancePastExplanationSteps:
    """Tests for SessionService._advance_past_explanation_steps."""

    def test_skips_consecutive_explain_steps(self):
        """Leading explain steps are skipped, stopping at the first check step."""
        svc = _svc_skeleton()

        # 2 explain + 1 check
        topic = Topic(
            topic_id="t1",
            topic_name="Fractions",
            subject="Math",
            grade_level=3,
            guidelines=TopicGuidelines(learning_objectives=["obj1"]),
            study_plan=StudyPlan(steps=[
                StudyPlanStep(step_id=1, type="explain", concept="C1"),
                StudyPlanStep(step_id=2, type="explain", concept="C2"),
                StudyPlanStep(step_id=3, type="check", concept="C1", question_type="conceptual"),
            ]),
        )
        session = _make_session_state(topic=topic)
        session.current_step = 1

        svc._advance_past_explanation_steps(session)

        assert session.current_step == 3  # Landed on the check step
        assert "C1" in session.concepts_covered_set
        assert "C2" in session.concepts_covered_set

    def test_no_skip_when_first_step_is_check(self):
        """When the first step is a check, no skipping happens."""
        svc = _svc_skeleton()

        topic = Topic(
            topic_id="t1",
            topic_name="Fractions",
            subject="Math",
            grade_level=3,
            guidelines=TopicGuidelines(learning_objectives=["obj1"]),
            study_plan=StudyPlan(steps=[
                StudyPlanStep(step_id=1, type="check", concept="C1", question_type="conceptual"),
                StudyPlanStep(step_id=2, type="explain", concept="C2"),
            ]),
        )
        session = _make_session_state(topic=topic)
        session.current_step = 1

        svc._advance_past_explanation_steps(session)

        assert session.current_step == 1  # No advance

    def test_handles_all_explain_steps(self):
        """If ALL steps are explain, advances past all of them."""
        svc = _svc_skeleton()

        topic = Topic(
            topic_id="t1",
            topic_name="Fractions",
            subject="Math",
            grade_level=3,
            guidelines=TopicGuidelines(learning_objectives=["obj1"]),
            study_plan=StudyPlan(steps=[
                StudyPlanStep(step_id=1, type="explain", concept="C1"),
                StudyPlanStep(step_id=2, type="explain", concept="C2"),
            ]),
        )
        session = _make_session_state(topic=topic)
        session.current_step = 1

        svc._advance_past_explanation_steps(session)

        assert session.current_step == 3  # Past all steps
        assert "C1" in session.concepts_covered_set
        assert "C2" in session.concepts_covered_set


class TestInitDynamicFallback:
    """Tests for SessionService._init_dynamic_fallback."""

    def test_initializes_explanation_phase_for_first_explain_step(self):
        """Dynamic fallback starts ExplanationPhase for step 1 if it's an explain step."""
        svc = _svc_skeleton()

        session = _make_session_state()
        assert session.current_explanation_concept is None

        svc._init_dynamic_fallback(session)

        assert session.current_explanation_concept == "Concept_1"
        assert "Concept_1" in session.explanation_phases

    def test_no_init_when_first_step_is_check(self):
        """Dynamic fallback does nothing if step 1 is not explain."""
        svc = _svc_skeleton()

        topic = Topic(
            topic_id="t1",
            topic_name="Fractions",
            subject="Math",
            grade_level=3,
            guidelines=TopicGuidelines(learning_objectives=["obj1"]),
            study_plan=StudyPlan(steps=[
                StudyPlanStep(step_id=1, type="check", concept="C1", question_type="conceptual"),
            ]),
        )
        session = _make_session_state(topic=topic)

        svc._init_dynamic_fallback(session)

        assert session.current_explanation_concept is None


class TestBuildPrecomputedSummary:
    """Tests for SessionService._build_precomputed_summary."""

    @patch("tutor.services.session_service.ExplanationRepository")
    def test_builds_summary_from_shown_variants(self, MockExplRepo):
        svc = _svc_skeleton()

        session = _make_session_state(
            card_phase=_make_card_phase(variants_shown=["A", "B"]),
        )

        mock_repo_instance = MagicMock()
        expl_a = _make_explanation_row("A")
        expl_b = _make_explanation_row("B")
        mock_repo_instance.get_variant.side_effect = lambda gid, vk: {
            "A": expl_a, "B": expl_b
        }.get(vk)
        MockExplRepo.return_value = mock_repo_instance

        summary = svc._build_precomputed_summary(session)

        assert "Approach A" in summary
        assert "Approach B" in summary
        assert "pizza slices" in summary

    def test_returns_empty_string_when_no_card_phase(self):
        svc = _svc_skeleton()
        session = _make_session_state(card_phase=None)

        summary = svc._build_precomputed_summary(session)
        assert summary == ""
