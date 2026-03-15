"""Admin API for runtime feature flags."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from database import get_db
from shared.services.feature_flag_service import FeatureFlagService

router = APIRouter(prefix="/api/admin", tags=["feature-flags"])


class UpdateFeatureFlagRequest(BaseModel):
    enabled: bool


@router.get("/feature-flags")
def list_feature_flags(db: DBSession = Depends(get_db)):
    """Return all feature flags."""
    service = FeatureFlagService(db)
    return service.get_all_flags()


@router.put("/feature-flags/{flag_name}")
def update_feature_flag(
    flag_name: str,
    request: UpdateFeatureFlagRequest,
    db: DBSession = Depends(get_db),
):
    """Toggle a feature flag on/off. Only existing flags can be updated."""
    service = FeatureFlagService(db)
    if not service.flag_exists(flag_name):
        raise HTTPException(status_code=404, detail=f"Unknown feature flag '{flag_name}'")
    result = service.update_flag(flag_name=flag_name, enabled=request.enabled)
    db.commit()
    return result
