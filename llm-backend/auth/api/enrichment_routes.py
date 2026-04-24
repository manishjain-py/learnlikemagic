"""API endpoints for kid enrichment profiles and personality."""

import time
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from database import get_db, get_db_manager
from auth.middleware.auth_middleware import get_current_user
from auth.services.enrichment_service import EnrichmentService
from auth.services.personality_service import PersonalityService
from auth.models.enrichment_schemas import (
    EnrichmentProfileRequest,
    EnrichmentProfileResponse,
    EnrichmentUpdateResponse,
    PersonalityResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["enrichment"])


def _debounced_regenerate(user_id: str, expected_hash: str):
    """Sleep 5s, re-check hash, then regenerate if still needed."""
    time.sleep(5)

    with get_db_manager().session_scope() as db:
        service = EnrichmentService(db)
        current_hash = service.compute_inputs_hash(user_id)

        if current_hash != expected_hash:
            # Parent saved again within 5s — a newer task will handle it
            return

        # Only regenerate if at least 1 of the 9 main sections has data
        if not service.has_meaningful_enrichment_data(user_id):
            return

        PersonalityService(db).generate_personality(user_id)


@router.get("/enrichment", response_model=EnrichmentProfileResponse)
async def get_enrichment(
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get kid's enrichment profile (returns empty object if none exists)."""
    service = EnrichmentService(db)
    return service.get_profile(current_user.id)


@router.put("/enrichment", response_model=EnrichmentUpdateResponse)
async def update_enrichment(
    request: EnrichmentProfileRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Create or update enrichment profile (partial updates supported).

    After save, triggers personality regeneration asynchronously if data changed.
    """
    service = EnrichmentService(db)
    result = service.update_profile(current_user.id, request)

    if result.personality_status == "generating":
        background_tasks.add_task(_debounced_regenerate, current_user.id, result.inputs_hash)

    return result


@router.get("/personality", response_model=PersonalityResponse)
async def get_personality(
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get latest derived personality + status."""
    latest = PersonalityService(db).get_latest_personality(current_user.id)
    if not latest:
        return PersonalityResponse(status="none")
    return PersonalityResponse(
        personality_json=latest.personality_json,
        tutor_brief=latest.tutor_brief,
        status=latest.status,
        updated_at=latest.created_at,
    )


def _force_regenerate_bg(user_id: str):
    """Run force_regenerate with its own DB session (not request-scoped)."""
    with get_db_manager().session_scope() as db:
        PersonalityService(db).force_regenerate(user_id)


@router.post("/personality/regenerate")
async def regenerate_personality(
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Force regeneration of personality (admin/debug use)."""
    if not EnrichmentService(db).has_meaningful_enrichment_data(current_user.id):
        raise HTTPException(status_code=400, detail="No enrichment data to generate personality from")

    background_tasks.add_task(_force_regenerate_bg, current_user.id)
    return {"status": "regenerating"}
