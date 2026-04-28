"""Unit tests for the Phase 4 BaatcheetVisualEnrichmentService refactor.

Covers:
- V2 path: plan_json drives the selector; selected cards get PixiJS code
  routed through PixiCodeGenerator (LLM mocked).
- V1 fallback: card_type=="visual" cards with visual_intent enrich without
  the selector LLM call.
- Idempotency: cards with existing pixi_code skip unless force=True.
- Selector error: surfaces as a single failure entry, doesn't crash.
- Stage status_check: V2 done criterion is "every visual_required slot
  has a pixi card"; V1 fallback uses card_type=="visual" count.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock

import pytest

from book_ingestion_v2.services.baatcheet_visual_enrichment_service import (
    BaatcheetVisualEnrichmentService,
)
from book_ingestion_v2.stages.baatcheet_visuals import STAGE
from book_ingestion_v2.dag.types import StatusContext
from shared.models.entities import (
    Book,
    TeachingGuideline,
    TopicDialogue,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_guideline(db_session, *, topic_title="Comparing Fractions"):
    book_id = str(uuid.uuid4())
    guideline_id = str(uuid.uuid4())
    db_session.add(Book(
        id=book_id, title="T", country="India", board="CBSE", grade=4,
        subject="Mathematics", s3_prefix=f"books/{book_id}/",
    ))
    g = TeachingGuideline(
        id=guideline_id, country="India", board="CBSE", grade=4,
        subject="Mathematics", chapter="Fractions",
        topic="Comparing Fractions", guideline="g",
        chapter_key="chapter-1", topic_key="comparing-fractions",
        chapter_title="Fractions", topic_title=topic_title,
        book_id=book_id, review_status="APPROVED", topic_sequence=1,
    )
    db_session.add(g)
    db_session.commit()
    return g


def _v2_plan(visual_required_slots=(2, 4)):
    return {
        "spine": "road trip",
        "card_plan": [
            {"slot": s, "move": "x", "speaker": "tutor",
             "card_type": "tutor_turn", "target": "t", "intent": "...",
             "visual_required": (s in visual_required_slots)}
            for s in [2, 3, 4, 5]
        ],
    }


def _v2_dialogue_cards():
    return [
        {"card_idx": 1, "card_type": "welcome", "speaker": "tutor",
         "lines": [{"display": "Hello"}]},
        {"card_idx": 2, "card_type": "tutor_turn", "speaker": "tutor",
         "lines": [{"display": "Today we compare fractions."}]},
        {"card_idx": 3, "card_type": "peer_turn", "speaker": "peer",
         "lines": [{"display": "Hmm."}]},
        {"card_idx": 4, "card_type": "tutor_turn", "speaker": "tutor",
         "lines": [{"display": "Look at 1/2 vs 1/4."}]},
        {"card_idx": 5, "card_type": "peer_turn", "speaker": "peer",
         "lines": [{"display": "Got it."}]},
    ]


def _v1_dialogue_cards():
    return [
        {"card_idx": 1, "card_type": "welcome", "lines": [{"display": "Hi"}]},
        {"card_idx": 2, "card_type": "visual",
         "visual_intent": "A pie cut in half.",
         "lines": [{"display": "See the pie."}]},
        {"card_idx": 3, "card_type": "tutor_turn",
         "lines": [{"display": "What do you see?"}]},
        {"card_idx": 4, "card_type": "visual",
         "visual_intent": "A pie cut in quarters.",
         "lines": [{"display": "Now in quarters."}]},
    ]


def _seed_dialogue(
    db_session, guideline_id, *, cards, plan=None,
    source_content_hash="hash-1",
):
    dlg = TopicDialogue(
        id=str(uuid.uuid4()),
        guideline_id=guideline_id,
        cards_json=cards,
        plan_json=plan,
        generator_model="claude-opus-4-7",
        source_variant_key="A",
        source_content_hash=source_content_hash,
    )
    db_session.add(dlg)
    db_session.commit()
    return dlg


def _make_llm_with_selector(visualizations: list[dict]):
    """LLMService stub whose `.call(...)` returns a parsed selector response.

    The service code passes `json_mode=True` so it accepts either `parsed`
    or a JSON-bearing `output_text`. We populate `parsed` directly.
    """
    llm = MagicMock()
    llm.call.return_value = {
        "parsed": {"visualizations": visualizations},
        "output_text": "",
        "reasoning": None,
    }
    return llm


def _patch_pixi_gen(service, *, code: str = "/* fake pixi */"):
    """Replace the service's PixiCodeGenerator with one whose generate
    returns the supplied code."""
    async def _fake_generate(prompt, output_type="image"):
        return code
    service.pixi_gen = SimpleNamespace(generate=_fake_generate)


# ---------------------------------------------------------------------------
# V2 path
# ---------------------------------------------------------------------------


class TestEnrichV2:
    def test_required_cards_get_pixi(self, db_session):
        g = _seed_guideline(db_session)
        _seed_dialogue(
            db_session, g.id,
            cards=_v2_dialogue_cards(),
            plan=_v2_plan(visual_required_slots=(2, 4)),
        )
        # Selector picks both required slots + one extra (slot 3 conversational).
        llm = _make_llm_with_selector([
            {"card_idx": 2, "visual_intent": "Compare 1/2 and 1/4.",
             "why": "Anchors topic"},
            {"card_idx": 4, "visual_intent": "Pie chart half vs quarter.",
             "why": "Concrete"},
        ])
        svc = BaatcheetVisualEnrichmentService(db_session, llm)
        _patch_pixi_gen(svc, code="// pixi for card")

        result = svc.enrich_guideline(g)

        assert result["selected_count"] == 2
        assert result["enriched"] == 2
        assert result["failed"] == 0
        # LLM was called once (selector); pixi mocked.
        assert llm.call.call_count == 1

        # Persistence: cards 2 and 4 now have visual_explanation.pixi_code.
        from shared.repositories.dialogue_repository import DialogueRepository
        d = DialogueRepository(db_session).get_by_guideline_id(g.id)
        by_idx = {c["card_idx"]: c for c in d.cards_json}
        assert by_idx[2]["visual_explanation"]["pixi_code"] == "// pixi for card"
        assert by_idx[2]["visual_explanation"]["output_type"] == "static_visual"
        assert by_idx[4]["visual_explanation"]["pixi_code"] == "// pixi for card"
        assert "visual_explanation" not in by_idx[3]
        # plan_json survived the upsert.
        assert d.plan_json is not None and d.plan_json["spine"] == "road trip"

    def test_selector_failure_records_failure_no_pixi_calls(self, db_session):
        g = _seed_guideline(db_session)
        _seed_dialogue(
            db_session, g.id,
            cards=_v2_dialogue_cards(),
            plan=_v2_plan(),
        )
        # LLM call returns unparseable response.
        llm = MagicMock()
        llm.call.return_value = {
            "parsed": None,
            "output_text": "I don't know how to do this",
            "reasoning": None,
        }
        svc = BaatcheetVisualEnrichmentService(db_session, llm)
        pixi_calls: list = []

        async def _track_generate(prompt, output_type="image"):
            pixi_calls.append(prompt)
            return "should-not-be-called"
        svc.pixi_gen = SimpleNamespace(generate=_track_generate)

        result = svc.enrich_guideline(g)
        assert result["failed"] == 1
        assert result["enriched"] == 0
        # Selector failure short-circuits BEFORE any pixi call.
        assert pixi_calls == []
        assert any("selector failed" in e for e in result["errors"])

    def test_pixi_failure_records_failure_other_cards_continue(self, db_session):
        g = _seed_guideline(db_session)
        _seed_dialogue(
            db_session, g.id,
            cards=_v2_dialogue_cards(),
            plan=_v2_plan(visual_required_slots=(2, 4)),
        )
        llm = _make_llm_with_selector([
            {"card_idx": 2, "visual_intent": "A.", "why": "x"},
            {"card_idx": 4, "visual_intent": "B.", "why": "y"},
        ])
        svc = BaatcheetVisualEnrichmentService(db_session, llm)

        # Pixi fails on card 2 (returns empty), succeeds on card 4.
        async def _selective(prompt, output_type="image"):
            if "A." in prompt:
                return ""  # service treats empty as failure
            return "// ok"
        svc.pixi_gen = SimpleNamespace(generate=_selective)

        result = svc.enrich_guideline(g)
        assert result["enriched"] == 1
        assert result["failed"] == 1
        assert result["cards_with_visuals_total"] == 2

        from shared.repositories.dialogue_repository import DialogueRepository
        d = DialogueRepository(db_session).get_by_guideline_id(g.id)
        by_idx = {c["card_idx"]: c for c in d.cards_json}
        assert "visual_explanation" not in by_idx[2]
        assert by_idx[4]["visual_explanation"]["pixi_code"] == "// ok"

    def test_idempotent_skips_existing_unless_force(self, db_session):
        g = _seed_guideline(db_session)
        cards = _v2_dialogue_cards()
        # Pre-existing pixi on card 2.
        cards[1]["visual_explanation"] = {
            "output_type": "static_visual",
            "pixi_code": "// existing",
        }
        _seed_dialogue(
            db_session, g.id, cards=cards,
            plan=_v2_plan(visual_required_slots=(2, 4)),
        )
        llm = _make_llm_with_selector([
            {"card_idx": 2, "visual_intent": "A.", "why": "x"},
            {"card_idx": 4, "visual_intent": "B.", "why": "y"},
        ])
        svc = BaatcheetVisualEnrichmentService(db_session, llm)
        _patch_pixi_gen(svc, code="// fresh")

        # Without force: card 2 keeps existing, card 4 gets fresh.
        result = svc.enrich_guideline(g)
        assert result["enriched"] == 1
        assert result["skipped"] == 1

        from shared.repositories.dialogue_repository import DialogueRepository
        d = DialogueRepository(db_session).get_by_guideline_id(g.id)
        by_idx = {c["card_idx"]: c for c in d.cards_json}
        assert by_idx[2]["visual_explanation"]["pixi_code"] == "// existing"
        assert by_idx[4]["visual_explanation"]["pixi_code"] == "// fresh"

        # With force: card 2 also gets re-generated.
        result2 = svc.enrich_guideline(g, force=True)
        assert result2["enriched"] == 2
        d2 = DialogueRepository(db_session).get_by_guideline_id(g.id)
        by_idx2 = {c["card_idx"]: c for c in d2.cards_json}
        assert by_idx2[2]["visual_explanation"]["pixi_code"] == "// fresh"


# ---------------------------------------------------------------------------
# V1 fallback
# ---------------------------------------------------------------------------


class TestEnrichV1Fallback:
    def test_no_plan_uses_card_type_visual_cards(self, db_session):
        g = _seed_guideline(db_session)
        _seed_dialogue(
            db_session, g.id,
            cards=_v1_dialogue_cards(),
            plan=None,
        )
        # Selector should NOT be called when plan_json is missing.
        llm = MagicMock()
        llm.call.side_effect = AssertionError(
            "selector LLM must not be called for V1 dialogues"
        )
        svc = BaatcheetVisualEnrichmentService(db_session, llm)
        _patch_pixi_gen(svc, code="// v1 pixi")

        result = svc.enrich_guideline(g)
        assert result["enriched"] == 2
        assert llm.call.call_count == 0

        from shared.repositories.dialogue_repository import DialogueRepository
        d = DialogueRepository(db_session).get_by_guideline_id(g.id)
        by_idx = {c["card_idx"]: c for c in d.cards_json}
        assert by_idx[2]["visual_explanation"]["pixi_code"] == "// v1 pixi"
        assert by_idx[4]["visual_explanation"]["pixi_code"] == "// v1 pixi"
        assert "visual_explanation" not in by_idx[3]


# ---------------------------------------------------------------------------
# Stage status_check
# ---------------------------------------------------------------------------


class TestStageStatusV2:
    def _ctx(self, db_session, guideline_id, chapter_id="c"):
        return StatusContext(
            db=db_session, guideline_id=guideline_id,
            chapter_id=chapter_id, explanations=[], content_anchor=None,
        )

    def _has_pixi(self, card_idx, code="// p"):
        return {
            "card_idx": card_idx, "card_type": "tutor_turn",
            "lines": [{"display": "x"}],
            "visual_explanation": {
                "output_type": "static_visual", "pixi_code": code,
            },
        }

    def _no_pixi(self, card_idx):
        return {
            "card_idx": card_idx, "card_type": "tutor_turn",
            "lines": [{"display": "x"}],
        }

    def test_done_when_every_required_card_has_pixi(self, db_session):
        g = _seed_guideline(db_session)
        cards = [
            {"card_idx": 1, "card_type": "welcome", "lines": []},
            self._has_pixi(2),
            {"card_idx": 3, "card_type": "peer_turn", "lines": []},
            self._has_pixi(4),
        ]
        _seed_dialogue(
            db_session, g.id, cards=cards,
            plan=_v2_plan(visual_required_slots=(2, 4)),
        )
        out = STAGE.status_check(self._ctx(db_session, g.id))
        assert out.state == "done"
        assert "2/2 required" in out.summary

    def test_warning_when_some_required_missing(self, db_session):
        g = _seed_guideline(db_session)
        cards = [
            {"card_idx": 1, "card_type": "welcome", "lines": []},
            self._has_pixi(2),
            self._no_pixi(4),
        ]
        _seed_dialogue(
            db_session, g.id, cards=cards,
            plan=_v2_plan(visual_required_slots=(2, 4)),
        )
        out = STAGE.status_check(self._ctx(db_session, g.id))
        assert out.state == "warning"
        assert "1/2 required" in out.summary

    def test_ready_when_no_pixi_anywhere(self, db_session):
        g = _seed_guideline(db_session)
        cards = [
            {"card_idx": 1, "card_type": "welcome", "lines": []},
            self._no_pixi(2),
            self._no_pixi(4),
        ]
        _seed_dialogue(
            db_session, g.id, cards=cards,
            plan=_v2_plan(visual_required_slots=(2, 4)),
        )
        out = STAGE.status_check(self._ctx(db_session, g.id))
        assert out.state == "ready"

    def test_extras_count_does_not_gate_done(self, db_session):
        # Required slots 2,4 done; extra card 3 also has pixi → still done.
        g = _seed_guideline(db_session)
        cards = [
            {"card_idx": 1, "card_type": "welcome", "lines": []},
            self._has_pixi(2),
            self._has_pixi(3),  # extra, not visual_required
            self._has_pixi(4),
        ]
        _seed_dialogue(
            db_session, g.id, cards=cards,
            plan=_v2_plan(visual_required_slots=(2, 4)),
        )
        out = STAGE.status_check(self._ctx(db_session, g.id))
        assert out.state == "done"
        assert "1 extras" in out.summary

    def test_no_required_slots_is_trivially_done(self, db_session):
        g = _seed_guideline(db_session)
        cards = [
            {"card_idx": 1, "card_type": "welcome", "lines": []},
            self._no_pixi(2),
        ]
        _seed_dialogue(
            db_session, g.id, cards=cards,
            plan=_v2_plan(visual_required_slots=()),
        )
        out = STAGE.status_check(self._ctx(db_session, g.id))
        assert out.state == "done"

    def test_blocked_when_no_dialogue(self, db_session):
        g = _seed_guideline(db_session)
        # No dialogue row.
        out = STAGE.status_check(self._ctx(db_session, g.id))
        assert out.state == "blocked"


class TestStageStatusV1Fallback:
    def _ctx(self, db_session, guideline_id, chapter_id="c"):
        return StatusContext(
            db=db_session, guideline_id=guideline_id,
            chapter_id=chapter_id, explanations=[], content_anchor=None,
        )

    def test_v1_done_when_all_visual_cards_have_pixi(self, db_session):
        g = _seed_guideline(db_session)
        cards = [
            {"card_idx": 1, "card_type": "welcome", "lines": []},
            {"card_idx": 2, "card_type": "visual",
             "visual_explanation": {
                 "output_type": "static_visual", "pixi_code": "//p"
             }},
            {"card_idx": 3, "card_type": "visual",
             "visual_explanation": {
                 "output_type": "static_visual", "pixi_code": "//q"
             }},
        ]
        _seed_dialogue(db_session, g.id, cards=cards, plan=None)
        out = STAGE.status_check(self._ctx(db_session, g.id))
        assert out.state == "done"
        assert "2/2 visual cards" in out.summary

    def test_v1_warning_when_some_missing(self, db_session):
        g = _seed_guideline(db_session)
        cards = [
            {"card_idx": 1, "card_type": "welcome", "lines": []},
            {"card_idx": 2, "card_type": "visual",
             "visual_explanation": {
                 "output_type": "static_visual", "pixi_code": "//p"
             }},
            {"card_idx": 3, "card_type": "visual"},  # no pixi
        ]
        _seed_dialogue(db_session, g.id, cards=cards, plan=None)
        out = STAGE.status_check(self._ctx(db_session, g.id))
        assert out.state == "warning"


# ---------------------------------------------------------------------------
# Helpers — slim_cards_for_prompt + selector parsing
# ---------------------------------------------------------------------------


class TestSelectorParsing:
    def test_extract_json_from_fenced(self):
        from book_ingestion_v2.services.baatcheet_visual_enrichment_service import (
            _extract_json,
        )
        text = '```json\n{"visualizations": [{"card_idx": 2}]}\n```'
        assert _extract_json(text) == {"visualizations": [{"card_idx": 2}]}

    def test_extract_json_from_bare(self):
        from book_ingestion_v2.services.baatcheet_visual_enrichment_service import (
            _extract_json,
        )
        text = 'Some preamble {"visualizations": [{"card_idx": 2}]} trailing'
        assert _extract_json(text) == {"visualizations": [{"card_idx": 2}]}

    def test_extract_json_returns_none_on_garbage(self):
        from book_ingestion_v2.services.baatcheet_visual_enrichment_service import (
            _extract_json,
        )
        assert _extract_json("nothing useful") is None

    def test_slim_cards_only_keeps_essentials(self):
        cards = [
            {"card_idx": 2, "card_type": "tutor_turn", "speaker": "tutor",
             "speaker_name": "Mr. Verma",
             "lines": [{"display": "X", "audio": "X."}],
             "visual_intent": "old intent", "extra_garbage": True},
        ]
        slim = BaatcheetVisualEnrichmentService._slim_cards_for_prompt(cards)
        assert slim == [{
            "card_idx": 2, "card_type": "tutor_turn", "speaker": "tutor",
            "speaker_name": "Mr. Verma",
            "lines": [{"display": "X"}],
            "existing_visual_intent": "old intent",
        }]
