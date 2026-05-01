"""Admin API for the TTS provider toggle.

Single dropdown in the admin dashboard (mirrors the LLM provider toggle
pattern but with its own narrow vocabulary). Reads/writes the
`llm_config` row keyed `tts` via `TTSConfigService`.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from database import get_db
from shared.services.tts_config_service import (
    TTSConfigService,
    VALID_TTS_PROVIDERS,
)

router = APIRouter(prefix="/api/admin", tags=["tts-config"])


class UpdateTTSConfigRequest(BaseModel):
    provider: str


@router.get("/tts-config")
def get_tts_config(db: DBSession = Depends(get_db)):
    """Return the resolved active TTS provider + the available options."""
    service = TTSConfigService(db)
    return {
        "provider": service.get_provider(),
        "available_providers": sorted(VALID_TTS_PROVIDERS),
    }


@router.put("/tts-config")
def update_tts_config(
    request: UpdateTTSConfigRequest,
    db: DBSession = Depends(get_db),
):
    """Update the active TTS provider."""
    service = TTSConfigService(db)
    try:
        result = service.update_provider(provider=request.provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result
