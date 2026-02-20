"""
Boundary Detection Service

Simplifications:
- No hysteresis/confidence scores (simpler decision making)
- Takes full page text as input (not minisummary)
- Extracts page guidelines in same call (combined operation)
- Context pack includes full guidelines text for better matching

Single Responsibility Principle:
- Detects boundaries AND extracts guidelines in one LLM call
- Uses simplified BoundaryDecision model
- Delegates LLM calls to injected client
"""

import logging
import json
from pathlib import Path
from typing import Tuple, Optional
from datetime import datetime

from openai import OpenAI

from ..models.guideline_models import (
    BoundaryDecision,
    ContextPack,
    slugify,
    deslugify
)

logger = logging.getLogger(__name__)


class BoundaryDetectionService:
    """
    Boundary Detection - Detects topic/subtopic boundaries with page guidelines extraction.

    Features:
    - Input: Full page text
    - Input: Open topics include guidelines text for context
    - Output: is_new_topic, topic_name, subtopic_name, page_guidelines
    - No confidence scores or hysteresis (simple decision making)
    """

    def __init__(self, openai_client: Optional[OpenAI] = None, *, model: str):
        """
        Initialize boundary detection service.

        Args:
            openai_client: Optional OpenAI client (if None, creates new one)
            model: LLM model name from DB config (required)
        """
        self.client = openai_client or OpenAI()
        self.model = model
        self.max_tokens = 1000  # Increased for guidelines extraction

        # Load prompt template
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load boundary detection prompt template"""
        prompt_path = Path(__file__).parent.parent / "prompts" / "boundary_detection.txt"

        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.error(f"Prompt template not found: {prompt_path}")
            raise

    def detect(
        self,
        context_pack: ContextPack,
        page_text: str
    ) -> Tuple[bool, str, str, str, str, str]:
        """
        Detect boundary and extract guidelines.

        Args:
            context_pack: Current context with 5 recent summaries + guidelines
            page_text: Full page text

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
            import time
            import json
            start_time = time.time()

            logger.info(json.dumps({
                "step": "BOUNDARY_DETECT",
                "status": "starting",
                "book_id": context_pack.book_id,
                "page": context_pack.current_page
            }))

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
            decision = BoundaryDecision(**decision_data)

            # Normalize keys (lowercase, slugified)
            topic_key = slugify(decision.topic_name)
            subtopic_key = slugify(decision.subtopic_name)

            # Generate titles if needed (deslugify)
            topic_title = deslugify(topic_key) if decision.topic_name == topic_key else decision.topic_name
            subtopic_title = deslugify(subtopic_key) if decision.subtopic_name == subtopic_key else decision.subtopic_name

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(json.dumps({
                "step": "BOUNDARY_DETECT",
                "status": "complete",
                "book_id": context_pack.book_id,
                "page": context_pack.current_page,
                "output": {
                    "is_new_topic": decision.is_new_topic,
                    "topic": topic_key,
                    "subtopic": subtopic_key
                },
                "duration_ms": duration_ms
            }))

            # Log reasoning to file - REMOVED in favor of structured logging above
            # self._log_boundary_decision(...)

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
        Build boundary detection prompt.

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
                # Include guidelines text
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

    def _log_boundary_decision(
        self,
        book_id: str,
        page_number: int,
        is_new_topic: bool,
        topic_key: str,
        subtopic_key: str,
        reasoning: str
    ) -> None:
        """
        Log boundary detection decision and reasoning to file.

        Args:
            book_id: Book identifier
            page_number: Current page number
            is_new_topic: Whether this is a new topic
            topic_key: Topic key
            subtopic_key: Subtopic key
            reasoning: LLM's reasoning for the decision
        """
        log_file = Path(__file__).parent.parent.parent.parent / "boundary_detection_llm_logs.txt"

        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            decision = "NEW TOPIC" if is_new_topic else "CONTINUE"

            log_entry = f"""
{'=' * 80}
Timestamp: {timestamp}
Book ID: {book_id}
Page: {page_number}
Decision: {decision}
Topic: {topic_key}
Subtopic: {subtopic_key}

Reasoning:
{reasoning}
{'=' * 80}

"""

            # Append to log file
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)

            logger.debug(f"Logged boundary decision for page {page_number} to {log_file}")

        except Exception as e:
            logger.warning(f"Failed to write to boundary detection log file: {str(e)}")
