"""
State Adapter for converting between TutorState and SimplifiedState.

This adapter enables the new TutorWorkflow to work with the existing
API contracts without breaking changes.
"""

from typing import Dict, Any, List
from shared.models import TutorState, HistoryEntry, GradingResult, StudentPrefs
from tutor.models.state import SimplifiedState
from tutor.models.helpers import get_timestamp


class StateConverter:
    """
    Converts between old TutorState (API) and new SimplifiedState (Workflow).

    Key Mappings:
    - TutorState.history → SimplifiedState.conversation
    - TutorState.goal.topic → SimplifiedState.topic_info
    - TutorState.student → SimplifiedState.student_profile
    - TutorState.step_idx → Derived from study_plan statuses
    - TutorState.mastery_score → Calculated from evaluation scores
    """

    @staticmethod
    def tutor_state_to_simplified(
        tutor_state: TutorState,
        teaching_guideline: str
    ) -> SimplifiedState:
        """
        Convert TutorState to SimplifiedState for TutorWorkflow input.

        Args:
            tutor_state: Old state from database
            teaching_guideline: Teaching guidelines text

        Returns:
            SimplifiedState compatible with TutorWorkflow
        """
        # Convert history to conversation format
        conversation = []
        for entry in tutor_state.history:
            conversation.append({
                "role": "tutor" if entry.role == "teacher" else entry.role,
                "content": entry.msg,
                "timestamp": get_timestamp(),
                "meta": entry.meta or {}
            })

        # Extract student profile
        prefs = tutor_state.student.prefs or StudentPrefs()
        student_profile = {
            "grade": tutor_state.student.grade,
            "interests": [],  # Not available in old StudentPrefs
            "learning_style": prefs.style or "visual",
            "strengths": [],
            "challenges": [],
        }

        # Extract topic info
        topic_info = {
            "topic": tutor_state.goal.topic,
            "subtopic": tutor_state.goal.learning_objectives[0] if tutor_state.goal.learning_objectives else tutor_state.goal.topic,
            "grade": tutor_state.student.grade,
        }

        # Session context
        session_context = {
            "estimated_duration_minutes": 20,  # Default
            "session_type": "practice",
        }

        # Build simplified state
        simplified_state: SimplifiedState = {
            "session_id": tutor_state.session_id,
            "created_at": get_timestamp(),
            "last_updated_at": get_timestamp(),
            "guidelines": teaching_guideline,
            "student_profile": student_profile,
            "topic_info": topic_info,
            "session_context": session_context,
            "study_plan": {},  # Will be created by PLANNER
            "assessment_notes": "",
            "conversation": conversation,
            "replan_needed": False,
            "replan_reason": None,
            "agent_logs": [],
        }

        return simplified_state

    @staticmethod
    def simplified_to_tutor_state(
        simplified_state: SimplifiedState,
        original_tutor_state: TutorState
    ) -> TutorState:
        """
        Convert SimplifiedState back to TutorState for API response.

        Args:
            simplified_state: State from TutorWorkflow
            original_tutor_state: Original state (for fields we don't change)

        Returns:
            Updated TutorState
        """
        # Convert conversation back to history
        history = []
        for msg in simplified_state["conversation"]:
            history.append(HistoryEntry(
                role="teacher" if msg["role"] == "tutor" else msg["role"],
                msg=msg["content"],
                meta=msg.get("meta")
            ))

        # Calculate step_idx from study plan
        step_idx = StateConverter._calculate_step_idx(simplified_state)

        # Calculate mastery score from evaluation results
        mastery_score = StateConverter._calculate_mastery_score(simplified_state)

        # Extract last grading from conversation/assessment
        last_grading = StateConverter._extract_last_grading(simplified_state)

        # Build updated tutor state
        updated_state = TutorState(
            session_id=original_tutor_state.session_id,
            student=original_tutor_state.student,
            goal=original_tutor_state.goal,
            step_idx=step_idx,
            history=history,
            evidence=original_tutor_state.evidence,  # Preserve evidence
            mastery_score=mastery_score,
            last_grading=last_grading,
            next_action="present" if step_idx < 10 else "complete"
        )

        return updated_state

    @staticmethod
    def _calculate_step_idx(simplified_state: SimplifiedState) -> int:
        """Calculate step index from study plan progress."""
        study_plan = simplified_state.get("study_plan", {})
        todo_list = study_plan.get("todo_list", [])

        if not todo_list:
            return 0

        # Count completed steps
        completed = sum(1 for step in todo_list if step.get("status") == "completed")
        return completed

    @staticmethod
    def _calculate_mastery_score(simplified_state: SimplifiedState) -> float:
        """
        Calculate mastery score from evaluation results.

        Uses the average of evaluation scores from assessment notes
        or defaults to 0.5.
        """
        study_plan = simplified_state.get("study_plan", {})
        todo_list = study_plan.get("todo_list", [])

        if not todo_list:
            return 0.5

        # Calculate based on completed steps vs total steps
        total_steps = len(todo_list)
        completed_steps = sum(1 for step in todo_list if step.get("status") == "completed")

        if total_steps == 0:
            return 0.5

        # Base mastery on completion percentage
        completion_ratio = completed_steps / total_steps

        # Scale to 0.5-1.0 range (start at 0.5, max 1.0)
        mastery = 0.5 + (completion_ratio * 0.5)

        return round(mastery, 2)

    @staticmethod
    def _extract_last_grading(simplified_state: SimplifiedState) -> GradingResult | None:
        """
        Extract the last grading result from conversation/assessment notes.

        This looks for evaluator feedback in the conversation history.
        """
        conversation = simplified_state.get("conversation", [])

        # Look backwards through conversation for evaluator feedback
        for msg in reversed(conversation):
            if msg.get("role") == "tutor" and "score" in msg.get("meta", {}):
                # Found an evaluation message
                meta = msg["meta"]
                return GradingResult(
                    score=meta.get("score", 0.5),
                    rationale=msg.get("content", ""),
                    labels=[],
                    confidence=meta.get("confidence", 0.8)
                )

        # No grading found
        return None
