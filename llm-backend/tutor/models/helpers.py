"""
Workflow Helper Functions

This module provides utility functions for the tutor workflow:
- Dynamic step calculation (status-based)
- Plan status updates
- Context management
- Timestamp utilities

Design Principles:
- Pure functions where possible
- Type safety
- Clear error handling
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import uuid


def get_current_step(plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Dynamically calculate current step from plan statuses.

    NO manual tracking needed! The step status is the source of truth.

    Priority logic:
    1. First check: any step with status = "in_progress"?
    2. Else: first step with status = "pending"?
    3. All completed? Return None (session done)

    Args:
        plan: Study plan with todo_list

    Returns:
        Current step dictionary or None if all completed

    Example:
        >>> plan = {"todo_list": [
        ...     {"step_id": "1", "status": "completed"},
        ...     {"step_id": "2", "status": "in_progress"},
        ...     {"step_id": "3", "status": "pending"}
        ... ]}
        >>> get_current_step(plan)
        {"step_id": "2", "status": "in_progress"}
    """
    todo_list = plan.get("todo_list", [])

    # Priority 1: Any step in progress?
    for step in todo_list:
        if step.get("status") == "in_progress":
            return step

    # Priority 2: First pending step?
    for step in todo_list:
        if step.get("status") == "pending":
            return step

    # All steps completed
    return None


def update_plan_statuses(
    plan: Dict[str, Any],
    status_updates: Dict[str, str],
    info_updates: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Apply EVALUATOR's status updates to plan.

    Validates that only ONE step is in_progress at a time.

    Args:
        plan: Current study plan
        status_updates: Dict of {step_id: new_status}
        info_updates: Dict of {step_id: status_info updates}

    Returns:
        Updated plan

    Raises:
        ValueError: If multiple steps would be in_progress

    Example:
        >>> plan = {"todo_list": [...], "metadata": {...}}
        >>> status_updates = {"step_2": "completed"}
        >>> info_updates = {"step_2": {"questions_correct": 3}}
        >>> updated_plan = update_plan_statuses(plan, status_updates, info_updates)
    """
    updated_list = []
    in_progress_count = 0

    for step in plan["todo_list"]:
        step_id = step["step_id"]
        step_copy = step.copy()

        # Apply status update if present
        if step_id in status_updates:
            step_copy["status"] = status_updates[step_id]

        # Apply info update if present
        if step_id in info_updates:
            step_copy["status_info"] = {
                **step_copy.get("status_info", {}),
                **info_updates[step_id],
            }

        # Count in_progress steps
        if step_copy["status"] == "in_progress":
            in_progress_count += 1

        updated_list.append(step_copy)

    # Validate: only one in_progress
    if in_progress_count > 1:
        raise ValueError(
            f"Invalid state: {in_progress_count} steps in_progress! "
            "Only one step can be in_progress at a time."
        )

    # Update plan
    updated_plan = plan.copy()
    updated_plan["todo_list"] = updated_list
    updated_plan["metadata"]["last_updated_at"] = get_timestamp()

    return updated_plan


def get_relevant_context(
    conversation: List[Dict[str, Any]], max_messages: int = 15
) -> List[Dict[str, Any]]:
    """
    Get recent conversation with summary of older messages.

    Prevents context window overflow in long sessions.

    Strategy:
    - Keep first 3 messages (introduction)
    - Add summary placeholder for middle
    - Keep last N messages (recent context)

    Args:
        conversation: Full conversation history
        max_messages: Maximum messages to return

    Returns:
        Filtered conversation list

    Example:
        >>> conversation = [msg1, msg2, ..., msg20]
        >>> relevant = get_relevant_context(conversation, max_messages=15)
        >>> len(relevant) <= 15
        True
    """
    if len(conversation) <= max_messages:
        return conversation

    # Keep first 3 (intro) + last (max_messages - 4) (recent)
    intro_count = 3
    recent_count = max_messages - 4  # Reserve 1 for summary

    summary_count = len(conversation) - (intro_count + recent_count)
    summary_msg = {
        "role": "system",
        "content": f"[{summary_count} earlier messages summarized]",
        "timestamp": get_timestamp(),
    }

    return (
        conversation[:intro_count] + [summary_msg] + conversation[-recent_count:]
    )


def validate_status_updates(
    plan: Dict[str, Any], updates: Dict[str, str]
) -> bool:
    """
    Validate status updates before applying.

    Checks:
    - All step_ids exist in plan
    - Status values are valid
    - Only one step would be in_progress

    Args:
        plan: Current study plan
        updates: Proposed status updates

    Returns:
        True if valid, False otherwise
    """
    valid_statuses = {"pending", "in_progress", "completed", "blocked"}
    existing_step_ids = {step["step_id"] for step in plan["todo_list"]}

    # Check all step_ids exist
    for step_id in updates.keys():
        if step_id not in existing_step_ids:
            return False

    # Check all statuses are valid
    for status in updates.values():
        if status not in valid_statuses:
            return False

    # Check only one in_progress
    in_progress_count = 0
    for step in plan["todo_list"]:
        step_id = step["step_id"]
        status = updates.get(step_id, step["status"])
        if status == "in_progress":
            in_progress_count += 1

    return in_progress_count <= 1


def is_session_complete(plan: Dict[str, Any]) -> bool:
    """
    Check if all steps in plan are completed.

    Args:
        plan: Study plan

    Returns:
        True if all steps completed, False otherwise

    Example:
        >>> plan = {"todo_list": [
        ...     {"status": "completed"},
        ...     {"status": "completed"}
        ... ]}
        >>> is_session_complete(plan)
        True
    """
    todo_list = plan.get("todo_list", [])
    return all(step.get("status") == "completed" for step in todo_list)


def get_timestamp() -> str:
    """
    Get current UTC timestamp in ISO 8601 format.

    Returns:
        ISO timestamp string (e.g., "2024-11-19T14:30:00Z")

    Example:
        >>> ts = get_timestamp()
        >>> ts.endswith('Z')
        True
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_session_id() -> str:
    """
    Generate unique session ID.

    Returns:
        UUID string

    Example:
        >>> session_id = generate_session_id()
        >>> len(session_id) == 36
        True
    """
    return str(uuid.uuid4())


def generate_step_id() -> str:
    """
    Generate unique step ID.

    Returns:
        UUID string prefixed with "step_"

    Example:
        >>> step_id = generate_step_id()
        >>> step_id.startswith('step_')
        True
    """
    return f"step_{uuid.uuid4()}"


def calculate_progress(plan: Dict[str, Any]) -> Dict[str, int]:
    """
    Calculate session progress metrics.

    Args:
        plan: Study plan

    Returns:
        Dict with progress metrics:
            - steps_completed: Number of completed steps
            - steps_total: Total number of steps
            - questions_asked: Total questions across all steps
            - questions_correct: Total correct answers

    Example:
        >>> plan = {"todo_list": [
        ...     {"status": "completed", "status_info": {"questions_asked": 3, "questions_correct": 2}},
        ...     {"status": "in_progress", "status_info": {"questions_asked": 1, "questions_correct": 1}}
        ... ]}
        >>> progress = calculate_progress(plan)
        >>> progress['steps_completed']
        1
    """
    todo_list = plan.get("todo_list", [])

    steps_completed = sum(1 for step in todo_list if step.get("status") == "completed")
    steps_total = len(todo_list)

    questions_asked = sum(
        step.get("status_info", {}).get("questions_asked", 0) for step in todo_list
    )
    questions_correct = sum(
        step.get("status_info", {}).get("questions_correct", 0) for step in todo_list
    )

    return {
        "steps_completed": steps_completed,
        "steps_total": steps_total,
        "questions_asked": questions_asked,
        "questions_correct": questions_correct,
        "accuracy": (
            questions_correct / questions_asked if questions_asked > 0 else 0.0
        ),
    }


def should_trigger_replan(evaluator_output: Dict[str, Any], plan: Dict[str, Any]) -> bool:
    """
    Determine if replanning should be triggered based on evaluator output.

    Checks:
    - EVALUATOR explicitly set replan_needed
    - Haven't exceeded max_replans

    Args:
        evaluator_output: Output from EVALUATOR
        plan: Current study plan

    Returns:
        True if should replan, False otherwise
    """
    if not evaluator_output.get("replan_needed", False):
        return False

    metadata = plan.get("metadata", {})
    replan_count = metadata.get("replan_count", 0)
    max_replans = metadata.get("max_replans", 3)

    return replan_count < max_replans
