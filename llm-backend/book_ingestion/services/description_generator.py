"""
Description Generator Service

Responsibility: Generate comprehensive 200-300 word descriptions for stable subtopics.

Single Responsibility Principle:
- Only handles comprehensive description generation
- Delegates LLM calls to injected client
- Returns 200-300 word descriptions covering what/how/assessment/misconceptions

Description Format (200-300 words):
- Single comprehensive paragraph
- Covers: what the topic is, how to teach it, how to assess it, common misconceptions
- Clear, practical language for teachers
"""

import logging
import json
from pathlib import Path
from typing import Optional, Tuple

from openai import OpenAI

from ..models.guideline_models import SubtopicShard

logger = logging.getLogger(__name__)


class DescriptionGenerator:
    """
    Generate comprehensive descriptions for subtopics.

    A description is a 200-300 word comprehensive paragraph that tells
    teachers everything they need to know about teaching this subtopic:
    - What the concept/topic is about
    - How to teach it (sequence, approach, strategies)
    - How to assess understanding
    - Common misconceptions to address
    """

    # Word count constraints
    MIN_WORDS = 150
    TARGET_MIN_WORDS = 200
    TARGET_MAX_WORDS = 300
    MAX_WORDS = 350

    def __init__(self, openai_client: Optional[OpenAI] = None, *, model: str):
        """
        Initialize description generator.

        Args:
            openai_client: Optional OpenAI client (if None, creates new one)
            model: LLM model name from DB config (required)
        """
        self.client = openai_client or OpenAI()
        self.model = model
        self.max_tokens = 600  # ~450 words max (with buffer)

        # Load prompt template
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load description generation prompt template"""
        prompt_path = Path(__file__).parent.parent / "prompts" / "description_generation.txt"

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
        Generate comprehensive description for a subtopic.

        Args:
            shard: Subtopic shard with all accumulated facts
            grade: Grade level (for age-appropriate language)
            subject: Subject (Math, Science, etc.)

        Returns:
            Comprehensive description (200-300 words)

        Raises:
            ValueError: If shard has insufficient data or LLM fails
        """
        # Validate shard has minimum content
        if len(shard.objectives) < 1:
            raise ValueError(
                f"Shard {shard.subtopic_key} has no objectives, "
                "cannot generate description"
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
            evidence_summary=shard.evidence_summary or "Not available"
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
                            "Generate comprehensive, practical teaching descriptions. "
                            "Output must be 200-300 words in a single paragraph."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_completion_tokens=self.max_tokens,
                temperature=0.5  # Balanced creativity and consistency
            )

            # Extract description
            description = response.choices[0].message.content.strip()

            # Validate word count
            word_count = len(description.split())

            if word_count < self.MIN_WORDS:
                logger.warning(
                    f"Description too short ({word_count} words), "
                    f"expected {self.TARGET_MIN_WORDS}-{self.TARGET_MAX_WORDS}"
                )
            elif word_count > self.MAX_WORDS:
                logger.warning(
                    f"Description too long ({word_count} words), "
                    f"expected {self.TARGET_MIN_WORDS}-{self.TARGET_MAX_WORDS}"
                )

            logger.info(
                f"Generated description for {shard.subtopic_key}: {word_count} words"
            )

            return description

        except Exception as e:
            logger.error(
                f"Failed to generate description for {shard.subtopic_key}: {str(e)}",
                exc_info=True
            )
            raise ValueError(f"Description generation failed: {str(e)}")

    def generate_with_validation(
        self,
        shard: SubtopicShard,
        grade: int,
        subject: str,
        max_retries: int = 2
    ) -> Tuple[str, bool]:
        """
        Generate description with validation and retry logic.

        Args:
            shard: Subtopic shard
            grade: Grade level
            subject: Subject
            max_retries: Maximum retry attempts

        Returns:
            Tuple of (description, is_valid)
            - description: Generated description
            - is_valid: True if within target word count (200-300)
        """
        for attempt in range(max_retries + 1):
            try:
                description = self.generate(shard, grade, subject)
                word_count = len(description.split())

                # Check if within target range
                is_valid = (
                    self.TARGET_MIN_WORDS <= word_count <= self.TARGET_MAX_WORDS
                )

                if is_valid or attempt == max_retries:
                    # Accept if valid OR we've exhausted retries
                    if not is_valid:
                        logger.warning(
                            f"Accepting description after {max_retries} retries "
                            f"({word_count} words)"
                        )
                    return description, is_valid

                # Not valid and have retries left
                logger.info(
                    f"Description word count {word_count} out of range, "
                    f"retrying ({attempt + 1}/{max_retries})..."
                )

            except Exception as e:
                if attempt == max_retries:
                    logger.error(f"All retry attempts failed: {str(e)}")
                    raise
                logger.warning(f"Attempt {attempt + 1} failed, retrying...")

        # Should never reach here, but just in case
        raise ValueError("Description generation failed after all retries")

    def _build_context_from_shard(self, shard: SubtopicShard) -> dict:
        """
        Build context strings from shard data.

        Args:
            shard: Subtopic shard

        Returns:
            Dict with formatted strings for objectives, examples, etc.
        """
        # Format objectives
        if shard.objectives:
            objectives_str = "\n".join(f"- {obj}" for obj in shard.objectives)
        else:
            objectives_str = "None specified"

        # Format examples
        if shard.examples:
            examples_str = "\n".join(f"- {ex}" for ex in shard.examples)
        else:
            examples_str = "None provided"

        # Format misconceptions
        if shard.misconceptions:
            misconceptions_str = "\n".join(f"- {mis}" for mis in shard.misconceptions)
        else:
            misconceptions_str = "None identified"

        # Format assessments
        if shard.assessments:
            assessments_list = []
            for a in shard.assessments:
                assessments_list.append(f"- [{a.level}] {a.prompt}")
            assessments_str = "\n".join(assessments_list)
        else:
            assessments_str = "None provided"

        return {
            "objectives_str": objectives_str,
            "examples_str": examples_str,
            "misconceptions_str": misconceptions_str,
            "assessments_str": assessments_str
        }
