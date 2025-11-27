"""
Workflow Adapter for SessionService integration.

This adapter wraps the new TutorWorkflow to work with the existing
SessionService API without breaking changes.
"""

from typing import Tuple
from sqlalchemy.orm import Session as DBSession

from models import TutorState
from workflows.tutor_workflow import TutorWorkflow
from services.llm_service import LLMService
from services.agent_logging_service import AgentLoggingService
from adapters.state_adapter import StateAdapter
from repositories import TeachingGuidelineRepository


class SessionWorkflowAdapter:
    """
    Adapter that makes TutorWorkflow compatible with SessionService.

    This allows SessionService to use the new workflow system while
    maintaining the existing API contract.
    """

    def __init__(self, db: DBSession):
        """
        Initialize the workflow adapter.

        Args:
            db: Database session
        """
        self.db = db
        self.guideline_repo = TeachingGuidelineRepository(db)

        # Initialize new workflow services
        from config import get_settings
        settings = get_settings()
        
        api_key = settings.openai_api_key
        gemini_key = settings.gemini_api_key
        
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        self.llm_service = LLMService(api_key=api_key, gemini_api_key=gemini_key, max_retries=3)
        self.logging_service = AgentLoggingService(log_base_dir="logs/sessions")

        # Create PostgreSQL connection for LangGraph checkpointing
        from psycopg import connect
        from psycopg.rows import dict_row
        from config import get_settings

        settings = get_settings()
        db_conn = connect(
            str(settings.database_url),
            autocommit=True,
            row_factory=dict_row
        )

        self.workflow = TutorWorkflow(
            self.llm_service,
            self.logging_service,
            db_connection=db_conn
        )

        self.state_adapter = StateAdapter()

    def execute_present_node(
        self,
        tutor_state: TutorState,
        teaching_guideline: str
    ) -> TutorState:
        """
        Execute present node to generate teaching message.

        This is called for initial session creation.

        Args:
            tutor_state: Current tutor state
            teaching_guideline: Full guideline text (pre-loaded)

        Returns:
            Updated tutor state with new message in history
        """
        # Convert to simplified state
        simplified_state = self.state_adapter.tutor_state_to_simplified(
            tutor_state,
            teaching_guideline
        )

        # Use TutorWorkflow to start the session
        result = self.workflow.start_session(
            session_id=tutor_state.session_id,
            guidelines=teaching_guideline,
            student_profile=simplified_state["student_profile"],
            topic_info=simplified_state["topic_info"],
            session_context=simplified_state["session_context"]
        )

        # Get the updated state from checkpoint
        final_state = self.workflow.get_session_state(tutor_state.session_id)

        # Convert back to tutor state
        updated_tutor_state = self.state_adapter.simplified_to_tutor_state(
            final_state,
            tutor_state
        )

        return updated_tutor_state

    def execute_step_workflow(
        self,
        tutor_state: TutorState,
        student_reply: str
    ) -> Tuple[TutorState, str]:
        """
        Execute full step workflow: evaluate → route → present.

        This is the core tutoring loop replacement.

        Args:
            tutor_state: Current tutor state with student reply in history
            student_reply: The student's answer

        Returns:
            Tuple of (updated_tutor_state, routing_decision)
            routing_decision is "advance" or "remediate" (mapped from new workflow)
        """
        # Use TutorWorkflow to submit the response
        result = self.workflow.submit_response(
            tutor_state.session_id,
            student_reply
        )

        # Get the updated state from checkpoint
        final_state = self.workflow.get_session_state(tutor_state.session_id)

        # Convert back to tutor state
        updated_tutor_state = self.state_adapter.simplified_to_tutor_state(
            final_state,
            tutor_state
        )

        # Map routing from new workflow to old workflow terminology
        # In new workflow: continue/replan/end
        # In old workflow: advance/remediate
        routing = self._map_routing(result, final_state)

        return updated_tutor_state, routing

    def _map_routing(self, result: dict, final_state: dict) -> str:
        """
        Map new workflow routing to old workflow terminology.

        New workflow has: continue, replan, end
        Old workflow expects: advance, remediate

        Args:
            result: Result from submit_response
            final_state: Final state after workflow execution

        Returns:
            "advance" or "remediate"
        """
        # Check if replanning was triggered
        if result.get("plan_updated"):
            return "remediate"  # Replan means student struggled, like remediate

        # Check session status
        if result.get("session_status") == "completed":
            return "advance"  # Session complete, like advancing

        # Default to advance (continuing with next question)
        return "advance"
