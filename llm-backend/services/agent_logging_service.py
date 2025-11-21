"""
Agent Logging Service

This service provides structured logging for agent executions with:
- Dual format: machine-readable (JSONL) and human-readable (TXT)
- Session-based organization
- Full observability (input, output, reasoning, duration)
- Type-safe log entries

Design Principles:
- Single Responsibility: Only handles agent logging
- Separation of Concerns: Logging separate from business logic
- Observability First: Every execution captured
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Literal, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class AgentLoggingService:
    """
    Service for logging agent executions in dual format.

    Features:
    - JSONL format for machine processing
    - TXT format for human reading
    - Session-based directory structure
    - Automatic directory creation
    - Type-safe log entries
    """

    def __init__(self, log_base_dir: str = "logs/sessions"):
        """
        Initialize logging service.

        Args:
            log_base_dir: Base directory for session logs
        """
        self.log_base_dir = Path(log_base_dir)
        self.log_base_dir.mkdir(parents=True, exist_ok=True)

    def log_agent_execution(
        self,
        session_id: str,
        agent: Literal["planner", "executor", "evaluator"],
        input_summary: str,
        output: Dict[str, Any],
        reasoning: str,
        duration_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Log an agent execution.

        Args:
            session_id: Session identifier
            agent: Which agent executed
            input_summary: Brief summary of input
            output: Full output dictionary
            reasoning: Agent's internal reasoning
            duration_ms: Execution duration in milliseconds

        Returns:
            Log entry dictionary
        """
        # Create log entry
        log_entry = {
            "agent": agent,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "input_summary": input_summary,
            "output": output,
            "reasoning": reasoning,
            "duration_ms": duration_ms,
        }

        # Get session log directory
        session_dir = self._get_session_dir(session_id)

        # Write to JSONL
        self._write_jsonl(session_dir, log_entry)

        # Write to TXT
        self._write_txt(session_dir, log_entry)

        logger.info(
            f"Logged {agent} execution for session {session_id[:8]}... "
            f"(duration: {duration_ms}ms)"
        )

        return log_entry

    def _get_session_dir(self, session_id: str) -> Path:
        """Get or create session log directory"""
        session_dir = self.log_base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def _write_jsonl(self, session_dir: Path, log_entry: Dict[str, Any]):
        """
        Write log entry to JSONL file.

        Format: One JSON object per line
        """
        jsonl_path = session_dir / "agent_steps.jsonl"

        try:
            with open(jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            logger.error(f"Failed to write JSONL log: {e}")

    def _write_txt(self, session_dir: Path, log_entry: Dict[str, Any]):
        """
        Write log entry to human-readable TXT file.

        Format: Structured text with clear sections
        """
        txt_path = session_dir / "agent_steps.txt"

        try:
            with open(txt_path, "a", encoding="utf-8") as f:
                f.write("=" * 80 + "\n")
                f.write(f"AGENT: {log_entry['agent'].upper()}\n")
                f.write(f"TIMESTAMP: {log_entry['timestamp']}\n")
                if log_entry.get("duration_ms"):
                    f.write(f"DURATION: {log_entry['duration_ms']}ms\n")
                f.write("-" * 80 + "\n\n")

                f.write(f"INPUT SUMMARY:\n{log_entry['input_summary']}\n\n")

                f.write(f"OUTPUT:\n")
                f.write(json.dumps(log_entry['output'], indent=2, ensure_ascii=False))
                f.write("\n\n")

                f.write(f"REASONING:\n{log_entry['reasoning']}\n\n")

                f.write("=" * 80 + "\n\n")
        except Exception as e:
            logger.error(f"Failed to write TXT log: {e}")

    def get_session_logs(self, session_id: str) -> list[Dict[str, Any]]:
        """
        Retrieve all logs for a session.

        Args:
            session_id: Session identifier

        Returns:
            List of log entries
        """
        session_dir = self._get_session_dir(session_id)
        jsonl_path = session_dir / "agent_steps.jsonl"

        if not jsonl_path.exists():
            return []

        logs = []
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        logs.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to read session logs: {e}")

        return logs

    def get_session_txt_logs(self, session_id: str) -> str:
        """
        Retrieve human-readable logs for a session.

        Args:
            session_id: Session identifier

        Returns:
            TXT log content
        """
        session_dir = self._get_session_dir(session_id)
        txt_path = session_dir / "agent_steps.txt"

        if not txt_path.exists():
            return ""

        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read TXT logs: {e}")
            return ""
