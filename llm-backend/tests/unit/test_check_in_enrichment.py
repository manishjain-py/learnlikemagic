"""Tests for check-in enrichment: validation, card insertion, struggle signals, summary builder."""
import json
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from shared.repositories.explanation_repository import (
    ExplanationCard, MatchPair, CheckInActivity,
)
from tutor.models.session_state import (
    CardPhaseState, CheckInStruggleEvent,
)
from tutor.models.messages import CardActionRequest, CheckInEventDTO


# ─── Helpers ──────────────────────────────────────────────────────────────

def _sample_cards(n=5, include_summary=True):
    """Build a list of explanation card dicts (1-based card_idx)."""
    cards = []
    for i in range(1, n + 1):
        card_type = "summary" if include_summary and i == n else "concept"
        cards.append({
            "card_id": str(uuid4()),
            "card_idx": i,
            "card_type": card_type,
            "title": f"Card {i}",
            "content": f"Content for card {i}",
            "audio_text": f"Audio for card {i}",
        })
    return cards


def _make_check_in_decision(insert_after=3, num_pairs=3, activity_type="match_pairs"):
    """Build a mock CheckInDecision."""
    from book_ingestion_v2.services.check_in_enrichment_service import CheckInDecision, MatchPairOutput
    return CheckInDecision(
        insert_after_card_idx=insert_after,
        activity_type=activity_type,
        title="Let's check!",
        instruction="Match each term to its meaning",
        pairs=[MatchPairOutput(left=f"Term {j}", right=f"Meaning {j}") for j in range(num_pairs)],
        hint="Think about what you just read",
        success_message="Great job!",
        audio_text="Match each term to its meaning",
    )


# ─── Model Tests ──────────────────────────────────────────────────────────

class TestExplanationCardModel:
    """ExplanationCard Pydantic model with new check-in fields."""

    def test_parses_with_check_in(self):
        card = ExplanationCard(
            card_id="uuid-1", card_idx=1, card_type="check_in", title="Check",
            content="Match them", audio_text="Match them",
            check_in=CheckInActivity(
                activity_type="match_pairs", instruction="Match",
                pairs=[MatchPair(left="A", right="B")],
                hint="Try again", success_message="Nice!", audio_text="Match",
            ),
        )
        assert card.card_type == "check_in"
        assert card.check_in.pairs[0].left == "A"

    def test_parses_without_check_in(self):
        """Backwards compat — existing cards without card_id/check_in still parse."""
        card = ExplanationCard(
            card_idx=1, card_type="concept", title="Fractions",
            content="A fraction is...",
        )
        assert card.card_id is None
        assert card.check_in is None

    def test_roundtrip_serialization(self):
        card = ExplanationCard(
            card_id="uuid-1", card_idx=1, card_type="check_in", title="Check",
            content="Match", check_in=CheckInActivity(
                activity_type="match_pairs", instruction="Match",
                pairs=[MatchPair(left="X", right="Y")],
                hint="Hint", success_message="Done!", audio_text="Match",
            ),
        )
        dumped = card.model_dump()
        restored = ExplanationCard.model_validate(dumped)
        assert restored.check_in.pairs[0].left == "X"


class TestCheckInStruggleEvent:
    def test_creates_with_confused_pairs(self):
        evt = CheckInStruggleEvent(
            card_idx=5, card_title="Match fractions",
            wrong_count=3, hints_shown=2,
            confused_pairs=[{"left": "1/2", "right": "half", "wrong_count": 2, "wrong_picks": ["quarter"]}],
            auto_revealed=0,
        )
        assert evt.wrong_count == 3
        assert evt.confused_pairs[0]["wrong_picks"] == ["quarter"]

    def test_card_phase_state_includes_check_in_struggles(self):
        cps = CardPhaseState(
            guideline_id="g1", variants_shown=["A"], available_variant_keys=["A"],
            check_in_struggles=[
                CheckInStruggleEvent(card_idx=5, card_title="Check", wrong_count=2),
            ],
        )
        assert len(cps.check_in_struggles) == 1


class TestCardActionRequest:
    def test_accepts_check_in_events(self):
        req = CardActionRequest(
            action="clear",
            check_in_events=[
                CheckInEventDTO(card_idx=5, card_title="Match fractions", wrong_count=3),
            ],
        )
        assert req.check_in_events[0].card_title == "Match fractions"

    def test_works_without_check_in_events(self):
        req = CardActionRequest(action="explain_differently")
        assert req.check_in_events is None


# ─── Validation Tests ─────────────────────────────────────────────────────

class TestCheckInValidation:
    """Tests for _validate_check_ins in CheckInEnrichmentService."""

    def _get_service(self):
        from book_ingestion_v2.services.check_in_enrichment_service import CheckInEnrichmentService
        svc = CheckInEnrichmentService.__new__(CheckInEnrichmentService)
        return svc

    def test_valid_check_in_passes(self):
        svc = self._get_service()
        cards = _sample_cards(6)
        ci = _make_check_in_decision(insert_after=3, num_pairs=3)
        result = svc._validate_check_ins([ci], cards)
        assert len(result) == 1

    def test_rejects_too_few_pairs(self):
        svc = self._get_service()
        cards = _sample_cards(6)
        ci = _make_check_in_decision(insert_after=3, num_pairs=1)
        result = svc._validate_check_ins([ci], cards)
        assert len(result) == 0

    def test_rejects_too_many_pairs(self):
        svc = self._get_service()
        cards = _sample_cards(6)
        ci = _make_check_in_decision(insert_after=3, num_pairs=4)  # MAX_PAIRS is now 3
        result = svc._validate_check_ins([ci], cards)
        assert len(result) == 0

    def test_rejects_invalid_card_idx(self):
        svc = self._get_service()
        cards = _sample_cards(6)
        ci = _make_check_in_decision(insert_after=99)
        result = svc._validate_check_ins([ci], cards)
        assert len(result) == 0

    def test_rejects_after_summary(self):
        svc = self._get_service()
        cards = _sample_cards(6, include_summary=True)  # card 6 is summary
        ci = _make_check_in_decision(insert_after=6)
        result = svc._validate_check_ins([ci], cards)
        assert len(result) == 0

    def test_rejects_too_early(self):
        """Check-in before card_idx 3 is dropped."""
        svc = self._get_service()
        cards = _sample_cards(6)
        ci = _make_check_in_decision(insert_after=1)
        result = svc._validate_check_ins([ci], cards)
        assert len(result) == 0

    def test_rejects_insufficient_gap(self):
        """Two check-ins at same card_idx — second is dropped (gap=0 < MIN_GAP=1)."""
        svc = self._get_service()
        cards = _sample_cards(8)
        ci1 = _make_check_in_decision(insert_after=3)
        ci2 = _make_check_in_decision(insert_after=3)  # gap of 0 — too close
        result = svc._validate_check_ins([ci1, ci2], cards)
        assert len(result) == 1
        assert result[0].insert_after_card_idx == 3

    def test_accepts_sufficient_gap(self):
        """Two check-ins with gap >= 1 — both pass."""
        svc = self._get_service()
        cards = _sample_cards(8)
        ci1 = _make_check_in_decision(insert_after=3)
        ci2 = _make_check_in_decision(insert_after=4)  # gap of 1 — OK (MIN_GAP=1)
        result = svc._validate_check_ins([ci1, ci2], cards)
        assert len(result) == 2

    def test_rejects_duplicate_left_items(self):
        from book_ingestion_v2.services.check_in_enrichment_service import CheckInDecision, MatchPairOutput
        svc = self._get_service()
        cards = _sample_cards(6)
        ci = CheckInDecision(
            insert_after_card_idx=3, activity_type="match_pairs",
            title="Check", instruction="Match",
            pairs=[
                MatchPairOutput(left="Same", right="A"),
                MatchPairOutput(left="Same", right="B"),  # duplicate left
                MatchPairOutput(left="Other", right="C"),
            ],
            hint="Hint", success_message="Done!", audio_text="Match",
        )
        result = svc._validate_check_ins([ci], cards)
        assert len(result) == 0


# ─── Card Insertion Tests ─────────────────────────────────────────────────

class TestCardInsertion:
    def _get_service(self):
        from book_ingestion_v2.services.check_in_enrichment_service import CheckInEnrichmentService
        svc = CheckInEnrichmentService.__new__(CheckInEnrichmentService)
        return svc

    def test_inserts_at_correct_position(self):
        svc = self._get_service()
        cards = _sample_cards(5)
        ci = _make_check_in_decision(insert_after=3)
        merged = svc._insert_check_ins(cards, [ci])
        # Should be: card1, card2, card3, CHECK-IN, card4, card5
        assert len(merged) == 6
        assert merged[0]["card_type"] == "concept"  # card 1
        assert merged[2]["card_type"] == "concept"  # card 3
        assert merged[3]["card_type"] == "check_in"  # inserted
        assert merged[4]["card_type"] == "concept"  # card 4

    def test_check_in_card_has_required_fields(self):
        svc = self._get_service()
        cards = _sample_cards(5)
        ci = _make_check_in_decision(insert_after=3)
        merged = svc._insert_check_ins(cards, [ci])
        check_in_card = merged[3]
        assert check_in_card["card_type"] == "check_in"
        assert "card_id" in check_in_card
        assert "check_in" in check_in_card
        assert check_in_card["check_in"]["activity_type"] == "match_pairs"
        assert len(check_in_card["check_in"]["pairs"]) == 3

    def test_multiple_insertions_correct_order(self):
        svc = self._get_service()
        cards = _sample_cards(8)
        ci1 = _make_check_in_decision(insert_after=3)
        ci2 = _make_check_in_decision(insert_after=6)
        merged = svc._insert_check_ins(cards, [ci1, ci2])
        assert len(merged) == 10
        # Find check-in positions
        check_in_positions = [i for i, c in enumerate(merged) if c["card_type"] == "check_in"]
        assert len(check_in_positions) == 2
        # First check-in after card 3 (index 2), so at index 3
        assert check_in_positions[0] == 3
        # Second check-in after card 6 (was index 5, now index 6 due to first insertion), so at index 7
        assert check_in_positions[1] == 7

    def test_card_ids_assigned_after_enrichment(self):
        """card_id assignment happens in _enrich_variant before _insert_check_ins.
        Verify that _insert_check_ins adds card_id to new check-in cards."""
        svc = self._get_service()
        cards = _sample_cards(5)
        ci = _make_check_in_decision(insert_after=3)
        merged = svc._insert_check_ins(cards, [ci])
        # Check-in card should have a card_id (generated by _insert_check_ins)
        check_in_card = [c for c in merged if c["card_type"] == "check_in"][0]
        assert "card_id" in check_in_card
        assert len(check_in_card["card_id"]) > 0


# ─── Summary Builder Tests ────────────────────────────────────────────────

class TestSummaryBuilderCheckIns:
    """Test that _build_precomputed_summary includes check-in struggle section."""

    def test_check_in_struggles_in_summary(self):
        from tutor.models.session_state import SessionState, CardPhaseState, CheckInStruggleEvent
        from tutor.services.session_service import SessionService

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()

        # Build session with check-in struggles
        session = MagicMock()
        session.card_phase = CardPhaseState(
            guideline_id="g1", variants_shown=["A"], available_variant_keys=["A"],
            check_in_struggles=[
                CheckInStruggleEvent(
                    card_idx=5, card_title="Match fractions",
                    wrong_count=4, hints_shown=2,
                    confused_pairs=[{"left": "1/2", "right": "half", "wrong_count": 3, "wrong_picks": ["quarter", "third"]}],
                    auto_revealed=0,
                ),
            ],
            confusion_events=[],
        )
        session.precomputed_explanation_summary = None

        # Mock the explanation repo
        mock_repo = MagicMock()
        mock_repo.get_variant.return_value = None
        with patch("tutor.services.session_service.ExplanationRepository", return_value=mock_repo):
            summary = svc._build_precomputed_summary(session)

        assert "Check-in struggles:" in summary
        assert "Match fractions" in summary
        assert "4 wrong attempts" in summary
        assert "quarter" in summary  # wrong_picks should appear

    def test_no_check_in_section_when_empty(self):
        from tutor.services.session_service import SessionService

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()

        session = MagicMock()
        session.card_phase = CardPhaseState(
            guideline_id="g1", variants_shown=["A"], available_variant_keys=["A"],
            check_in_struggles=[],
            confusion_events=[],
        )

        mock_repo = MagicMock()
        mock_repo.get_variant.return_value = None
        with patch("tutor.services.session_service.ExplanationRepository", return_value=mock_repo):
            summary = svc._build_precomputed_summary(session)

        assert "Check-in struggles:" not in summary


# ─── Review-Refine Tests ──────────────────────────────────────────────────

def _make_guideline_mock(topic="Place Value", grade=3, guideline_text="Teach digit counting."):
    """Minimal guideline-like object for review prompts."""
    g = MagicMock()
    g.topic_title = topic
    g.topic = topic
    g.subject = "Mathematics"
    g.grade = grade
    g.guideline = guideline_text
    g.description = guideline_text
    g.id = "g1"
    g.book_id = "b1"
    g.chapter_key = "chapter-1"
    return g


def _make_sort_buckets_decision(
    items=None, bucket_names=("3-DIGIT NUMBER", "4-DIGIT NUMBER"),
    insert_after=3, instruction="Put each number in the right group.",
):
    """Build a sort_buckets CheckInDecision for review tests.

    `items` is a list of (text, correct_bucket) tuples. Defaults to the exact
    bug from the screenshot: '87' miscategorised as a 3-digit number.
    """
    from book_ingestion_v2.services.check_in_enrichment_service import (
        CheckInDecision, BucketItemOutput,
    )
    if items is None:
        items = [
            ("352", 0), ("87", 0), ("999", 0),
            ("7,089", 1), ("1,000", 1), ("3,527", 1),
        ]
    return CheckInDecision(
        insert_after_card_idx=insert_after,
        activity_type="sort_buckets",
        title="Quick check!",
        instruction=instruction,
        hint="Count the digits.",
        success_message="Well done! 4-digit numbers start from 1,000.",
        audio_text=instruction,
        bucket_names=list(bucket_names),
        bucket_items=[BucketItemOutput(text=t, correct_bucket=b) for t, b in items],
    )


class TestCheckInReviewRefine:
    """Tests for _review_and_refine_check_ins — the accuracy-only LLM pass."""

    def _get_service_with_mock_llm(self):
        """Service skeleton with a MagicMock LLM and stubbed schema."""
        from book_ingestion_v2.services.check_in_enrichment_service import CheckInEnrichmentService
        svc = CheckInEnrichmentService.__new__(CheckInEnrichmentService)
        svc.llm = MagicMock()
        svc.llm.provider = "openai"
        svc._generation_schema = {"type": "object"}  # value unused; we mock parse_json_response
        return svc

    def test_preserves_unchanged_output_when_llm_returns_same(self):
        svc = self._get_service_with_mock_llm()
        ci = _make_sort_buckets_decision(items=[
            ("352", 0), ("387", 0), ("999", 0),
            ("7,089", 1), ("1,000", 1), ("3,527", 1),
        ])
        explanation_cards = _sample_cards(5)
        guideline = _make_guideline_mock()

        svc.llm.call.return_value = {"output_text": "unused — parse_json_response is mocked"}
        svc.llm.parse_json_response.return_value = {
            "check_ins": [ci.model_dump()],
        }

        out = svc._review_and_refine_check_ins([ci], explanation_cards, guideline)

        assert out is not None
        assert len(out.check_ins) == 1
        assert out.check_ins[0].activity_type == "sort_buckets"
        assert [bi.text for bi in out.check_ins[0].bucket_items] == \
            ["352", "387", "999", "7,089", "1,000", "3,527"]
        svc.llm.call.assert_called_once()

    def test_fixes_accuracy_bug_when_llm_corrects(self):
        """Input has '87' in '3-DIGIT NUMBER' bucket; reviewer rewrites to '387'."""
        svc = self._get_service_with_mock_llm()
        buggy = _make_sort_buckets_decision()  # defaults to the '87' bug
        fixed = _make_sort_buckets_decision(items=[
            ("352", 0), ("387", 0), ("999", 0),
            ("7,089", 1), ("1,000", 1), ("3,527", 1),
        ])
        explanation_cards = _sample_cards(5)
        guideline = _make_guideline_mock()

        svc.llm.call.return_value = {"output_text": "unused"}
        svc.llm.parse_json_response.return_value = {
            "check_ins": [fixed.model_dump()],
        }

        out = svc._review_and_refine_check_ins([buggy], explanation_cards, guideline)

        assert out is not None
        texts = [bi.text for bi in out.check_ins[0].bucket_items]
        assert "87" not in texts  # the bug is gone
        assert "387" in texts     # fixed value present

    def test_returns_none_on_llm_error(self):
        from shared.services.llm_service import LLMServiceError
        svc = self._get_service_with_mock_llm()
        ci = _make_sort_buckets_decision()
        guideline = _make_guideline_mock()
        svc.llm.call.side_effect = LLMServiceError("boom")

        out = svc._review_and_refine_check_ins([ci], _sample_cards(5), guideline)

        assert out is None

    def test_returns_none_on_invalid_json(self):
        svc = self._get_service_with_mock_llm()
        ci = _make_sort_buckets_decision()
        guideline = _make_guideline_mock()
        svc.llm.call.return_value = {"output_text": "not json"}
        svc.llm.parse_json_response.side_effect = json.JSONDecodeError("bad", "doc", 0)

        out = svc._review_and_refine_check_ins([ci], _sample_cards(5), guideline)

        assert out is None

    def test_prompt_includes_check_in_and_guideline_text(self):
        """Reviewer prompt must contain the check-in to review AND the ground-truth guideline."""
        svc = self._get_service_with_mock_llm()
        ci = _make_sort_buckets_decision()
        guideline = _make_guideline_mock(
            guideline_text="A 3-digit number has exactly three digits in the 100-999 range.",
        )

        svc.llm.call.return_value = {"output_text": "{}"}
        svc.llm.parse_json_response.return_value = {"check_ins": [ci.model_dump()]}

        svc._review_and_refine_check_ins([ci], _sample_cards(5), guideline)

        sent_prompt = svc.llm.call.call_args.kwargs["prompt"]
        assert "87" in sent_prompt  # the suspect item is visible to the reviewer
        assert "3-DIGIT NUMBER" in sent_prompt
        assert "three digits" in sent_prompt  # guideline text threaded through


class TestEnrichVariantReviewRounds:
    """Tests that _enrich_variant invokes the review loop correctly per review_rounds."""

    def _get_service(self):
        from book_ingestion_v2.services.check_in_enrichment_service import CheckInEnrichmentService
        svc = CheckInEnrichmentService.__new__(CheckInEnrichmentService)
        svc.llm = MagicMock()
        svc.db = MagicMock()
        svc.repo = MagicMock()
        svc._generation_schema = {"type": "object"}
        # no-op refresh so we don't hit real DB
        svc._refresh_db_session = lambda: None
        return svc

    def _make_explanation(self, cards):
        expl = MagicMock()
        expl.id = "e1"
        expl.variant_key = "A"
        expl.cards_json = cards
        return expl

    def _wire_generate_output(self, svc, decision):
        from book_ingestion_v2.services.check_in_enrichment_service import CheckInGenerationOutput
        svc._generate_check_ins = MagicMock(
            return_value=CheckInGenerationOutput(check_ins=[decision])
        )

    def test_review_skipped_when_rounds_zero(self):
        svc = self._get_service()
        cards = _sample_cards(6)
        expl = self._make_explanation(cards)
        guideline = _make_guideline_mock()
        ci = _make_check_in_decision(insert_after=3, num_pairs=3)
        self._wire_generate_output(svc, ci)
        svc._review_and_refine_check_ins = MagicMock()

        ok = svc._enrich_variant(expl, guideline, force=False, review_rounds=0)

        assert ok is True
        svc._review_and_refine_check_ins.assert_not_called()

    def test_review_called_n_times(self):
        svc = self._get_service()
        cards = _sample_cards(6)
        expl = self._make_explanation(cards)
        guideline = _make_guideline_mock()
        ci = _make_check_in_decision(insert_after=3, num_pairs=3)
        self._wire_generate_output(svc, ci)
        from book_ingestion_v2.services.check_in_enrichment_service import CheckInGenerationOutput
        svc._review_and_refine_check_ins = MagicMock(
            return_value=CheckInGenerationOutput(check_ins=[ci])
        )

        svc._enrich_variant(expl, guideline, force=False, review_rounds=3)

        assert svc._review_and_refine_check_ins.call_count == 3

    def test_review_failure_preserves_prior_output(self):
        """If review returns None, the loop breaks but prior output is kept and inserted."""
        svc = self._get_service()
        cards = _sample_cards(6)
        expl = self._make_explanation(cards)
        guideline = _make_guideline_mock()
        ci = _make_check_in_decision(insert_after=3, num_pairs=3)
        self._wire_generate_output(svc, ci)
        svc._review_and_refine_check_ins = MagicMock(return_value=None)

        ok = svc._enrich_variant(expl, guideline, force=False, review_rounds=2)

        # review failed → loop breaks after first call → original output flows to validation
        assert ok is True
        assert svc._review_and_refine_check_ins.call_count == 1
        # Commit happened, meaning we got past validation and insertion
        svc.db.commit.assert_called_once()
