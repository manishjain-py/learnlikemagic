"""Integration tests for VisualRenderHarness.

Skip-guarded — require:
  1. playwright python package installed
  2. chromium driver installed (`playwright install chromium`)
  3. frontend dev server reachable at http://localhost:3000

Every test is wrapped with skip markers so a missing prerequisite produces
a clear skip message, not a failure. Do not add these to any CI job that
doesn't provision playwright + chromium + a running frontend.
"""
import sys
from pathlib import Path

import pytest


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def _frontend_reachable() -> bool:
    from book_ingestion_v2.services.visual_render_harness import VisualRenderHarness
    ok, _ = VisualRenderHarness.preflight(timeout_seconds=1.0)
    return ok


playwright_required = pytest.mark.skipif(
    not _playwright_available(),
    reason="playwright not installed (pip install playwright; playwright install chromium)",
)

frontend_required = pytest.mark.skipif(
    not (_playwright_available() and _frontend_reachable()),
    reason="frontend dev server not running on localhost:3000",
)


# Minimal "clean" pixi snippet: three well-spaced text labels.
CLEAN_PIXI = """
const a = new PIXI.Text({ text: 'Hundreds', style: { fontSize: 20, fill: 0xffffff } });
a.x = 40; a.y = 80;
const b = new PIXI.Text({ text: 'Tens', style: { fontSize: 20, fill: 0xffffff } });
b.x = 200; b.y = 80;
const c = new PIXI.Text({ text: 'Ones', style: { fontSize: 20, fill: 0xffffff } });
c.x = 360; c.y = 80;
app.stage.addChild(a); app.stage.addChild(b); app.stage.addChild(c);
"""

# The observed defect reproduction: place-value labels that collide.
COLLIDING_PIXI = """
const a = new PIXI.Text({ text: 'Lakhs Period', style: { fontSize: 20, fill: 0xffffff } });
a.x = 40; a.y = 80;
const b = new PIXI.Text({ text: 'Thousands Period', style: { fontSize: 20, fill: 0xffffff } });
b.x = 120; b.y = 80;
const c = new PIXI.Text({ text: 'Ones Period', style: { fontSize: 20, fill: 0xffffff } });
c.x = 200; c.y = 80;
app.stage.addChild(a); app.stage.addChild(b); app.stage.addChild(c);
"""

# Code that throws at runtime.
BROKEN_PIXI = """
throw new Error('intentional test error');
"""


@frontend_required
class TestRenderClean:
    def test_clean_visual_returns_bounds_no_overlaps(self):
        from book_ingestion_v2.services.visual_render_harness import VisualRenderHarness
        from book_ingestion_v2.services.visual_overlap_detector import detect_overlaps

        result = VisualRenderHarness().render(CLEAN_PIXI, output_type="static_visual")
        assert result.ok, result.error
        texts = [b for b in result.bounds if b.type == "Text"]
        assert len(texts) >= 3
        overlaps = detect_overlaps(result.bounds)
        assert overlaps == []


@frontend_required
class TestRenderColliding:
    def test_place_value_collision_detected(self):
        from book_ingestion_v2.services.visual_render_harness import VisualRenderHarness
        from book_ingestion_v2.services.visual_overlap_detector import (
            detect_overlaps, format_collision_report,
        )

        result = VisualRenderHarness().render(COLLIDING_PIXI, output_type="static_visual")
        assert result.ok, result.error
        overlaps = detect_overlaps(result.bounds)
        assert len(overlaps) >= 1
        report = format_collision_report(overlaps)
        assert "Lakhs" in report or "Thousands" in report


@frontend_required
class TestRenderBroken:
    def test_runtime_error_reported(self):
        from book_ingestion_v2.services.visual_render_harness import VisualRenderHarness
        result = VisualRenderHarness().render(BROKEN_PIXI, output_type="static_visual")
        assert result.ok is False
        assert result.error is not None
        assert "error" in result.error.lower() or "intentional" in result.error.lower()


@playwright_required
class TestRenderHarnessUnreachableFrontend:
    def test_unreachable_frontend_returns_error(self, monkeypatch):
        from book_ingestion_v2.services import visual_render_harness
        # Redirect to a guaranteed-unused localhost port.
        monkeypatch.setattr(visual_render_harness, "FRONTEND_URL", "http://localhost:9999")

        from book_ingestion_v2.services.visual_render_harness import VisualRenderHarness
        result = VisualRenderHarness().render(CLEAN_PIXI, output_type="static_visual")
        assert result.ok is False
        assert result.error is not None


class TestPreflight:
    """preflight uses stdlib urllib — no Playwright needed."""

    def test_preflight_against_dead_port_returns_false(self, monkeypatch):
        from book_ingestion_v2.services import visual_render_harness
        from book_ingestion_v2.services.visual_render_harness import VisualRenderHarness

        monkeypatch.setattr(visual_render_harness, "FRONTEND_URL", "http://localhost:9999")
        ok, err = VisualRenderHarness.preflight(timeout_seconds=0.5)
        assert ok is False
        assert err is not None
