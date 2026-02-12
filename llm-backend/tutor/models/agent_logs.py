"""
Agent Logging Models

In-memory storage for capturing detailed agent execution logs.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
import threading


class AgentLogEntry(BaseModel):
    """Single agent execution log entry."""

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    session_id: str
    turn_id: str
    agent_name: str
    event_type: str
    input_summary: Optional[str] = None
    output: Optional[Dict[str, Any]] = None
    reasoning: Optional[str] = None
    duration_ms: Optional[int] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentLogStore:
    """In-memory storage for agent logs, thread-safe."""

    def __init__(self, max_logs_per_session: int = 200):
        self._logs: Dict[str, List[AgentLogEntry]] = {}
        self._lock = threading.Lock()
        self._max_logs = max_logs_per_session

    def add_log(self, entry: AgentLogEntry) -> None:
        with self._lock:
            session_id = entry.session_id
            if session_id not in self._logs:
                self._logs[session_id] = []
            self._logs[session_id].append(entry)
            if len(self._logs[session_id]) > self._max_logs:
                self._logs[session_id] = self._logs[session_id][-self._max_logs:]

    def get_logs(
        self,
        session_id: str,
        turn_id: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> List[AgentLogEntry]:
        with self._lock:
            logs = self._logs.get(session_id, [])
            if turn_id:
                logs = [log for log in logs if log.turn_id == turn_id]
            if agent_name:
                logs = [log for log in logs if log.agent_name == agent_name]
            return logs

    def get_recent_logs(self, session_id: str, limit: int = 50) -> List[AgentLogEntry]:
        with self._lock:
            logs = self._logs.get(session_id, [])
            return logs[-limit:] if logs else []

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._logs:
                del self._logs[session_id]

    def get_stats(self) -> Dict[str, int]:
        with self._lock:
            total_logs = sum(len(logs) for logs in self._logs.values())
            return {
                "session_count": len(self._logs),
                "total_logs": total_logs,
                "max_logs_per_session": self._max_logs,
            }


_agent_log_store: Optional[AgentLogStore] = None


def get_agent_log_store() -> AgentLogStore:
    global _agent_log_store
    if _agent_log_store is None:
        _agent_log_store = AgentLogStore()
    return _agent_log_store
