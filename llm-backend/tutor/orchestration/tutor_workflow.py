"""
Tutor Workflow - LangGraph Implementation

This module defines the complete LangGraph workflow for the tutor system:
- 4 nodes: ROUTER (entry), PLANNER, EXECUTOR, EVALUATOR
- Intelligent entry routing based on session context
- Conditional routing from EVALUATOR
- Session persistence with checkpointing

Architecture:

    START → ROUTER (smart entry point)
              ↓
              ├─→ PLANNER (new session) → EXECUTOR → END
              │                              ↓
              ├─→ EVALUATOR (student response) → (route_after_evaluation)
              │                                      ↓
              │                                      ├─→ replan → PLANNER
              │                                      ├─→ continue → EXECUTOR → END
              │                                      └─→ end → END
              │
              └─→ EXECUTOR (edge case)

Flow Details:
1. New Session (start_session):
   START → ROUTER → PLANNER → EXECUTOR → END

2. Student Response (submit_response):
   START → ROUTER → EVALUATOR → [replan/continue/end]

3. The ROUTER node intelligently decides entry path:
   - No plan exists → PLANNER (initial planning)
   - Plan exists + last msg is student → EVALUATOR (evaluate response)
   - Plan exists + last msg is tutor → EXECUTOR (edge case)

"""

from typing import Literal, Optional
import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection

from tutor.models.state import SimplifiedState
from tutor.agents.planner_agent import PlannerAgent
from tutor.agents.executor_agent import ExecutorAgent
from tutor.agents.evaluator_agent import EvaluatorAgent
from shared.services import LLMService

logger = logging.getLogger(__name__)


def route_entry(state: SimplifiedState) -> Literal["planner", "evaluator", "executor"]:
    """
    Smart entry point routing based on session context.

    Decision tree:
    1. No study plan exists → PLANNER (new session - initial planning)
    2. Plan exists + last message is student → EVALUATOR (resume - evaluate student response)
    3. Plan exists + last message is tutor → EXECUTOR (edge case - generate next message)

    Args:
        state: Current workflow state

    Returns:
        "planner" | "evaluator" | "executor"
    """
    study_plan = state.get("study_plan", {})
    conversation = state.get("conversation", [])

    # Case 1: No plan exists - new session, need initial planning
    if not study_plan or not study_plan.get("todo_list"):
        logger.info("Entry routing: NEW SESSION → PLANNER (initial planning)")
        return "planner"

    # Case 2: Plan exists and last message is from student - evaluate their response
    if conversation and conversation[-1].get("role") == "student":
        logger.info("Entry routing: STUDENT RESPONSE → EVALUATOR (evaluate answer)")
        return "evaluator"

    # Case 3: Plan exists but last message is tutor or no conversation
    # This shouldn't normally happen (we'd be at END waiting for student)
    # But handle gracefully by generating next message
    logger.warning(
        "Entry routing: EDGE CASE → EXECUTOR (plan exists but no student message)"
    )
    return "executor"


def route_after_executor(state: SimplifiedState) -> Literal["evaluator", "end"]:
    """
    Routing logic after EXECUTOR executes.

    If the last message is from a student, go to EVALUATOR to evaluate it.
    Otherwise, END (wait for student response).
    """
    conversation = state.get("conversation", [])
    if conversation and conversation[-1].get("role") == "student":
        logger.info("Student message found, routing to evaluator")
        return "evaluator"
    logger.info("No student message, ending to wait for response")
    return "end"


def route_after_evaluation(state: SimplifiedState) -> Literal["replan", "continue", "end"]:
    """
    Conditional routing logic after EVALUATOR executes.

    Decision tree:
    1. Check replan_needed flag (highest priority)
       - If yes: Check max_replans not exceeded
         - If exceeded: Flag intervention, END
         - Else: REPLAN
    2. Check if all steps completed
       - If yes: END
    3. Otherwise: CONTINUE

    Args:
        state: Current workflow state

    Returns:
        "replan" | "continue" | "end"
    """
    logger.info("Routing after evaluation...")

    # 1. Check replan flag
    if state.get("replan_needed", False):
        logger.info("Replanning needed")

        # Safety check: max replans reached?
        metadata = state["study_plan"].get("metadata", {})
        replan_count = metadata.get("replan_count", 0)
        max_replans = metadata.get("max_replans", 3)

        if replan_count >= max_replans:
            logger.warning(
                f"Max replans ({max_replans}) reached. Flagging for intervention."
            )
            # Note: We should add a flag to state here
            # For now, just end the session
            return "end"

        logger.info(f"Replanning (count: {replan_count}/{max_replans})")
        return "replan"

    # 2. Check session completion
    todo_list = state["study_plan"].get("todo_list", [])
    all_completed = all(step.get("status") == "completed" for step in todo_list)

    if all_completed:
        logger.info("All steps completed. Ending session.")
        return "end"

    # 3. Continue execution
    logger.info("Continuing execution...")
    return "continue"


def build_workflow(
    llm_service: LLMService,
    db_connection: Connection,
) -> StateGraph:
    """
    Build the complete LangGraph workflow.

    Args:
        llm_service: LLM service instance
        db_connection: Database connection for checkpoints

    Returns:
        Compiled LangGraph workflow app
    """
    logger.info("Building tutor workflow...")

    # Create agent instances
    planner = PlannerAgent(llm_service)
    executor = ExecutorAgent(llm_service)
    evaluator = EvaluatorAgent(llm_service)

    # Create StateGraph
    workflow = StateGraph(SimplifiedState)

    # Add nodes
    logger.info("Adding workflow nodes...")

    # Router node - pass-through that enables conditional entry routing
    def router_node(state: SimplifiedState) -> dict:
        """Pass-through node for entry point routing"""
        return {}  # No state changes, just enables routing

    workflow.add_node("router", router_node)
    workflow.add_node("planner", planner.execute)
    workflow.add_node("executor", executor.execute)
    workflow.add_node("evaluator", evaluator.execute)

    # Set entry point to router (not planner!)
    # This allows intelligent routing based on context
    workflow.set_entry_point("router")

    # Add edges
    logger.info("Adding workflow edges...")

    # ROUTER → Conditional routing based on session context
    # This is the KEY FIX - routes to evaluator when resuming with student response
    workflow.add_conditional_edges(
        "router",
        route_entry,
        {
            "planner": "planner",
            "evaluator": "evaluator",
            "executor": "executor",
        },
    )

    # PLANNER → EXECUTOR
    workflow.add_edge("planner", "executor")

    # EXECUTOR → Conditional routing
    # If last message is from student, go to EVALUATOR
    # Otherwise, END (wait for student response)
    workflow.add_conditional_edges(
        "executor",
        route_after_executor,
        {
            "evaluator": "evaluator",
            "end": END,
        },
    )

    # EVALUATOR → Conditional routing
    workflow.add_conditional_edges(
        "evaluator",
        route_after_evaluation,
        {
            "replan": "planner",  # Go back to planner with feedback
            "continue": "executor",  # Generate next message
            "end": END,  # Session complete
        },
    )

    # Set up checkpointing
    # Set up checkpointing
    logger.info("Setting up PostgreSQL checkpointing")
    checkpointer = PostgresSaver(db_connection)
    checkpointer.setup()

    # Compile workflow
    logger.info("Compiling workflow...")
    app = workflow.compile(checkpointer=checkpointer)

    logger.info("Workflow build complete!")
    return app


class TutorWorkflow:
    """
    High-level wrapper for the tutor workflow.

    Provides convenient methods for:
    - Starting new sessions
    - Submitting student responses
    - Resuming interrupted sessions
    """

    def __init__(
        self,
        llm_service: LLMService,
        db_connection: Connection,
    ):
        """
        Initialize workflow wrapper.

        Args:
            llm_service: LLM service instance
            db_connection: Database connection for checkpoints
        """
        self.llm_service = llm_service
        self.app = build_workflow(llm_service, db_connection)

    def start_session(
        self,
        session_id: str,
        guidelines: str,
        student_profile: dict,
        topic_info: dict,
        session_context: dict,
        prebuilt_plan: Optional[dict] = None,
    ) -> dict:
        """
        Start a new tutoring session.

        Executes: PLANNER → EXECUTOR
        Returns first teaching message.

        Args:
            session_id: Unique session identifier
            guidelines: Teaching guidelines
            student_profile: Student information
            topic_info: Topic information
            session_context: Session context

        Returns:
            Dict with first_message and study_plan
        """
        from tutor.models.helpers import get_timestamp

        logger.info(f"Starting session {session_id}")

        # Build initial state
        initial_state = {
            "session_id": session_id,
            "created_at": get_timestamp(),
            "last_updated_at": get_timestamp(),
            "guidelines": guidelines,
            "student_profile": student_profile,
            "topic_info": topic_info,
            "session_context": session_context,
            "study_plan": prebuilt_plan or {},
            "assessment_notes": "",
            "conversation": [],
            "replan_needed": False,
            "replan_reason": None,
            "agent_logs": [],
        }

        # Configure for this session
        config = {"configurable": {"thread_id": session_id}}

        # Run workflow: PLANNER → EXECUTOR
        # This will stop at EVALUATOR (waiting for student response)
        result = None
        for output in self.app.stream(initial_state, config):
            result = output
            logger.debug(f"Workflow step: {list(output.keys())}")

        # Extract state from last output
        # LangGraph returns dict with node name as key
        final_state = None
        if result:
            # Get the last node's output
            node_name = list(result.keys())[0]
            final_state = result[node_name]

        if not final_state:
            raise RuntimeError("Workflow did not produce output")

        # Get first message from conversation
        conversation = final_state.get("conversation", ())
        if not conversation:
            raise RuntimeError("No first message generated")

        first_message = conversation[-1].get("content", "")

        return {
            "first_message": first_message,
            "study_plan": final_state.get("study_plan", {}),
            "session_id": session_id,
        }

    def submit_response(
        self, session_id: str, student_reply: str
    ) -> dict:
        """
        Submit student response and get feedback.

        Adds student message to conversation, then executes:
        ROUTER → EVALUATOR → [replan/continue/end] → (EXECUTOR if continuing)

        The ROUTER intelligently detects the student message and routes to EVALUATOR,
        bypassing PLANNER to avoid the infinite reset bug.

        Args:
            session_id: Session identifier
            student_reply: Student's response

        Returns:
            Dict with feedback, next_message (if any), and status
        """
        from tutor.models.helpers import get_timestamp

        logger.info(f"Submitting response for session {session_id}")

        # Configure for this session
        config = {"configurable": {"thread_id": session_id}}

        # Get current state from checkpoint
        state_snapshot = self.app.get_state(config)
        if not state_snapshot or not state_snapshot.values:
            raise ValueError(f"Session {session_id} not found")

        current_state = state_snapshot.values

        # Add student message to conversation
        student_message = {
            "role": "student",
            "content": student_reply,
            "timestamp": get_timestamp(),
        }

        updated_state = {
            **current_state,
            "conversation": current_state.get("conversation", []) + [student_message],
        }

        # Execute workflow - ROUTER will detect student message and route to EVALUATOR
        # This bypasses PLANNER, fixing the infinite reset bug
        result = None
        for output in self.app.stream(updated_state, config, stream_mode="updates"):
            result = output
            logger.debug(f"Workflow step: {list(output.keys())}")

        if not result:
            raise RuntimeError("Workflow did not produce output")

        # Extract final state
        node_name = list(result.keys())[0]
        final_state = result[node_name]

        # Get feedback message (from EVALUATOR)
        conversation = final_state.get("conversation", ())
        feedback = None
        next_message = None

        # Find the feedback message (after student message)
        for i, msg in enumerate(reversed(conversation)):
            if msg.get("role") == "tutor":
                if feedback is None:
                    feedback = msg.get("content")
                elif next_message is None:
                    next_message = msg.get("content")
                    break

        # Determine session status
        todo_list = final_state.get("study_plan", {}).get("todo_list", [])
        all_completed = all(step.get("status") == "completed" for step in todo_list)

        status = "completed" if all_completed else "active"

        return {
            "feedback": feedback or "",
            "next_message": next_message,
            "session_status": status,
            "plan_updated": final_state.get("replan_needed", False),
            "replan_reason": final_state.get("replan_reason"),
        }

    def get_session_state(self, session_id: str) -> SimplifiedState:
        """
        Get current state of a session.

        Args:
            session_id: Session identifier

        Returns:
            Current state

        Raises:
            ValueError: If session not found
        """
        config = {"configurable": {"thread_id": session_id}}
        state_snapshot = self.app.get_state(config)

        if not state_snapshot or not state_snapshot.values:
            raise ValueError(f"Session {session_id} not found")

        return state_snapshot.values
