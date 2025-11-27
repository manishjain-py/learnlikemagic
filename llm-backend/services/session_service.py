"""Session management business logic."""
from typing import Optional, List
from sqlalchemy.orm import Session as DBSession
from uuid import uuid4
import logging

logger = logging.getLogger(__name__)

from models import (
    CreateSessionRequest,
    CreateSessionResponse,
    StepRequest,
    StepResponse,
    SummaryResponse,
    TutorState,
    Student,
    Goal,
    HistoryEntry,
    GradingResult
)
from repositories import SessionRepository, EventRepository, TeachingGuidelineRepository
from adapters.workflow_adapter import SessionWorkflowAdapter  # New workflow
from utils.formatting import extract_last_turn, build_turn_response
from utils.constants import MAX_STEPS, MASTERY_COMPLETION_THRESHOLD
from utils.exceptions import SessionNotFoundException, GuidelineNotFoundException


class SessionService:
    """Orchestrates session creation, step processing, and summary generation."""

    def __init__(self, db: DBSession):
        self.db = db
        self.session_repo = SessionRepository(db)
        self.event_repo = EventRepository(db)
        self.guideline_repo = TeachingGuidelineRepository(db)

        # Use new TutorWorkflow instead of old GraphService
        # This gives us: LangGraph, logging, bug fixes, and the EVALUATOR agent!
        self.graph_service = SessionWorkflowAdapter(db)

    def create_new_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        """
        Create a new learning session.

        Steps:
        1. Validate guideline exists
        2. Initialize tutor state
        3. Generate first question via graph
        4. Persist session
        5. Return first turn

        Args:
            request: CreateSessionRequest with student and goal data

        Returns:
            CreateSessionResponse with session_id and first_turn

        Raises:
            GuidelineNotFoundException: If guideline_id not found
        """
        # Validate guideline exists
        guideline = self.guideline_repo.get_guideline_by_id(request.goal.guideline_id)
        if not guideline:
            raise GuidelineNotFoundException(request.goal.guideline_id)

        # Generate session ID
        session_id = str(uuid4())
        logger.info(f"Generated session_id: {session_id}")

        # Initialize tutor state
        tutor_state = TutorState(
            session_id=session_id,
            student=request.student,
            goal=request.goal,
            step_idx=0,
            history=[],
            evidence=[],
            mastery_score=0.5,
            last_grading=None,
            next_action="present"
        )
        logger.info(f"Initialized tutor_state: {tutor_state}")

        # Generate first question using graph service
        tutor_state = self.graph_service.execute_present_node(
            tutor_state,
            teaching_guideline=guideline.guideline
        )
        logger.info(f"Generated first question: {tutor_state}")

        # Persist session
        self.session_repo.create(
            session_id=session_id,
            state=tutor_state
        )

        # Log event
        self.event_repo.log(
            session_id=session_id,
            node="present",
            step_idx=tutor_state.step_idx,
            payload={"action": "initial_question"}
        )

        # Build response
        message, hints = extract_last_turn(tutor_state.history)
        first_turn = {
            "message": message,
            "hints": hints,
            "step_idx": tutor_state.step_idx
        }

        return CreateSessionResponse(
            session_id=session_id,
            first_turn=first_turn
        )

    def process_step(self, session_id: str, request: StepRequest) -> StepResponse:
        """
        Process a student's answer and generate next turn.

        Steps:
        1. Load session
        2. Add student reply to history
        3. Execute graph workflow (check → route → advance/remediate → present)
        4. Update session state
        5. Log events
        6. Return next turn

        Args:
            session_id: Session identifier
            request: StepRequest with student_reply

        Returns:
            StepResponse with next_turn, routing, and last_grading

        Raises:
            SessionNotFoundException: If session_id not found
        """
        # Load session
        session = self.session_repo.get_by_id(session_id)
        if not session:
            raise SessionNotFoundException(session_id)

        tutor_state = TutorState.model_validate_json(session.state_json)

        # Add student reply to history
        tutor_state.history.append(HistoryEntry(
            role="student",
            msg=request.student_reply,
            meta=None
        ))

        # Execute graph workflow
        tutor_state, routing = self.graph_service.execute_step_workflow(
            tutor_state,
            student_reply=request.student_reply
        )

        # Update database
        self.session_repo.update(
            session_id=session_id,
            state=tutor_state
        )

        # Log events
        self.event_repo.log(
            session_id=session_id,
            node="check",
            step_idx=tutor_state.step_idx,
            payload={"grading": tutor_state.last_grading.model_dump() if tutor_state.last_grading else {}}
        )

        self.event_repo.log(
            session_id=session_id,
            node=routing,
            step_idx=tutor_state.step_idx,
            payload={"routing": routing}
        )

        # Build response
        next_turn = build_turn_response(
            history=tutor_state.history,
            step_idx=tutor_state.step_idx,
            mastery_score=tutor_state.mastery_score
        )

        return StepResponse(
            next_turn=next_turn,
            routing=routing.capitalize(),
            last_grading=tutor_state.last_grading
        )

    def get_summary(self, session_id: str) -> SummaryResponse:
        """
        Generate session summary with performance metrics and suggestions.

        Args:
            session_id: Session identifier

        Returns:
            SummaryResponse with steps, mastery, misconceptions, suggestions

        Raises:
            SessionNotFoundException: If session_id not found
        """
        session = self.session_repo.get_by_id(session_id)
        if not session:
            raise SessionNotFoundException(session_id)

        tutor_state = TutorState.model_validate_json(session.state_json)

        # Extract misconceptions from events
        events = self.event_repo.get_for_session(session_id)
        misconceptions_seen = set()

        for event in events:
            if event.node == "check" and event.payload_json:
                import json
                payload = json.loads(event.payload_json)
                if "grading" in payload:
                    grading = payload["grading"]
                    misconceptions_seen.update(grading.get("labels", []))

        # Generate suggestions based on mastery
        suggestions = self._generate_suggestions(tutor_state, misconceptions_seen)

        return SummaryResponse(
            steps_completed=tutor_state.step_idx,
            mastery_score=round(tutor_state.mastery_score, 2),
            misconceptions_seen=list(misconceptions_seen),
            suggestions=suggestions
        )

    def _generate_suggestions(
        self,
        state: TutorState,
        misconceptions: set
    ) -> List[str]:
        """
        Generate personalized suggestions based on performance.

        Args:
            state: Current tutor state
            misconceptions: Set of misconception labels seen

        Returns:
            List of suggestion strings
        """
        suggestions = []

        if state.mastery_score >= MASTERY_COMPLETION_THRESHOLD:
            suggestions.append(f"Excellent work on {state.goal.topic}!")
            suggestions.append("You're ready to move to more advanced topics.")
        elif state.mastery_score >= 0.7:
            suggestions.append("Good progress! Try 3-5 more practice problems.")
            if state.goal.learning_objectives:
                suggestions.append(f"Focus on: {state.goal.learning_objectives[0]}")
        else:
            suggestions.append("Keep practicing! Review the examples.")
            suggestions.append(f"Revisit the concepts around {state.goal.topic}")

        if misconceptions:
            top_misconceptions = list(misconceptions)[:2]
            suggestions.append(f"Work on understanding: {', '.join(top_misconceptions)}")

        return suggestions
