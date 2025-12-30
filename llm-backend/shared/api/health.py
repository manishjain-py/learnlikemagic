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
