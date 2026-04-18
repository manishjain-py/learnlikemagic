"""Unit tests for PracticeService.

Covers:
  - _select_set: difficulty mix (FR-16), free-form absorption (FR-17),
    bank-too-small error, format variety (FR-19).
  - start_or_resume: returns existing in-progress attempt (idempotent).
  - save_answer: 409 if status != in_progress.
  - submit: atomic flip + merges final answers + 409 for non-in-progress.
  - retry_grading: 409 unless status=='grading_failed'.
  - _redact_questions: strips correct-answer keys per format + seed-shuffles
    sequence_items.
"""
import random
from uuid import uuid4

import pytest

from shared.models.entities import PracticeAttempt, PracticeQuestion, User, TeachingGuideline
from tutor.models.practice import (
    PracticeBankEmptyError,
    PracticeConflictError,
    PracticeNotFoundError,
    PracticePermissionError,
)
from tutor.services.practice_service import PracticeService


# ─── Fixtures ─────────────────────────────────────────────────────────────

def _make_user_and_guideline(db_session, gid="g1", uid="u1"):
    user = User(id=uid, cognito_sub=f"sub-{uid}", auth_provider="email")
    guideline = TeachingGuideline(
        id=gid,
        topic="topic",
        chapter="chapter",
        subject="math",
        country="India",
        board="CBSE",
        grade=3,
        guideline="test",
    )
    db_session.add_all([user, guideline])
    db_session.commit()
    return user, guideline


def _seed_bank(db_session, guideline_id, spec):
    """Seed questions. `spec` is a list of dicts with `format`, `difficulty`.
    Returns the inserted question rows ordered by id.
    """
    rows = []
    for i, s in enumerate(spec):
        q = PracticeQuestion(
            id=str(uuid4()),
            guideline_id=guideline_id,
            format=s["format"],
            difficulty=s["difficulty"],
            concept_tag=s.get("concept_tag", f"tag{i}"),
            question_json={
                "question_text": f"q{i}",
                "explanation_why": "because",
                # Format-specific fields — fill enough so snapshots are valid
                "options": ["a", "b"],
                "correct_index": 0,
                "correct_answer_bool": True,
                "statement": "s",
                "pairs": [{"left": "a", "right": "1"}],
                "bucket_names": ["X", "Y"],
                "bucket_items": [{"text": "x", "correct_bucket": 0}],
                "sequence_items": ["1", "2", "3"],
                "error_steps": ["a", "b"],
                "error_index": 0,
                "odd_items": ["a", "b", "c"],
                "odd_index": 0,
                "expected_answer": "x",
                "grading_rubric": "r",
                "reveal_text": "reveal",
            },
        )
        db_session.add(q)
        rows.append(q)
    db_session.commit()
    return rows


# ─── _select_set ──────────────────────────────────────────────────────────

class TestSelectSet:
    def test_balances_3_5_2_when_bank_is_rich(self, db_session):
        """FR-16: plenty of questions at every difficulty → exact 3/5/2 mix."""
        _make_user_and_guideline(db_session)
        spec = (
            [{"format": "pick_one", "difficulty": "easy"}] * 10
            + [{"format": "true_false", "difficulty": "medium"}] * 10
            + [{"format": "fill_blank", "difficulty": "hard"}] * 10
        )
        bank = _seed_bank(db_session, "g1", spec)
        random.seed(42)
        svc = PracticeService(db_session)
        picked = svc._select_set(bank)
        counts = {"easy": 0, "medium": 0, "hard": 0}
        for q in picked:
            counts[q.difficulty] += 1
        assert counts == {"easy": 3, "medium": 5, "hard": 2}

    def test_absorbs_all_free_form(self, db_session):
        """FR-17: every free_form question in the bank is in the set.
        Difficulty quota reduces to compensate — set size stays 10.
        """
        _make_user_and_guideline(db_session)
        spec = (
            [{"format": "free_form", "difficulty": "medium"}] * 2  # both FFs must be included
            + [{"format": "pick_one", "difficulty": "easy"}] * 10
            + [{"format": "true_false", "difficulty": "medium"}] * 10
            + [{"format": "fill_blank", "difficulty": "hard"}] * 10
        )
        bank = _seed_bank(db_session, "g1", spec)
        random.seed(123)
        svc = PracticeService(db_session)
        picked = svc._select_set(bank)
        ff_picked = [q for q in picked if q.format == "free_form"]
        assert len(ff_picked) == 2
        assert len(picked) == 10

    def test_bank_too_small_raises(self, db_session):
        """Bank < 10 total → PracticeBankEmptyError."""
        _make_user_and_guideline(db_session)
        spec = [{"format": "pick_one", "difficulty": "medium"}] * 5
        bank = _seed_bank(db_session, "g1", spec)
        svc = PracticeService(db_session)
        with pytest.raises(PracticeBankEmptyError):
            # _select_set itself doesn't gate on count; start_or_resume does.
            # But start_or_resume raises when bank < SET_SIZE, so test via that:
            svc.start_or_resume("u1", "g1")

    def test_no_consecutive_same_format_when_possible(self, db_session):
        """FR-19: greedy reorder avoids same-format adjacency when possible."""
        _make_user_and_guideline(db_session)
        spec = (
            [{"format": "pick_one", "difficulty": "easy"}] * 3
            + [{"format": "true_false", "difficulty": "medium"}] * 5
            + [{"format": "fill_blank", "difficulty": "hard"}] * 2
        )
        bank = _seed_bank(db_session, "g1", spec)
        random.seed(77)
        svc = PracticeService(db_session)
        picked = svc._select_set(bank)
        # Count consecutive same-format pairs
        consecutive = sum(
            1 for i in range(len(picked) - 1) if picked[i].format == picked[i + 1].format
        )
        # With 3 distinct formats and 10 picks, the greedy reorder should be
        # able to achieve zero consecutive same-format pairs.
        assert consecutive == 0


# ─── start_or_resume ──────────────────────────────────────────────────────

class TestStartOrResume:
    def _seed_full_bank(self, db_session):
        spec = (
            [{"format": "pick_one", "difficulty": "easy"}] * 4
            + [{"format": "true_false", "difficulty": "medium"}] * 6
            + [{"format": "fill_blank", "difficulty": "hard"}] * 3
        )
        return _seed_bank(db_session, "g1", spec)

    def test_creates_new_attempt(self, db_session):
        _make_user_and_guideline(db_session)
        self._seed_full_bank(db_session)
        svc = PracticeService(db_session)
        attempt = svc.start_or_resume("u1", "g1")
        assert attempt.status == "in_progress"
        assert len(attempt.questions) == 10
        # Questions must be the redacted shape — no correct_index leaked
        for q in attempt.questions:
            assert "correct_index" not in q.question_json
            assert "correct_answer_bool" not in q.question_json
            assert "explanation_why" not in q.question_json

    def test_second_call_returns_same_in_progress_attempt(self, db_session):
        """Idempotent for the happy (non-race) path — same attempt ID."""
        _make_user_and_guideline(db_session)
        self._seed_full_bank(db_session)
        svc = PracticeService(db_session)
        a1 = svc.start_or_resume("u1", "g1")
        a2 = svc.start_or_resume("u1", "g1")
        assert a1.id == a2.id


# ─── save_answer ──────────────────────────────────────────────────────────

class TestSaveAnswer:
    def test_conflict_when_status_not_in_progress(self, db_session):
        """After submit, save_answer must 409 (not silent no-op) — this is
        the guarantee that prevents the debounce-race swallow.
        """
        _make_user_and_guideline(db_session)
        # Minimal attempt in 'grading' state
        attempt = PracticeAttempt(
            id=str(uuid4()),
            user_id="u1",
            guideline_id="g1",
            question_ids=[],
            questions_snapshot_json=[],
            answers_json={},
            status="grading",
            total_possible=10,
        )
        db_session.add(attempt)
        db_session.commit()

        svc = PracticeService(db_session)
        with pytest.raises(PracticeConflictError):
            svc.save_answer(attempt.id, 0, "late-answer", "u1")

    def test_wrong_owner_raises_permission(self, db_session):
        _make_user_and_guideline(db_session, uid="u1")
        _make_user_and_guideline(db_session, uid="u2", gid="g2")
        attempt = PracticeAttempt(
            id=str(uuid4()),
            user_id="u1",
            guideline_id="g1",
            question_ids=[],
            questions_snapshot_json=[],
            answers_json={},
            status="in_progress",
            total_possible=10,
        )
        db_session.add(attempt)
        db_session.commit()

        svc = PracticeService(db_session)
        with pytest.raises(PracticePermissionError):
            svc.save_answer(attempt.id, 0, "x", "u2")


# ─── submit ───────────────────────────────────────────────────────────────

class TestSubmit:
    def _make_in_progress(self, db_session):
        _make_user_and_guideline(db_session)
        attempt = PracticeAttempt(
            id=str(uuid4()),
            user_id="u1",
            guideline_id="g1",
            question_ids=["q0"],
            questions_snapshot_json=[{"_id": "q0", "_format": "pick_one", "_difficulty": "easy", "_concept_tag": "t", "options": ["a", "b"], "correct_index": 0, "question_text": "?"}],
            answers_json={"0": 1},  # Saved earlier
            status="in_progress",
            total_possible=1,
        )
        db_session.add(attempt)
        db_session.commit()
        return attempt

    def test_merges_final_answers_and_flips_status(self, db_session, monkeypatch):
        """Submit merges body's final_answers with saved answers AND flips
        status to 'grading' atomically. Worker-spawn is stubbed out.
        """
        attempt = self._make_in_progress(db_session)
        svc = PracticeService(db_session)
        monkeypatch.setattr(svc, "_spawn_grading_worker", lambda aid: None)

        result = svc.submit(attempt.id, {"0": 0}, "u1")  # override saved 1 → 0

        db_session.refresh(attempt)
        assert attempt.status == "grading"
        assert attempt.submitted_at is not None
        assert attempt.answers_json["0"] == 0  # final_answers won
        assert result.status == "grading"

    def test_conflict_if_already_submitted(self, db_session, monkeypatch):
        """A second submit request (e.g., double-tap) returns 409, not
        a fresh grading kickoff.
        """
        attempt = self._make_in_progress(db_session)
        attempt.status = "grading"
        db_session.commit()

        svc = PracticeService(db_session)
        monkeypatch.setattr(svc, "_spawn_grading_worker", lambda aid: None)
        with pytest.raises(PracticeConflictError):
            svc.submit(attempt.id, {}, "u1")

    def test_wrong_owner_raises_permission(self, db_session, monkeypatch):
        attempt = self._make_in_progress(db_session)
        _make_user_and_guideline(db_session, uid="u2", gid="g2")

        svc = PracticeService(db_session)
        monkeypatch.setattr(svc, "_spawn_grading_worker", lambda aid: None)
        with pytest.raises(PracticePermissionError):
            svc.submit(attempt.id, {}, "u2")


# ─── retry_grading ────────────────────────────────────────────────────────

class TestRetryGrading:
    def test_flips_grading_failed_to_grading(self, db_session, monkeypatch):
        _make_user_and_guideline(db_session)
        attempt = PracticeAttempt(
            id=str(uuid4()),
            user_id="u1",
            guideline_id="g1",
            question_ids=[],
            questions_snapshot_json=[],
            answers_json={},
            status="grading_failed",
            grading_error="timeout",
            total_possible=10,
        )
        db_session.add(attempt)
        db_session.commit()

        svc = PracticeService(db_session)
        monkeypatch.setattr(svc, "_spawn_grading_worker", lambda aid: None)
        svc.retry_grading(attempt.id, "u1")

        db_session.refresh(attempt)
        assert attempt.status == "grading"
        assert attempt.grading_error is None

    def test_conflict_when_status_is_graded(self, db_session, monkeypatch):
        """Retry on a graded attempt must 409 — you can't re-grade what's done."""
        _make_user_and_guideline(db_session)
        attempt = PracticeAttempt(
            id=str(uuid4()),
            user_id="u1",
            guideline_id="g1",
            question_ids=[],
            questions_snapshot_json=[],
            answers_json={},
            status="graded",
            total_score=8.0,
            total_possible=10,
        )
        db_session.add(attempt)
        db_session.commit()

        svc = PracticeService(db_session)
        monkeypatch.setattr(svc, "_spawn_grading_worker", lambda aid: None)
        with pytest.raises(PracticeConflictError):
            svc.retry_grading(attempt.id, "u1")


# ─── _redact_questions ────────────────────────────────────────────────────

class TestRedact:
    def test_strips_correct_answer_keys(self, db_session):
        svc = PracticeService(db_session)
        snapshot = [{
            "_id": "q0", "_format": "pick_one", "_difficulty": "easy",
            "_concept_tag": "t", "_presentation_seed": 123,
            "question_text": "?",
            "options": ["a", "b"],
            "correct_index": 0,
            "explanation_why": "secret",
        }]
        redacted = svc._redact_questions(snapshot)[0]
        assert "correct_index" not in redacted
        assert "explanation_why" not in redacted
        assert redacted["options"] == ["a", "b"]
        # Meta preserved
        assert redacted["_id"] == "q0"
        assert redacted["_presentation_seed"] == 123

    def test_match_pairs_splits_into_parallel_arrays(self, db_session):
        svc = PracticeService(db_session)
        snapshot = [{
            "_id": "q0", "_format": "match_pairs", "_presentation_seed": 0,
            "question_text": "?",
            "pairs": [{"left": "a", "right": "1"}, {"left": "b", "right": "2"}],
        }]
        redacted = svc._redact_questions(snapshot)[0]
        assert "pairs" not in redacted
        assert redacted["pair_lefts"] == ["a", "b"]
        assert redacted["pair_rights"] == ["1", "2"]

    def test_sequence_items_are_seed_shuffled(self, db_session):
        """Same seed → same shuffle on both first serve and resume."""
        svc = PracticeService(db_session)
        original = ["step1", "step2", "step3", "step4", "step5"]
        snapshot = [{
            "_id": "q0", "_format": "sequence", "_presentation_seed": 42,
            "question_text": "?",
            "sequence_items": list(original),
        }]
        r1 = svc._redact_questions(snapshot)[0]["sequence_items"]
        r2 = svc._redact_questions([dict(snapshot[0])])[0]["sequence_items"]
        assert r1 == r2  # deterministic from seed
        assert sorted(r1) == sorted(original)  # same items
        # Snapshot was NOT mutated in place (grading still sees original order)
        assert snapshot[0]["sequence_items"] == original

    def test_sort_buckets_strips_correct_bucket(self, db_session):
        svc = PracticeService(db_session)
        snapshot = [{
            "_id": "q0", "_format": "sort_buckets", "_presentation_seed": 0,
            "question_text": "?",
            "bucket_names": ["A", "B"],
            "bucket_items": [
                {"text": "x", "correct_bucket": 0},
                {"text": "y", "correct_bucket": 1},
            ],
        }]
        redacted = svc._redact_questions(snapshot)[0]
        for item in redacted["bucket_items"]:
            assert "correct_bucket" not in item
            assert "text" in item
