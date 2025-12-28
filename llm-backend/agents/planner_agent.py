"""
PLANNER Agent

This agent creates or updates the comprehensive study plan using GPT-5.2 with deep reasoning.

Responsibilities:
- Initial planning at session start
- Replanning when triggered by EVALUATOR
- Strategic thinking about learning sequence
- Adaptation to student profile

Uses:
- GPT-5.2 with reasoning_effort="high" for strategic planning
- Strict structured output via json_schema for guaranteed schema adherence
- planner_initial.txt or planner_replan.txt templates
"""

from typing import Dict, Any
import json
import logging
from workflows.state import SimplifiedState
from workflows.helpers import get_timestamp, generate_step_id
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    """
    Creates or updates study plans with strategic thinking.

    Features:
    - GPT-5.2 with high reasoning for deep strategic thinking
    - Strict structured output via json_schema for guaranteed schema adherence
    - Adaptive replanning based on feedback
    - Student-centered approach
    - Realistic pacing estimation
    """

    # Pre-computed strict schema for GPT-5.2 structured output
    from agents.llm_schemas import PLANNER_STRICT_SCHEMA
    _STRICT_SCHEMA = PLANNER_STRICT_SCHEMA

    @property
    def agent_name(self) -> str:
        return "planner"

    def execute_internal(
        self, state: SimplifiedState
    ) -> tuple[SimplifiedState, Dict[str, Any], str, str]:
        """
        Execute PLANNER agent.

        Determines if this is initial planning or replanning,
        renders appropriate prompt, calls GPT-4o, parses output,
        and updates state.

        SAFETY GUARD: If a plan already exists and replan_needed=False,
        this should not be called (indicates routing bug). Return
        current state unchanged with warning.

        Args:
            state: Current workflow state

        Returns:
            Tuple of (updated_state, output, reasoning, input_summary)
        """
        is_replanning = state.get("replan_needed", False)
        existing_plan = state.get("study_plan", {})
        has_existing_plan = existing_plan and existing_plan.get("todo_list")

        # SAFETY GUARD: Don't regenerate plan if one exists and no replan requested
        if has_existing_plan and not is_replanning:
            logger.warning(
                "⚠️  PLANNER called with existing plan and replan_needed=False. "
                "This indicates a routing issue. Returning current state unchanged."
            )
            return (
                state,
                {
                    "todo_list": existing_plan.get("todo_list", []),
                    "metadata": existing_plan.get("metadata", {}),
                },
                "Skipped planning - plan already exists and no replan requested",
                "Safety guard: Preserved existing plan",
            )

        if is_replanning:
            return self._execute_replan(state)
        else:
            return self._execute_initial_plan(state)

    def _execute_initial_plan(
        self, state: SimplifiedState
    ) -> tuple[SimplifiedState, Dict[str, Any], str, str]:
        """Execute initial planning"""

        logger.info("Creating initial study plan...")

        # Build prompt variables
        student_profile = state["student_profile"]
        topic_info = state["topic_info"]
        session_context = state["session_context"]
        logger.info(f"Student profile: {student_profile}")

        # HARDCODED PROFILE FOR EXPERIMENTATION
        student_profile = {
            "id": "experiment_student",
            "name": "Alex",
            "grade": 3,
            "interests": ["Sports", "Cricket"],
            "learning_style": "Visual",
            "strengths": ["Creative thinking"],
            "challenges": ["Reading long texts", "Staying focused on abstract concepts"]
        }
        logger.info(f"OVERRIDE: Using hardcoded student profile: {student_profile}")

        variables = {
            "guidelines": state["guidelines"],
            "student_interests": ", ".join(student_profile.get("interests", [])),
            "learning_style": student_profile.get("learning_style", "visual"),
            "grade": student_profile.get("grade", 4),
            "student_strengths": ", ".join(student_profile.get("strengths", [])) or "To be discovered",
            "student_challenges": ", ".join(student_profile.get("challenges", [])) or "To be discovered",
            "topic": topic_info.get("topic", ""),
            "subtopic": topic_info.get("subtopic", ""),
            "topic_grade": topic_info.get("grade", student_profile.get("grade", 4)),
            "estimated_duration": session_context.get("estimated_duration_minutes", 20),
        }

        # Render prompt
        prompt = self._render_prompt("planner_initial", variables)

        # Call GPT-5.2 with high reasoning for strategic planning
        logger.info("Calling GPT-5.2 (reasoning=high) for initial planning...")
        response = self.llm_service.call_gpt_5_2(
            prompt=prompt,
            reasoning_effort="high",
            json_schema=self._STRICT_SCHEMA,
            schema_name="PlannerOutput",
        )
        response_text = response["output_text"]

        # Parse response
        plan = self._parse_plan_output(response_text)

        # Ensure timestamps
        current_time = get_timestamp()
        if "metadata" not in plan:
            plan["metadata"] = {}
        plan["metadata"]["created_at"] = current_time
        plan["metadata"]["last_updated_at"] = current_time

        # Update state
        updated_state = {
            **state,
            "study_plan": plan,
            "replan_needed": False,
            "replan_reason": None,
            "last_updated_at": current_time,
        }

        output = {
            "todo_list": plan["todo_list"],
            "reasoning": plan.get("reasoning", ""),
            "metadata": plan.get("metadata", {}),
        }

        reasoning = plan.get("reasoning", "Initial planning completed")
        input_summary = f"Initial planning for {topic_info.get('topic')} - {topic_info.get('subtopic')}"

        return updated_state, output, reasoning, input_summary

    def _execute_replan(
        self, state: SimplifiedState
    ) -> tuple[SimplifiedState, Dict[str, Any], str, str]:
        """Execute replanning"""

        logger.info("Replanning study plan based on feedback...")

        # Build prompt variables
        student_profile = state["student_profile"]
        topic_info = state["topic_info"]

        # Get recent conversation (last 10 messages)
        recent_conversation = state.get("conversation", [])[-10:]
        conversation_text = "\n".join(
            [f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
             for msg in recent_conversation]
        )

        variables = {
            "guidelines": state["guidelines"],
            "student_interests": ", ".join(student_profile.get("interests", [])),
            "learning_style": student_profile.get("learning_style", "visual"),
            "grade": student_profile.get("grade", 4),
            "topic": topic_info.get("topic", ""),
            "subtopic": topic_info.get("subtopic", ""),
            "original_plan": json.dumps(state["study_plan"], indent=2),
            "assessment_notes": state.get("assessment_notes", "No notes yet"),
            "replan_reason": state.get("replan_reason", "Reason not specified"),
            "recent_conversation": conversation_text,
        }

        # Render prompt
        prompt = self._render_prompt("planner_replan", variables)

        # Call GPT-5.2 with high reasoning for replanning
        logger.info("Calling GPT-5.2 (reasoning=high) for replanning...")
        response = self.llm_service.call_gpt_5_2(
            prompt=prompt,
            reasoning_effort="high",
            json_schema=self._STRICT_SCHEMA,
            schema_name="PlannerOutput",
        )
        response_text = response["output_text"]

        # Parse response
        plan = self._parse_plan_output(response_text)

        # Increment replan count
        if "metadata" not in plan:
            plan["metadata"] = state["study_plan"].get("metadata", {})

        plan["metadata"]["plan_version"] = plan["metadata"].get("plan_version", 1) + 1
        plan["metadata"]["replan_count"] = plan["metadata"].get("replan_count", 0) + 1
        plan["metadata"]["last_updated_at"] = get_timestamp()

        # Update state
        updated_state = {
            **state,
            "study_plan": plan,
            "replan_needed": False,
            "replan_reason": None,
            "last_updated_at": get_timestamp(),
        }

        output = {
            "todo_list": plan["todo_list"],
            "reasoning": plan.get("reasoning", ""),
            "metadata": plan.get("metadata", {}),
            "changes_made": plan.get("changes_made", ""),
        }

        reasoning = plan.get("reasoning", "Replanning completed")
        input_summary = f"Replanning (version {plan['metadata']['plan_version']}): {state.get('replan_reason', '')[:100]}"

        return updated_state, output, reasoning, input_summary

    def _parse_plan_output(self, output_text: str) -> Dict[str, Any]:
        """
        Parse and validate PLANNER output.

        Args:
            output_text: JSON string from GPT-5.2

        Returns:
            Parsed plan dictionary

        Raises:
            ValueError: If output is invalid
        """
        try:
            plan = self.llm_service.parse_json_response(output_text)
        except Exception as e:
            logger.error(f"Failed to parse plan output: {e}")
            raise ValueError(f"Invalid plan output: {str(e)}")

        # Validate required fields
        if "todo_list" not in plan:
            raise ValueError("Plan missing 'todo_list'")

        if not isinstance(plan["todo_list"], list):
            raise ValueError("'todo_list' must be a list")

        if len(plan["todo_list"]) == 0:
            raise ValueError("'todo_list' cannot be empty")

        # Validate each step
        for i, step in enumerate(plan["todo_list"]):
            if "step_id" not in step:
                # Generate step_id if missing
                step["step_id"] = generate_step_id()

            if "status" not in step:
                step["status"] = "pending"

            if "status_info" not in step:
                step["status_info"] = {}

            # Validate required step fields
            required_fields = ["title", "description", "teaching_approach", "success_criteria"]
            for field in required_fields:
                if field not in step:
                    raise ValueError(f"Step {i} missing required field: {field}")

        # Validate metadata
        if "metadata" not in plan:
            plan["metadata"] = {}

        # Ensure metadata has required fields
        if "plan_version" not in plan["metadata"]:
            plan["metadata"]["plan_version"] = 1

        if "replan_count" not in plan["metadata"]:
            plan["metadata"]["replan_count"] = 0

        if "max_replans" not in plan["metadata"]:
            plan["metadata"]["max_replans"] = 3

        return plan
