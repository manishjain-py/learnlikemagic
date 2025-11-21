"""
Logs API Endpoints

Provides comprehensive access to agent execution logs via REST API.

Features:
- List all sessions with log metadata
- Get full logs for a session (JSON or text)
- Filter logs by agent type
- Pagination support
- Real-time streaming (Server-Sent Events)
- Log statistics and summaries
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, PlainTextResponse
from typing import Optional, Literal
from pathlib import Path
import json
import asyncio
import time

from models.logs import (
    SessionLogsResponse,
    FilteredLogsResponse,
    SessionLogsSummary,
    AllSessionsLogsResponse,
    TextLogsResponse,
    AgentLogEntry,
)
from services.agent_logging_service import AgentLoggingService

router = APIRouter(prefix="/sessions", tags=["logs"])

# Initialize logging service
logging_service = AgentLoggingService(log_base_dir="logs/sessions")


@router.get("/logs", response_model=AllSessionsLogsResponse)
async def list_all_session_logs(
    limit: int = Query(100, ge=1, le=1000, description="Maximum sessions to return"),
    offset: int = Query(0, ge=0, description="Number of sessions to skip"),
    sort_by: Literal["newest", "oldest", "most_active"] = Query(
        "newest", description="Sort order"
    ),
):
    """
    List all sessions with log metadata.

    Returns summary information for all sessions that have logs,
    including execution counts, timestamps, and performance metrics.

    Query Parameters:
    - **limit**: Maximum number of sessions to return (1-1000, default: 100)
    - **offset**: Number of sessions to skip for pagination (default: 0)
    - **sort_by**: Sort order (newest|oldest|most_active, default: newest)

    Example:
    ```bash
    curl http://localhost:8000/sessions/logs?limit=10&sort_by=newest
    ```
    """
    log_base_path = Path("logs/sessions")

    if not log_base_path.exists():
        return AllSessionsLogsResponse(total_sessions=0, sessions=[])

    # Get all session directories
    session_dirs = [
        d for d in log_base_path.iterdir() if d.is_dir() and (d / "agent_steps.jsonl").exists()
    ]

    # Build summaries
    summaries = []
    for session_dir in session_dirs:
        try:
            summary = _get_session_summary(session_dir.name)
            if summary:
                summaries.append(summary)
        except Exception as e:
            # Skip sessions with corrupted logs
            continue

    # Sort
    if sort_by == "newest":
        summaries.sort(
            key=lambda s: s.last_execution or s.first_execution or "", reverse=True
        )
    elif sort_by == "oldest":
        summaries.sort(key=lambda s: s.first_execution or s.last_execution or "")
    elif sort_by == "most_active":
        summaries.sort(key=lambda s: s.total_entries, reverse=True)

    # Paginate
    total = len(summaries)
    summaries = summaries[offset : offset + limit]

    return AllSessionsLogsResponse(total_sessions=total, sessions=summaries)


@router.get("/{session_id}/logs", response_model=SessionLogsResponse)
async def get_session_logs(
    session_id: str,
    agent: Optional[Literal["planner", "executor", "evaluator", "router"]] = Query(
        None, description="Filter by agent type"
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum entries to return"),
    offset: int = Query(0, ge=0, description="Number of entries to skip"),
):
    """
    Get all logs for a specific session in JSON format.

    Returns complete agent execution logs with structured data,
    including inputs, outputs, reasoning, and performance metrics.

    Path Parameters:
    - **session_id**: Unique session identifier

    Query Parameters:
    - **agent**: Filter by agent type (planner|executor|evaluator|router)
    - **limit**: Maximum number of log entries (1-1000, default: 100)
    - **offset**: Number of entries to skip (default: 0)

    Example:
    ```bash
    # Get all logs
    curl http://localhost:8000/sessions/{session_id}/logs

    # Filter by agent type
    curl http://localhost:8000/sessions/{session_id}/logs?agent=evaluator

    # Pagination
    curl http://localhost:8000/sessions/{session_id}/logs?limit=10&offset=20
    ```
    """
    try:
        logs = logging_service.get_session_logs(session_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error reading logs: {str(e)}"
        )

    if not logs:
        # Check if session exists
        session_dir = Path("logs/sessions") / session_id
        if not session_dir.exists():
            raise HTTPException(
                status_code=404, detail=f"No logs found for session: {session_id}"
            )
        return SessionLogsResponse(session_id=session_id, total_entries=0, logs=[])

    # Filter by agent if requested
    if agent:
        logs = [log for log in logs if log.get("agent") == agent]

    # Paginate
    total = len(logs)
    logs = logs[offset : offset + limit]

    # Convert to Pydantic models
    log_entries = [AgentLogEntry(**log) for log in logs]

    return SessionLogsResponse(
        session_id=session_id, total_entries=total, logs=log_entries
    )


@router.get("/{session_id}/logs/text", response_class=PlainTextResponse)
async def get_session_logs_text(
    session_id: str,
    download: bool = Query(False, description="Download as file attachment"),
):
    """
    Get human-readable text logs for a session.

    Returns the complete agent_steps.txt file with formatted,
    human-readable log entries.

    Path Parameters:
    - **session_id**: Unique session identifier

    Query Parameters:
    - **download**: If true, returns as downloadable file (default: false)

    Example:
    ```bash
    # View in browser/terminal
    curl http://localhost:8000/sessions/{session_id}/logs/text

    # Download as file
    curl -O http://localhost:8000/sessions/{session_id}/logs/text?download=true
    ```
    """
    try:
        content = logging_service.get_session_txt_logs(session_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error reading text logs: {str(e)}"
        )

    if not content:
        session_dir = Path("logs/sessions") / session_id
        if not session_dir.exists():
            raise HTTPException(
                status_code=404, detail=f"No logs found for session: {session_id}"
            )
        return PlainTextResponse(
            f"No log entries found for session: {session_id}", status_code=200
        )

    if download:
        return PlainTextResponse(
            content,
            headers={
                "Content-Disposition": f"attachment; filename=session_{session_id}_logs.txt"
            },
        )

    return PlainTextResponse(content)


@router.get("/{session_id}/logs/summary", response_model=SessionLogsSummary)
async def get_session_logs_summary(session_id: str):
    """
    Get summary statistics for a session's logs.

    Returns aggregated metrics including execution counts per agent,
    timestamps, and performance statistics.

    Path Parameters:
    - **session_id**: Unique session identifier

    Example:
    ```bash
    curl http://localhost:8000/sessions/{session_id}/logs/summary
    ```

    Response includes:
    - Total number of log entries
    - Count of executions per agent type
    - First and last execution timestamps
    - Total and average execution duration
    """
    summary = _get_session_summary(session_id)

    if not summary:
        raise HTTPException(
            status_code=404, detail=f"No logs found for session: {session_id}"
        )

    return summary


@router.get("/{session_id}/logs/stream")
async def stream_session_logs(
    session_id: str,
    follow: bool = Query(
        False, description="Keep connection open and stream new logs as they arrive"
    ),
):
    """
    Stream session logs using Server-Sent Events (SSE).

    Provides real-time log streaming for monitoring active sessions.

    Path Parameters:
    - **session_id**: Unique session identifier

    Query Parameters:
    - **follow**: Keep connection open for new logs (default: false)

    Example:
    ```bash
    # Stream existing logs
    curl -N http://localhost:8000/sessions/{session_id}/logs/stream

    # Follow mode (wait for new logs)
    curl -N http://localhost:8000/sessions/{session_id}/logs/stream?follow=true
    ```

    **JavaScript Client Example:**
    ```javascript
    const eventSource = new EventSource(
        `http://localhost:8000/sessions/${sessionId}/logs/stream?follow=true`
    );

    eventSource.onmessage = (event) => {
        const log = JSON.parse(event.data);
        console.log(`${log.agent}: ${log.input_summary}`);
    };
    ```
    """

    async def event_generator():
        """Generate Server-Sent Events for log streaming."""
        jsonl_path = Path("logs/sessions") / session_id / "agent_steps.jsonl"

        if not jsonl_path.exists():
            yield f"event: error\ndata: Session not found: {session_id}\n\n"
            return

        # Send existing logs
        with open(jsonl_path, "r") as f:
            for line in f:
                if line.strip():
                    yield f"data: {line}\n\n"

        if follow:
            # Keep connection open and watch for new logs
            last_size = jsonl_path.stat().st_size
            retry_count = 0
            max_retries = 300  # 5 minutes with 1-second intervals

            while retry_count < max_retries:
                await asyncio.sleep(1)  # Check every second

                if not jsonl_path.exists():
                    yield f"event: error\ndata: Log file removed\n\n"
                    break

                current_size = jsonl_path.stat().st_size

                if current_size > last_size:
                    # New data available
                    with open(jsonl_path, "r") as f:
                        f.seek(last_size)
                        for line in f:
                            if line.strip():
                                yield f"data: {line}\n\n"
                    last_size = current_size
                    retry_count = 0  # Reset retry count on activity
                else:
                    retry_count += 1

            # Timeout or max retries reached
            yield f"event: close\ndata: Stream timeout\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# Helper Functions


def _get_session_summary(session_id: str) -> Optional[SessionLogsSummary]:
    """Get summary statistics for a session's logs."""
    try:
        logs = logging_service.get_session_logs(session_id)
    except Exception:
        return None

    if not logs:
        return None

    # Count agents
    agents_called = {}
    for log in logs:
        agent = log.get("agent", "unknown")
        agents_called[agent] = agents_called.get(agent, 0) + 1

    # Get timestamps
    first_execution = logs[0].get("timestamp") if logs else None
    last_execution = logs[-1].get("timestamp") if logs else None

    # Calculate durations
    total_duration = sum(
        log.get("duration_ms", 0) for log in logs if log.get("duration_ms")
    )
    durations = [log.get("duration_ms") for log in logs if log.get("duration_ms")]
    average_duration = sum(durations) // len(durations) if durations else None

    return SessionLogsSummary(
        session_id=session_id,
        total_entries=len(logs),
        agents_called=agents_called,
        first_execution=first_execution,
        last_execution=last_execution,
        total_duration_ms=total_duration if total_duration > 0 else None,
        average_duration_ms=average_duration,
    )
