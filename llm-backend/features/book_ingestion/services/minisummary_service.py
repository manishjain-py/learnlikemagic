"""
Minisummary Generator Service

Responsibility: Generate compact 60-word summaries of textbook pages.

Single Responsibility Principle:
- Only handles minisummary generation
- Delegates prompt loading to helper
- Delegates LLM calls to injected client
"""

import logging
from pathlib import Path
from typing import Optional

from openai import OpenAI

from ..models.guideline_models import MinisummaryResponse

logger = logging.getLogger(__name__)


class MinisummaryService:
    """
    Generate extractive summaries (≤60 words) from textbook pages.

    This service creates compact summaries that:
    - Focus on main concepts and examples
    - Are factual and extractive (no interpretation)
    - Serve as input to boundary detection and context building
    """

    def __init__(self, openai_client: Optional[OpenAI] = None):
        """
        Initialize minisummary service.

        Args:
            openai_client: Optional OpenAI client (if None, creates new one)
        """
        self.client = openai_client or OpenAI()
        self.model = "gpt-4o-mini"
        self.max_tokens = 200  # ~60 words + overhead

        # Load prompt template
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load minisummary prompt template from file"""
        prompt_path = Path(__file__).parent.parent / "prompts" / "minisummary.txt"

        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.error(f"Prompt template not found: {prompt_path}")
            raise

    def generate(self, page_text: str) -> str:
        """
        Generate minisummary for a single page.

        Args:
            page_text: Full OCR text from the page

        Returns:
            Minisummary string (≤60 words)

        Raises:
            ValueError: If page_text is empty
            Exception: If LLM call fails
        """
        if not page_text or not page_text.strip():
            raise ValueError("Page text cannot be empty")

        # Truncate page text if too long (keep first 3000 chars ~500 words)
        truncated_text = page_text[:3000]

        # Build prompt
        prompt = self.prompt_template.format(page_text=truncated_text)

        try:
            # Call LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a textbook content summarizer. Provide concise, factual summaries."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=self.max_tokens,
                temperature=0.3  # Low temperature for consistent, factual output
            )

            summary = response.choices[0].message.content.strip()

            # Validate response
            if not summary:
                raise ValueError("LLM returned empty summary")

            # Validate word count (soft limit, warning only)
            word_count = len(summary.split())
            if word_count > 70:  # 60 + 10 tolerance
                logger.warning(
                    f"Minisummary exceeds target length: {word_count} words "
                    f"(target: ≤60). Summary: {summary[:100]}..."
                )

            logger.debug(f"Generated minisummary ({word_count} words): {summary[:100]}...")

            return summary

        except Exception as e:
            logger.error(f"Failed to generate minisummary: {str(e)}")
            raise

    def generate_batch(self, page_texts: list[str]) -> list[str]:
        """
        Generate minisummaries for multiple pages (sequential for MVP v1).

        Args:
            page_texts: List of page OCR texts

        Returns:
            List of minisummaries (same order as input)

        Note:
            MVP v1 processes sequentially. Future versions can parallelize.
        """
        summaries = []

        for i, page_text in enumerate(page_texts, start=1):
            try:
                summary = self.generate(page_text)
                summaries.append(summary)
                logger.info(f"Generated minisummary for page {i}/{len(page_texts)}")
            except Exception as e:
                logger.error(f"Failed to generate minisummary for page {i}: {str(e)}")
                # Use fallback: first 60 words
                fallback = " ".join(page_text.split()[:60])
                summaries.append(fallback)
                logger.warning(f"Using fallback summary for page {i}")

        return summaries
