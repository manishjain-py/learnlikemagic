"""
Logs API Endpoints (Deprecated)

These endpoints are deprecated as logging has moved to stdout.
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, PlainTextResponse
from typing import Optional, Literal, List

from models.logs import (
    SessionLogsResponse,
    SessionLogsSummary,
    AllSessionsLogsResponse,
)

router = APIRouter(prefix="/sessions", tags=["logs"])


@router.get("/logs", response_model=AllSessionsLogsResponse)
async def list_all_session_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: Literal["newest", "oldest", "most_active"] = Query("newest"),
):
    """Deprecated: Returns empty list."""
    return AllSessionsLogsResponse(total_sessions=0, sessions=[])


@router.get("/{session_id}/logs", response_model=SessionLogsResponse)
async def get_session_logs(
    session_id: str,
    agent: Optional[Literal["planner", "executor", "evaluator", "router"]] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Deprecated: Returns empty logs."""
    return SessionLogsResponse(session_id=session_id, total_entries=0, logs=[])


@router.get("/{session_id}/logs/text", response_class=PlainTextResponse)
async def get_session_logs_text(
    session_id: str,
    download: bool = Query(False),
):
    """Deprecated: Returns message about deprecation."""
    return PlainTextResponse("Logs are now streamed to stdout. File-based logs are deprecated.")


@router.get("/{session_id}/logs/summary", response_model=SessionLogsSummary)
async def get_session_logs_summary(session_id: str):
    """Deprecated: Returns empty summary."""
    # Return a dummy summary to avoid breaking clients immediately
    return SessionLogsSummary(
        session_id=session_id,
        total_entries=0,
        agents_called={},
        first_execution=None,
        last_execution=None,
        total_duration_ms=0,
        average_duration_ms=0,
    )


@router.get("/{session_id}/logs/stream")
async def stream_session_logs(
    session_id: str,
    follow: bool = Query(False),
):
    """Deprecated: Returns stream closed event."""
    async def event_generator():
        yield "event: close\ndata: Logs are now streamed to stdout\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
