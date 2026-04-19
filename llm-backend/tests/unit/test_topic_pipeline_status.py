"""Unit tests for TopicPipelineStatusService (Phase 1).

Covers:
- fresh topic → explanations ready, downstream blocked
- full done state
- layout warnings
- partial/stale practice bank
- running/failed job overlays
- historical-row (chapter_id-as-guideline_id) overload handling
- no staleness flash on in-place cards_json write
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.models.database import (
    BookChapter,
    ChapterProcessingJob,
)
from book_ingestion_v2.services.topic_pipeline_status_service import (
    TopicPipelineStatusService,
)
from shared.models.entities import (
    Book,
    PracticeQuestion,
    TeachingGuideline,
    TopicExplanation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seed_book_chapter_topic(db_session):
    """Create a minimal book/chapter/topic scaffold for the tests."""
    book_id = str(uuid.uuid4())
    chapter_id = str(uuid.uuid4())
    guideline_id = str(uuid.uuid4())
    topic_key = "comparing-fractions"
    chapter_number = 3
    chapter_key = f"chapter-{chapter_number}"

    db_session.add(Book(
        id=book_id,
        title="Test Book",
        country="India",
        board="CBSE",
        grade=3,
        subject="Mathematics",
        s3_prefix=f"books/{book_id}/",
    ))
    db_session.add(BookChapter(
        id=chapter_id,
        book_id=book_id,
        chapter_number=chapter_number,
        chapter_title="Fractions",
        start_page=1,
        end_page=20,
        status="chapter_completed",
        total_pages=20,
        uploaded_page_count=20,
    ))
    db_session.add(TeachingGuideline(
        id=guideline_id,
        country="India",
        board="CBSE",
        grade=3,
        subject="Mathematics",
        chapter="Fractions",
        topic="Comparing Fractions",
        guideline="Teach comparison of fractions.",
        chapter_key=chapter_key,
        topic_key=topic_key,
        chapter_title="Fractions",
        topic_title="Comparing Fractions",
        book_id=book_id,
        review_status="APPROVED",
        topic_sequence=1,
    ))
    db_session.commit()
    return {
        "book_id": book_id,
        "chapter_id": chapter_id,
        "guideline_id": guideline_id,
        "topic_key": topic_key,
    }


def _add_explanation(db, guideline_id: str, cards: list, variant: str = "A", created_at: datetime | None = None):
    expl = TopicExplanation(
        id=str(uuid.uuid4()),
        guideline_id=guideline_id,
        variant_key=variant,
        variant_label=f"Variant {variant}",
        cards_json=cards,
    )
    if created_at is not None:
        expl.created_at = created_at
    db.add(expl)
    db.commit()
    return expl


def _add_job(
    db,
    *,
    book_id: str,
    chapter_id: str,
    job_type: str,
    status: str,
    error: str | None = None,
    completed_at: datetime | None = None,
    created_at: datetime | None = None,
):
    job = ChapterProcessingJob(
        id=str(uuid.uuid4()),
        book_id=book_id,
        chapter_id=chapter_id,
        job_type=job_type,
        status=status,
        error_message=error,
        completed_at=completed_at,
    )
    if created_at is not None:
        job.created_at = created_at
    db.add(job)
    db.commit()
    return job


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFreshTopic:
    def test_no_artifacts_explanations_ready_others_blocked(self, db_session, seed_book_chapter_topic):
        svc = TopicPipelineStatusService(db_session)
        resp = svc.get_pipeline_status(
            seed_book_chapter_topic["book_id"],
            seed_book_chapter_topic["chapter_id"],
            seed_book_chapter_topic["topic_key"],
        )

        by_id = {s.stage_id: s for s in resp.stages}
        assert by_id["explanations"].state == "ready"
        for stage_id in ("visuals", "check_ins", "practice_bank", "audio_review", "audio_synthesis"):
            assert by_id[stage_id].state == "blocked", f"{stage_id} should be blocked on fresh topic"
            assert by_id[stage_id].blocked_by == "explanations"


class TestFullDone:
    def test_all_stages_done_when_artifacts_present(self, db_session, seed_book_chapter_topic):
        gid = seed_book_chapter_topic["guideline_id"]
        cards = [
            {
                "card_type": "explain",
                "visual_explanation": {"pixi_code": "(() => {})()"},
                "lines": [{"text": "Line 1", "audio_url": "https://s3.example/1.mp3"}],
            },
            {
                "card_type": "check_in",
                "visual_explanation": {"pixi_code": "(() => {})()"},
                "lines": [{"text": "Question?", "audio_url": "https://s3.example/2.mp3"}],
            },
        ]
        _add_explanation(db_session, gid, cards)

        # 30 practice questions — past threshold
        for i in range(30):
            db_session.add(PracticeQuestion(
                id=str(uuid.uuid4()),
                guideline_id=gid,
                format="mcq",
                difficulty="easy",
                concept_tag="tag",
                question_json={"stem": f"Q{i}"},
            ))
        db_session.commit()

        # Completed audio review job — historical overload stores guideline_id in chapter_id.
        _add_job(
            db_session,
            book_id=seed_book_chapter_topic["book_id"],
            chapter_id=gid,
            job_type=V2JobType.AUDIO_TEXT_REVIEW.value,
            status="completed",
            completed_at=datetime.utcnow(),
        )

        svc = TopicPipelineStatusService(db_session)
        resp = svc.get_pipeline_status(
            seed_book_chapter_topic["book_id"],
            seed_book_chapter_topic["chapter_id"],
            seed_book_chapter_topic["topic_key"],
        )
        by_id = {s.stage_id: s for s in resp.stages}
        assert by_id["explanations"].state == "done"
        assert by_id["visuals"].state == "done"
        assert by_id["check_ins"].state == "done"
        assert by_id["practice_bank"].state == "done"
        assert by_id["audio_review"].state == "done"
        assert by_id["audio_synthesis"].state == "done"


class TestWarningStates:
    def test_layout_warning_flips_visuals_to_warning(self, db_session, seed_book_chapter_topic):
        gid = seed_book_chapter_topic["guideline_id"]
        cards = [
            {
                "card_type": "explain",
                "visual_explanation": {"pixi_code": "code1", "layout_warning": True},
            },
            {
                "card_type": "explain",
                "visual_explanation": {"pixi_code": "code2"},
            },
        ]
        _add_explanation(db_session, gid, cards)

        svc = TopicPipelineStatusService(db_session)
        resp = svc.get_pipeline_status(
            seed_book_chapter_topic["book_id"],
            seed_book_chapter_topic["chapter_id"],
            seed_book_chapter_topic["topic_key"],
        )
        visuals = next(s for s in resp.stages if s.stage_id == "visuals")
        assert visuals.state == "warning"
        assert any("layout warning" in w for w in visuals.warnings)

    def test_partial_practice_bank_is_warning(self, db_session, seed_book_chapter_topic):
        gid = seed_book_chapter_topic["guideline_id"]
        _add_explanation(db_session, gid, [{"card_type": "explain"}])
        for i in range(15):
            db_session.add(PracticeQuestion(
                id=str(uuid.uuid4()),
                guideline_id=gid,
                format="mcq",
                difficulty="easy",
                concept_tag="tag",
                question_json={"stem": f"Q{i}"},
            ))
        db_session.commit()

        svc = TopicPipelineStatusService(db_session)
        resp = svc.get_pipeline_status(
            seed_book_chapter_topic["book_id"],
            seed_book_chapter_topic["chapter_id"],
            seed_book_chapter_topic["topic_key"],
        )
        pb = next(s for s in resp.stages if s.stage_id == "practice_bank")
        assert pb.state == "warning"
        assert "15" in pb.summary

    def test_stale_practice_bank_via_content_anchor(self, db_session, seed_book_chapter_topic):
        gid = seed_book_chapter_topic["guideline_id"]
        old_time = datetime.utcnow() - timedelta(hours=2)
        new_time = datetime.utcnow()

        # Practice questions created BEFORE the latest explanation
        for i in range(30):
            pq = PracticeQuestion(
                id=str(uuid.uuid4()),
                guideline_id=gid,
                format="mcq",
                difficulty="easy",
                concept_tag="tag",
                question_json={"stem": f"Q{i}"},
            )
            pq.created_at = old_time
            db_session.add(pq)
        db_session.commit()
        _add_explanation(db_session, gid, [{"card_type": "explain"}], created_at=new_time)

        svc = TopicPipelineStatusService(db_session)
        resp = svc.get_pipeline_status(
            seed_book_chapter_topic["book_id"],
            seed_book_chapter_topic["chapter_id"],
            seed_book_chapter_topic["topic_key"],
        )
        pb = next(s for s in resp.stages if s.stage_id == "practice_bank")
        assert pb.state == "warning"
        assert pb.is_stale is True
        assert any("predates" in w or "stale" in w.lower() for w in pb.warnings)

    def test_not_stale_when_practice_newer_than_explanation(self, db_session, seed_book_chapter_topic):
        gid = seed_book_chapter_topic["guideline_id"]
        old_time = datetime.utcnow() - timedelta(hours=2)
        new_time = datetime.utcnow()

        _add_explanation(db_session, gid, [{"card_type": "explain"}], created_at=old_time)
        for i in range(30):
            pq = PracticeQuestion(
                id=str(uuid.uuid4()),
                guideline_id=gid,
                format="mcq",
                difficulty="easy",
                concept_tag="tag",
                question_json={"stem": f"Q{i}"},
            )
            pq.created_at = new_time
            db_session.add(pq)
        db_session.commit()

        svc = TopicPipelineStatusService(db_session)
        resp = svc.get_pipeline_status(
            seed_book_chapter_topic["book_id"],
            seed_book_chapter_topic["chapter_id"],
            seed_book_chapter_topic["topic_key"],
        )
        pb = next(s for s in resp.stages if s.stage_id == "practice_bank")
        assert pb.state == "done"
        assert pb.is_stale is False


class TestJobOverlays:
    def test_running_job_flips_stage_to_running(self, db_session, seed_book_chapter_topic):
        gid = seed_book_chapter_topic["guideline_id"]
        _add_job(
            db_session,
            book_id=seed_book_chapter_topic["book_id"],
            chapter_id=gid,  # Phase-1 overload: post-sync jobs use guideline_id in chapter_id col
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            status="running",
        )

        svc = TopicPipelineStatusService(db_session)
        resp = svc.get_pipeline_status(
            seed_book_chapter_topic["book_id"],
            seed_book_chapter_topic["chapter_id"],
            seed_book_chapter_topic["topic_key"],
        )
        expl = next(s for s in resp.stages if s.stage_id == "explanations")
        assert expl.state == "running"
        assert expl.last_job_status == "running"

    def test_failed_job_surfaces_error(self, db_session, seed_book_chapter_topic):
        gid = seed_book_chapter_topic["guideline_id"]
        _add_explanation(db_session, gid, [{"card_type": "explain"}])
        _add_job(
            db_session,
            book_id=seed_book_chapter_topic["book_id"],
            chapter_id=gid,
            job_type=V2JobType.VISUAL_ENRICHMENT.value,
            status="failed",
            error="pixi compile failed",
        )

        svc = TopicPipelineStatusService(db_session)
        resp = svc.get_pipeline_status(
            seed_book_chapter_topic["book_id"],
            seed_book_chapter_topic["chapter_id"],
            seed_book_chapter_topic["topic_key"],
        )
        vis = next(s for s in resp.stages if s.stage_id == "visuals")
        assert vis.state == "failed"
        assert vis.last_job_error == "pixi compile failed"

    def test_historical_row_chapter_id_overload_resolved(self, db_session, seed_book_chapter_topic):
        """Historical post-sync rows stored guideline_id in chapter_id column.

        The status service must still find them for the right topic.
        """
        gid = seed_book_chapter_topic["guideline_id"]
        _add_job(
            db_session,
            book_id=seed_book_chapter_topic["book_id"],
            chapter_id=gid,  # <- the historical overload
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            status="failed",
            error="historical failure",
        )

        svc = TopicPipelineStatusService(db_session)
        resp = svc.get_pipeline_status(
            seed_book_chapter_topic["book_id"],
            seed_book_chapter_topic["chapter_id"],
            seed_book_chapter_topic["topic_key"],
        )
        expl = next(s for s in resp.stages if s.stage_id == "explanations")
        assert expl.state == "failed"
        assert expl.last_job_error == "historical failure"


class TestInPlaceCardsJsonWrites:
    def test_writing_cards_json_inplace_does_not_flip_practice_stale(
        self, db_session, seed_book_chapter_topic
    ):
        """After Phase 2 audio-synth writes cards_json in-place, explanation.updated_at
        advances — but the staleness anchor (`created_at`) must NOT move, so
        practice bank shouldn't flash stale. Simulates the same thing.
        """
        gid = seed_book_chapter_topic["guideline_id"]
        baseline = datetime.utcnow()

        expl = _add_explanation(db_session, gid, [{"card_type": "explain"}], created_at=baseline)

        for i in range(30):
            pq = PracticeQuestion(
                id=str(uuid.uuid4()),
                guideline_id=gid,
                format="mcq",
                difficulty="easy",
                concept_tag="tag",
                question_json={"stem": f"Q{i}"},
            )
            pq.created_at = baseline + timedelta(seconds=1)
            db_session.add(pq)
        db_session.commit()

        # Simulate in-place cards_json write (audio synthesis): advance updated_at
        # but DO NOT touch created_at.
        expl.cards_json = [
            {"card_type": "explain", "lines": [{"text": "a", "audio_url": "u"}]}
        ]
        db_session.commit()

        svc = TopicPipelineStatusService(db_session)
        resp = svc.get_pipeline_status(
            seed_book_chapter_topic["book_id"],
            seed_book_chapter_topic["chapter_id"],
            seed_book_chapter_topic["topic_key"],
        )
        pb = next(s for s in resp.stages if s.stage_id == "practice_bank")
        assert pb.is_stale is False, "practice bank must not flip stale on in-place cards_json write"


class TestChapterSummary:
    def test_chapter_summary_returns_topic_rollups(self, db_session, seed_book_chapter_topic):
        gid = seed_book_chapter_topic["guideline_id"]
        _add_explanation(db_session, gid, [{"card_type": "explain"}])

        svc = TopicPipelineStatusService(db_session)
        summary = svc.get_chapter_summary(
            seed_book_chapter_topic["book_id"],
            seed_book_chapter_topic["chapter_id"],
        )
        assert summary.chapter_totals.topics_total == 1
        assert len(summary.topics) == 1
        topic = summary.topics[0]
        assert topic.topic_key == seed_book_chapter_topic["topic_key"]
        counts = topic.stage_counts
        assert counts.done + counts.warning + counts.running + counts.ready + counts.blocked + counts.failed == 6
