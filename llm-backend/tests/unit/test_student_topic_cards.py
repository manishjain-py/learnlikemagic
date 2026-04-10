"""Unit tests for StudentTopicCardsRepository.

Covers:
1. upsert creates a new record on first call, appends on subsequent calls
2. Separate variant keys create separate rows
3. Mismatched explanation_id resets simplifications
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

from shared.repositories.student_topic_cards_repository import StudentTopicCardsRepository
from shared.models.entities import StudentTopicCards


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo_with_mock_db():
    """Return (repo, mock_db) where mock_db is a MagicMock SQLAlchemy session."""
    db = MagicMock()
    repo = StudentTopicCardsRepository(db)
    return repo, db


def _make_record(user_id="u1", guideline_id="g1", variant_key="A",
                 explanation_id="exp1", simplifications=None):
    """Create a StudentTopicCards instance with sensible defaults."""
    record = StudentTopicCards(
        id="test-id",
        user_id=user_id,
        guideline_id=guideline_id,
        variant_key=variant_key,
        explanation_id=explanation_id,
        simplifications=simplifications or {},
        updated_at=datetime.utcnow(),
    )
    return record


SAMPLE_SIMPLIFICATION_1 = {
    "card_type": "simplification",
    "title": "Simpler Addition",
    "lines": [{"display": "Put things together to add.", "audio": "Put things together to add."}],
    "content": "Put things together to add.",
    "audio_text": "Put things together to add.",
}

SAMPLE_SIMPLIFICATION_2 = {
    "card_type": "simplification",
    "title": "Even Simpler Addition",
    "lines": [{"display": "Combine groups.", "audio": "Combine groups."}],
    "content": "Combine groups.",
    "audio_text": "Combine groups.",
}


# ---------------------------------------------------------------------------
# 1. Upsert: create on first call, append on subsequent
# ---------------------------------------------------------------------------

class TestStudentTopicCardsUpsert:

    def test_upsert_creates_record_on_first_call(self):
        """First upsert for a user+guideline+variant creates a new row."""
        repo, db = _make_repo_with_mock_db()

        # get() returns None — no existing record
        db.query.return_value.filter.return_value.first.return_value = None

        repo.upsert(
            user_id="u1",
            guideline_id="g1",
            variant_key="A",
            explanation_id="exp1",
            card_idx=2,
            simplification=SAMPLE_SIMPLIFICATION_1,
        )

        # Should have called db.add with a new StudentTopicCards
        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert isinstance(added, StudentTopicCards)
        assert added.user_id == "u1"
        assert added.guideline_id == "g1"
        assert added.variant_key == "A"
        assert added.explanation_id == "exp1"
        assert "2" in added.simplifications
        assert len(added.simplifications["2"]) == 1
        assert added.simplifications["2"][0]["title"] == "Simpler Addition"

    def test_upsert_appends_on_subsequent_call(self):
        """Second upsert for same card_idx appends to the list."""
        repo, db = _make_repo_with_mock_db()

        existing = _make_record(
            explanation_id="exp1",
            simplifications={"2": [SAMPLE_SIMPLIFICATION_1]},
        )
        db.query.return_value.filter.return_value.first.return_value = existing

        repo.upsert(
            user_id="u1",
            guideline_id="g1",
            variant_key="A",
            explanation_id="exp1",
            card_idx=2,
            simplification=SAMPLE_SIMPLIFICATION_2,
        )

        # Should NOT create a new record
        db.add.assert_not_called()
        # Should have appended to existing list
        assert len(existing.simplifications["2"]) == 2
        assert existing.simplifications["2"][1]["title"] == "Even Simpler Addition"

    def test_upsert_different_card_idx_creates_new_key(self):
        """Upsert for a different card_idx creates a new key in simplifications."""
        repo, db = _make_repo_with_mock_db()

        existing = _make_record(
            explanation_id="exp1",
            simplifications={"2": [SAMPLE_SIMPLIFICATION_1]},
        )
        db.query.return_value.filter.return_value.first.return_value = existing

        repo.upsert(
            user_id="u1",
            guideline_id="g1",
            variant_key="A",
            explanation_id="exp1",
            card_idx=0,
            simplification=SAMPLE_SIMPLIFICATION_2,
        )

        assert "0" in existing.simplifications
        assert len(existing.simplifications["0"]) == 1
        # Original key untouched
        assert len(existing.simplifications["2"]) == 1


# ---------------------------------------------------------------------------
# 2. Per-variant isolation
# ---------------------------------------------------------------------------

class TestStudentTopicCardsPerVariant:

    def test_separate_variants_create_separate_rows(self):
        """Different variant_key values result in separate DB rows."""
        repo, db = _make_repo_with_mock_db()

        # First call: variant A — no existing record
        db.query.return_value.filter.return_value.first.return_value = None

        repo.upsert(
            user_id="u1",
            guideline_id="g1",
            variant_key="A",
            explanation_id="exp1",
            card_idx=0,
            simplification=SAMPLE_SIMPLIFICATION_1,
        )
        first_add = db.add.call_args[0][0]
        assert first_add.variant_key == "A"

        # Second call: variant B — still no existing record (different variant)
        db.add.reset_mock()
        db.query.return_value.filter.return_value.first.return_value = None

        repo.upsert(
            user_id="u1",
            guideline_id="g1",
            variant_key="B",
            explanation_id="exp1",
            card_idx=0,
            simplification=SAMPLE_SIMPLIFICATION_2,
        )
        second_add = db.add.call_args[0][0]
        assert second_add.variant_key == "B"

        # Both are separate StudentTopicCards instances
        assert first_add is not second_add


# ---------------------------------------------------------------------------
# 3. Stale explanation resets simplifications
# ---------------------------------------------------------------------------

class TestStudentTopicCardsStaleExplanation:

    def test_mismatched_explanation_id_resets_simplifications(self):
        """When explanation_id changes, old simplifications are cleared."""
        repo, db = _make_repo_with_mock_db()

        existing = _make_record(
            explanation_id="exp_old",
            simplifications={
                "0": [SAMPLE_SIMPLIFICATION_1],
                "2": [SAMPLE_SIMPLIFICATION_1, SAMPLE_SIMPLIFICATION_2],
            },
        )
        db.query.return_value.filter.return_value.first.return_value = existing

        repo.upsert(
            user_id="u1",
            guideline_id="g1",
            variant_key="A",
            explanation_id="exp_new",  # different from exp_old
            card_idx=1,
            simplification=SAMPLE_SIMPLIFICATION_2,
        )

        # Old simplifications should be gone; only the new one remains
        assert existing.explanation_id == "exp_new"
        assert "0" not in existing.simplifications
        assert "2" not in existing.simplifications
        assert "1" in existing.simplifications
        assert len(existing.simplifications["1"]) == 1
        assert existing.simplifications["1"][0]["title"] == "Even Simpler Addition"

    def test_same_explanation_id_preserves_simplifications(self):
        """When explanation_id matches, existing simplifications are preserved."""
        repo, db = _make_repo_with_mock_db()

        existing = _make_record(
            explanation_id="exp1",
            simplifications={"0": [SAMPLE_SIMPLIFICATION_1]},
        )
        db.query.return_value.filter.return_value.first.return_value = existing

        repo.upsert(
            user_id="u1",
            guideline_id="g1",
            variant_key="A",
            explanation_id="exp1",  # same as existing
            card_idx=2,
            simplification=SAMPLE_SIMPLIFICATION_2,
        )

        # Old simplifications preserved
        assert "0" in existing.simplifications
        assert len(existing.simplifications["0"]) == 1
        # New one added
        assert "2" in existing.simplifications
        assert len(existing.simplifications["2"]) == 1
