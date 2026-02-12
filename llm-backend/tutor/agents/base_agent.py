"""
Base Agent for Tutoring System

Abstract base class for all specialist agents. Uses the existing
LLMService from shared.services for LLM calls.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Type, Optional
import json
import time
import asyncio
import logging

from pydantic import BaseModel

from shared.services.llm_service import LLMService
from tutor.exceptions import AgentError, AgentExecutionError, AgentTimeoutError
from tutor.utils.schema_utils import get_strict_schema, validate_agent_output


logger = logging.getLogger("tutor.agents")


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

            # Use existing LLMService.call_gpt_5_2 with strict schema
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.llm.call_gpt_5_2(
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

    def _summarize_output(self, output: BaseModel) -> Dict[str, Any]:
        return {
            "output_type": output.__class__.__name__,
            "fields": list(output.model_fields.keys()),
        }
