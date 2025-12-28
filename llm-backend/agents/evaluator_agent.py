"""
EVALUATOR Agent

This is the most complex agent with 5 key responsibilities:
1. Evaluate student response and provide feedback
2. Update step statuses based on performance
3. Track assessment notes
4. Handle off-topic responses
5. Decide if replanning is needed

This agent acts as the traffic controller for the workflow.

Uses:
- GPT-5.2 with reasoning_effort="medium" for balanced evaluation
- Strict structured output via json_schema for guaranteed schema adherence
- evaluator.txt template (5 sections)
"""

from typing import Dict, Any
import json
import logging
from workflows.state import SimplifiedState
from workflows.helpers import (
    get_current_step,
    update_plan_statuses,
    get_relevant_context,
    get_timestamp,
)
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class EvaluatorAgent(BaseAgent):
    """
    Evaluates student responses and controls workflow routing.

    Features:
    - GPT-5.2 with medium reasoning for balanced evaluation logic
    - Strict structured output via json_schema for guaranteed schema adherence
    - Multi-faceted evaluation (score, feedback, reasoning)
    - Step status management
    - Assessment note tracking
    - Off-topic detection and redirection
    - Replanning decision logic
    - Comprehensive output validation
    """

    # Pre-computed strict schema for GPT-5.2 structured output
    from agents.llm_schemas import EVALUATOR_STRICT_SCHEMA
    _STRICT_SCHEMA = EVALUATOR_STRICT_SCHEMA

    @property
    def agent_name(self) -> str:
        return "evaluator"

    def execute_internal(
        self, state: SimplifiedState
    ) -> tuple[SimplifiedState, Dict[str, Any], str, str]:
        """
        Execute EVALUATOR agent.

        Gets student response, current step, renders prompt,
        calls GPT-4o, parses complex output, updates plan statuses,
        appends assessment notes, handles off-topic, sets control flags.

        Args:
            state: Current workflow state

        Returns:
            Tuple of (updated_state, output, reasoning, input_summary)
        """
        # Get student's last message
        conversation = state.get("conversation", [])
        if not conversation:
            raise ValueError("No conversation to evaluate")

        last_message = conversation[-1]
        if last_message.get("role") != "student":
            raise ValueError("Last message must be from student")

        student_response = last_message.get("content", "")

        # Get current step
        current_step = get_current_step(state["study_plan"])
        if not current_step:
            logger.warning("No current step found during evaluation")
            raise ValueError("No current step to evaluate against")

        logger.info(f"Evaluating response for step: {current_step.get('title')}")

        # Get the question that was asked (second to last message)
        question_asked = ""
        if len(conversation) >= 2:
            tutor_message = conversation[-2]
            if tutor_message.get("role") == "tutor":
                question_asked = tutor_message.get("content", "")

        # Build prompt variables
        student_profile = state["student_profile"]
        status_info = current_step.get("status_info", {})

        relevant_conversation = get_relevant_context(list(conversation), max_messages=10)
        conversation_text = "\n".join(
            [
                f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
                for msg in relevant_conversation
            ]
        )

        variables = {
            "guidelines": state["guidelines"],
            "student_response": student_response,
            "question_asked": question_asked or "No specific question",
            "step_title": current_step.get("title", ""),
            "step_description": current_step.get("description", ""),
            "success_criteria": current_step.get("success_criteria", ""),
            "step_status": current_step.get("status", "pending"),
            "questions_asked": status_info.get("questions_asked", 0),
            "questions_correct": status_info.get("questions_correct", 0),
            "attempts": status_info.get("attempts", 0),
            "full_plan": json.dumps(state["study_plan"], indent=2),
            "assessment_notes": state.get("assessment_notes", "No notes yet"),
            "recent_conversation": conversation_text,
        }

        # Render prompt
        prompt = self._render_prompt("evaluator", variables)

        # Call GPT-5.2 with medium reasoning for evaluation
        logger.info("Calling GPT-5.2 (reasoning=medium) for evaluation...")
        llm_response = self.llm_service.call_gpt_5_2(
            prompt=prompt,
            reasoning_effort="medium",
            json_schema=self._STRICT_SCHEMA,
            schema_name="EvaluatorOutput",
        )
        response = llm_response["output_text"]

        # Parse response
        eval_output = self._parse_evaluator_output(response)

        # Update plan statuses
        try:
            updated_plan = update_plan_statuses(
                state["study_plan"],
                eval_output["updated_step_statuses"],
                eval_output["updated_status_info"],
            )
        except ValueError as e:
            logger.error(f"Failed to update plan statuses: {e}")
            raise

        # Append assessment note
        current_notes = state.get("assessment_notes", "")
        new_note = eval_output["assessment_note"]
        updated_notes = (current_notes + "\n\n" + new_note).strip()

        # Choose feedback message (off-topic vs normal)
        feedback_message = (
            eval_output["off_topic_response"]
            if eval_output["was_off_topic"]
            else eval_output["feedback"]
        )

        # Add feedback to conversation
        feedback_msg = {
            "role": "tutor",
            "content": feedback_message,
            "timestamp": get_timestamp(),
        }

        # Update state
        updated_state = {
            **state,
            "study_plan": updated_plan,
            "assessment_notes": updated_notes,
            "conversation": state.get("conversation", []) + [feedback_msg],
            "replan_needed": eval_output["replan_needed"],
            "replan_reason": eval_output.get("replan_reason"),
            "last_updated_at": get_timestamp(),
        }

        reasoning = eval_output.get("reasoning", "")
        input_summary = (
            f"Evaluate response for {current_step.get('title')}: "
            f"Score {eval_output['score']:.2f}, "
            f"Replan={eval_output['replan_needed']}"
        )

        return updated_state, eval_output, reasoning, input_summary

    def _parse_evaluator_output(self, output_text: str) -> Dict[str, Any]:
        """
        Parse and validate EVALUATOR output.

        This is the most complex output with many fields.

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
            logger.error(f"Failed to parse evaluator output: {e}")
            raise ValueError(f"Invalid evaluator output: {str(e)}")

        # Validate required fields
        required_fields = [
            "score",
            "feedback",
            "reasoning",
            "updated_step_statuses",
            "updated_status_info",
            "assessment_note",
            "was_off_topic",
            "replan_needed",
        ]

        for field in required_fields:
            if field not in output:
                raise ValueError(f"Evaluator output missing required field: {field}")

        # Validate score (0.0 - 1.0)
        try:
            score = float(output["score"])
            if not (0.0 <= score <= 1.0):
                raise ValueError(f"Score must be between 0.0 and 1.0, got {score}")
            output["score"] = score
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid score value: {e}")

        # Validate step statuses
        if not isinstance(output["updated_step_statuses"], dict):
            raise ValueError("'updated_step_statuses' must be a dictionary")

        valid_statuses = {"pending", "in_progress", "completed", "blocked"}
        for step_id, status in output["updated_step_statuses"].items():
            if status not in valid_statuses:
                raise ValueError(f"Invalid status '{status}' for step {step_id}")

        # Validate status_info
        if not isinstance(output["updated_status_info"], dict):
            raise ValueError("'updated_status_info' must be a dictionary")

        # Validate booleans
        if not isinstance(output["was_off_topic"], bool):
            output["was_off_topic"] = bool(output["was_off_topic"])

        if not isinstance(output["replan_needed"], bool):
            output["replan_needed"] = bool(output["replan_needed"])

        # Validate conditional fields
        if output["was_off_topic"]:
            if "off_topic_response" not in output or not output["off_topic_response"]:
                raise ValueError("'off_topic_response' required when was_off_topic=true")
        else:
            output["off_topic_response"] = None

        if output["replan_needed"]:
            if "replan_reason" not in output or not output["replan_reason"]:
                raise ValueError("'replan_reason' required when replan_needed=true")
        else:
            output["replan_reason"] = None

        # Ensure assessment_note has timestamp
        if "2024-" not in output["assessment_note"]:
            current_time = get_timestamp()
            output["assessment_note"] = f"{current_time} - {output['assessment_note']}"

        return output
