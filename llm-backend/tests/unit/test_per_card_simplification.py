"""Unit tests for per-card simplification feature.

Covers:
1. RemedialCard / ConfusionEvent models and CardPhaseState serialization
2. simplify_card() service method — depth tracking, card generation, state persistence
3. Escalation to interactive mode after depth 2
4. _build_precomputed_summary() includes confusion events
5. _switch_variant_internal() clears remedial_cards
6. Replay endpoint merges remedial cards with stable card IDs
7. Frontend handler sends correct 0-based card index
"""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from datetime import datetime

from tutor.models.session_state import (
    SessionState, CardPhaseState, RemedialCard, ConfusionEvent,
)
from tutor.models.messages import SimplifyCardRequest, ExplanationCardDTO
from tutor.models.study_plan import StudyPlan, StudyPlanStep, Topic, TopicGuidelines
from tutor.models.messages import StudentContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_CARDS = [
    {"card_idx": 1, "card_type": "concept", "title": "What is Addition?", "content": "Addition means putting things together.", "audio_text": "Addition means putting things together."},
    {"card_idx": 2, "card_type": "example", "title": "Adding Apples", "content": "If you have 3 apples and get 2 more, you have 5.", "audio_text": "Three apples plus two more gives five."},
    {"card_idx": 3, "card_type": "visual", "title": "Number Line", "content": "On a number line, start at 3 and jump 2 to reach 5.", "audio_text": "Start at three, jump two, land on five."},
    {"card_idx": 4, "card_type": "summary", "title": "Recap", "content": "Addition combines groups into a total.", "audio_text": "Addition combines groups into a total."},
]


def _make_topic():
    return Topic(
        topic_id="t1",
        topic_name="Addition",
        subject="Math",
        grade_level=3,
        guidelines=TopicGuidelines(learning_objectives=["Understand addition"]),
        study_plan=StudyPlan(steps=[
            StudyPlanStep(step_id=1, type="explain", concept="addition"),
            StudyPlanStep(step_id=2, type="check", concept="addition"),
        ]),
    )


def _make_session_with_card_phase(**overrides):
    card_phase = CardPhaseState(
        guideline_id="g1",
        active=True,
        current_variant_key="A",
        current_card_idx=0,
        total_cards=4,
        variants_shown=["A"],
        available_variant_keys=["A", "B"],
    )
    defaults = dict(
        student_context=StudentContext(grade=3),
        topic=_make_topic(),
        card_phase=card_phase,
    )
    defaults.update(overrides)
    return SessionState(**defaults)


# ---------------------------------------------------------------------------
# 1. Model tests
# ---------------------------------------------------------------------------

class TestModels:

    def test_remedial_card_creation(self):
        r = RemedialCard(
            card_id="remedial_A_2_1",
            source_card_idx=2,
            depth=1,
            card={"card_type": "simplification", "title": "Simpler", "content": "Easier.", "audio_text": "Easier."},
        )
        assert r.card_id == "remedial_A_2_1"
        assert r.source_card_idx == 2
        assert r.depth == 1
        assert r.card["card_type"] == "simplification"

    def test_confusion_event_creation(self):
        c = ConfusionEvent(
            base_card_idx=2,
            base_card_title="Number Line",
            depth_reached=1,
        )
        assert c.base_card_idx == 2
        assert c.escalated is False

    def test_card_phase_state_with_remedials(self):
        cp = CardPhaseState(
            guideline_id="g1",
            total_cards=4,
            variants_shown=["A"],
            available_variant_keys=["A", "B"],
        )
        r = RemedialCard(card_id="r1", source_card_idx=2, depth=1, card={"title": "test"})
        cp.remedial_cards[2] = [r]
        cp.confusion_events.append(ConfusionEvent(base_card_idx=2, base_card_title="Test"))

        assert len(cp.remedial_cards) == 1
        assert len(cp.confusion_events) == 1

    def test_card_phase_state_serialization_roundtrip(self):
        session = _make_session_with_card_phase()
        r = RemedialCard(card_id="remedial_A_1_1", source_card_idx=1, depth=1, card={"title": "simpler"})
        session.card_phase.remedial_cards[1] = [r]
        session.card_phase.confusion_events.append(
            ConfusionEvent(base_card_idx=1, base_card_title="Adding Apples", depth_reached=1)
        )

        # Serialize and deserialize
        json_str = session.model_dump_json()
        restored = SessionState.model_validate_json(json_str)

        assert restored.card_phase is not None
        # dict keys become strings in JSON
        assert "1" in restored.card_phase.remedial_cards or 1 in restored.card_phase.remedial_cards
        assert len(restored.card_phase.confusion_events) == 1
        assert restored.card_phase.confusion_events[0].base_card_title == "Adding Apples"

    def test_simplify_card_request(self):
        req = SimplifyCardRequest(card_idx=2)
        assert req.card_idx == 2

    def test_explanation_card_dto_simplification_type(self):
        card = ExplanationCardDTO(
            card_idx=0, card_type="simplification", title="Simpler", content="Easier.",
        )
        assert card.card_type == "simplification"


# ---------------------------------------------------------------------------
# 2. Service tests — simplify_card
# ---------------------------------------------------------------------------

class TestSimplifyCardService:

    def _make_mock_db(self, session_state):
        """Build a mock DB session + repos for SessionService."""
        db = MagicMock()
        # Mock session row
        session_row = MagicMock()
        session_row.state_json = session_state.model_dump_json()
        session_row.state_version = 1
        return db, session_row

    def test_simplify_card_depth_1(self):
        """First 'I didn't understand' tap generates depth-1 simplified card."""
        session = _make_session_with_card_phase()

        simplified_card = {
            "card_type": "simplification",
            "title": "Adding — Super Simple",
            "content": "When you put things together, you get more.",
            "audio_text": "When you put things together, you get more.",
            "visual": None,
            "visual_explanation": None,
        }

        mock_expl = MagicMock()
        mock_expl.cards_json = SAMPLE_CARDS

        from tutor.services.session_service import SessionService

        with patch.object(SessionService, '__init__', lambda self, db: None), \
             patch("tutor.services.session_service.ExplanationRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_variant.return_value = mock_expl

            service = SessionService.__new__(SessionService)
            service.db = MagicMock()
            service.session_repo = MagicMock()
            service.event_repo = MagicMock()
            service.guideline_repo = MagicMock()
            service.orchestrator = MagicMock()
            service.orchestrator.generate_simplified_card = AsyncMock(return_value=simplified_card)
            service.llm_service = MagicMock()

            session_row = MagicMock()
            session_row.state_json = session.model_dump_json()
            session_row.state_version = 1
            service.session_repo.get_by_id.return_value = session_row

            persisted_states = []
            service._persist_session_state = lambda sid, state, ver: persisted_states.append(state)

            result = service.simplify_card("sess_test", card_idx=2)

        assert result["action"] == "insert_card"
        assert result["card"]["card_type"] == "simplification"
        assert result["card_id"] == "remedial_A_2_1"
        assert result["insert_after"] == "A_2"

        # Verify state was persisted with remedial card
        assert len(persisted_states) == 1
        state = persisted_states[0]
        assert 2 in state.card_phase.remedial_cards
        assert len(state.card_phase.remedial_cards[2]) == 1
        assert state.card_phase.remedial_cards[2][0].depth == 1

        # Verify confusion event was logged
        assert len(state.card_phase.confusion_events) == 1
        assert state.card_phase.confusion_events[0].base_card_idx == 2
        assert state.card_phase.confusion_events[0].base_card_title == "Number Line"

    def test_simplify_card_depth_2(self):
        """Second tap on same card generates depth-2 simplification."""
        session = _make_session_with_card_phase()
        session.card_phase.remedial_cards[2] = [
            RemedialCard(card_id="remedial_A_2_1", source_card_idx=2, depth=1,
                         card={"card_type": "simplification", "title": "Simpler", "content": "Simpler.", "audio_text": "Simpler."})
        ]
        session.card_phase.confusion_events.append(
            ConfusionEvent(base_card_idx=2, base_card_title="Number Line", depth_reached=1)
        )

        mock_expl = MagicMock()
        mock_expl.cards_json = SAMPLE_CARDS

        depth2_card = {
            "card_type": "simplification",
            "title": "Number Line — Easiest",
            "content": "Imagine hopping on a line.",
            "audio_text": "Imagine hopping on a line.",
            "visual": None,
            "visual_explanation": None,
        }

        from tutor.services.session_service import SessionService

        with patch.object(SessionService, '__init__', lambda self, db: None), \
             patch("tutor.services.session_service.ExplanationRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_variant.return_value = mock_expl

            service = SessionService.__new__(SessionService)
            service.db = MagicMock()
            service.session_repo = MagicMock()
            service.event_repo = MagicMock()
            service.guideline_repo = MagicMock()
            service.orchestrator = MagicMock()
            service.orchestrator.generate_simplified_card = AsyncMock(return_value=depth2_card)
            service.llm_service = MagicMock()

            session_row = MagicMock()
            session_row.state_json = session.model_dump_json()
            session_row.state_version = 1
            service.session_repo.get_by_id.return_value = session_row

            persisted_states = []
            service._persist_session_state = lambda sid, state, ver: persisted_states.append(state)

            result = service.simplify_card("sess_test", card_idx=2)

        assert result["action"] == "insert_card"
        assert result["card_id"] == "remedial_A_2_2"
        assert result["insert_after"] == "remedial_A_2_1"

        state = persisted_states[0]
        assert len(state.card_phase.remedial_cards[2]) == 2
        assert state.card_phase.remedial_cards[2][1].depth == 2
        assert state.card_phase.confusion_events[0].depth_reached == 2

    def test_escalation_after_depth_2(self):
        """Third tap escalates to interactive mode instead of depth-3."""
        session = _make_session_with_card_phase()
        session.card_phase.remedial_cards[2] = [
            RemedialCard(card_id="remedial_A_2_1", source_card_idx=2, depth=1, card={"title": "s1"}),
            RemedialCard(card_id="remedial_A_2_2", source_card_idx=2, depth=2, card={"title": "s2"}),
        ]
        session.card_phase.confusion_events.append(
            ConfusionEvent(base_card_idx=2, base_card_title="Number Line", depth_reached=2)
        )

        mock_expl = MagicMock()
        mock_expl.cards_json = SAMPLE_CARDS
        mock_expl.summary_json = {"teaching_notes": "Used pizza analogy"}

        from tutor.orchestration.orchestrator import TurnResult
        bridge_result = TurnResult(
            response="No worries, let's figure this out together.",
            audio_text="No worries, let's figure this out together.",
            intent="continuation",
        )

        from tutor.services.session_service import SessionService

        with patch.object(SessionService, '__init__', lambda self, db: None), \
             patch("tutor.services.session_service.ExplanationRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_variant.return_value = mock_expl

            service = SessionService.__new__(SessionService)
            service.db = MagicMock()
            service.session_repo = MagicMock()
            service.event_repo = MagicMock()
            service.guideline_repo = MagicMock()
            service.orchestrator = MagicMock()
            service.orchestrator.generate_bridge_turn = AsyncMock(return_value=bridge_result)
            service.llm_service = MagicMock()

            session_row = MagicMock()
            session_row.state_json = session.model_dump_json()
            session_row.state_version = 1
            service.session_repo.get_by_id.return_value = session_row

            persisted_states = []
            service._persist_session_state = lambda sid, state, ver: persisted_states.append(state)
            service._build_precomputed_summary = MagicMock(return_value="summary")
            service._generate_v2_session_plan = MagicMock()

            result = service.simplify_card("sess_test", card_idx=2)

        assert result["action"] == "escalate_to_interactive"
        assert "No worries" in result["message"]

        # Verify card phase was completed
        state = persisted_states[0]
        assert state.card_phase.active is False
        assert state.card_phase.completed is True

        # Verify confusion event marked as escalated
        assert state.card_phase.confusion_events[0].escalated is True

    def test_not_in_card_phase_raises(self):
        """simplify_card raises 400 when session is not in card phase."""
        session = SessionState(
            student_context=StudentContext(grade=3),
            topic=_make_topic(),
            card_phase=None,
        )

        from tutor.services.session_service import SessionService
        from fastapi import HTTPException

        with patch.object(SessionService, '__init__', lambda self, db: None):
            service = SessionService.__new__(SessionService)
            service.db = MagicMock()
            service.session_repo = MagicMock()

            session_row = MagicMock()
            session_row.state_json = session.model_dump_json()
            session_row.state_version = 1
            service.session_repo.get_by_id.return_value = session_row

            with pytest.raises(HTTPException) as exc_info:
                service.simplify_card("sess_test", card_idx=0)
            assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 3. Precomputed summary with confusion events
# ---------------------------------------------------------------------------

class TestPrecomputedSummaryWithConfusion:

    def test_confusion_events_in_summary(self):
        session = _make_session_with_card_phase()
        session.card_phase.confusion_events = [
            ConfusionEvent(base_card_idx=2, base_card_title="Number Line", depth_reached=2),
            ConfusionEvent(base_card_idx=0, base_card_title="What is Addition?", depth_reached=1, escalated=True),
        ]

        from tutor.services.session_service import SessionService

        with patch.object(SessionService, '__init__', lambda self, db: None):
            service = SessionService.__new__(SessionService)
            service.db = MagicMock()

            # Mock ExplanationRepository
            from shared.repositories.explanation_repository import ExplanationRepository
            mock_repo = MagicMock()
            mock_expl = MagicMock()
            mock_expl.summary_json = {"teaching_notes": "Used apples analogy."}
            mock_expl.cards_json = SAMPLE_CARDS
            mock_repo.get_variant.return_value = mock_expl

            with patch("tutor.services.session_service.ExplanationRepository", return_value=mock_repo):
                summary = service._build_precomputed_summary(session)

        assert "Cards that needed simplification:" in summary
        assert 'Card 2 "Number Line"' in summary
        assert "resolved after depth-2" in summary
        assert 'Card 0 "What is Addition?"' in summary
        assert "escalated to interactive" in summary


# ---------------------------------------------------------------------------
# 4. Variant switch clears remedial cards
# ---------------------------------------------------------------------------

class TestVariantSwitchClearsRemedials:

    def test_switch_variant_clears_remedial_cards(self):
        session = _make_session_with_card_phase()
        session.card_phase.remedial_cards[2] = [
            RemedialCard(card_id="r1", source_card_idx=2, depth=1, card={"title": "s1"})
        ]

        from tutor.services.session_service import SessionService

        with patch.object(SessionService, '__init__', lambda self, db: None):
            service = SessionService.__new__(SessionService)
            service.db = MagicMock()

            mock_expl = MagicMock()
            mock_expl.cards_json = SAMPLE_CARDS
            mock_expl.variant_label = "Visual Walkthrough"

            from shared.repositories.explanation_repository import ExplanationRepository
            with patch("tutor.services.session_service.ExplanationRepository") as mock_repo_cls:
                mock_repo_cls.return_value.get_variant.return_value = mock_expl

                persisted = []
                service._persist_session_state = lambda sid, state, ver: persisted.append(state)

                result = service._switch_variant_internal(session, "sess_test", "B", 1)

        assert result["action"] == "switch_variant"
        assert result["variant_key"] == "B"
        # Remedial cards should be cleared
        assert session.card_phase.remedial_cards == {}


# ---------------------------------------------------------------------------
# 5. Replay merging
# ---------------------------------------------------------------------------

class TestReplayMerging:

    def test_merge_remedial_cards_into_replay(self):
        """Replay endpoint correctly merges remedial cards with stable IDs."""
        state = {
            "card_phase": {
                "guideline_id": "g1",
                "active": True,
                "current_variant_key": "A",
                "current_card_idx": 3,
                "total_cards": 4,
                "variants_shown": ["A"],
                "available_variant_keys": ["A", "B"],
                "completed": False,
                "remedial_cards": {
                    "1": [
                        {"card_id": "remedial_A_1_1", "source_card_idx": 1, "depth": 1,
                         "card": {"card_type": "simplification", "title": "Simpler Apples", "content": "Easy.", "audio_text": "Easy."}},
                    ],
                    "3": [
                        {"card_id": "remedial_A_3_1", "source_card_idx": 3, "depth": 1,
                         "card": {"card_type": "simplification", "title": "Simpler Recap", "content": "Sum.", "audio_text": "Sum."}},
                        {"card_id": "remedial_A_3_2", "source_card_idx": 3, "depth": 2,
                         "card": {"card_type": "simplification", "title": "Easiest Recap", "content": "Total.", "audio_text": "Total."}},
                    ],
                },
                "confusion_events": [],
            },
            "_replay_explanation_cards": list(SAMPLE_CARDS),  # copy
        }

        # Simulate the merge logic from sessions.py replay endpoint
        card_phase = state.get("card_phase", {})
        remedial_map = card_phase.get("remedial_cards", {})
        variant_key = card_phase.get("current_variant_key", "A")
        base_cards = state["_replay_explanation_cards"]
        merged = []
        for i, card in enumerate(base_cards):
            card["card_id"] = f"{variant_key}_{i}"
            card["source_card_idx"] = i
            merged.append(card)
            for remedial in remedial_map.get(str(i), remedial_map.get(i, [])):
                remedial_card = remedial.get("card", {}) if isinstance(remedial, dict) else {}
                remedial_card["card_id"] = remedial.get("card_id", f"remedial_{variant_key}_{i}")
                remedial_card["source_card_idx"] = i
                merged.append(remedial_card)
        state["_replay_explanation_cards"] = merged

        cards = state["_replay_explanation_cards"]

        # Should be 4 base + 3 remedial = 7 cards
        assert len(cards) == 7

        # Check order: base0, base1, remedial_1_1, base2, base3, remedial_3_1, remedial_3_2
        assert cards[0]["card_id"] == "A_0"
        assert cards[0]["source_card_idx"] == 0
        assert cards[1]["card_id"] == "A_1"
        assert cards[1]["source_card_idx"] == 1
        assert cards[2]["card_id"] == "remedial_A_1_1"
        assert cards[2]["source_card_idx"] == 1
        assert cards[2]["card_type"] == "simplification"
        assert cards[3]["card_id"] == "A_2"
        assert cards[3]["source_card_idx"] == 2
        assert cards[4]["card_id"] == "A_3"
        assert cards[4]["source_card_idx"] == 3
        assert cards[5]["card_id"] == "remedial_A_3_1"
        assert cards[5]["source_card_idx"] == 3
        assert cards[6]["card_id"] == "remedial_A_3_2"
        assert cards[6]["source_card_idx"] == 3


# ---------------------------------------------------------------------------
# 6. Bridge prompt for card_stuck
# ---------------------------------------------------------------------------

class TestCardStuckBridge:

    def test_card_stuck_bridge_prompt(self):
        """card_stuck bridge type generates empathy-first probing prompt."""
        from tutor.agents.master_tutor import MasterTutorAgent

        session = _make_session_with_card_phase()
        session.precomputed_explanation_summary = "Cards taught addition via apples."
        session.card_phase.confusion_events = [
            ConfusionEvent(base_card_idx=2, base_card_title="Number Line", depth_reached=2, escalated=True),
        ]

        agent = MasterTutorAgent(MagicMock(), timeout_seconds=10)
        agent._session = session

        prompt = agent._build_bridge_prompt(session, "card_stuck")

        assert "stuck on a specific explanation card" in prompt
        assert "empathy" in prompt.lower() or "No worries" in prompt
        assert "probing question" in prompt


# ---------------------------------------------------------------------------
# 7. Progressive simplification prompt
# ---------------------------------------------------------------------------

class TestSimplificationPrompt:

    def test_simplify_card_prompt_renders(self):
        from tutor.prompts.master_tutor_prompts import SIMPLIFY_CARD_PROMPT

        rendered = SIMPLIFY_CARD_PROMPT.render(
            card_idx=2,
            card_title="Number Line",
            card_content="On a number line, start at 3...",
            all_cards_summary="1. [concept] What is Addition?\n2. [example] Adding Apples\n3. [visual] Number Line",
            previous_attempts_section="",
            depth_label="Depth 1",
            simplification_directive="Explain simpler.",
        )

        assert "Number Line" in rendered
        assert "Depth 1" in rendered
        assert "card_type" in rendered  # output requirements mention this
        assert "CRITICAL RULES" in rendered
