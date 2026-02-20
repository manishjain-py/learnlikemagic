"""
Facts Extraction Service

Responsibility: Extract structured facts from textbook pages.

Single Responsibility Principle:
- Only handles facts extraction (objectives, examples, misconceptions, assessments)
- Delegates LLM calls to injected client
- Returns structured PageFacts model
"""

import logging
import json
from pathlib import Path
from typing import Optional

from openai import OpenAI

from ..models.guideline_models import PageFacts, FactsExtractionResponse

logger = logging.getLogger(__name__)


class FactsExtractionService:
    """
    Extract structured educational facts from textbook pages.

    Extracts:
    - Learning objectives (what students should learn)
    - Worked examples (demonstrations with solutions)
    - Common misconceptions (student errors to address)
    - Assessment items (practice problems with answers)
    """

    def __init__(self, openai_client: Optional[OpenAI] = None, *, model: str):
        """
        Initialize facts extraction service.

        Args:
            openai_client: Optional OpenAI client (if None, creates new one)
            model: LLM model name from DB config (required)
        """
        self.client = openai_client or OpenAI()
        self.model = model
        self.max_tokens = 500  # Structured facts are concise

        # Load prompt template
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load facts extraction prompt template"""
        prompt_path = Path(__file__).parent.parent / "prompts" / "facts_extraction.txt"

        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.error(f"Prompt template not found: {prompt_path}")
            raise

    def extract(
        self,
        page_text: str,
        subtopic_title: str,
        grade: int,
        subject: str
    ) -> PageFacts:
        """
        Extract structured facts from a page.

        Args:
            page_text: Full OCR text from the page
            subtopic_title: Current subtopic (for context)
            grade: Grade level (for age-appropriate extraction)
            subject: Subject (Math, Science, etc.)

        Returns:
            PageFacts model with extracted facts

        Raises:
            ValueError: If page_text is empty or LLM returns invalid response
        """
        if not page_text or not page_text.strip():
            raise ValueError("Page text cannot be empty")

        # Truncate page text if too long
        truncated_text = page_text[:4000]  # ~650 words

        # Build prompt
        prompt = self.prompt_template.format(
            grade=grade,
            subject=subject,
            subtopic_title=subtopic_title,
            page_text=truncated_text
        )

        try:
            # Call LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an educational content analyzer. "
                            "Extract structured facts from textbook pages. "
                            "Respond with valid JSON only, no markdown formatting."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=self.max_tokens,
                temperature=0.3,  # Low temperature for consistent extraction
                response_format={"type": "json_object"}  # Force JSON response
            )

            # Parse response
            raw_response = response.choices[0].message.content.strip()
            facts_data = json.loads(raw_response)

            # Validate with Pydantic
            facts_response = FactsExtractionResponse(**facts_data)

            # Convert to PageFacts (without _add suffix)
            page_facts = PageFacts(
                objectives_add=facts_response.objectives_add,
                examples_add=facts_response.examples_add,
                misconceptions_add=facts_response.misconceptions_add,
                assessments_add=facts_response.assessments_add
            )

            logger.debug(
                f"Extracted facts: {len(page_facts.objectives_add)} objectives, "
                f"{len(page_facts.examples_add)} examples, "
                f"{len(page_facts.misconceptions_add)} misconceptions, "
                f"{len(page_facts.assessments_add)} assessments"
            )

            return page_facts

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {str(e)}")
            logger.error(f"Raw response: {raw_response[:500]}")
            # Return empty facts rather than failing
            return PageFacts()

        except Exception as e:
            logger.error(f"Facts extraction failed: {str(e)}")
            # Return empty facts rather than failing
            return PageFacts()

    def extract_batch(
        self,
        page_texts: list[str],
        subtopic_titles: list[str],
        grade: int,
        subject: str
    ) -> list[PageFacts]:
        """
        Extract facts from multiple pages (sequential for MVP v1).

        Args:
            page_texts: List of page OCR texts
            subtopic_titles: List of subtopic titles (one per page)
            grade: Grade level
            subject: Subject

        Returns:
            List of PageFacts (same order as input)

        Note:
            MVP v1 processes sequentially. Future versions can parallelize.
        """
        if len(page_texts) != len(subtopic_titles):
            raise ValueError("page_texts and subtopic_titles must have same length")

        facts_list = []

        for i, (page_text, subtopic_title) in enumerate(
            zip(page_texts, subtopic_titles), start=1
        ):
            try:
                facts = self.extract(page_text, subtopic_title, grade, subject)
                facts_list.append(facts)
                logger.info(f"Extracted facts from page {i}/{len(page_texts)}")
            except Exception as e:
                logger.error(f"Failed to extract facts from page {i}: {str(e)}")
                # Use empty facts as fallback
                facts_list.append(PageFacts())

        return facts_list
