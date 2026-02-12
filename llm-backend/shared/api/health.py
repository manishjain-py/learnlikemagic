"""Health check API endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from database import get_db, get_db_manager

router = APIRouter(tags=["health"])


@router.get("/")
def read_root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "LearnLikeMagic LLM Backend",
        "version": "1.0.0"
    }


@router.get("/config/models")
def get_model_config():
    """Return current LLM model configuration per workflow."""
    from config import get_settings
    settings = get_settings()

    PROVIDER_LABELS = {
        "openai": "GPT-5.2",
        "anthropic": "Claude Opus 4.6",
        "anthropic-haiku": "Claude Haiku 4.5",
    }

    tutor_provider = settings.resolved_tutor_provider
    return {
        "tutor": {
            "provider": tutor_provider,
            "model_label": PROVIDER_LABELS.get(tutor_provider, tutor_provider),
        },
        "ingestion": {
            "provider": settings.ingestion_llm_provider,
            "model_label": "GPT-4o Mini",
        },
    }


@router.get("/health/db")
def database_health(db: DBSession = Depends(get_db)):
    """Database health check."""
    try:
        db_manager = get_db_manager()
        is_healthy = db_manager.health_check()

        if is_healthy:
            return {"status": "ok", "database": "connected"}
        else:
            return {"status": "error", "database": "connection_failed"}
    except Exception as e:
        return {"status": "error", "database": f"error: {str(e)}"}
