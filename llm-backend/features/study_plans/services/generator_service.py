import json
import logging
from typing import Dict, Any
from services.llm_service import LLMService
from models.database import TeachingGuideline

logger = logging.getLogger(__name__)

class StudyPlanGeneratorService:
    """
    Service to generate generic study plans from teaching guidelines using heavy-reasoning credentials.
    """

    def __init__(self, llm_service: LLMService, prompt_loader):
        """
        Args:
            llm_service: Service for LLM calls (GPT-5.1)
            prompt_loader: Utility to load prompt templates
        """
        self.llm_service = llm_service
        self.prompt_loader = prompt_loader

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
                "topic": topic
            }))

            # 3. Call LLM (GPT-4o with JSON mode)
            response_text = self.llm_service.call_gpt_4o(
                prompt=prompt,
                max_tokens=4096,
                json_mode=True
            )

            # 4. Parse Output
            plan_json = self.llm_service.parse_json_response(response_text)

            # 5. Schema Validation
            self._validate_plan_schema(plan_json)

            logger.info(json.dumps({
                "step": "STUDY_PLAN_GENERATION",
                "status": "complete",
                "guideline_id": guideline.id
            }))

            return {
                "plan": plan_json,
                "reasoning": "",
                "model": "gpt-4o"
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
                from workflows.helpers import generate_step_id
                item["step_id"] = generate_step_id()
                
            # Default status
            if "status" not in item:
                item["status"] = "pending"
