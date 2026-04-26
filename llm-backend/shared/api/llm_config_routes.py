"""Admin API for centralized LLM model configuration."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from database import get_db
from shared.services.llm_config_service import LLMConfigService, LLMConfigNotFoundError

router = APIRouter(prefix="/api/admin", tags=["llm-config"])

# Available models per provider (for frontend dropdowns)
AVAILABLE_MODELS = {
    "openai": ["gpt-5.4", "gpt-5.4-nano", "gpt-5.3-codex", "gpt-5.2", "gpt-5.1", "gpt-4o", "gpt-4o-mini"],
    "anthropic": ["claude-opus-4-6", "claude-haiku-4-5-20251001"],
    "google": ["gemini-3-pro-preview"],
    "claude_code": ["claude-code"],
}


VALID_REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


class UpdateLLMConfigRequest(BaseModel):
    provider: str
    model_id: str
    reasoning_effort: str = "max"


@router.get("/llm-config")
def list_llm_configs(db: DBSession = Depends(get_db)):
    """Return all LLM configs."""
    service = LLMConfigService(db)
    return service.get_all_configs()


@router.put("/llm-config/{component_key}")
def update_llm_config(
    component_key: str,
    request: UpdateLLMConfigRequest,
    db: DBSession = Depends(get_db),
):
    """Update provider + model + reasoning_effort for a component."""
    # Validate provider
    if request.provider not in AVAILABLE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{request.provider}'. Valid: {list(AVAILABLE_MODELS.keys())}",
        )

    # Validate model for that provider
    if request.model_id not in AVAILABLE_MODELS[request.provider]:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model '{request.model_id}' for provider '{request.provider}'. "
                   f"Valid: {AVAILABLE_MODELS[request.provider]}",
        )

    # Validate reasoning_effort
    if request.reasoning_effort not in VALID_REASONING_EFFORTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown reasoning_effort '{request.reasoning_effort}'. "
                   f"Valid: {sorted(VALID_REASONING_EFFORTS)}",
        )

    service = LLMConfigService(db)
    result = service.update_config(
        component_key=component_key,
        provider=request.provider,
        model_id=request.model_id,
        reasoning_effort=request.reasoning_effort,
    )
    db.commit()
    return result


@router.get("/llm-config/options")
def get_llm_config_options():
    """Return available models per provider (for frontend dropdowns)."""
    return AVAILABLE_MODELS
