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

# Pixi v8 density test fixtures — exercise the _BOUNDS_WALK_JS density
# detection. The fix added a v8 branch that introspects
# obj.context.instructions for fill actions. Prior to the fix, v8 Graphics
# always returned dense=true (both v6/v7 API lookups were undefined), which
# caused false-positive overlap flagging on empty or stroke-only Graphics.
DENSE_GRAPHICS_PIXI = """
// Filled rectangle — Pixi v8 emits a 'fill' instruction into obj.context.instructions.
const box = new PIXI.Graphics();
box.rect(100, 100, 200, 100);
box.fill(0xff0000);
app.stage.addChild(box);
"""

STROKE_ONLY_GRAPHICS_PIXI = """
// Stroke-only rectangle — no 'fill' instruction. Should be dense=false on v8
// with the fix in place (previously: dense=true — false positive).
const box = new PIXI.Graphics();
box.rect(100, 100, 200, 100);
box.stroke({ color: 0xffffff, width: 2 });
app.stage.addChild(box);
"""

TEXT_OVER_DENSE_GRAPHICS_PIXI = """
// Text inside a filled rectangle — exactly the layout category the overlap
// gate is supposed to flag. With the v8 density fix, detect_overlaps sees
// the Graphics as dense and should report the Text↔Graphics overlap.
const box = new PIXI.Graphics();
box.rect(100, 100, 200, 100);
box.fill(0x444488);
app.stage.addChild(box);

const label = new PIXI.Text({ text: 'Tens', style: { fontSize: 22, fill: 0xffffff } });
label.x = 140; label.y = 130;
app.stage.addChild(label);
"""

TEXT_OVER_STROKE_ONLY_PIXI = """
// Text inside a stroke-only rectangle — no solid fill, so should NOT be
// flagged as overlapping Graphics on v8 with the fix. Prior bug: it WAS
// flagged because v8 density defaulted to true.
const frame = new PIXI.Graphics();
frame.rect(100, 100, 200, 100);
frame.stroke({ color: 0xffffff, width: 2 });
app.stage.addChild(frame);

const label = new PIXI.Text({ text: 'Tens', style: { fontSize: 22, fill: 0xffffff } });
label.x = 140; label.y = 130;
app.stage.addChild(label);
"""


# NOTE: the TestRenderClean / TestRenderColliding / TestPixiV8DensityDetection
# classes below do NOT invoke VisualRenderHarness.render() directly. That
# method uses an in-process preview store (see visual_preview_store.py) —
# when pytest runs, the harness puts code in the pytest-process store, but
# the frontend fetches from the backend-process store. So we drive the same
# pipeline through _render_via_backend() which POSTs to the real backend
# endpoint, keeping both sides aligned on the same store.


def _backend_reachable() -> bool:
    """Probe the backend at :8000 — the preview store lives there, not in
    the pytest process, so we must POST code through the backend's
    /admin/v2/visual-preview/prepare endpoint for Playwright to find it."""
    import urllib.request

    try:
        with urllib.request.urlopen("http://localhost:8000/health", timeout=1.0) as r:
            return r.status == 200
    except Exception:
        return False


backend_required = pytest.mark.skipif(
    not (_playwright_available() and _frontend_reachable() and _backend_reachable()),
    reason="needs playwright + frontend:3000 + backend:8000 all running",
)


def _render_via_backend(pixi_code: str, output_type: str = "static_visual") -> list[dict]:
    """POST code to the backend's prepare endpoint (so its in-process store
    has the id), then use Playwright directly to navigate and walk the tree.

    Returns the raw bounds list as captured by _BOUNDS_WALK_JS. We deliberately
    do NOT route through VisualRenderHarness here — the harness's preview
    store is in-process, so a pytest-invoked harness would stash code in the
    pytest process's singleton while the frontend fetches from the backend
    process's singleton. POSTing to the backend endpoint keeps them aligned.
    """
    import json as _json
    import urllib.request

    from book_ingestion_v2.services.visual_render_harness import _BOUNDS_WALK_JS
    from playwright.sync_api import sync_playwright

    req = urllib.request.Request(
        "http://localhost:8000/admin/v2/visual-preview/prepare",
        method="POST",
        data=_json.dumps({"pixi_code": pixi_code, "output_type": output_type}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        preview_id = _json.loads(resp.read())["id"]

    url = f"http://localhost:3000/admin/visual-render-preview/{preview_id}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 800, "height": 600})
            page = context.new_page()
            page.goto(url, timeout=30_000)
            page.wait_for_selector(
                '[data-pixi-state="ready"], [data-pixi-state="error"]',
                timeout=30_000,
            )
            state = page.locator("[data-pixi-state]").first.get_attribute("data-pixi-state")
            if state == "error":
                err = page.evaluate("() => window.__pixiError || 'unknown'")
                raise AssertionError(f"Pixi render errored: {err}")
            return page.evaluate(_BOUNDS_WALK_JS)
        finally:
            browser.close()


@backend_required
class TestRenderClean:
    def test_clean_visual_returns_bounds_no_overlaps(self):
        from book_ingestion_v2.services.visual_overlap_detector import (
            ObjectBounds, detect_overlaps,
        )

        raw = _render_via_backend(CLEAN_PIXI)
        bounds = [ObjectBounds(**b) for b in raw]
        texts = [b for b in bounds if b.type == "Text"]
        assert len(texts) >= 3, f"expected >=3 Text nodes; got {texts}"
        overlaps = detect_overlaps(bounds)
        assert overlaps == [], f"unexpected overlaps: {overlaps}"


@backend_required
class TestRenderColliding:
    def test_place_value_collision_detected(self):
        from book_ingestion_v2.services.visual_overlap_detector import (
            ObjectBounds, detect_overlaps, format_collision_report,
        )

        raw = _render_via_backend(COLLIDING_PIXI)
        bounds = [ObjectBounds(**b) for b in raw]
        overlaps = detect_overlaps(bounds)
        assert len(overlaps) >= 1, f"no overlaps found; raw={raw}"
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


@backend_required
class TestPixiV8DensityDetection:
    """Regression coverage for the v8 density branch in _BOUNDS_WALK_JS.

    Before the fix, obj.geometry.drawCalls and obj.graphicsData were both
    undefined on Pixi v8 Graphics, so `dense` stayed at its default `true`
    for every Graphics object — causing detect_overlaps to treat even
    stroke-only or empty Graphics as collision candidates.

    After the fix, v8's obj.context.instructions is inspected for any
    `action === 'fill'` entry, giving an accurate dense signal.
    """

    def test_filled_graphics_reports_dense_true(self):
        bounds = _render_via_backend(DENSE_GRAPHICS_PIXI)
        graphics = [b for b in bounds if b["type"] == "Graphics"]
        assert graphics, f"no Graphics captured; bounds={bounds}"
        assert any(g.get("dense") for g in graphics), (
            f"no Graphics reported dense=true (v8 fill branch should fire): {graphics}"
        )

    def test_stroke_only_graphics_reports_dense_false(self):
        bounds = _render_via_backend(STROKE_ONLY_GRAPHICS_PIXI)
        graphics = [b for b in bounds if b["type"] == "Graphics"]
        assert graphics, f"no Graphics captured; bounds={bounds}"
        # Prior bug: v8 density always defaulted to true, so this would fail.
        assert all(not g.get("dense") for g in graphics), (
            f"stroke-only Graphics should not be dense: {graphics}"
        )

    def test_text_over_filled_graphics_flags_overlap(self):
        """End-to-end: dense Graphics + overlapping Text → detect_overlaps
        reports the pair. Validates the v8 density path flows through to
        the collision decision."""
        from book_ingestion_v2.services.visual_overlap_detector import (
            ObjectBounds, detect_overlaps,
        )

        raw = _render_via_backend(TEXT_OVER_DENSE_GRAPHICS_PIXI)
        bounds = [ObjectBounds(**b) for b in raw]
        overlaps = detect_overlaps(bounds)
        assert overlaps, f"Expected Text↔dense-Graphics overlap; raw={raw}"
        labels = {(o.a_label, o.b_label) for o in overlaps}
        assert any("Tens" in pair for pair in labels), (
            f"Text 'Tens' missing from overlap labels: {labels}"
        )

    def test_text_over_stroke_only_does_not_flag(self):
        """Exactly the false-positive scenario the v8 fix eliminates: text
        sitting inside a stroke-only frame should NOT be flagged. Prior to
        the fix, v8 Graphics always reported dense=true and this would
        incorrectly trip the overlap detector."""
        from book_ingestion_v2.services.visual_overlap_detector import (
            ObjectBounds, detect_overlaps,
        )

        raw = _render_via_backend(TEXT_OVER_STROKE_ONLY_PIXI)
        bounds = [ObjectBounds(**b) for b in raw]
        types = {b.type for b in bounds}
        assert "Graphics" in types, f"expected a Graphics object; raw={raw}"
        overlaps = detect_overlaps(bounds)
        assert overlaps == [], (
            f"Stroke-only Graphics + Text should not flag overlap: {overlaps}"
        )
