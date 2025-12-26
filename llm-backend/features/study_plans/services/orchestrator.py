import json
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from services.llm_service import LLMService
from models.database import TeachingGuideline, StudyPlan
from features.study_plans.services.generator_service import StudyPlanGeneratorService
from features.study_plans.services.reviewer_service import StudyPlanReviewerService
from prompts.loader import PromptLoader

logger = logging.getLogger(__name__)

class StudyPlanOrchestrator:
    """
    Orchestrates the creation and lifecycle of study plans.
    """

    def __init__(self, db: Session, llm_service: LLMService):
        self.db = db
        self.llm_service = llm_service
        self.prompt_loader = PromptLoader() # Assuming this standard loader works
        self.generator = StudyPlanGeneratorService(llm_service, self.prompt_loader)
        self.reviewer = StudyPlanReviewerService(llm_service, self.prompt_loader)

    def get_study_plan(self, guideline_id: str) -> dict | None:
        """Get existing study plan for a guideline."""
        plan = self.db.query(StudyPlan).filter(StudyPlan.guideline_id == guideline_id).first()
        if plan:
            return json.loads(plan.plan_json)
        return None

    def generate_study_plan(self, guideline_id: str, force_regenerate: bool = False) -> dict:
        """
        Generate (or regenerate) a study plan for a guideline.
        Runs the Generate -> Review -> (Improve) loop.
        """
        # 1. Check if exists
        existing_plan = self.db.query(StudyPlan).filter(StudyPlan.guideline_id == guideline_id).first()
        if existing_plan and not force_regenerate:
            logger.info(f"Study plan for {guideline_id} already exists. Returning existing.")
            return json.loads(existing_plan.plan_json)

        # 2. Load Guideline
        guideline = self.db.query(TeachingGuideline).filter(TeachingGuideline.id == guideline_id).first()
        if not guideline:
            raise ValueError(f"Guideline {guideline_id} not found")

        logger.info(f"Starting generic study plan generation for {guideline.topic}/{guideline.subtopic}")

        # 3. Generate Initial Plan
        gen_result = self.generator.generate_plan(guideline)
        current_plan = gen_result["plan"]
        gen_reasoning = gen_result["reasoning"]
        gen_model = gen_result["model"]

        # 4. Review Plan
        review_result = self.reviewer.review_plan(current_plan, guideline)
        
        final_plan = current_plan
        was_revised = False
        
        # 5. Improvement Loop (Single Pass)
        if not review_result["approved"]:
            logger.info(f"Plan not approved. Attempting revision. Feedback: {review_result['feedback']}")
            try:
                final_plan = self._improve_plan(current_plan, review_result, guideline)
                was_revised = True
                logger.info("Plan revised successfully.")
            except Exception as e:
                logger.error(f"Failed to improve plan: {e}. Saving original with warning.")
                # We save it anyway but maybe mark status? For now just save.

        # 6. Save to DB
        plan_json_str = json.dumps(final_plan)
        
        if existing_plan:
            # Update
            existing_plan.plan_json = plan_json_str
            existing_plan.generator_model = gen_model
            existing_plan.reviewer_model = review_result["model"]
            existing_plan.generation_reasoning = gen_reasoning
            existing_plan.reviewer_feedback = review_result["feedback"]
            existing_plan.was_revised = 1 if was_revised else 0
            existing_plan.version += 1
            existing_plan.updated_at = datetime.utcnow()
        else:
            # Create
            new_plan = StudyPlan(
                id=f"sp_{guideline_id}_{int(datetime.utcnow().timestamp())}", # Simple ID generation
                guideline_id=guideline_id,
                plan_json=plan_json_str,
                generator_model=gen_model,
                reviewer_model=review_result["model"],
                generation_reasoning=gen_reasoning,
                reviewer_feedback=review_result["feedback"],
                was_revised=1 if was_revised else 0,
                version=1
            )
            self.db.add(new_plan)
        
        self.db.commit()
        
        return final_plan

    def _improve_plan(
        self,
        current_plan: dict,
        review_result: dict,
        guideline: TeachingGuideline
    ) -> dict:
        """Helper to call LLM for plan improvement."""
        prompt_template = self.prompt_loader.load("study_plan_improve")

        topic = guideline.topic_title or guideline.topic
        subtopic = guideline.subtopic_title or guideline.subtopic
        guideline_text = guideline.guideline or guideline.description or ""

        prompt = prompt_template.format(
            topic=topic,
            subtopic=subtopic,
            grade=guideline.grade,
            guideline_text=guideline_text,
            current_plan_json=json.dumps(current_plan, indent=2),
            feedback=review_result["feedback"],
            suggested_improvements=json.dumps(review_result["suggested_improvements"], indent=2)
        )

        # Call GPT-4o with JSON mode
        response_text = self.llm_service.call_gpt_4o(
            prompt=prompt,
            max_tokens=4096,
            json_mode=True
        )

        # Parse and return
        return self.llm_service.parse_json_response(response_text)
