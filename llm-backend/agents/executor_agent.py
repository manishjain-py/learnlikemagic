"""
EXECUTOR Agent

This agent generates the next teaching message based on the current plan state using GPT-4o.

Responsibilities:
- Generate questions for practice
- Provide explanations when needed
- Offer encouragement and hints
- Follow the teaching approach in the plan
- Stay faithful to the plan (no going rogue!)

Uses:
- GPT-4o for fast execution
- executor.txt template
"""

from typing import Dict, Any
import json
import logging
from workflows.state import SimplifiedState
from workflows.helpers import get_current_step, get_relevant_context, get_timestamp
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class ExecutorAgent(BaseAgent):
    """
    Generates teaching messages based on study plan.

    Features:
    - Context-aware message generation
    - Follows teaching approach from plan
    - Adapts to student profile
    - Tracks question numbering
    """

    @property
    def agent_name(self) -> str:
        return "executor"

    def execute_internal(
        self, state: SimplifiedState
    ) -> tuple[SimplifiedState, Dict[str, Any], str, str]:
        """
        Execute EXECUTOR agent.

        Gets current step, renders prompt with context,
        calls GPT-4o, parses output, adds message to conversation.

        Args:
            state: Current workflow state

        Returns:
            Tuple of (updated_state, output, reasoning, input_summary)
        """
        # Get current step
        current_step = get_current_step(state["study_plan"])

        if not current_step:
            logger.warning("No current step found - all steps may be completed")
            raise ValueError("No current step to generate message for")

        logger.info(f"Generating message for step: {current_step.get('title')}")

        # Build prompt variables
        student_profile = state["student_profile"]
        status_info = current_step.get("status_info", {})

        # Get relevant conversation context
        relevant_conversation = get_relevant_context(
            list(state.get("conversation", [])), max_messages=10
        )
        conversation_text = "\n".join(
            [
                f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
                for msg in relevant_conversation
            ]
        )

        # Calculate question number for this step
        question_number = status_info.get("questions_asked", 0) + 1

        variables = {
            "guidelines": state["guidelines"],
            "student_interests": ", ".join(student_profile.get("interests", [])),
            "learning_style": student_profile.get("learning_style", "visual"),
            "grade": student_profile.get("grade", 4),
            "step_title": current_step.get("title", ""),
            "step_description": current_step.get("description", ""),
            "teaching_approach": current_step.get("teaching_approach", ""),
            "success_criteria": current_step.get("success_criteria", ""),
            "questions_asked": status_info.get("questions_asked", 0),
            "questions_correct": status_info.get("questions_correct", 0),
            "assessment_notes": state.get("assessment_notes", "No notes yet"),
            "recent_conversation": conversation_text or "No conversation yet",
            "full_plan": json.dumps(state["study_plan"], indent=2),
            "current_step_id": current_step.get("step_id", ""),
        }

        # Render prompt
        prompt = self._render_prompt("executor", variables)

        # Call GPT-4o
        logger.info("Calling GPT-4o for message generation...")
        response = self.llm_service.call_gpt_4o(
            prompt=prompt, max_tokens=1024, temperature=0.7, json_mode=True
        )

        # Parse response
        output = self._parse_executor_output(response)

        # Ensure step_id is set
        if "step_id" not in output or not output["step_id"]:
            output["step_id"] = current_step["step_id"]

        # Ensure question_number is set
        if "question_number" not in output:
            output["question_number"] = question_number

        # Add message to conversation
        conversation_message = {
            "role": "tutor",
            "content": output["message"],
            "step_id": output["step_id"],
            "timestamp": get_timestamp(),
        }

        updated_state = {
            **state,
            "conversation": state.get("conversation", []) + [conversation_message],
            "last_updated_at": get_timestamp(),
        }

        reasoning = output.get("reasoning", "")
        input_summary = f"Generate message for step: {current_step.get('title')} (Q{question_number})"

        return updated_state, output, reasoning, input_summary

    def _parse_executor_output(self, output_text: str) -> Dict[str, Any]:
        """
        Parse and validate EXECUTOR output.

        Args:
            output_text: JSON string from GPT-4o

        Returns:
            Parsed output dictionary

        Raises:
            ValueError: If output is invalid
        """
        try:
            output = self.llm_service.parse_json_response(output_text)
        except Exception as e:
            logger.error(f"Failed to parse executor output: {e}")
            raise ValueError(f"Invalid executor output: {str(e)}")

        # Validate required fields
        required_fields = ["message", "reasoning", "meta"]
        for field in required_fields:
            if field not in output:
                raise ValueError(f"Executor output missing required field: {field}")

        # Validate meta
        if not isinstance(output["meta"], dict):
            raise ValueError("'meta' must be a dictionary")

        if "message_type" not in output["meta"]:
            output["meta"]["message_type"] = "question"

        if "difficulty" not in output["meta"]:
            output["meta"]["difficulty"] = "medium"

        # Validate message_type
        valid_types = {"question", "explanation", "encouragement", "hint", "summary"}
        if output["meta"]["message_type"] not in valid_types:
            logger.warning(
                f"Invalid message_type: {output['meta']['message_type']}. Defaulting to 'question'"
            )
            output["meta"]["message_type"] = "question"

        # Validate difficulty
        valid_difficulties = {"easy", "medium", "hard"}
        if output["meta"]["difficulty"] not in valid_difficulties:
            logger.warning(
                f"Invalid difficulty: {output['meta']['difficulty']}. Defaulting to 'medium'"
            )
            output["meta"]["difficulty"] = "medium"

        return output
