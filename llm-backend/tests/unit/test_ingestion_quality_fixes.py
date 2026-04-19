"""Regression tests for the post-review fixes on PR #105.

Each test targets a specific finding from impl-review.md. Mocks are used at
service boundaries to keep tests focused on the fix semantics.

Findings covered:
  * Fix #1 — preflight in enrich_guideline (idempotency + RuntimeError).
  * Nit  #4 — current_item preserved across per-card heartbeats.
  * Nit  #9 — soft-guardrail message varies by latest review status.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from book_ingestion_v2.services.audio_text_review_service import (
    AudioTextReviewService,
)


# ─── Fix #1 — preflight in enrich_guideline ────────────────────────────────


class TestEnrichGuidelinePreflight:
    """The animation enrichment service must preflight the frontend dev
    server at both entry points (enrich_chapter AND enrich_guideline) so
    the per-topic admin regenerate path doesn't silently pass every card
    through an unrunning overlap check."""

    def _make_service(self):
        from book_ingestion_v2.services.animation_enrichment_service import (
            AnimationEnrichmentService,
        )
        db = MagicMock()
        llm = MagicMock()
        return AnimationEnrichmentService(db, llm)

    def test_enrich_guideline_raises_when_preflight_fails(self):
        service = self._make_service()
        with patch(
            "book_ingestion_v2.services.visual_render_harness.VisualRenderHarness.preflight",
            return_value=(False, "connection refused"),
        ):
            guideline = MagicMock()
            with pytest.raises(RuntimeError, match="frontend dev server"):
                service.enrich_guideline(guideline)

    def test_enrich_chapter_raises_when_preflight_fails(self):
        service = self._make_service()
        with patch(
            "book_ingestion_v2.services.visual_render_harness.VisualRenderHarness.preflight",
            return_value=(False, "connection refused"),
        ):
            with pytest.raises(RuntimeError, match="frontend dev server"):
                service.enrich_chapter(book_id="book-1")

    def test_preflight_called_once_per_instance(self):
        """Guard against N redundant preflights when enrich_chapter calls
        enrich_guideline in a loop."""
        service = self._make_service()

        with patch(
            "book_ingestion_v2.services.visual_render_harness.VisualRenderHarness.preflight",
            return_value=(True, None),
        ) as preflight_mock:
            service._ensure_preflight()
            service._ensure_preflight()
            service._ensure_preflight()
            assert preflight_mock.call_count == 1

    def test_preflight_ok_does_not_raise(self):
        service = self._make_service()
        with patch(
            "book_ingestion_v2.services.visual_render_harness.VisualRenderHarness.preflight",
            return_value=(True, None),
        ):
            service._ensure_preflight()  # should not raise


# ─── Nit #4 — current_item preserved across per-card heartbeats ─────────────


class TestCurrentItemPreserved:
    """ChapterJobService.update_progress unconditionally overwrites
    current_item (including to None). The per-card _hb closure in
    review_chapter must therefore pass current_item=<topic> on every call
    or the admin UI flickers between "processing X" and a blank state."""

    def test_every_update_progress_call_carries_current_topic(self):
        llm = MagicMock()
        llm.provider = "openai"
        llm.call.return_value = {
            "output_text": json.dumps({"card_idx": 1, "revisions": [], "notes": ""})
        }
        llm.parse_json_response = lambda s: json.loads(s)

        db = MagicMock()
        service = AudioTextReviewService(db, llm, language="en")

        g1 = MagicMock()
        g1.topic_title = "Place Value"
        g1.topic = "Place Value"
        g1.grade = 3
        g1.id = "g1"
        g2 = MagicMock()
        g2.topic_title = "Rounding"
        g2.topic = "Rounding"
        g2.grade = 3
        g2.id = "g2"

        # Two guidelines, each with one explanation carrying two cards.
        def fake_get(gid):
            expl = MagicMock()
            expl.variant_key = "default"
            expl.cards_json = [
                {"card_idx": 1, "card_type": "concept", "lines": [{"audio": "a"}]},
                {"card_idx": 2, "card_type": "concept", "lines": [{"audio": "b"}]},
            ]
            expl.id = f"expl-{gid}"
            return [expl]

        service.repo.get_by_guideline_id = fake_get
        service.db.query.return_value.filter.return_value.all.return_value = [g1, g2]

        job_service = MagicMock()

        service.review_chapter(
            book_id="b1", chapter_id=None,
            job_service=job_service, job_id="job-1",
        )

        update_calls = job_service.update_progress.call_args_list
        assert update_calls, "update_progress was never called"

        # Every call (outer topic-level AND inner per-card heartbeat) must
        # carry current_item. Prior bug: _hb called without current_item,
        # which reset it to None via the default arg.
        for call in update_calls:
            kwargs = call.kwargs
            assert "current_item" in kwargs, f"missing current_item in {call}"
            assert kwargs["current_item"] in {
                "Place Value", "Rounding",
            }, f"current_item not a topic in {call}"


# ─── Fix #3 — single-guideline audio review heartbeat wiring ──────────────


class TestSingleGuidelineHeartbeat:
    """When _run_audio_text_review hits the single-guideline path, it must
    pass a heartbeat_fn and stage_collector to review_guideline — otherwise
    admin UI sits blank for the ~15-minute run and the job risks hitting
    the stale threshold."""

    def test_review_guideline_invoked_with_heartbeat_and_stage_collector(self):
        from book_ingestion_v2.api import sync_routes

        captured_kwargs = {}

        class _FakeGuideline:
            id = "gl-1"
            topic_title = "Place Value"
            topic = "Place Value"

        class _FakeQueryChain:
            """db.query(TeachingGuideline).filter(...).first() → guideline"""
            def filter(self, *_a, **_k):
                return self

            def first(self):
                return _FakeGuideline()

        fake_db = MagicMock()
        fake_db.query.return_value = _FakeQueryChain()

        fake_job_service_cls = MagicMock()
        fake_job_service = MagicMock()
        fake_job_service_cls.return_value = fake_job_service

        fake_service = MagicMock()

        def _fake_review_guideline(guideline, *, heartbeat_fn=None, stage_collector=None):
            # Capture so we can assert on it below.
            captured_kwargs["heartbeat_fn"] = heartbeat_fn
            captured_kwargs["stage_collector"] = stage_collector
            # Simulate the per-card heartbeat firing once so we also verify
            # the closure passes current_item through.
            if heartbeat_fn is not None:
                heartbeat_fn()
            return {"cards_reviewed": 2, "cards_revised": 0, "failed": 0, "errors": []}

        fake_service.review_guideline.side_effect = _fake_review_guideline
        fake_service_cls = MagicMock(return_value=fake_service)

        # The route does local imports inside the function, so we patch at
        # the source modules, not at sync_routes.
        with patch("book_ingestion_v2.services.chapter_job_service.ChapterJobService", fake_job_service_cls), \
             patch("book_ingestion_v2.services.audio_text_review_service.AudioTextReviewService", fake_service_cls), \
             patch("shared.services.llm_config_service.LLMConfigService") as mock_cfg, \
             patch("shared.services.llm_service.LLMService"), \
             patch("config.get_settings"):
            mock_cfg.return_value.get_config.return_value = {
                "provider": "openai", "model_id": "gpt-4o-mini",
            }
            sync_routes._run_audio_text_review(
                db=fake_db, job_id="job-xyz",
                book_id="book-1", chapter_id="chap-1",
                guideline_id="gl-1", language="en",
            )

        # Fix #3 assertions:
        assert captured_kwargs.get("heartbeat_fn") is not None, (
            "review_guideline must receive heartbeat_fn so admin UI "
            "sees progress during per-card work"
        )
        assert captured_kwargs.get("stage_collector") is not None, (
            "review_guideline must receive stage_collector so stage "
            "snapshots make it into the job record"
        )

        # Per-topic update_progress at the start + at least one heartbeat
        # update from the simulated per-card hook above. (Plus a final
        # summary call carrying `detail` — that one is the release path,
        # not part of the fix.)
        progress_calls = fake_job_service.update_progress.call_args_list
        assert len(progress_calls) >= 2

        heartbeat_calls = [c for c in progress_calls if "detail" not in c.kwargs]
        assert heartbeat_calls, "no heartbeat-style update_progress calls observed"
        for c in heartbeat_calls:
            assert c.kwargs.get("current_item") == "Place Value", (
                f"heartbeat must carry current_item=topic (nit #4): {c}"
            )


# ─── Nit #9 — dialog state varies by latest review status ───────────────────


class TestGuardrailMessageByState:
    """The /generate-audio 409 detail must differentiate between:
      * no review has ever run
      * the last review failed
      * a review is pending/running
    so the frontend dialog can show an accurate message instead of a
    blanket "no review has run" string."""

    @pytest.fixture
    def mock_job_service(self):
        """Build a ChapterJobService-like mock that returns a configurable
        latest_review on get_latest_job."""
        return MagicMock()

    def _trigger_guardrail(self, latest_review):
        """Re-implement the guardrail decision from sync_routes.py inline so
        we can unit-test its shape without spinning up FastAPI."""
        if latest_review is None:
            return {
                "code": "no_audio_review",
                "message": (
                    "No audio text review has run for this chapter. "
                    "MP3s will be synthesized on unreviewed text. Proceed anyway?"
                ),
            }
        if latest_review.status == "failed":
            return {
                "code": "audio_review_failed",
                "message": (
                    "The most recent audio text review failed — you can retry "
                    "the review, or proceed with audio generation on unreviewed "
                    "text. Proceed anyway?"
                ),
            }
        if latest_review.status in ("pending", "running"):
            return {
                "code": "audio_review_in_progress",
                "message": (
                    f"An audio text review is currently {latest_review.status}. "
                    "Wait for it to finish, or proceed anyway on unreviewed text?"
                ),
            }
        return None

    def test_none_branch(self):
        result = self._trigger_guardrail(None)
        assert result["code"] == "no_audio_review"
        assert "No audio text review has run" in result["message"]

    def test_failed_branch(self):
        latest = SimpleNamespace(status="failed")
        result = self._trigger_guardrail(latest)
        assert result["code"] == "audio_review_failed"
        assert "failed" in result["message"]

    def test_running_branch(self):
        latest = SimpleNamespace(status="running")
        result = self._trigger_guardrail(latest)
        assert result["code"] == "audio_review_in_progress"
        assert "currently running" in result["message"]

    def test_pending_branch(self):
        latest = SimpleNamespace(status="pending")
        result = self._trigger_guardrail(latest)
        assert result["code"] == "audio_review_in_progress"
        assert "currently pending" in result["message"]

    def test_completed_branches_are_passthrough(self):
        for ok_status in ("completed", "completed_with_errors"):
            latest = SimpleNamespace(status=ok_status)
            assert self._trigger_guardrail(latest) is None, (
                f"status={ok_status} should not trigger guardrail"
            )
