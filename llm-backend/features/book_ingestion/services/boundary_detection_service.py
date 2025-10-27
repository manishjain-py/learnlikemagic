"""
Boundary Detection Service

Responsibility: Determine if a page continues current subtopic or starts new one.

Single Responsibility Principle:
- Only handles boundary detection logic
- Implements hysteresis to prevent "boundary flapping"
- Delegates LLM calls to injected client

Key Innovation: Hysteresis Zone (0.6-0.75)
- Strong continue (≥0.6, new<0.7): CONTINUE
- Strong new (≥0.75): NEW
- Ambiguous (between 0.6-0.75): Provisional continue (best guess)
"""

import logging
import json
from pathlib import Path
from typing import Tuple, Optional, Literal

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
    Detect topic/subtopic boundaries using LLM + hysteresis.

    This service prevents "boundary flapping" by requiring strong
    evidence before switching subtopics.
    """

    # Hysteresis thresholds
    CONTINUE_THRESHOLD = 0.6
    NEW_THRESHOLD = 0.75

    def __init__(self, openai_client: Optional[OpenAI] = None):
        """
        Initialize boundary detection service.

        Args:
            openai_client: Optional OpenAI client (if None, creates new one)
        """
        self.client = openai_client or OpenAI()
        self.model = "gpt-4o-mini"
        self.max_tokens = 300  # Boundary decisions are concise

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
        minisummary: str,
        default_topic_key: str = "unknown-topic"
    ) -> Tuple[str, str, str, str, float]:
        """
        Detect if page continues or starts new subtopic.

        Args:
            context_pack: Current context
            minisummary: Current page summary
            default_topic_key: Default topic if starting fresh (slugified)

        Returns:
            Tuple of (decision, topic_key, topic_title, subtopic_key, subtopic_title, confidence)
            - decision: "continue" or "new"
            - topic_key: Slugified topic identifier
            - topic_title: Human-readable topic name
            - subtopic_key: Slugified subtopic identifier
            - subtopic_title: Human-readable subtopic name
            - confidence: Float 0.0-1.0

        Raises:
            ValueError: If LLM returns invalid response
        """
        # Build prompt
        prompt = self._build_prompt(context_pack, minisummary)

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
            decision = BoundaryDecision(**decision_data)

            # Apply hysteresis
            final_decision, confidence = self._apply_hysteresis(decision)

            # Extract topic/subtopic information
            if final_decision == "continue":
                topic_key, topic_title, subtopic_key, subtopic_title = (
                    self._extract_continue_info(decision, context_pack)
                )
            else:  # new
                topic_key, topic_title, subtopic_key, subtopic_title = (
                    self._extract_new_info(decision, context_pack, default_topic_key)
                )

            logger.info(
                f"Boundary decision: {final_decision.upper()} "
                f"(continue={decision.continue_score:.2f}, new={decision.new_score:.2f}) "
                f"→ {topic_key}/{subtopic_key} (confidence={confidence:.2f})"
            )

            return final_decision, topic_key, topic_title, subtopic_key, subtopic_title, confidence

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {str(e)}")
            raise ValueError(f"Invalid JSON response from LLM: {raw_response[:200]}")
        except Exception as e:
            logger.error(f"Boundary detection failed: {str(e)}")
            raise

    def _build_prompt(self, context_pack: ContextPack, minisummary: str) -> str:
        """Build boundary detection prompt from template"""
        # Format open subtopics
        open_subtopics_str = ""
        for topic in context_pack.open_topics:
            open_subtopics_str += f"Topic: {topic.topic_title}\n"
            for subtopic in topic.open_subtopics:
                open_subtopics_str += (
                    f"  - {subtopic.subtopic_title} ({subtopic.subtopic_key})\n"
                    f"    Evidence: {subtopic.evidence_summary}\n"
                )

        if not open_subtopics_str:
            open_subtopics_str = "(No open subtopics yet - this may be the first page)"

        # Format recent summaries
        recent_summaries_str = ""
        for summary in context_pack.recent_page_summaries:
            recent_summaries_str += f"Page {summary.page}: {summary.summary}\n"

        if not recent_summaries_str:
            recent_summaries_str = "(No recent pages)"

        # Fill template
        return self.prompt_template.format(
            grade=context_pack.book_metadata.get("grade", "?"),
            subject=context_pack.book_metadata.get("subject", "?"),
            board=context_pack.book_metadata.get("board", "?"),
            current_page=context_pack.current_page,
            open_subtopics=open_subtopics_str,
            recent_summaries=recent_summaries_str,
            minisummary=minisummary
        )

    def _apply_hysteresis(
        self,
        decision: BoundaryDecision
    ) -> Tuple[Literal["continue", "new"], float]:
        """
        Apply hysteresis to prevent boundary flapping.

        Hysteresis zones:
        - Strong continue (≥0.6, new<0.7): CONTINUE
        - Strong new (≥0.75): NEW
        - Ambiguous (0.6-0.75): Use best guess, mark low confidence

        Args:
            decision: Raw LLM decision

        Returns:
            Tuple of (final_decision, confidence)
        """
        continue_score = decision.continue_score
        new_score = decision.new_score

        # Strong continue signal
        if continue_score >= self.CONTINUE_THRESHOLD and new_score < 0.7:
            return "continue", continue_score

        # Strong new signal
        if new_score >= self.NEW_THRESHOLD:
            return "new", new_score

        # Ambiguous zone (0.6-0.75)
        # Use best guess but mark as low confidence
        if continue_score > new_score:
            logger.warning(
                f"Ambiguous decision (continue={continue_score:.2f}, "
                f"new={new_score:.2f}), defaulting to CONTINUE"
            )
            return "continue", min(continue_score, 0.65)  # Cap confidence
        else:
            logger.warning(
                f"Ambiguous decision (continue={continue_score:.2f}, "
                f"new={new_score:.2f}), defaulting to NEW"
            )
            return "new", min(new_score, 0.65)  # Cap confidence

    def _extract_continue_info(
        self,
        decision: BoundaryDecision,
        context_pack: ContextPack
    ) -> Tuple[str, str, str, str]:
        """
        Extract topic/subtopic info when continuing.

        Returns:
            Tuple of (topic_key, topic_title, subtopic_key, subtopic_title)
        """
        # Find the subtopic to continue
        subtopic_key = decision.continue_subtopic_key

        if not subtopic_key:
            # LLM didn't specify - use last open subtopic
            if context_pack.open_topics:
                last_topic = context_pack.open_topics[-1]
                if last_topic.open_subtopics:
                    last_subtopic = last_topic.open_subtopics[-1]
                    return (
                        last_topic.topic_key,
                        last_topic.topic_title,
                        last_subtopic.subtopic_key,
                        last_subtopic.subtopic_title
                    )

            raise ValueError("No open subtopic to continue")

        # Find the specified subtopic
        for topic in context_pack.open_topics:
            for subtopic in topic.open_subtopics:
                if subtopic.subtopic_key == subtopic_key:
                    return (
                        topic.topic_key,
                        topic.topic_title,
                        subtopic.subtopic_key,
                        subtopic.subtopic_title
                    )

        raise ValueError(f"Subtopic {subtopic_key} not found in open subtopics")

    def _extract_new_info(
        self,
        decision: BoundaryDecision,
        context_pack: ContextPack,
        default_topic_key: str
    ) -> Tuple[str, str, str, str]:
        """
        Extract topic/subtopic info when starting new.

        Returns:
            Tuple of (topic_key, topic_title, subtopic_key, subtopic_title)
        """
        subtopic_key = decision.new_subtopic_key
        subtopic_title = decision.new_subtopic_title

        if not subtopic_key or not subtopic_title:
            raise ValueError("LLM must provide new_subtopic_key and new_subtopic_title")

        # Normalize subtopic_key (ensure slugified)
        subtopic_key = slugify(subtopic_key)

        # Infer topic from context or use default
        if context_pack.open_topics:
            # Continue with last topic (common case: new subtopic within same topic)
            last_topic = context_pack.open_topics[-1]
            topic_key = last_topic.topic_key
            topic_title = last_topic.topic_title
        else:
            # First subtopic - use default topic
            topic_key = default_topic_key
            topic_title = deslugify(default_topic_key)

        return topic_key, topic_title, subtopic_key, subtopic_title
