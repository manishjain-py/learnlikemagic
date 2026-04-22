"""Unit tests for the stage-7 visual review gate in AnimationEnrichmentService.

Covers the decision logic only — render harness + vision adapter are mocked.
Real browser and real Claude Code CLI are never invoked here.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from book_ingestion_v2.services.animation_enrichment_service import (
    AnimationEnrichmentService, VisualDecision,
)
from book_ingestion_v2.services.visual_render_harness import RenderResult


class _FakeGuideline:
    def __init__(self):
        self.id = 1
        self.topic = "place-value"
        self.topic_title = "Place Value"
        self.subject = "Mathematics"
        self.grade = 3


class _FakeExplanation:
    id = 99
    variant_key = "v1"


def _mk_service() -> AnimationEnrichmentService:
    db = MagicMock()
    llm = MagicMock()
    svc = AnimationEnrichmentService(db=db, llm_service=llm)
    svc._validate_code = lambda code: bool(code)  # accept any truthy code
    return svc


def _mk_decision() -> VisualDecision:
    return VisualDecision(
        card_idx=7,
        decision="static_visual",
        title="Demo",
        visual_summary="sum",
        visual_spec="spec",
    )


def _render_ok(path: Path) -> RenderResult:
    path.write_bytes(b"fake-png")
    return RenderResult(ok=True, screenshot_path=str(path))


class TestVisualReviewGate:
    def test_ok_response_passes_gate_without_refine(self):
        svc = _mk_service()
        decision = _mk_decision()
        card = {"content": "content"}

        with patch("book_ingestion_v2.services.visual_render_harness.VisualRenderHarness") as HarnessCls:
            harness = HarnessCls.return_value
            harness.render.side_effect = lambda code, output_type, screenshot_path: _render_ok(screenshot_path)

            with patch.object(svc, "_visual_review", return_value=(False, "")):
                with patch.object(svc, "_review_and_refine_code") as refine:
                    code, warning = svc._visual_review_gate(
                        pixi_code="orig",
                        decision=decision,
                        card=card,
                        guideline=_FakeGuideline(),
                        explanation=_FakeExplanation(),
                        stage_collector=[],
                    )

        assert code == "orig"
        assert warning is False
        refine.assert_not_called()

    def test_flagged_then_refine_clears_review(self):
        svc = _mk_service()
        decision = _mk_decision()
        card = {"content": "content"}

        with patch("book_ingestion_v2.services.visual_render_harness.VisualRenderHarness") as HarnessCls:
            harness = HarnessCls.return_value
            harness.render.side_effect = lambda code, output_type, screenshot_path: _render_ok(screenshot_path)

            with patch.object(svc, "_visual_review", side_effect=[
                (True, "Text 'A' overlaps text 'B'"),
                (False, ""),
            ]) as review:
                with patch.object(svc, "_review_and_refine_code", return_value="refined_code"):
                    code, warning = svc._visual_review_gate(
                        pixi_code="orig",
                        decision=decision,
                        card=card,
                        guideline=_FakeGuideline(),
                        explanation=_FakeExplanation(),
                        stage_collector=[],
                    )

        assert code == "refined_code"
        assert warning is False
        assert review.call_count == 2

    def test_flagged_persists_after_refine_sets_warning(self):
        svc = _mk_service()
        decision = _mk_decision()
        card = {"content": "content"}

        with patch("book_ingestion_v2.services.visual_render_harness.VisualRenderHarness") as HarnessCls:
            harness = HarnessCls.return_value
            harness.render.side_effect = lambda code, output_type, screenshot_path: _render_ok(screenshot_path)

            with patch.object(svc, "_visual_review", side_effect=[
                (True, "issue1"),
                (True, "issue2"),
            ]):
                with patch.object(svc, "_review_and_refine_code", return_value="refined_code"):
                    code, warning = svc._visual_review_gate(
                        pixi_code="orig",
                        decision=decision,
                        card=card,
                        guideline=_FakeGuideline(),
                        explanation=_FakeExplanation(),
                        stage_collector=[],
                    )

        assert code == "refined_code"
        assert warning is True

    def test_refine_returns_no_valid_code_flags_original(self):
        svc = _mk_service()
        decision = _mk_decision()
        card = {"content": "content"}

        with patch("book_ingestion_v2.services.visual_render_harness.VisualRenderHarness") as HarnessCls:
            harness = HarnessCls.return_value
            harness.render.side_effect = lambda code, output_type, screenshot_path: _render_ok(screenshot_path)

            with patch.object(svc, "_visual_review", return_value=(True, "issue")):
                with patch.object(svc, "_review_and_refine_code", return_value=None):
                    code, warning = svc._visual_review_gate(
                        pixi_code="orig",
                        decision=decision,
                        card=card,
                        guideline=_FakeGuideline(),
                        explanation=_FakeExplanation(),
                        stage_collector=[],
                    )

        assert code == "orig"
        assert warning is True

    def test_harness_render_failure_skips_gate_without_warning(self):
        svc = _mk_service()
        decision = _mk_decision()
        card = {"content": "content"}

        with patch("book_ingestion_v2.services.visual_render_harness.VisualRenderHarness") as HarnessCls:
            harness = HarnessCls.return_value
            harness.render.return_value = RenderResult(ok=False, error="playwright missing")

            with patch.object(svc, "_visual_review") as review:
                with patch.object(svc, "_review_and_refine_code") as refine:
                    code, warning = svc._visual_review_gate(
                        pixi_code="orig",
                        decision=decision,
                        card=card,
                        guideline=_FakeGuideline(),
                        explanation=_FakeExplanation(),
                        stage_collector=[],
                    )

        assert code == "orig"
        assert warning is False
        review.assert_not_called()
        refine.assert_not_called()

    def test_rerender_failure_after_refine_sets_warning(self):
        svc = _mk_service()
        decision = _mk_decision()
        card = {"content": "content"}

        renders = iter([
            lambda path: _render_ok(path),
            lambda path: RenderResult(ok=False, error="second render failed"),
        ])

        def _render(code, output_type, screenshot_path):
            return next(renders)(screenshot_path)

        with patch("book_ingestion_v2.services.visual_render_harness.VisualRenderHarness") as HarnessCls:
            HarnessCls.return_value.render.side_effect = _render

            with patch.object(svc, "_visual_review", return_value=(True, "issue")):
                with patch.object(svc, "_review_and_refine_code", return_value="refined_code"):
                    code, warning = svc._visual_review_gate(
                        pixi_code="orig",
                        decision=decision,
                        card=card,
                        guideline=_FakeGuideline(),
                        explanation=_FakeExplanation(),
                        stage_collector=[],
                    )

        assert code == "refined_code"
        assert warning is True


class TestVisualReview:
    def test_ok_response_returns_not_flagged(self):
        svc = _mk_service()
        decision = _mk_decision()
        card = {"content": "content"}

        adapter = MagicMock()
        adapter.call_vision_sync.return_value = "OK"
        with patch.object(svc, "_get_vision_adapter", return_value=adapter):
            flagged, note = svc._visual_review(
                screenshot_path=Path("/tmp/unused.png"),
                decision=decision,
                card=card,
                guideline=_FakeGuideline(),
            )

        assert flagged is False
        assert note == ""

    def test_ok_with_trailing_whitespace_not_flagged(self):
        svc = _mk_service()
        adapter = MagicMock()
        adapter.call_vision_sync.return_value = "  OK\n"
        with patch.object(svc, "_get_vision_adapter", return_value=adapter):
            flagged, note = svc._visual_review(
                screenshot_path=Path("/tmp/unused.png"),
                decision=_mk_decision(),
                card={"content": "content"},
                guideline=_FakeGuideline(),
            )
        assert flagged is False
        assert note == ""

    def test_issue_list_returns_flagged_with_note(self):
        svc = _mk_service()
        adapter = MagicMock()
        adapter.call_vision_sync.return_value = "- Label 'A' overlaps 'B'"
        with patch.object(svc, "_get_vision_adapter", return_value=adapter):
            flagged, note = svc._visual_review(
                screenshot_path=Path("/tmp/unused.png"),
                decision=_mk_decision(),
                card={"content": "content"},
                guideline=_FakeGuideline(),
            )
        assert flagged is True
        assert "Label 'A'" in note

    def test_adapter_exception_returns_not_flagged(self):
        svc = _mk_service()
        adapter = MagicMock()
        adapter.call_vision_sync.side_effect = RuntimeError("CLI failed")
        with patch.object(svc, "_get_vision_adapter", return_value=adapter):
            flagged, note = svc._visual_review(
                screenshot_path=Path("/tmp/unused.png"),
                decision=_mk_decision(),
                card={"content": "content"},
                guideline=_FakeGuideline(),
            )
        assert flagged is False
        assert note == ""
