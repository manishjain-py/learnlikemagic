import json
import logging
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from pydantic import BaseModel, Field
from shared.services import LLMService
from shared.models.entities import TeachingGuideline

if TYPE_CHECKING:
    from tutor.models.messages import StudentContext

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models for Strict Structured Output
# =============================================================================

class StudyPlanStep(BaseModel):
    """A single step in the study plan."""
    step_id: str = Field(description="Unique identifier for the step (e.g., 'step_1')")
    title: str = Field(description="Brief, catchy title (e.g., 'Pizza Fraction Party')")
    description: str = Field(description="Short, fun description of the activity")
    teaching_approach: str = Field(description="Specific method (e.g., 'Visual + Gamification')")
    success_criteria: str = Field(description="Observable outcome that defines completion")
    building_blocks: List[str] = Field(default_factory=list, description="Ordered sub-ideas to cover (simplest to complex)")
    analogy: str = Field(default="", description="Age-appropriate real-world connection")
    status: str = Field(default="pending", description="Current status of the step")


class StudyPlanMetadata(BaseModel):
    """Metadata for the study plan."""
    plan_version: int = Field(default=1, description="Version of the plan")
    estimated_duration_minutes: int = Field(description="Estimated total duration in minutes")
    difficulty_level: str = Field(description="Difficulty level (e.g., 'grade-appropriate')")
    is_generic: bool = Field(default=True, description="Whether this is a generic plan")
    creative_theme: str = Field(default="", description="Optional theme (e.g., 'Space Adventure')")


# v2 session plan models

class SessionPlanStep(BaseModel):
    """A single step in a v2 session plan (post-explanation interactive)."""
    step_id: int = Field(description="Step number (1-indexed)")
    type: str = Field(description="Step type: check_understanding, guided_practice, independent_practice, extend")
    concept: str = Field(description="What concept/skill this step focuses on")
    description: str = Field(description="What the tutor should do in this step")
    card_references: List[str] = Field(default_factory=list, description="Card concepts/analogies to reference")
    misconceptions_to_probe: List[str] = Field(default_factory=list, description="What errors to watch for")
    success_criteria: str = Field(default="", description="How to know the student has passed this step")
    difficulty: str = Field(default="easy", description="easy, medium, or hard")
    personalization_hint: str = Field(default="", description="How to use student interests")


class SessionPlanMetadata(BaseModel):
    """Metadata for v2 session plan."""
    plan_version: int = Field(default=2, description="Always 2 for session plans")
    variants_shown: List[str] = Field(default_factory=list, description="Which explanation variants the student saw")
    estimated_duration_minutes: int = Field(default=20, description="Estimated duration")
    is_generic: bool = Field(default=True, description="Whether personalized to student")


class SessionPlan(BaseModel):
    """V2 session plan structure (post-explanation interactive)."""
    steps: List[SessionPlanStep] = Field(description="List of interactive steps (3-5)")
    metadata: SessionPlanMetadata = Field(description="Plan metadata")


class StudyPlan(BaseModel):
    """Complete study plan structure."""
    todo_list: List[StudyPlanStep] = Field(description="List of study plan steps (3-5 items)")
    metadata: StudyPlanMetadata = Field(description="Plan metadata")

class StudyPlanGeneratorService:
    """
    Service to generate generic study plans from teaching guidelines.

    Uses high reasoning effort and strict schema validation
    for high-quality, structured study plan generation.
    """

    def __init__(self, llm_service: LLMService, prompt_loader):
        """
        Args:
            llm_service: Service for LLM calls (uses high reasoning effort)
            prompt_loader: Utility to load prompt templates
        """
        self.llm_service = llm_service
        self.prompt_loader = prompt_loader

        # Pre-compute the strict schema for structured output
        self._study_plan_schema = LLMService.make_schema_strict(
            StudyPlan.model_json_schema()
        )
        self._session_plan_schema = LLMService.make_schema_strict(
            SessionPlan.model_json_schema()
        )

    def generate_plan(self, guideline: TeachingGuideline, student_context: Optional["StudentContext"] = None) -> Dict[str, Any]:
        """
        Generate a study plan for the given guideline.

        Args:
            guideline: The teaching guideline database model
            student_context: Optional student context for personalization

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
            chapter = guideline.chapter_title or guideline.chapter
            topic = guideline.topic_title or guideline.topic
            guideline_text = guideline.guideline or guideline.description or ""

            prompt = prompt_template.format(
                chapter=chapter,
                topic=topic,
                grade=guideline.grade,
                guideline_text=guideline_text,
                student_personality_section=self._build_personality_section(student_context),
            )

            logger.info(json.dumps({
                "step": "STUDY_PLAN_GENERATION",
                "status": "starting",
                "guideline_id": guideline.id,
                "topic": topic,
                "model": self.llm_service.model_id,
                "reasoning_effort": "high"
            }))

            # 3. Call LLM (uses provider/model from DB config)
            response = self.llm_service.call(
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
                "model": self.llm_service.model_id,
                "has_reasoning": bool(reasoning_str)
            }))

            return {
                "plan": plan_dict,
                "reasoning": reasoning_str,
                "model": self.llm_service.model_id
            }

        except Exception as e:
            logger.error(f"Failed to generate study plan: {str(e)}", exc_info=True)
            raise

    def generate_plan_with_feedback(
        self,
        guideline: TeachingGuideline,
        student_context: Optional["StudentContext"],
        feedback_text: str,
        concepts_covered: List[str],
        current_step: int,
        total_steps: int,
    ) -> Dict[str, Any]:
        """Generate a new study plan adjusted for mid-session feedback.

        Same as generate_plan() but appends feedback context to the personality section.
        Skips the reviewer pass for speed.
        """
        try:
            prompt_template = self.prompt_loader.load("study_plan_generator")

            chapter = guideline.chapter_title or guideline.chapter
            topic = guideline.topic_title or guideline.topic
            guideline_text = guideline.guideline or guideline.description or ""

            personality_section = self._build_personality_section(student_context)
            feedback_section = self._build_feedback_section(
                feedback_text, concepts_covered, current_step, total_steps
            )

            prompt = prompt_template.format(
                chapter=chapter,
                topic=topic,
                grade=guideline.grade,
                guideline_text=guideline_text,
                student_personality_section=personality_section + feedback_section,
            )

            logger.info(json.dumps({
                "step": "STUDY_PLAN_FEEDBACK_GENERATION",
                "status": "starting",
                "guideline_id": guideline.id,
                "topic": topic,
                "model": self.llm_service.model_id,
            }))

            response = self.llm_service.call(
                prompt=prompt,
                reasoning_effort="high",
                json_schema=self._study_plan_schema,
                schema_name="StudyPlan"
            )

            plan_json = self.llm_service.parse_json_response(response["output_text"])
            validated_plan = StudyPlan.model_validate(plan_json)
            plan_dict = validated_plan.model_dump()
            self._validate_plan_schema(plan_dict)

            reasoning_obj = response.get("reasoning")
            reasoning_str = ""
            if reasoning_obj is not None:
                if hasattr(reasoning_obj, "summary"):
                    reasoning_str = str(reasoning_obj.summary) if reasoning_obj.summary else ""
                elif hasattr(reasoning_obj, "text"):
                    reasoning_str = str(reasoning_obj.text) if reasoning_obj.text else ""
                else:
                    reasoning_str = str(reasoning_obj)

            logger.info(json.dumps({
                "step": "STUDY_PLAN_FEEDBACK_GENERATION",
                "status": "complete",
                "guideline_id": guideline.id,
            }))

            return {
                "plan": plan_dict,
                "reasoning": reasoning_str,
                "model": self.llm_service.model_id,
            }

        except Exception as e:
            logger.error(f"Failed to generate feedback plan: {str(e)}", exc_info=True)
            raise

    def generate_session_plan(
        self,
        guideline: TeachingGuideline,
        explanation_summaries: List[Dict[str, Any]],
        card_titles: List[str],
        variants_shown: List[str],
        student_context: Optional["StudentContext"] = None,
    ) -> Dict[str, Any]:
        """Generate a v2 session plan based on explanation cards the student just read.

        Called at card phase completion — after the student reads cards and says "I understand".

        Args:
            guideline: Teaching guideline for the topic
            explanation_summaries: summary_json dicts for each variant shown
            card_titles: Ordered card titles from the final variant
            variants_shown: Which variant keys the student saw (e.g., ["A"] or ["A", "B"])
            student_context: Optional student profile for personalization
        """
        try:
            prompt_template = self.prompt_loader.load("session_plan_generator")

            chapter = guideline.chapter_title or guideline.chapter
            topic = guideline.topic_title or guideline.topic
            guideline_text = guideline.guideline or guideline.description or ""

            # Build explanation context from summaries
            teaching_notes_parts = []
            all_analogies = []
            all_examples = []
            approach_labels = []
            for s in explanation_summaries:
                if s.get("teaching_notes"):
                    teaching_notes_parts.append(s["teaching_notes"])
                all_analogies.extend(s.get("key_analogies", []))
                all_examples.extend(s.get("key_examples", []))
                if s.get("approach_label"):
                    approach_labels.append(s["approach_label"])

            teaching_notes = "\n".join(teaching_notes_parts) or "No teaching notes available."
            key_analogies = ", ".join(all_analogies) or "None"
            key_examples = ", ".join(all_examples) or "None"
            approach_label = ", ".join(approach_labels) or "Standard"

            card_titles_formatted = "\n".join(
                f"  {i+1}. {t}" for i, t in enumerate(card_titles)
            ) or "  (no card titles available)"

            # Common misconceptions from guideline metadata
            metadata = guideline.guideline_metadata_json or {}
            misconceptions = metadata.get("common_misconceptions", [])
            common_misconceptions = "\n".join(f"- {m}" for m in misconceptions) if misconceptions else "None specified"

            prompt = prompt_template.format(
                topic=topic,
                grade=guideline.grade,
                approach_label=approach_label,
                card_titles_formatted=card_titles_formatted,
                teaching_notes=teaching_notes,
                key_analogies=key_analogies,
                key_examples=key_examples,
                guideline_text=guideline_text,
                common_misconceptions=common_misconceptions,
                student_personality_section=self._build_personality_section(student_context),
            )

            logger.info(json.dumps({
                "step": "SESSION_PLAN_GENERATION",
                "status": "starting",
                "guideline_id": guideline.id,
                "topic": topic,
                "variants_shown": variants_shown,
            }))

            response = self.llm_service.call(
                prompt=prompt,
                reasoning_effort="high",
                json_schema=self._session_plan_schema,
                schema_name="SessionPlan",
            )

            plan_json = self.llm_service.parse_json_response(response["output_text"])
            validated_plan = SessionPlan.model_validate(plan_json)

            # Ensure metadata has correct version and variants
            plan_dict = validated_plan.model_dump()
            plan_dict["metadata"]["plan_version"] = 2
            plan_dict["metadata"]["variants_shown"] = variants_shown
            if student_context and student_context.student_name:
                plan_dict["metadata"]["is_generic"] = False

            reasoning_obj = response.get("reasoning")
            reasoning_str = ""
            if reasoning_obj is not None:
                if hasattr(reasoning_obj, "summary"):
                    reasoning_str = str(reasoning_obj.summary) if reasoning_obj.summary else ""
                elif hasattr(reasoning_obj, "text"):
                    reasoning_str = str(reasoning_obj.text) if reasoning_obj.text else ""
                else:
                    reasoning_str = str(reasoning_obj)

            logger.info(json.dumps({
                "step": "SESSION_PLAN_GENERATION",
                "status": "complete",
                "guideline_id": guideline.id,
                "steps_count": len(plan_dict.get("steps", [])),
            }))

            return {
                "plan": plan_dict,
                "reasoning": reasoning_str,
                "model": self.llm_service.model_id,
            }

        except Exception as e:
            logger.error(f"Failed to generate session plan: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def _build_feedback_section(
        feedback_text: str,
        concepts_covered: List[str],
        current_step: int,
        total_steps: int,
    ) -> str:
        """Build the feedback context string to append to the prompt."""
        covered_str = ", ".join(concepts_covered) if concepts_covered else "None yet"
        return (
            f"\n## Mid-Session Feedback (IMPORTANT - adjust the plan based on this)\n"
            f"- The student/parent provided this feedback: \"{feedback_text}\"\n"
            f"- Concepts already covered: {covered_str}\n"
            f"- Progress: step {current_step} of {total_steps}\n"
            f"- Do NOT repeat covered concepts. Adjust remaining plan per feedback.\n"
        )

    @staticmethod
    def _build_personality_section(student_context: Optional["StudentContext"]) -> str:
        """Build the student personality section for the prompt template."""
        if not student_context:
            return ""

        lines = ["\n## Student Profile (personalize the plan for this student)"]
        if student_context.student_name:
            lines.append(f"- Name: {student_context.student_name}")
        if student_context.student_age:
            lines.append(f"- Age: {student_context.student_age}")
        if student_context.preferred_examples:
            lines.append(f"- Interests: {', '.join(student_context.preferred_examples)}")
        if student_context.attention_span:
            lines.append(f"- Attention span: {student_context.attention_span}")
        if student_context.tutor_brief:
            lines.append(f"- Personality brief: {student_context.tutor_brief}")

        # Only return section if we have meaningful data beyond the header
        if len(lines) <= 1:
            return ""
        return "\n".join(lines) + "\n"

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
