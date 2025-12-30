"""
Pydantic models for Logs API endpoints.

These models define the request/response schemas for accessing
agent execution logs via the REST API.
"""

from typing import Optional, List, Literal, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class AgentLogEntry(BaseModel):
    """Single agent execution log entry."""

    agent: Literal["planner", "executor", "evaluator", "router"]
    timestamp: str = Field(description="ISO 8601 timestamp")
    input_summary: str = Field(description="Brief summary of what the agent was asked to do")
    output: Dict[str, Any] = Field(description="Agent output (structured data)")
    reasoning: str = Field(description="Agent's internal reasoning/thinking")
    duration_ms: Optional[int] = Field(None, description="Execution duration in milliseconds")

    class Config:
        json_schema_extra = {
            "example": {
                "agent": "planner",
                "timestamp": "2025-11-20T07:56:14.186801Z",
                "input_summary": "Initial planning for Fractions - Comparing Fractions",
                "output": {
                    "todo_list": [{"step_id": "step_1", "title": "Quick fraction warm-up"}]
                },
                "reasoning": "This plan is designed for a quick 15-minute session...",
                "duration_ms": 993408,
            }
        }


class SessionLogsResponse(BaseModel):
    """Complete logs for a session."""

    session_id: str
    total_entries: int = Field(description="Total number of log entries")
    logs: List[AgentLogEntry] = Field(description="Chronological list of agent executions")

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "a3e05a75-8937-4d6d-acf0-3a5d1d90ac22",
                "total_entries": 3,
                "logs": [
                    {
                        "agent": "planner",
                        "timestamp": "2025-11-20T07:56:14Z",
                        "input_summary": "Initial planning",
                        "output": {},
                        "reasoning": "...",
                        "duration_ms": 993408,
                    }
                ],
            }
        }


class FilteredLogsResponse(BaseModel):
    """Filtered logs with pagination."""

    session_id: str
    filter_agent: Optional[str] = Field(None, description="Agent filter applied")
    total_entries: int = Field(description="Total entries matching filter")
    returned_entries: int = Field(description="Number of entries in this response")
    offset: int = Field(description="Starting offset")
    limit: int = Field(description="Maximum entries returned")
    logs: List[AgentLogEntry]


class SessionLogsSummary(BaseModel):
    """Summary of logs for a session."""

    session_id: str
    total_entries: int
    agents_called: Dict[str, int] = Field(
        description="Count of executions per agent type"
    )
    first_execution: Optional[str] = Field(None, description="Timestamp of first log")
    last_execution: Optional[str] = Field(None, description="Timestamp of last log")
    total_duration_ms: Optional[int] = Field(
        None, description="Total execution time across all agents"
    )
    average_duration_ms: Optional[int] = Field(
        None, description="Average execution time per agent"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "a3e05a75-8937-4d6d-acf0-3a5d1d90ac22",
                "total_entries": 5,
                "agents_called": {"planner": 1, "executor": 2, "evaluator": 2},
                "first_execution": "2025-11-20T07:56:14Z",
                "last_execution": "2025-11-20T08:10:30Z",
                "total_duration_ms": 1500000,
                "average_duration_ms": 300000,
            }
        }


class AllSessionsLogsResponse(BaseModel):
    """List of all sessions with log metadata."""

    total_sessions: int
    sessions: List[SessionLogsSummary]

    class Config:
        json_schema_extra = {
            "example": {
                "total_sessions": 3,
                "sessions": [
                    {
                        "session_id": "session-1",
                        "total_entries": 5,
                        "agents_called": {"planner": 1, "executor": 2, "evaluator": 2},
                        "first_execution": "2025-11-20T07:56:14Z",
                        "last_execution": "2025-11-20T08:10:30Z",
                        "total_duration_ms": 1500000,
                        "average_duration_ms": 300000,
                    }
                ],
            }
        }


class TextLogsResponse(BaseModel):
    """Human-readable text logs."""

    session_id: str
    content: str = Field(description="Full text log content")
    total_lines: int = Field(description="Number of lines in the log")

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "a3e05a75-8937-4d6d-acf0-3a5d1d90ac22",
                "content": "================\nAGENT: PLANNER\n...",
                "total_lines": 150,
            }
        }
