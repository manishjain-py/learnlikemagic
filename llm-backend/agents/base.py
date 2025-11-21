"""
Base Agent Abstract Class

This module provides the abstract base class for all agents in the tutor workflow.
It implements common functionality:
- Prompt loading and rendering
- Execution timing
- Logging integration
- Error handling

Design Principles:
- Template Method Pattern: Define skeleton, subclasses implement specifics
- Dependency Injection: Receive services via constructor
- Single Responsibility: Each agent does one thing
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import time
import logging
from workflows.state import SimplifiedState
from services.llm_service import LLMService
from services.agent_logging_service import AgentLoggingService
from agents.prompts import PromptLoader

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base class for all agents.

    Provides:
    - Prompt loading and rendering
    - Execution timing
    - Logging integration
    - Common error handling

    Subclasses must implement:
    - agent_name: Name of the agent
    - execute_internal: Core agent logic
    """

    def __init__(
        self,
        llm_service: LLMService,
        logging_service: AgentLoggingService,
        prompt_loader: Optional[PromptLoader] = None,
    ):
        """
        Initialize base agent.

        Args:
            llm_service: Service for LLM API calls
            logging_service: Service for agent logging
            prompt_loader: Prompt template loader (uses default if None)
        """
        self.llm_service = llm_service
        self.logging_service = logging_service
        self.prompt_loader = prompt_loader or PromptLoader()

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Name of the agent (e.g., 'planner', 'executor', 'evaluator')"""
        pass

    def execute(self, state: SimplifiedState) -> SimplifiedState:
        """
        Execute the agent with timing and logging.

        This is the public interface. It:
        1. Starts timing
        2. Calls execute_internal (implemented by subclass)
        3. Logs execution
        4. Returns updated state

        Args:
            state: Current workflow state

        Returns:
            Updated workflow state

        Raises:
            Exception: If agent execution fails
        """
        start_time = time.time()

        try:
            logger.info(f"Executing {self.agent_name} agent...")

            # Call subclass implementation
            updated_state, output, reasoning, input_summary = self.execute_internal(state)

            # Calculate duration
            duration_ms = int((time.time() - start_time) * 1000)

            # Log execution
            log_entry = self.logging_service.log_agent_execution(
                session_id=state["session_id"],
                agent=self.agent_name,
                input_summary=input_summary,
                output=output,
                reasoning=reasoning,
                duration_ms=duration_ms,
            )

            # Add log entry to state
            updated_state = self._append_log(updated_state, log_entry)

            logger.info(
                f"{self.agent_name} agent completed in {duration_ms}ms"
            )

            return updated_state

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                f"{self.agent_name} agent failed after {duration_ms}ms: {str(e)}"
            )
            raise

    @abstractmethod
    def execute_internal(
        self, state: SimplifiedState
    ) -> tuple[SimplifiedState, Dict[str, Any], str, str]:
        """
        Core agent logic to be implemented by subclasses.

        Args:
            state: Current workflow state

        Returns:
            Tuple of:
                - updated_state: Modified state
                - output: Agent output (for logging)
                - reasoning: Agent reasoning (for logging)
                - input_summary: Brief input summary (for logging)

        Raises:
            Exception: If execution fails
        """
        pass

    def _load_prompt(self, template_name: str) -> str:
        """
        Load a prompt template.

        Args:
            template_name: Name of template file (without .txt)

        Returns:
            Template string

        Raises:
            FileNotFoundError: If template doesn't exist
        """
        return self.prompt_loader.load(template_name)

    def _render_prompt(self, template_name: str, variables: Dict[str, Any]) -> str:
        """
        Load and render a prompt template with variables.

        Args:
            template_name: Name of template file
            variables: Variables to substitute

        Returns:
            Rendered prompt string

        Raises:
            FileNotFoundError: If template doesn't exist
            KeyError: If required variable is missing
        """
        return self.prompt_loader.render(template_name, variables)

    def _append_log(
        self, state: SimplifiedState, log_entry: Dict[str, Any]
    ) -> SimplifiedState:
        """
        Append log entry to state.

        Args:
            state: Current state
            log_entry: Log entry to append

        Returns:
            Updated state
        """
        return {
            **state,
            "agent_logs": state["agent_logs"] + [log_entry],
        }

    def _update_timestamp(self, state: SimplifiedState) -> SimplifiedState:
        """
        Update last_updated_at timestamp in state.

        Args:
            state: Current state

        Returns:
            Updated state
        """
        from workflows.helpers import get_timestamp

        return {
            **state,
            "last_updated_at": get_timestamp(),
        }
