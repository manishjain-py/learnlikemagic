"""Render pixi code in headless Chrome and capture a PNG screenshot.

Uses playwright-python. Stashes code server-side via the visual preview store,
then navigates to the id-keyed /admin/visual-render-preview/{id} page — the
admin preview mounts Pixi directly. We wait for the page to flip to ready
and then screenshot the canvas.

Dependencies:
- playwright-python (`pip install playwright`)
- Chromium driver (`playwright install chromium`)
- Frontend dev server on http://localhost:3000 (admin preview page)

The preflight() classmethod exists so callers can fail a long-running job
fast when the frontend isn't up, instead of silently skipping the stage-7
visual review gate on every card.
"""
import logging
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

from book_ingestion_v2.services.visual_preview_store import get_preview_store

logger = logging.getLogger(__name__)


FRONTEND_URL = "http://localhost:3000"
RENDER_TIMEOUT_MS = 30_000


class RenderResult(BaseModel):
    ok: bool
    screenshot_path: Optional[str] = None
    error: Optional[str] = None


class VisualRenderHarness:
    """Per-call: boot browser, render code, capture screenshot.

    Serial — not thread-safe. Use one instance per job, not shared across threads.
    """

    def render(
        self,
        pixi_code: str,
        *,
        output_type: Literal["static_visual", "animated_visual"] = "static_visual",
        screenshot_path: Optional[Path] = None,
    ) -> RenderResult:
        """Render pixi code in headless Chromium and write a PNG screenshot."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return RenderResult(ok=False, error="playwright not installed")

        preview_id = get_preview_store().put(code=pixi_code, output_type=output_type)
        url = f"{FRONTEND_URL}/admin/visual-render-preview/{preview_id}"

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    context = browser.new_context(viewport={"width": 800, "height": 600})
                    page = context.new_page()
                    page.goto(url, timeout=RENDER_TIMEOUT_MS)
                    page.wait_for_selector(
                        '[data-pixi-state="ready"], [data-pixi-state="error"]',
                        timeout=RENDER_TIMEOUT_MS,
                    )
                    state = page.locator("[data-pixi-state]").first.get_attribute("data-pixi-state")
                    if state == "error":
                        err_msg = page.evaluate("() => window.__pixiError || 'unknown error'")
                        return RenderResult(ok=False, error=f"pixi error: {err_msg}")

                    if screenshot_path:
                        try:
                            page.locator('[data-pixi-state="ready"]').screenshot(
                                path=str(screenshot_path)
                            )
                        except Exception as shot_err:
                            logger.warning(
                                f"Screenshot failed for {preview_id}: {shot_err}"
                            )
                            return RenderResult(
                                ok=False, error=f"screenshot failed: {shot_err}"
                            )

                    context.close()
                finally:
                    browser.close()

                return RenderResult(
                    ok=True,
                    screenshot_path=str(screenshot_path) if screenshot_path else None,
                )
        except Exception as e:
            logger.exception(f"Render harness failed for preview {preview_id}: {e}")
            return RenderResult(ok=False, error=str(e))

    @staticmethod
    def preflight(timeout_seconds: float = 3.0) -> tuple[bool, Optional[str]]:
        """HEAD the frontend root. Fails fast when localhost:3000 isn't up.

        Called once at the top of a stage-7 visual enrichment job so admin
        sees a clear error in seconds, rather than silently skipping the
        review gate on every card.
        """
        import urllib.error
        import urllib.request

        try:
            req = urllib.request.Request(FRONTEND_URL, method="HEAD")
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                if 200 <= resp.status < 500:
                    return True, None
                return False, f"frontend returned HTTP {resp.status}"
        except urllib.error.URLError as e:
            return False, f"frontend unreachable at {FRONTEND_URL}: {e.reason}"
        except Exception as e:
            return False, f"preflight failed: {e}"
