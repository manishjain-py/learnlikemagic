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
