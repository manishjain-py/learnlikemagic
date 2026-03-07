"""
Base Agent for Tutoring System

Abstract base class for all specialist agents. Uses the existing
LLMService from shared.services for LLM calls.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, Tuple, Type, Optional, Union
import json
import time
import asyncio
import logging

from pydantic import BaseModel

from shared.services.llm_service import LLMService
from tutor.exceptions import AgentError, AgentExecutionError, AgentTimeoutError
from tutor.utils.schema_utils import get_strict_schema, validate_agent_output


logger = logging.getLogger("tutor.agents")


class ResponseFieldExtractor:
    """Extracts the 'response' field value from streaming structured JSON.

    As JSON tokens arrive, detects the "response" key and streams its string
    value character-by-character (handling JSON escape sequences).
    """

    TRIGGER = '"response"'

    def __init__(self):
        self._scan_buffer = ""
        self._state = "scanning"  # scanning | found_key | in_value | done
        self._escape_next = False

    def feed(self, chunk: str) -> str:
        """Feed a JSON chunk. Returns any extracted response text."""
        if self._state == "done":
            return ""

        output = []
        for char in chunk:
            if self._state == "scanning":
                self._scan_buffer += char
                if len(self._scan_buffer) > 30:
                    self._scan_buffer = self._scan_buffer[-20:]
                if self._scan_buffer.endswith(self.TRIGGER):
                    self._state = "found_key"
                    self._scan_buffer = ""

            elif self._state == "found_key":
                self._scan_buffer += char
                stripped = self._scan_buffer.lstrip()
                if stripped.startswith(":"):
                    after_colon = stripped[1:].lstrip()
                    if after_colon.startswith('"'):
                        self._state = "in_value"
                        self._scan_buffer = ""

            elif self._state == "in_value":
                if self._escape_next:
                    _ESC = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "r": "\r", "/": "/"}
                    output.append(_ESC.get(char, char))
                    self._escape_next = False
                elif char == "\\":
                    self._escape_next = True
                elif char == '"':
                    self._state = "done"
                    break
                else:
                    output.append(char)

        return "".join(output)


class AgentContext(BaseModel):
    """Standard context passed to all agents."""

    session_id: str
    turn_id: str
    student_message: str
    current_step: int
    current_concept: Optional[str] = None
    student_grade: int = 5
    language_level: str = "simple"
    additional_context: Dict[str, Any] = {}


class BaseAgent(ABC):
    """
    Abstract base class for all specialist agents.

    Uses the existing LLMService (OpenAI GPT-5.2) for structured output.
    Provides logging, timeout handling, and output validation.
    """

    def __init__(
        self,
        llm_service: LLMService,
        timeout_seconds: int = 30,
        reasoning_effort: str = "none",
    ):
        self.llm = llm_service
        self.timeout_seconds = timeout_seconds
        self._reasoning_effort = reasoning_effort
        self._last_prompt: Optional[str] = None

    @property
    @abstractmethod
    def agent_name(self) -> str:
        ...

    @abstractmethod
    def get_output_model(self) -> Type[BaseModel]:
        ...

    @abstractmethod
    def build_prompt(self, context: AgentContext) -> str:
        ...

    @property
    def last_prompt(self) -> Optional[str]:
        return self._last_prompt

    async def execute(self, context: AgentContext) -> BaseModel:
        """Execute the agent and return validated output."""
        start_time = time.time()

        logger.info(json.dumps({
            "agent": self.agent_name,
            "event": "started",
            "turn_id": context.turn_id,
            "current_step": context.current_step,
        }))

        try:
            prompt = self.build_prompt(context)
            self._last_prompt = prompt

            output_model = self.get_output_model()
            schema = get_strict_schema(output_model)

            # Call LLM with strict schema — routes via provider/model from DB config
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.llm.call(
                    prompt=prompt,
                    reasoning_effort=self._reasoning_effort,
                    json_schema=schema,
                    schema_name=output_model.__name__,
                ),
            )

            # Parse output
            output_text = result.get("output_text", "{}")
            try:
                parsed = json.loads(output_text)
            except (json.JSONDecodeError, TypeError):
                parsed = {}

            validated = validate_agent_output(
                output=parsed,
                model=output_model,
                agent_name=self.agent_name,
            )

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(json.dumps({
                "agent": self.agent_name,
                "event": "completed",
                "turn_id": context.turn_id,
                "duration_ms": duration_ms,
            }))

            return validated

        except asyncio.TimeoutError:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.warning(json.dumps({
                "agent": self.agent_name,
                "event": "timeout",
                "turn_id": context.turn_id,
                "duration_ms": duration_ms,
            }))
            raise AgentTimeoutError(self.agent_name, self.timeout_seconds)

        except AgentError:
            raise

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(json.dumps({
                "agent": self.agent_name,
                "event": "failed",
                "turn_id": context.turn_id,
                "error": str(e),
                "duration_ms": duration_ms,
            }))
            raise AgentExecutionError(self.agent_name, str(e)) from e

    async def execute_stream(
        self, context: AgentContext
    ) -> AsyncGenerator[Tuple[str, Union[str, BaseModel]], None]:
        """Execute agent with streaming. Yields tuples:

        - ("token", str)       — text chunk from the response field
        - ("result", BaseModel) — final validated output (always last)
        """
        start_time = time.time()

        logger.info(json.dumps({
            "agent": self.agent_name,
            "event": "stream_started",
            "turn_id": context.turn_id,
        }))

        try:
            prompt = self.build_prompt(context)
            self._last_prompt = prompt

            output_model = self.get_output_model()
            schema = get_strict_schema(output_model)

            extractor = ResponseFieldExtractor()
            full_json_chunks: list[str] = []
            queue: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_event_loop()

            def _stream_in_thread():
                try:
                    for chunk in self.llm.call_stream(
                        prompt=prompt,
                        reasoning_effort=self._reasoning_effort,
                        json_schema=schema,
                        schema_name=output_model.__name__,
                    ):
                        full_json_chunks.append(chunk)
                        response_text = extractor.feed(chunk)
                        if response_text:
                            loop.call_soon_threadsafe(queue.put_nowait, ("token", response_text))
                    loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
                except Exception as e:
                    loop.call_soon_threadsafe(queue.put_nowait, ("error", e))

            # Fire streaming in background thread
            _future = loop.run_in_executor(None, _stream_in_thread)

            while True:
                msg_type, data = await queue.get()
                if msg_type == "token":
                    yield ("token", data)
                elif msg_type == "done":
                    break
                elif msg_type == "error":
                    raise AgentExecutionError(self.agent_name, str(data))

            # Parse the complete JSON
            complete_text = "".join(full_json_chunks)
            try:
                parsed = json.loads(complete_text)
            except (json.JSONDecodeError, TypeError):
                parsed = {}

            validated = validate_agent_output(
                output=parsed,
                model=output_model,
                agent_name=self.agent_name,
            )

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(json.dumps({
                "agent": self.agent_name,
                "event": "stream_completed",
                "turn_id": context.turn_id,
                "duration_ms": duration_ms,
            }))

            yield ("result", validated)

        except AgentError:
            raise
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(json.dumps({
                "agent": self.agent_name,
                "event": "stream_failed",
                "turn_id": context.turn_id,
                "error": str(e),
                "duration_ms": duration_ms,
            }))
            raise AgentExecutionError(self.agent_name, str(e)) from e

    def _summarize_output(self, output: BaseModel) -> Dict[str, Any]:
        return {
            "output_type": output.__class__.__name__,
            "fields": list(output.model_fields.keys()),
        }
