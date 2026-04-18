"""Unit tests for PracticeGradingService.

Scope:
  - _check_structured deterministic path for all 11 non-FF formats + blank handling.
  - grade_attempt end-to-end with mocked LLM: half-point rounding, mark_grading_failed
    on retries exhausted, idempotent skip when status != 'grading'.
"""
from unittest.mock import MagicMock
from datetime import datetime
from uuid import uuid4

import pytest

from shared.models.entities import PracticeAttempt, User, TeachingGuideline
from tutor.services.practice_grading_service import (
    PracticeGradingService,
    FF_CORRECT_THRESHOLD,
)


# ─── Helpers ──────────────────────────────────────────────────────────────

def _grader(db_session):
    """Build a PracticeGradingService with a MagicMock LLM."""
    llm = MagicMock()
    svc = PracticeGradingService(db_session, llm)
    return svc, llm


def _q(fmt, **overrides):
    """Build a snapshot-shaped question dict with sensible defaults per format."""
    base = {"_format": fmt, "_id": str(uuid4()), "_difficulty": "medium", "_concept_tag": "tag", "question_text": "?"}
    base.update(overrides)
    return base


# ─── _check_structured: 11 formats + blank ─────────────────────────────────

class TestCheckStructured:
    """Deterministic grading for each of the 11 structured formats."""

    def test_pick_one_correct(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("pick_one", options=["a", "b", "c"], correct_index=1)
        assert svc._check_structured(q, 1) is True

    def test_pick_one_wrong(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("pick_one", options=["a", "b", "c"], correct_index=1)
        assert svc._check_structured(q, 0) is False

    def test_pick_one_blank(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("pick_one", options=["a", "b", "c"], correct_index=1)
        assert svc._check_structured(q, None) is False

    @pytest.mark.parametrize("fmt", ["fill_blank", "tap_to_eliminate", "predict_then_reveal"])
    def test_other_index_formats_correct(self, db_session, fmt):
        svc, _ = _grader(db_session)
        q = _q(fmt, options=["a", "b"], correct_index=0)
        assert svc._check_structured(q, 0) is True
        assert svc._check_structured(q, 1) is False

    def test_true_false_correct(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("true_false", statement="2+2=4", correct_answer_bool=True)
        assert svc._check_structured(q, True) is True
        assert svc._check_structured(q, False) is False

    def test_match_pairs_correct(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("match_pairs", pairs=[{"left": "a", "right": "1"}, {"left": "b", "right": "2"}])
        assert svc._check_structured(q, {"a": "1", "b": "2"}) is True

    def test_match_pairs_partial_wrong(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("match_pairs", pairs=[{"left": "a", "right": "1"}, {"left": "b", "right": "2"}])
        assert svc._check_structured(q, {"a": "1", "b": "1"}) is False

    def test_match_pairs_unknown_key_with_none_value(self, db_session):
        """Regression: expected.get('x') returned None, which used to match a
        student_answer[x]=None — making the answer appear correct.
        """
        svc, _ = _grader(db_session)
        q = _q("match_pairs", pairs=[{"left": "a", "right": "1"}])
        assert svc._check_structured(q, {"wrong_key": None}) is False

    @pytest.mark.parametrize("fmt", ["sort_buckets", "swipe_classify"])
    def test_bucket_formats_correct(self, db_session, fmt):
        svc, _ = _grader(db_session)
        q = _q(fmt, bucket_names=["A", "B"], bucket_items=[
            {"text": "x", "correct_bucket": 0},
            {"text": "y", "correct_bucket": 1},
            {"text": "z", "correct_bucket": 0},
        ])
        assert svc._check_structured(q, [0, 1, 0]) is True
        assert svc._check_structured(q, [1, 1, 0]) is False

    def test_bucket_length_mismatch_wrong(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("sort_buckets", bucket_names=["A", "B"], bucket_items=[
            {"text": "x", "correct_bucket": 0},
            {"text": "y", "correct_bucket": 1},
        ])
        assert svc._check_structured(q, [0]) is False

    def test_sequence_correct(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("sequence", sequence_items=["first", "second", "third"])
        assert svc._check_structured(q, ["first", "second", "third"]) is True
        assert svc._check_structured(q, ["second", "first", "third"]) is False

    def test_spot_the_error_correct(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("spot_the_error", error_steps=["ok", "ok", "bad", "ok"], error_index=2)
        assert svc._check_structured(q, 2) is True
        assert svc._check_structured(q, 1) is False

    def test_odd_one_out_correct(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("odd_one_out", odd_items=["dog", "cat", "apple", "bird"], odd_index=2)
        assert svc._check_structured(q, 2) is True
        assert svc._check_structured(q, 0) is False

    def test_unknown_format_returns_false(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("mystery_format")
        assert svc._check_structured(q, "anything") is False


# ─── _summarize_correct + _summarize_pick sanity ──────────────────────────

class TestSummarize:
    def test_summarize_correct_pick_one(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("pick_one", options=["a", "b", "c"], correct_index=2)
        assert svc._summarize_correct(q) == "c"

    def test_summarize_correct_true_false(self, db_session):
        svc, _ = _grader(db_session)
        assert svc._summarize_correct(_q("true_false", correct_answer_bool=True)) == "TRUE"
        assert svc._summarize_correct(_q("true_false", correct_answer_bool=False)) == "FALSE"

    def test_summarize_pick_blank(self, db_session):
        svc, _ = _grader(db_session)
        q = _q("pick_one", options=["a", "b"], correct_index=0)
        assert "blank" in svc._summarize_pick(q, None).lower()


# ─── grade_attempt end-to-end ─────────────────────────────────────────────

def _create_user_and_guideline(db_session):
    """Spin up the minimum FK chain for PracticeAttempt inserts."""
    user = User(
        id="u1",
        cognito_sub="sub1",
        auth_provider="email",
    )
    guideline = TeachingGuideline(
        id="g1",
        topic="topic1",
        chapter="chapter1",
        subject="math",
        country="India",
        board="CBSE",
        grade=3,
        guideline="test",
    )
    db_session.add_all([user, guideline])
    db_session.commit()
    return user, guideline


def _create_grading_attempt(db_session, questions, answers):
    """Insert a `status='grading'` attempt ready for grade_attempt()."""
    user, guideline = _create_user_and_guideline(db_session)
    attempt = PracticeAttempt(
        id=str(uuid4()),
        user_id=user.id,
        guideline_id=guideline.id,
        question_ids=[q.get("_id") or str(i) for i, q in enumerate(questions)],
        questions_snapshot_json=questions,
        answers_json=answers,
        status="grading",
        total_possible=len(questions),
        submitted_at=datetime.utcnow(),
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


class TestGradeAttempt:
    def test_half_point_rounding_applied(self, db_session):
        """Raw total is rounded to the nearest half-point at write time.
        10 × 0.63 = 6.3 → rounds to 6.5 (round(12.6)=13, /2=6.5).
        Uses a per-question score map (not a queue) because ThreadPoolExecutor
        fans out in non-deterministic order.
        """
        questions = [_q("free_form", question_text=f"q{i}", expected_answer="x", grading_rubric="r") for i in range(10)]
        answers = {str(i): f"ans{i}" for i in range(10)}
        attempt = _create_grading_attempt(db_session, questions, answers)

        score_map = {f"q{i}": 0.63 for i in range(10)}
        svc, _ = _grader(db_session)

        def _fake_ff(q, a):
            class R:
                score = score_map[q["question_text"]]
                rationale = "ok"
            return R()

        svc._grade_free_form = _fake_ff  # type: ignore

        svc.grade_attempt(attempt.id)
        db_session.refresh(attempt)
        assert attempt.status == "graded"
        assert attempt.total_score == 6.5

    def test_skips_when_status_not_grading(self, db_session):
        """Idempotent guard: re-entry while status='graded' is a silent no-op."""
        questions = [_q("pick_one", options=["a", "b"], correct_index=0)]
        attempt = _create_grading_attempt(db_session, questions, {"0": 0})
        attempt.status = "graded"
        db_session.commit()

        svc, llm = _grader(db_session)
        svc.grade_attempt(attempt.id)
        # No exception, no LLM call, status unchanged
        assert llm.call.called is False
        db_session.refresh(attempt)
        assert attempt.status == "graded"

    def test_all_structured_correct_no_llm_calls(self, db_session):
        """Pure-structured attempt with all correct answers hits 0 LLM calls."""
        questions = [
            _q("pick_one", options=["a", "b"], correct_index=0),
            _q("true_false", correct_answer_bool=True),
            _q("sequence", sequence_items=["1", "2", "3"]),
        ]
        answers = {"0": 0, "1": True, "2": ["1", "2", "3"]}
        attempt = _create_grading_attempt(db_session, questions, answers)

        svc, llm = _grader(db_session)
        svc.grade_attempt(attempt.id)

        assert llm.call.called is False
        db_session.refresh(attempt)
        assert attempt.status == "graded"
        assert attempt.total_score == 3.0

    def test_llm_exception_marks_grading_failed(self, db_session):
        """Any unhandled LLM error → attempt.status = 'grading_failed'."""
        questions = [_q("pick_one", options=["a", "b"], correct_index=0)]
        # Student answered wrong so the per-pick LLM rationale runs.
        attempt = _create_grading_attempt(db_session, questions, {"0": 1})

        svc, _ = _grader(db_session)
        def _raise(*a, **k):
            raise RuntimeError("LLM down")
        svc._explain_wrong_pick = _raise  # type: ignore

        svc.grade_attempt(attempt.id)
        db_session.refresh(attempt)
        assert attempt.status == "grading_failed"
        assert attempt.grading_error and "LLM down" in attempt.grading_error

    def test_ff_threshold_correct_boundary(self, db_session):
        """FF score >= FF_CORRECT_THRESHOLD → correct=True; below → False."""
        questions = [
            _q("free_form", question_text="q0", expected_answer="x", grading_rubric="r"),
            _q("free_form", question_text="q1", expected_answer="x", grading_rubric="r"),
        ]
        attempt = _create_grading_attempt(db_session, questions, {"0": "a", "1": "b"})

        svc, _ = _grader(db_session)
        results = iter([FF_CORRECT_THRESHOLD, FF_CORRECT_THRESHOLD - 0.01])
        def _fake_ff(q, a):
            class R: pass
            R.score = next(results)
            R.rationale = "ok"
            return R()
        svc._grade_free_form = _fake_ff  # type: ignore

        svc.grade_attempt(attempt.id)
        db_session.refresh(attempt)
        grading = attempt.grading_json
        assert grading["0"]["correct"] is True   # at threshold
        assert grading["1"]["correct"] is False  # below threshold
