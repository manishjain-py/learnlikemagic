"""Graph execution orchestration service."""
from typing import Tuple
from sqlalchemy.orm import Session as DBSession

from models import TutorState
from graph.state import tutor_state_to_graph_state, graph_state_to_tutor_state
from graph.nodes import (
    check_node,
    advance_node,
    remediate_node,
    diagnose_node,
    present_node,
    route_after_check,
    route_after_advance
)
from repositories import TeachingGuidelineRepository
from utils.constants import DEFAULT_GUIDELINE


class GraphService:
    """Orchestrates LangGraph node execution without direct database access in nodes."""

    def __init__(self, db: DBSession):
        self.db = db
        self.guideline_repo = TeachingGuidelineRepository(db)

    def execute_present_node(
        self,
        tutor_state: TutorState,
        teaching_guideline: str
    ) -> TutorState:
        """
        Execute present node to generate teaching message.

        Args:
            tutor_state: Current tutor state
            teaching_guideline: Full guideline text (pre-loaded)

        Returns:
            Updated tutor state with new message in history
        """
        graph_state = tutor_state_to_graph_state(tutor_state)
        graph_state["teaching_guideline"] = teaching_guideline

        # Execute node
        graph_state = present_node(graph_state)

        return graph_state_to_tutor_state(graph_state)

    def execute_step_workflow(
        self,
        tutor_state: TutorState,
        student_reply: str
    ) -> Tuple[TutorState, str]:
        """
        Execute full step workflow: check → route → advance/remediate → present.

        This is the core tutoring loop:
        1. Grade student's answer (check)
        2. Decide path based on score (route_after_check)
        3a. If advance: increment step → maybe present next question
        3b. If remediate: provide help → diagnose → (don't present)

        Args:
            tutor_state: Current tutor state with student reply in history
            student_reply: The student's answer

        Returns:
            Tuple of (updated_tutor_state, routing_decision)
            routing_decision is either "advance" or "remediate"
        """
        # Convert to graph state
        graph_state = tutor_state_to_graph_state(tutor_state)
        graph_state["current_student_reply"] = student_reply

        # Load teaching guideline for potential present node
        guideline = self._get_teaching_guideline(tutor_state.goal.guideline_id)
        graph_state["teaching_guideline"] = guideline

        # 1. Check (grade the response)
        graph_state = check_node(graph_state)

        # 2. Route based on score
        routing = route_after_check(graph_state)

        # 3. Execute appropriate path
        if routing == "advance":
            # Advance path: increment step, then maybe present next question
            graph_state = advance_node(graph_state)

            # Check if we should continue or end
            next_step = route_after_advance(graph_state)

            if next_step == "present":
                # Continue with next question
                graph_state = present_node(graph_state)
            # else: session ends (step_idx >= 10 or mastery >= 0.85)

        else:  # remediate
            # Remediate path: provide help, then diagnose
            graph_state = remediate_node(graph_state)
            graph_state = diagnose_node(graph_state)
            # Note: No present after remediation - remediation message is the response

        # Convert back to tutor state
        tutor_state = graph_state_to_tutor_state(graph_state)

        return tutor_state, routing

    def _get_teaching_guideline(self, guideline_id: str) -> str:
        """
        Get teaching guideline or return default.

        Args:
            guideline_id: Guideline identifier

        Returns:
            Guideline text or default fallback
        """
        if not guideline_id:
            return DEFAULT_GUIDELINE

        guideline = self.guideline_repo.get_guideline_by_id(guideline_id)
        if not guideline:
            print(f"[GraphService] WARNING: Guideline {guideline_id} not found, using default")
            return DEFAULT_GUIDELINE

        return guideline.guideline
