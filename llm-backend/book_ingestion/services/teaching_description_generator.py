"""
Teaching Description Generator Service

Responsibility: Generate concise teaching descriptions for stable subtopics.

Single Responsibility Principle:
- Only handles teaching description generation
- Delegates LLM calls to injected client
- Returns 3-6 line teacher-ready descriptions

Teaching Description Format (3-6 lines):
1. Concept summary (what is being taught)
2. Teaching sequence (how to teach it step-by-step)
3. Key misconceptions to address
4. Comprehension checks (how to verify understanding)
"""

import logging
import json
from pathlib import Path
from typing import Optional

from openai import OpenAI

from ..models.guideline_models import SubtopicShard

logger = logging.getLogger(__name__)


class TeachingDescriptionGenerator:
    """
    Generate teaching descriptions for subtopics.

    A teaching description is a 3-6 line instruction set that tells
    the AI tutor HOW to teach this subtopic, including:
    - What the concept is
    - How to sequence the teaching
    - What misconceptions to address
    - How to check comprehension
    """

    def __init__(self, openai_client: Optional[OpenAI] = None):
        """
        Initialize teaching description generator.

        Args:
            openai_client: Optional OpenAI client (if None, creates new one)
        """
        self.client = openai_client or OpenAI()
        self.model = "gpt-4o-mini"
        self.max_tokens = 400  # ~100 words (3-6 lines)

        # Load prompt template
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load teaching description prompt template"""
        prompt_path = Path(__file__).parent.parent / "prompts" / "teaching_description.txt"

        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.error(f"Prompt template not found: {prompt_path}")
            raise

    def generate(
        self,
        shard: SubtopicShard,
        grade: int,
        subject: str
    ) -> str:
        """
        Generate teaching description for a subtopic.

        Args:
            shard: Subtopic shard with all accumulated facts
            grade: Grade level (for age-appropriate language)
            subject: Subject (Math, Science, etc.)

        Returns:
            Teaching description (3-6 lines)

        Raises:
            ValueError: If shard has insufficient data or LLM fails
        """
        # Validate shard has minimum content
        if len(shard.objectives) < 1:
            raise ValueError(
                f"Shard {shard.subtopic_key} has no objectives, "
                "cannot generate teaching description"
            )

        # Build context from shard
        context = self._build_context_from_shard(shard)

        # Build prompt
        prompt = self.prompt_template.format(
            grade=grade,
            subject=subject,
            topic_title=shard.topic_title,
            subtopic_title=shard.subtopic_title,
            objectives=context["objectives_str"],
            examples=context["examples_str"],
            misconceptions=context["misconceptions_str"],
            assessments=context["assessments_str"],
            page_range=f"{shard.source_page_start}-{shard.source_page_end}",
            num_pages=len(shard.source_pages)
        )

        try:
            # Call LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert curriculum designer. "
                            "Generate concise, actionable teaching instructions. "
                            "Output exactly 3-6 lines, no more."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=self.max_tokens,
                temperature=0.4  # Slightly higher for natural language
            )

            # Extract teaching description
            teaching_description = response.choices[0].message.content.strip()

            # Validate line count
            lines = [line for line in teaching_description.split('\n') if line.strip()]
            if len(lines) < 3:
                logger.warning(
                    f"Teaching description too short ({len(lines)} lines), "
                    "expected 3-6 lines"
                )
            elif len(lines) > 6:
                logger.warning(
                    f"Teaching description too long ({len(lines)} lines), "
                    "expected 3-6 lines, truncating"
                )
                # Truncate to 6 lines
                teaching_description = '\n'.join(lines[:6])

            logger.info(
                f"Generated teaching description for {shard.subtopic_key}: "
                f"{len(lines)} lines, {len(teaching_description)} chars"
            )

            return teaching_description

        except Exception as e:
            logger.error(f"Teaching description generation failed: {str(e)}")
            raise ValueError(f"Failed to generate teaching description: {str(e)}")

    def _build_context_from_shard(self, shard: SubtopicShard) -> dict:
        """
        Build context string from shard facts.

        Args:
            shard: Subtopic shard

        Returns:
            Dict with formatted strings for objectives, examples, etc.
        """
        # Format objectives
        objectives_str = "\n".join([
            f"- {obj}" for obj in shard.objectives
        ]) if shard.objectives else "(None)"

        # Format examples (limit to 5 for brevity)
        examples_list = shard.examples[:5]
        examples_str = "\n".join([
            f"- {ex}" for ex in examples_list
        ]) if examples_list else "(None)"
        if len(shard.examples) > 5:
            examples_str += f"\n... and {len(shard.examples) - 5} more"

        # Format misconceptions
        misconceptions_str = "\n".join([
            f"- {m}" for m in shard.misconceptions
        ]) if shard.misconceptions else "(None)"

        # Format assessments (limit to 3 for brevity)
        assessments_list = shard.assessments[:3]
        assessments_str = "\n".join([
            f"- [{a.level}] {a.prompt} (Answer: {a.answer})"
            for a in assessments_list
        ]) if assessments_list else "(None)"
        if len(shard.assessments) > 3:
            assessments_str += f"\n... and {len(shard.assessments) - 3} more"

        return {
            "objectives_str": objectives_str,
            "examples_str": examples_str,
            "misconceptions_str": misconceptions_str,
            "assessments_str": assessments_str
        }

    def validate_teaching_description(
        self,
        teaching_description: str
    ) -> tuple[bool, list[str]]:
        """
        Validate teaching description quality.

        Args:
            teaching_description: Generated teaching description

        Returns:
            Tuple of (is_valid, error_messages)

        Validation criteria:
        - 3-6 lines
        - Each line ≥20 chars
        - Total length ≤600 chars
        - Contains key teaching elements
        """
        errors = []

        # Check line count
        lines = [line for line in teaching_description.split('\n') if line.strip()]
        if len(lines) < 3:
            errors.append(f"Too few lines ({len(lines)}/3 minimum)")
        elif len(lines) > 6:
            errors.append(f"Too many lines ({len(lines)}/6 maximum)")

        # Check line lengths
        for i, line in enumerate(lines, 1):
            if len(line.strip()) < 20:
                errors.append(f"Line {i} too short ({len(line.strip())} chars)")

        # Check total length
        if len(teaching_description) > 600:
            errors.append(
                f"Total length too long ({len(teaching_description)} chars, "
                "max 600)"
            )

        # Check for key teaching elements (heuristic)
        lower_text = teaching_description.lower()
        has_teaching_words = any(word in lower_text for word in [
            "teach", "explain", "demonstrate", "show", "help",
            "understand", "learn", "practice", "check", "assess",
            "concept", "example", "misconception", "exercise"
        ])

        if not has_teaching_words:
            errors.append("Missing teaching-related vocabulary")

        is_valid = len(errors) == 0

        if is_valid:
            logger.debug(
                f"Teaching description validation PASSED: "
                f"{len(lines)} lines, {len(teaching_description)} chars"
            )
        else:
            logger.warning(
                f"Teaching description validation FAILED: {', '.join(errors)}"
            )

        return is_valid, errors

    def generate_with_validation(
        self,
        shard: SubtopicShard,
        grade: int,
        subject: str,
        max_retries: int = 2
    ) -> tuple[str, bool]:
        """
        Generate teaching description with automatic validation and retry.

        Args:
            shard: Subtopic shard
            grade: Grade level
            subject: Subject
            max_retries: Maximum number of generation attempts

        Returns:
            Tuple of (teaching_description, is_valid)

        Note:
            If validation fails after max_retries, returns the best attempt
            with is_valid=False (caller should mark as "needs_review")
        """
        best_attempt = None
        best_errors = None

        for attempt in range(1, max_retries + 1):
            try:
                teaching_description = self.generate(shard, grade, subject)
                is_valid, errors = self.validate_teaching_description(teaching_description)

                if is_valid:
                    logger.info(
                        f"Teaching description generated and validated "
                        f"(attempt {attempt}/{max_retries})"
                    )
                    return teaching_description, True

                # Save best attempt
                if best_attempt is None or len(errors) < len(best_errors):
                    best_attempt = teaching_description
                    best_errors = errors

                logger.warning(
                    f"Teaching description validation failed "
                    f"(attempt {attempt}/{max_retries}): {', '.join(errors)}"
                )

            except Exception as e:
                logger.error(
                    f"Teaching description generation failed "
                    f"(attempt {attempt}/{max_retries}): {str(e)}"
                )
                if attempt == max_retries:
                    raise

        # All attempts failed validation
        logger.warning(
            f"Teaching description validation failed after {max_retries} attempts, "
            f"using best attempt with errors: {', '.join(best_errors)}"
        )
        return best_attempt, False
