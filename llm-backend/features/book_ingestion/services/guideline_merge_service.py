"""
Guideline Merge Service (V2)

V2 Innovation: LLM-based intelligent merging instead of rule-based appending.

Single Responsibility Principle:
- Only handles merging of guidelines text
- Uses LLM to intelligently consolidate information
- Delegates LLM calls to injected client
"""

import logging
from pathlib import Path
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


class GuidelineMergeService:
    """
    V2 service for merging guidelines using LLM.

    Replaces V1's rule-based array appending with intelligent text merging.
    """

    def __init__(self, openai_client: Optional[OpenAI] = None):
        """
        Initialize guideline merge service.

        Args:
            openai_client: Optional OpenAI client (if None, creates new one)
        """
        self.client = openai_client or OpenAI()
        self.model = "gpt-4o-mini"
        self.max_tokens = 1500  # Merged guidelines can be lengthy
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load guideline merge prompt template"""
        prompt_path = Path(__file__).parent.parent / "prompts" / "guideline_merge_v2.txt"

        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.error(f"Prompt template not found: {prompt_path}")
            raise

    def merge(
        self,
        existing_guidelines: str,
        new_page_guidelines: str,
        topic_title: str,
        subtopic_title: str,
        grade: int,
        subject: str
    ) -> str:
        """
        Merge new page guidelines into existing guidelines.

        Args:
            existing_guidelines: Current guidelines text
            new_page_guidelines: Guidelines from new page
            topic_title: Topic name (for context)
            subtopic_title: Subtopic name (for context)
            grade: Grade level
            subject: Subject

        Returns:
            Merged guidelines text

        Raises:
            ValueError: If merging fails
        """
        # Build prompt
        prompt = self._build_prompt(
            existing_guidelines,
            new_page_guidelines,
            topic_title,
            subtopic_title,
            grade,
            subject
        )

        try:
            # Call LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a teaching guidelines consolidation expert."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=self.max_tokens,
                temperature=0.3  # Some creativity for natural merging
            )

            merged_guidelines = response.choices[0].message.content.strip()

            # Validate non-empty
            if not merged_guidelines:
                raise ValueError("LLM returned empty merged guidelines")

            logger.info(
                f"Merged guidelines for {topic_title}/{subtopic_title}: "
                f"{len(existing_guidelines)} + {len(new_page_guidelines)} → {len(merged_guidelines)} chars"
            )

            return merged_guidelines

        except Exception as e:
            logger.error(f"Failed to merge guidelines: {str(e)}")
            # Fallback: simple concatenation
            logger.warning("Using fallback: simple concatenation")
            return f"{existing_guidelines}\n\n{new_page_guidelines}"

    def _build_prompt(
        self,
        existing: str,
        new: str,
        topic: str,
        subtopic: str,
        grade: int,
        subject: str
    ) -> str:
        """
        Build guideline merge prompt.

        Args:
            existing: Existing guidelines
            new: New page guidelines
            topic: Topic title
            subtopic: Subtopic title
            grade: Grade level
            subject: Subject

        Returns:
            Formatted prompt string
        """
        return self.prompt_template.format(
            topic=topic,
            subtopic=subtopic,
            grade=grade,
            subject=subject,
            existing_guidelines=existing,
            new_page_guidelines=new
        )
