"""
LLM Output Schemas for GPT-5.2 Structured Output

These Pydantic models define the exact output format expected from GPT-5.2.
They are intentionally simpler than the validation schemas in workflows/schemas.py
because they only include fields the LLM should generate.

Usage:
    from agents.llm_schemas import (
        PlannerLLMOutput, PLANNER_STRICT_SCHEMA,
        ExecutorLLMOutput, EXECUTOR_STRICT_SCHEMA,
        EvaluatorLLMOutput, EVALUATOR_STRICT_SCHEMA,
    )

    response = llm_service.call_gpt_5_2(
        prompt=prompt,
        json_schema=PLANNER_STRICT_SCHEMA,
        schema_name="PlannerOutput",
        reasoning_effort="high",
    )
"""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


def _make_schema_strict(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform a JSON schema to meet OpenAI's strict mode requirements.

    OpenAI's structured output with strict=true requires:
    1. All objects must have additionalProperties: false
    2. All properties must be in the required array
    3. $defs references must also be transformed
    4. $ref cannot have sibling keywords (like description)

    This is a local copy of LLMService.make_schema_strict() to avoid
    circular imports.

    Args:
        schema: Original JSON schema (e.g., from Pydantic's model_json_schema())

    Returns:
        Transformed schema meeting OpenAI's strict requirements
    """
    def transform(obj: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(obj, dict):
            return obj

        # If this object has a $ref, remove sibling keywords
        # OpenAI requires $ref to be alone (no description, title, etc.)
        if "$ref" in obj:
            return {"$ref": obj["$ref"]}

        result = {}
        for key, value in obj.items():
            if key == "$defs":
                # Transform all definitions
                result[key] = {k: transform(v) for k, v in value.items()}
            elif isinstance(value, dict):
                result[key] = transform(value)
            elif isinstance(value, list):
                result[key] = [
                    transform(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value

        # If this is an object type, add strict requirements
        if result.get("type") == "object" and "properties" in result:
            result["additionalProperties"] = False
            # All properties must be required in strict mode
            result["required"] = list(result["properties"].keys())

        return result

    return transform(schema)


# === Step Status Types ===
StepStatus = Literal["pending", "in_progress", "completed", "blocked"]
MessageType = Literal["question", "explanation", "encouragement", "hint", "summary"]
Difficulty = Literal["easy", "medium", "hard"]


# =============================================================================
# PLANNER OUTPUT SCHEMA
# =============================================================================

class PlannerStepOutput(BaseModel):
    """Step structure expected from PLANNER LLM output."""

    step_id: str = Field(description="Unique identifier for this step (e.g., 'step_1')")
    title: str = Field(description="Fun, engaging step title")
    description: str = Field(description="Detailed description of what to teach")
    teaching_approach: str = Field(description="Specific creative teaching approach")
    success_criteria: str = Field(description="Clear criteria for step completion")
    status: StepStatus = Field(default="pending", description="Step status (always 'pending' for new plans)")


class PlannerMetadataOutput(BaseModel):
    """Metadata structure expected from PLANNER LLM output."""

    plan_version: int = Field(default=1, description="Plan version number")
    estimated_total_questions: int = Field(description="Estimated total questions in session")
    estimated_duration_minutes: int = Field(description="Estimated session duration in minutes")
    replan_count: int = Field(default=0, description="Number of times plan has been revised")
    max_replans: int = Field(default=3, description="Maximum allowed replans")


class PlannerLLMOutput(BaseModel):
    """
    Complete output structure for PLANNER agent (GPT-5.2 with high reasoning).

    Used for both initial planning and replanning.
    """

    todo_list: List[PlannerStepOutput] = Field(
        description="List of 3-5 learning steps"
    )
    reasoning: str = Field(
        description="Deep thinking about why this plan was created, creative choices, and sequencing rationale"
    )
    metadata: PlannerMetadataOutput = Field(
        description="Plan metadata including version and estimates"
    )
    changes_made: Optional[str] = Field(
        default=None,
        description="Summary of changes (only for replanning, null for initial plans)"
    )


# =============================================================================
# EXECUTOR OUTPUT SCHEMA
# =============================================================================

class ExecutorMetaOutput(BaseModel):
    """Meta information for executor message."""

    message_type: MessageType = Field(
        description="Type of message being sent"
    )
    difficulty: Difficulty = Field(
        description="Difficulty level of the content"
    )


class ExecutorLLMOutput(BaseModel):
    """
    Complete output structure for EXECUTOR agent (GPT-5.2 with none reasoning).

    Fast execution for generating teaching messages.
    """

    message: str = Field(
        description="The teaching message to send to the student"
    )
    reasoning: str = Field(
        description="Brief reasoning for why this message was chosen"
    )
    step_id: str = Field(
        description="ID of the step this message addresses"
    )
    question_number: int = Field(
        description="Question number within the current step"
    )
    meta: ExecutorMetaOutput = Field(
        description="Metadata about the message type and difficulty"
    )


# =============================================================================
# EVALUATOR OUTPUT SCHEMA
# =============================================================================

class EvaluatorStatusInfo(BaseModel):
    """Status info updates for a step."""

    questions_asked: int = Field(description="Total questions asked for this step")
    questions_correct: int = Field(description="Total correct answers for this step")
    attempts: int = Field(description="Total attempts for this step")


class EvaluatorLLMOutput(BaseModel):
    """
    Complete output structure for EVALUATOR agent (GPT-5.2 with medium reasoning).

    Handles 5 responsibilities:
    1. Evaluate student response
    2. Update step statuses
    3. Track assessment notes
    4. Handle off-topic responses
    5. Decide if replanning is needed
    """

    # 1. Evaluation
    score: float = Field(
        description="Response score from 0.0 to 1.0"
    )
    feedback: str = Field(
        description="Feedback message for the student"
    )
    reasoning: str = Field(
        description="Internal reasoning for the evaluation"
    )

    # 2. Step status updates
    updated_step_statuses: Dict[str, StepStatus] = Field(
        description="Map of step_id to new status"
    )
    updated_status_info: Dict[str, EvaluatorStatusInfo] = Field(
        description="Map of step_id to status info updates"
    )

    # 3. Assessment tracking
    assessment_note: str = Field(
        description="Timestamped observation to append to assessment notes"
    )

    # 4. Off-topic handling
    was_off_topic: bool = Field(
        description="Whether the student response was off-topic"
    )
    off_topic_response: Optional[str] = Field(
        default=None,
        description="Friendly redirect message if response was off-topic"
    )

    # 5. Replanning decision
    replan_needed: bool = Field(
        description="Whether replanning is needed"
    )
    replan_reason: Optional[str] = Field(
        default=None,
        description="Reason for replanning if needed"
    )


# =============================================================================
# PRE-COMPUTED STRICT SCHEMAS
# =============================================================================

# Generate strict schemas once at module load time for efficiency
PLANNER_STRICT_SCHEMA = _make_schema_strict(
    PlannerLLMOutput.model_json_schema()
)

EXECUTOR_STRICT_SCHEMA = _make_schema_strict(
    ExecutorLLMOutput.model_json_schema()
)

EVALUATOR_STRICT_SCHEMA = _make_schema_strict(
    EvaluatorLLMOutput.model_json_schema()
)
