"""
Tutor Workflow State Definition

This module defines the SimplifiedState TypedDict that serves as the core state
for the LangGraph workflow. The state follows these principles:
- The study plan is the source of truth (status-based navigation)
- Assessment notes are simple accumulated text
- All execution is logged for observability
"""

from typing import TypedDict, Annotated, Sequence, Optional, Any, Dict, List
import operator


class SimplifiedState(TypedDict):
    """
    Core state for the tutor workflow.

    Design Principles:
    - Status-based navigation: No manual step_number tracking
    - Plan is source of truth: All flow determined by step statuses
    - Simple assessment: Text notes only, no rigid schema
    - Full observability: Every agent execution logged
    """

    # === Session Metadata ===
    session_id: str
    created_at: str  # ISO timestamp
    last_updated_at: str  # ISO timestamp

    # === Inputs (Immutable Context) ===
    guidelines: str  # Teaching philosophy/approach
    student_profile: Dict[str, Any]  # {interests, learning_style, grade, ...}
    topic_info: Dict[str, Any]  # {topic, subtopic, grade}
    session_context: Dict[str, Any]  # {estimated_duration_minutes}

    # === Dynamic State (THE PLAN IS THE SOURCE OF TRUTH) ===
    study_plan: Dict[str, Any]  # Contains todo_list with step statuses
    assessment_notes: str  # SIMPLIFIED: accumulated text observations
    conversation: Annotated[Sequence[Dict[str, Any]], operator.add]  # Append-only

    # === Control Flags (Set by EVALUATOR) ===
    replan_needed: bool  # Triggers replanning
    replan_reason: Optional[str]  # Why replanning is needed

    # === Observability (Full Audit Trail) ===
    agent_logs: Annotated[Sequence[Dict[str, Any]], operator.add]  # Append-only


# Type aliases for clarity
StudyPlan = Dict[str, Any]
Step = Dict[str, Any]
Message = Dict[str, Any]
AgentLog = Dict[str, Any]
