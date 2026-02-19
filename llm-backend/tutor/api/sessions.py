"""Session management API endpoints — REST + WebSocket."""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel

from database import get_db
from shared.models import (
    CreateSessionRequest,
    CreateSessionResponse,
    StepRequest,
    StepResponse,
    SummaryResponse,
)
from tutor.services import SessionService
from tutor.models.agent_logs import get_agent_log_store
from tutor.models.session_state import SessionState
from tutor.models.messages import (
    ClientMessage,
    SessionStateDTO,
    create_assistant_response,
    create_error_response,
    create_state_update,
    create_typing_indicator,
)
from shared.utils.exceptions import LearnLikeMagicException
from shared.repositories import SessionRepository
from auth.middleware.auth_middleware import get_optional_user, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ──────────────────────────────────────────────
# REST Endpoints (existing contract preserved)
# ──────────────────────────────────────────────


def _check_session_ownership(session, current_user) -> None:
    """
    Verify that the caller owns the session.
    - If the session is linked to a user, the caller must be that user.
    - If the session is anonymous (user_id=None), allow access (backward compat).
    - If no auth token is provided (current_user=None) but the session IS user-linked, deny.
    """
    if session.user_id is None:
        return  # Anonymous session — allow
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required for this session")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your session")


@router.get("")
def list_sessions(
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List sessions for the current user."""
    repo = SessionRepository(db)
    sessions = repo.list_by_user(current_user.id)
    return {"sessions": sessions, "total": len(sessions)}


@router.get("/history")
def get_session_history(
    subject: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List current user's past sessions, paginated."""
    repo = SessionRepository(db)
    sessions = repo.list_by_user(
        user_id=current_user.id,
        subject=subject,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    total = repo.count_by_user(current_user.id, subject=subject)
    return {"sessions": sessions, "page": page, "page_size": page_size, "total": total}


@router.get("/stats")
def get_learning_stats(
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Aggregated learning stats for the current user."""
    repo = SessionRepository(db)
    return repo.get_user_stats(current_user.id)


@router.get("/{session_id}/replay")
def get_session_replay(
    session_id: str,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get full conversation replay for a session owned by the current user."""
    repo = SessionRepository(db)
    session = repo.get_by_id(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your session")

    return json.loads(session.state_json)


@router.post("", response_model=CreateSessionResponse)
def create_session(
    request: CreateSessionRequest,
    db: DBSession = Depends(get_db),
    current_user=Depends(get_optional_user),
):
    """Create a new learning session and get the first question."""
    try:
        service = SessionService(db)
        return service.create_new_session(request, user_id=current_user.id if current_user else None)
    except LearnLikeMagicException as e:
        raise e.to_http_exception()
    except Exception as e:
        import traceback
        logger.error(f"Error creating session: {e}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail={"message": f"Error creating session: {e}", "type": type(e).__name__},
        )


@router.post("/{session_id}/step", response_model=StepResponse)
def submit_step(
    session_id: str,
    request: StepRequest,
    db: DBSession = Depends(get_db),
    current_user=Depends(get_optional_user),
):
    """Submit a student answer and get the next turn."""
    try:
        repo = SessionRepository(db)
        session = repo.get_by_id(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        _check_session_ownership(session, current_user)

        service = SessionService(db)
        return service.process_step(session_id, request)
    except HTTPException:
        raise
    except LearnLikeMagicException as e:
        raise e.to_http_exception()
    except Exception as e:
        import traceback
        logger.error(f"Error processing step: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error processing step: {e}")


@router.get("/{session_id}/summary", response_model=SummaryResponse)
def get_summary(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user=Depends(get_optional_user),
):
    """Get session summary with performance metrics and suggestions."""
    try:
        repo = SessionRepository(db)
        session = repo.get_by_id(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        _check_session_ownership(session, current_user)

        service = SessionService(db)
        return service.get_summary(session_id)
    except HTTPException:
        raise
    except LearnLikeMagicException as e:
        raise e.to_http_exception()
    except Exception as e:
        import traceback
        logger.error(f"Error getting summary: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error getting summary: {e}")


@router.get("/{session_id}")
def get_session_state(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user=Depends(get_optional_user),
):
    """Get full session state (debug endpoint). Requires ownership for user-linked sessions."""
    repo = SessionRepository(db)
    session = repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _check_session_ownership(session, current_user)
    return json.loads(session.state_json)


# ──────────────────────────────────────────────
# Agent Logs Endpoint
# ──────────────────────────────────────────────


class AgentLogEntryDTO(BaseModel):
    timestamp: str
    turn_id: str
    agent_name: str
    event_type: str
    input_summary: Optional[str] = None
    output: Optional[dict] = None
    reasoning: Optional[str] = None
    duration_ms: Optional[int] = None
    prompt: Optional[str] = None
    model: Optional[str] = None


class AgentLogsResponse(BaseModel):
    session_id: str
    turn_id: Optional[str] = None
    logs: list[AgentLogEntryDTO]
    total_count: int


@router.get("/{session_id}/agent-logs", response_model=AgentLogsResponse)
def get_agent_logs(
    session_id: str,
    turn_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    limit: int = 100,
    db: DBSession = Depends(get_db),
):
    """Get agent execution logs for a session."""
    # Validate session exists
    repo = SessionRepository(db)
    session = repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    log_store = get_agent_log_store()

    if turn_id or agent_name:
        logs = log_store.get_logs(session_id, turn_id=turn_id, agent_name=agent_name)
    else:
        logs = log_store.get_recent_logs(session_id, limit=limit)

    log_dtos = [
        AgentLogEntryDTO(
            timestamp=log.timestamp.isoformat(),
            turn_id=log.turn_id,
            agent_name=log.agent_name,
            event_type=log.event_type,
            input_summary=log.input_summary,
            output=log.output,
            reasoning=log.reasoning,
            duration_ms=log.duration_ms,
            prompt=log.prompt,
            model=log.model,
        )
        for log in logs
    ]

    return AgentLogsResponse(
        session_id=session_id,
        turn_id=turn_id,
        logs=log_dtos,
        total_count=len(log_dtos),
    )


# ──────────────────────────────────────────────
# WebSocket Endpoint
# ──────────────────────────────────────────────


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time chat with the tutor."""
    await websocket.accept()
    logger.info(f"WebSocket connected: {session_id}")

    # We need a fresh DB session for the WebSocket lifecycle
    from database import get_db_manager

    db_manager = get_db_manager()
    db = db_manager.session_factory()

    try:
        repo = SessionRepository(db)
        db_session = repo.get_by_id(session_id)
        if not db_session:
            await websocket.send_json(create_error_response("Session not found").model_dump())
            await websocket.close()
            return

        session = SessionState.model_validate_json(db_session.state_json)

        # Build orchestrator
        from config import get_settings
        from shared.services.llm_service import LLMService
        from tutor.orchestration import TeacherOrchestrator

        settings = get_settings()
        llm_service = LLMService(
            api_key=settings.openai_api_key,
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
            provider=settings.resolved_tutor_provider,
        )
        orchestrator = TeacherOrchestrator(llm_service)

        # Send initial state
        state_dto = SessionStateDTO(
            session_id=session.session_id,
            current_step=session.current_step,
            total_steps=session.topic.study_plan.total_steps if session.topic else 0,
            current_concept=session.current_step_data.concept if session.current_step_data else None,
            progress_percentage=session.progress_percentage,
            mastery_estimates=session.mastery_estimates,
            is_complete=session.is_complete,
        )
        await websocket.send_json(create_state_update(state_dto).model_dump())

        # Send welcome if first turn
        if session.turn_count == 0:
            welcome = await orchestrator.generate_welcome_message(session)
            from tutor.models.messages import create_teacher_message

            session.add_message(create_teacher_message(welcome))
            _save_session_to_db(db, session_id, session)
            await websocket.send_json(create_assistant_response(welcome).model_dump())

        # Main message loop
        while True:
            data = await websocket.receive_json()
            logger.info(f"WS message received: {session_id} type={data.get('type')}")

            try:
                client_msg = ClientMessage.model_validate(data)
            except Exception as e:
                await websocket.send_json(
                    create_error_response(f"Invalid message format: {e}").model_dump()
                )
                continue

            if client_msg.type == "chat":
                await websocket.send_json(create_typing_indicator().model_dump())

                result = await orchestrator.process_turn(
                    session=session,
                    student_message=client_msg.payload.message or "",
                )

                _save_session_to_db(db, session_id, session)

                await websocket.send_json(
                    create_assistant_response(result.response).model_dump()
                )

                state_dto = SessionStateDTO(
                    session_id=session.session_id,
                    current_step=session.current_step,
                    total_steps=session.topic.study_plan.total_steps if session.topic else 0,
                    current_concept=session.current_step_data.concept if session.current_step_data else None,
                    progress_percentage=session.progress_percentage,
                    mastery_estimates=session.mastery_estimates,
                    is_complete=session.is_complete,
                )
                await websocket.send_json(create_state_update(state_dto).model_dump())

            elif client_msg.type == "get_state":
                state_dto = SessionStateDTO(
                    session_id=session.session_id,
                    current_step=session.current_step,
                    total_steps=session.topic.study_plan.total_steps if session.topic else 0,
                    current_concept=session.current_step_data.concept if session.current_step_data else None,
                    progress_percentage=session.progress_percentage,
                    mastery_estimates=session.mastery_estimates,
                    is_complete=session.is_complete,
                )
                await websocket.send_json(create_state_update(state_dto).model_dump())

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json(create_error_response(f"Server error: {e}").model_dump())
        except Exception:
            pass
    finally:
        db.close()


def _save_session_to_db(db: DBSession, session_id: str, session: SessionState) -> None:
    """Persist session state to DB."""
    from shared.models.entities import Session as SessionModel
    from datetime import datetime

    db_record = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if db_record:
        db_record.state_json = session.model_dump_json()
        db_record.mastery = session.overall_mastery
        db_record.step_idx = session.current_step
        db_record.updated_at = datetime.utcnow()
        db.commit()
