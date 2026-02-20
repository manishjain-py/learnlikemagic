import json
import logging
from typing import Dict, Any
from shared.services import LLMService
from shared.models.entities import TeachingGuideline

logger = logging.getLogger(__name__)

class StudyPlanReviewerService:
    """
    Service to review generated study plans for quality assurance.
    """

    def __init__(self, llm_service: LLMService, prompt_loader):
        self.llm_service = llm_service
        self.prompt_loader = prompt_loader

    def review_plan(
        self, 
        plan_json: Dict[str, Any], 
        guideline: TeachingGuideline
    ) -> Dict[str, Any]:
        """
        Review a study plan.

        Args:
            plan_json: The plan to review
            guideline: The source guideline

        Returns:
            Dict containing:
                - approved: bool
                - feedback: str
                - suggested_improvements: list
                - model: str
        """
        try:
            # 1. Load prompt
            prompt_template = self.prompt_loader.load("study_plan_reviewer")

            # 2. Format prompt
            topic = guideline.topic_title or guideline.topic
            subtopic = guideline.subtopic_title or guideline.subtopic
            guideline_text = guideline.guideline or guideline.description or ""

            prompt = prompt_template.format(
                topic=topic,
                subtopic=subtopic,
                grade=guideline.grade,
                guideline_text=guideline_text,
                plan_json=json.dumps(plan_json, indent=2)
            )

            logger.info(json.dumps({
                "step": "STUDY_PLAN_REVIEW",
                "status": "starting",
                "guideline_id": guideline.id
            }))

            # 3. Call LLM with JSON mode
            response = self.llm_service.call(
                prompt=prompt,
                json_mode=True
            )

            # 4. Parse Output
            review_json = self.llm_service.parse_json_response(response["output_text"])

            logger.info(json.dumps({
                "step": "STUDY_PLAN_REVIEW",
                "status": "complete",
                "approved": review_json.get("approved", False),
                "rating": review_json.get("overall_rating")
            }))

            return {
                "approved": bool(review_json.get("approved", False)),
                "feedback": review_json.get("feedback", ""),
                "suggested_improvements": review_json.get("suggested_improvements", []),
                "overall_rating": review_json.get("overall_rating"),
                "model": self.llm_service.model_id
            }

        except Exception as e:
            logger.error(f"Failed to review study plan: {str(e)}", exc_info=True)
            # Fail safe: if review fails, we don't automatically approve, but we note the error
            raise
