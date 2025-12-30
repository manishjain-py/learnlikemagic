"""Session management API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
import json

from database import get_db
from shared.models import CreateSessionRequest, CreateSessionResponse, StepRequest, StepResponse, SummaryResponse
from tutor.services import SessionService
from shared.utils.exceptions import LearnLikeMagicException

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=CreateSessionResponse)
def create_session(request: CreateSessionRequest, db: DBSession = Depends(get_db)):
    """Create a new learning session and get the first question."""
    try:
        service = SessionService(db)
        return service.create_new_session(request)
    except LearnLikeMagicException as e:
        raise e.to_http_exception()
    except Exception as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        error_details = f"Error creating session: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_details)
        # Ensure we return a JSON response even for 500 errors
        raise HTTPException(status_code=500, detail={"message": f"Error creating session: {str(e)}", "type": type(e).__name__})


@router.post("/{session_id}/step", response_model=StepResponse)
def submit_step(session_id: str, request: StepRequest, db: DBSession = Depends(get_db)):
    """Submit a student answer and get the next turn."""
    try:
        service = SessionService(db)
        return service.process_step(session_id, request)
    except LearnLikeMagicException as e:
        raise e.to_http_exception()
    except Exception as e:
        import traceback
        error_details = f"Error processing step: {str(e)}\n{traceback.format_exc()}"
        print(error_details)
        raise HTTPException(status_code=500, detail=f"Error processing step: {str(e)}")


@router.get("/{session_id}/summary", response_model=SummaryResponse)
def get_summary(session_id: str, db: DBSession = Depends(get_db)):
    """Get session summary with performance metrics and suggestions."""
    try:
        service = SessionService(db)
        return service.get_summary(session_id)
    except LearnLikeMagicException as e:
        raise e.to_http_exception()
    except Exception as e:
        import traceback
        error_details = f"Error getting summary: {str(e)}\n{traceback.format_exc()}"
        print(error_details)
        raise HTTPException(status_code=500, detail=f"Error getting summary: {str(e)}")


@router.get("/{session_id}")
def get_session_state(session_id: str, db: DBSession = Depends(get_db)):
    """Get full session state (debug endpoint)."""
    from shared.repositories import SessionRepository

    repo = SessionRepository(db)
    session = repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return json.loads(session.state_json)
