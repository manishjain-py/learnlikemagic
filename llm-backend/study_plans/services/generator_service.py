import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from shared.services import LLMService
from shared.models.entities import TeachingGuideline

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models for Strict Structured Output (GPT-5.2)
# =============================================================================

class StudyPlanStep(BaseModel):
    """A single step in the study plan."""
    step_id: str = Field(description="Unique identifier for the step (e.g., 'step_1')")
    title: str = Field(description="Brief, catchy title (e.g., 'Pizza Fraction Party')")
    description: str = Field(description="Short, fun description of the activity")
    teaching_approach: str = Field(description="Specific method (e.g., 'Visual + Gamification')")
    success_criteria: str = Field(description="Observable outcome that defines completion")
    status: str = Field(default="pending", description="Current status of the step")


class StudyPlanMetadata(BaseModel):
    """Metadata for the study plan."""
    plan_version: int = Field(default=1, description="Version of the plan")
    estimated_duration_minutes: int = Field(description="Estimated total duration in minutes")
    difficulty_level: str = Field(description="Difficulty level (e.g., 'grade-appropriate')")
    is_generic: bool = Field(default=True, description="Whether this is a generic plan")
    creative_theme: str = Field(default="", description="Optional theme (e.g., 'Space Adventure')")


class StudyPlan(BaseModel):
    """Complete study plan structure."""
    todo_list: List[StudyPlanStep] = Field(description="List of study plan steps (3-5 items)")
    metadata: StudyPlanMetadata = Field(description="Plan metadata")

class StudyPlanGeneratorService:
    """
    Service to generate generic study plans from teaching guidelines.

    Uses GPT-5.2 with high reasoning effort and strict schema validation
    for high-quality, structured study plan generation.
    """

    def __init__(self, llm_service: LLMService, prompt_loader):
        """
        Args:
            llm_service: Service for LLM calls (uses GPT-5.2 with high reasoning)
            prompt_loader: Utility to load prompt templates
        """
        self.llm_service = llm_service
        self.prompt_loader = prompt_loader

        # Pre-compute the strict schema for GPT-5.2 structured output
        self._study_plan_schema = LLMService.make_schema_strict(
            StudyPlan.model_json_schema()
        )

    def generate_plan(self, guideline: TeachingGuideline) -> Dict[str, Any]:
        """
        Generate a study plan for the given guideline.

        Args:
            guideline: The teaching guideline database model

        Returns:
            Dict containing:
                - plan: The generated JSON plan
                - reasoning: The model's generation reasoning
                - model: The model used
        """
        try:
            # 1. Load prompt template
            prompt_template = self.prompt_loader.load("study_plan_generator")
            
            # 2. Format prompt
            # Handle V2/V1 schema differences gracefully
            topic = guideline.topic_title or guideline.topic
            subtopic = guideline.subtopic_title or guideline.subtopic
            # Use the new comprehensive 'guideline' field if available, otherwise fallback
            guideline_text = guideline.guideline or guideline.description or ""

            prompt = prompt_template.format(
                topic=topic,
                subtopic=subtopic,
                grade=guideline.grade,
                guideline_text=guideline_text
            )

            logger.info(json.dumps({
                "step": "STUDY_PLAN_GENERATION",
                "status": "starting",
                "guideline_id": guideline.id,
                "topic": topic,
                "model": "gpt-5.2",
                "reasoning_effort": "high"
            }))

            # 3. Call LLM (GPT-5.2 with high reasoning and strict schema)
            response = self.llm_service.call_gpt_5_2(
                prompt=prompt,
                reasoning_effort="high",
                json_schema=self._study_plan_schema,
                schema_name="StudyPlan"
            )

            # 4. Parse Output (guaranteed to match schema due to strict mode)
            plan_json = self.llm_service.parse_json_response(response["output_text"])

            # 5. Validate with Pydantic model (additional type safety)
            validated_plan = StudyPlan.model_validate(plan_json)

            # 6. Convert back to dict for compatibility with existing code
            plan_dict = validated_plan.model_dump()

            # 7. Legacy schema validation (belt and suspenders)
            self._validate_plan_schema(plan_dict)

            # Convert reasoning object to string (OpenAI SDK returns a Reasoning object)
            reasoning_obj = response.get("reasoning")
            reasoning_str = ""
            if reasoning_obj is not None:
                # The Reasoning object may have a summary or text attribute
                if hasattr(reasoning_obj, "summary"):
                    reasoning_str = str(reasoning_obj.summary) if reasoning_obj.summary else ""
                elif hasattr(reasoning_obj, "text"):
                    reasoning_str = str(reasoning_obj.text) if reasoning_obj.text else ""
                else:
                    reasoning_str = str(reasoning_obj)

            logger.info(json.dumps({
                "step": "STUDY_PLAN_GENERATION",
                "status": "complete",
                "guideline_id": guideline.id,
                "model": "gpt-5.2",
                "has_reasoning": bool(reasoning_str)
            }))

            return {
                "plan": plan_dict,
                "reasoning": reasoning_str,
                "model": "gpt-5.2"
            }

        except Exception as e:
            logger.error(f"Failed to generate study plan: {str(e)}", exc_info=True)
            raise

    def _validate_plan_schema(self, plan: Dict[str, Any]) -> None:
        """Validate that the generated plan matches the expected schema."""
        required_fields = ["todo_list", "metadata"]
        for field in required_fields:
            if field not in plan:
                raise ValueError(f"Missing required field: {field}")
        
        if not isinstance(plan["todo_list"], list):
            raise ValueError("todo_list must be a list")
            
        if not plan["todo_list"]:
            raise ValueError("todo_list cannot be empty")
            
        # Validate todo items
        item_required = ["title", "description", "teaching_approach", "success_criteria"]
        for i, item in enumerate(plan["todo_list"]):
            for field in item_required:
                if field not in item:
                    raise ValueError(f"Item {i} matches missing field: {field}")
            
            # Ensure items have step_id
            if "step_id" not in item:
                from tutor.models.helpers import generate_step_id
                item["step_id"] = generate_step_id()
                
            # Default status
            if "status" not in item:
                item["status"] = "pending"
