"""
Boundary Detection Service V2

V2 Simplifications:
- No hysteresis/confidence scores (simpler decision making)
- Takes full page text as input (not minisummary)
- Extracts page guidelines in same call (combined operation)
- Context pack includes full guidelines text for better matching

Single Responsibility Principle:
- Detects boundaries AND extracts guidelines in one LLM call
- Uses V2 models (BoundaryDecisionV2)
- Delegates LLM calls to injected client
"""

import logging
import json
from pathlib import Path
from typing import Tuple, Optional

from openai import OpenAI

from ..models.guideline_models import (
    BoundaryDecisionV2,
    ContextPack,
    slugify,
    deslugify
)

logger = logging.getLogger(__name__)


class BoundaryDetectionServiceV2:
    """
    V2 Boundary Detection - Simplified output with page guidelines extraction.

    Key changes from V1:
    - Input: Full page text instead of summary
    - Input: Open topics include guidelines text
    - Output: is_new_topic, topic_name, subtopic_name, page_guidelines
    - No confidence scores or hysteresis
    """

    def __init__(self, openai_client: Optional[OpenAI] = None):
        """
        Initialize V2 boundary detection service.

        Args:
            openai_client: Optional OpenAI client (if None, creates new one)
        """
        self.client = openai_client or OpenAI()
        self.model = "gpt-4o-mini"
        self.max_tokens = 1000  # V2: Increased for guidelines extraction

        # Load prompt template
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load V2 boundary detection prompt template"""
        prompt_path = Path(__file__).parent.parent / "prompts" / "boundary_detection_v2.txt"

        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.error(f"Prompt template not found: {prompt_path}")
            raise

    def detect(
        self,
        context_pack: ContextPack,
        page_text: str  # V2: Full text, not summary
    ) -> Tuple[bool, str, str, str, str, str]:
        """
        Detect boundary and extract guidelines (V2).

        Args:
            context_pack: Current context with 5 recent summaries + guidelines
            page_text: Full page text (not summary)

        Returns:
            Tuple of (is_new, topic_key, topic_title, subtopic_key, subtopic_title, page_guidelines)
            - is_new: True if new topic/subtopic, False if continuing
            - topic_key: Slugified topic identifier
            - topic_title: Human-readable topic name
            - subtopic_key: Slugified subtopic identifier
            - subtopic_title: Human-readable subtopic name
            - page_guidelines: Extracted guidelines text

        Raises:
            ValueError: If LLM returns invalid response
        """
        # Build prompt
        prompt = self._build_prompt(context_pack, page_text)

        try:
            # Call LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a textbook structure analyzer. "
                            "Respond with valid JSON only, no markdown formatting."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=self.max_tokens,
                temperature=0.2,  # Low temperature for consistent decisions
                response_format={"type": "json_object"}  # Force JSON response
            )

            # Parse response
            raw_response = response.choices[0].message.content.strip()
            decision_data = json.loads(raw_response)

            # Validate with Pydantic
            decision = BoundaryDecisionV2(**decision_data)

            # Normalize keys (lowercase, slugified)
            topic_key = slugify(decision.topic_name)
            subtopic_key = slugify(decision.subtopic_name)

            # Generate titles if needed (deslugify)
            topic_title = deslugify(topic_key) if decision.topic_name == topic_key else decision.topic_name
            subtopic_title = deslugify(subtopic_key) if decision.subtopic_name == subtopic_key else decision.subtopic_name

            logger.info(
                f"V2 Boundary decision: {'NEW' if decision.is_new_topic else 'CONTINUE'} "
                f"→ {topic_key}/{subtopic_key}"
            )

            return (
                decision.is_new_topic,
                topic_key,
                topic_title,
                subtopic_key,
                subtopic_title,
                decision.page_guidelines
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {str(e)}")
            logger.error(f"Raw response: {raw_response}")
            raise ValueError(f"Invalid JSON from LLM: {str(e)}")

        except Exception as e:
            logger.error(f"Boundary detection failed: {str(e)}")
            raise

    def _build_prompt(self, context_pack: ContextPack, page_text: str) -> str:
        """
        Build V2 boundary detection prompt.

        Args:
            context_pack: Current context
            page_text: Full page text

        Returns:
            Formatted prompt string
        """
        # Format open topics with guidelines
        open_topics_str = ""
        for topic in context_pack.open_topics:
            open_topics_str += f"\nTopic: {topic.topic_title} ({topic.topic_key})\n"
            for subtopic in topic.open_subtopics:
                # V2: Include guidelines text
                guidelines_preview = getattr(subtopic, 'guidelines', '')[:300] + "..." if hasattr(subtopic, 'guidelines') else 'N/A'
                open_topics_str += (
                    f"  Subtopic: {subtopic.subtopic_title} ({subtopic.subtopic_key})\n"
                    f"  Pages: {getattr(subtopic, 'page_start', '?')}-{getattr(subtopic, 'page_end', '?')}\n"
                    f"  Guidelines Preview: {guidelines_preview}\n\n"
                )

        if not open_topics_str:
            open_topics_str = "(No open topics yet - this is the first page)"

        # Format recent summaries
        recent_summaries_str = ""
        for summary in context_pack.recent_page_summaries:
            recent_summaries_str += f"Page {summary.page}:\n{summary.summary}\n\n"

        if not recent_summaries_str:
            recent_summaries_str = "(No recent pages)"

        # Fill template
        return self.prompt_template.format(
            grade=context_pack.book_metadata.get("grade", "?"),
            subject=context_pack.book_metadata.get("subject", "?"),
            board=context_pack.book_metadata.get("board", "?"),
            current_page=context_pack.current_page,
            open_topics=open_topics_str,
            recent_summaries=recent_summaries_str,
            page_text=page_text
        )
