"""Admin-only endpoints for the Visual Rendering Review preview store.

These are NOT book-scoped — they provide a short-lived id -> pixi-code map used
by the render harness to hand code to the admin preview React page without
putting executable code in the URL.
"""
import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from book_ingestion_v2.services.visual_preview_store import get_preview_store

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/admin/v2/visual-preview", tags=["Book Ingestion V2 - Visual Preview"])


class PreparePreviewRequest(BaseModel):
    pixi_code: str
    output_type: str = "static_visual"


class PreparePreviewResponse(BaseModel):
    id: str


class FetchPreviewResponse(BaseModel):
    pixi_code: str
    output_type: str


@router.post("/prepare", response_model=PreparePreviewResponse)
def prepare_visual_preview(payload: PreparePreviewRequest) -> PreparePreviewResponse:
    """Stash pixi code server-side under a short-lived random id.

    The render harness calls this, gets back the id, then navigates Playwright
    to /admin/visual-render-preview/{id} on the frontend. Closes the reflected-
    XSS vector of carrying executable code in a URL query param. Entries expire
    after TTL_SECONDS (see visual_preview_store).
    """
    if not payload.pixi_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pixi_code required",
        )
    preview_id = get_preview_store().put(
        code=payload.pixi_code, output_type=payload.output_type,
    )
    return PreparePreviewResponse(id=preview_id)


@router.get("/{preview_id}", response_model=FetchPreviewResponse)
def fetch_visual_preview(preview_id: str) -> FetchPreviewResponse:
    """Fetch the stashed pixi code for a preview id. 404 if missing or expired."""
    entry = get_preview_store().get(preview_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="preview not found or expired",
        )
    return FetchPreviewResponse(pixi_code=entry.code, output_type=entry.output_type)
