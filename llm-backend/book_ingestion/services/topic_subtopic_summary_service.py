"""
TopicSubtopicSummaryService - Generates one-line summaries for topics and subtopics.

Usage:
    service = TopicSubtopicSummaryService(openai_client)
    subtopic_summary = service.generate_subtopic_summary(title, guidelines)
    topic_summary = service.generate_topic_summary(title, subtopic_summaries)
"""
import logging
from pathlib import Path
from typing import List, Optional
from openai import OpenAI

logger = logging.getLogger(__name__)


class TopicSubtopicSummaryService:
    """Generates and updates one-line summaries for topics and subtopics."""

    def __init__(self, openai_client: OpenAI, *, model: str):
        self.openai_client = openai_client
        self.model = model
        self.subtopic_prompt_template = self._load_prompt("subtopic_summary.txt")
        self.topic_prompt_template = self._load_prompt("topic_summary.txt")

    def generate_subtopic_summary(
        self,
        subtopic_title: str,
        guidelines: str,
        max_chars: int = 3000
    ) -> str:
        """
        Generate one-line summary from guidelines text.

        Args:
            subtopic_title: Human-readable subtopic name
            guidelines: Full guidelines text (truncated if >max_chars)
            max_chars: Maximum characters to send to LLM

        Returns:
            One-line summary (15-30 words)
        """
        try:
            prompt = self.subtopic_prompt_template.format(
                subtopic_title=subtopic_title,
                guidelines=guidelines[:max_chars]
            )
            response = self.openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that summarizes teaching guidelines."},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=50,
                temperature=0.3
            )
            summary = response.choices[0].message.content.strip()
            logger.info(f"Generated subtopic summary for '{subtopic_title}': {len(summary.split())} words")
            return summary
        except Exception as e:
            logger.error(f"Failed to generate subtopic summary for '{subtopic_title}': {e}")
            return self._fallback_summary(subtopic_title)

    def generate_topic_summary(
        self,
        topic_title: str,
        subtopic_summaries: List[str]
    ) -> str:
        """
        Generate topic summary by synthesizing subtopic summaries.

        Args:
            topic_title: Human-readable topic name
            subtopic_summaries: List of subtopic summary strings

        Returns:
            One-line topic summary (20-40 words)
        """
        if not subtopic_summaries:
            return self._fallback_summary(topic_title)

        # Single subtopic case: rephrase the subtopic summary
        if len(subtopic_summaries) == 1:
            logger.info(f"Single subtopic for '{topic_title}', using subtopic summary as base")
            # Still call LLM to rephrase at topic level

        formatted_subtopics = "\n".join(f"- {s}" for s in subtopic_summaries)

        try:
            prompt = self.topic_prompt_template.format(
                topic_title=topic_title,
                subtopic_summaries=formatted_subtopics
            )
            response = self.openai_client.chat.completions.create(
                model=self.model,
                temperature=0.3,
                max_completion_tokens=120,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            summary = response.choices[0].message.content.strip()
            logger.info(f"Generated topic summary for '{topic_title}': {len(summary.split())} words")
            return summary
        except Exception as e:
            logger.error(f"Failed to generate topic summary for '{topic_title}': {e}")
            return self._fallback_summary(topic_title)

    def _fallback_summary(self, title: str) -> str:
        """Generate fallback summary when LLM fails."""
        return f"{title} - teaching guidelines"

    def _load_prompt(self, filename: str) -> str:
        """Load prompt template from prompts directory."""
        prompt_path = Path(__file__).parent.parent / "prompts" / filename
        if prompt_path.exists():
            return prompt_path.read_text()
        else:
            logger.warning(f"Prompt file not found: {prompt_path}")
            return self._default_prompt(filename)

    def _default_prompt(self, filename: str) -> str:
        """Return default prompt if file not found."""
        if "subtopic" in filename:
            return """Summarize this teaching guideline in ONE concise line (15-30 words).
SUBTOPIC: {subtopic_title}
GUIDELINES: {guidelines}
Return ONLY the summary line."""
        else:
            return """Create a topic-level summary (20-40 words) from subtopic summaries.
TOPIC: {topic_title}
SUBTOPICS: {subtopic_summaries}
Return ONLY the summary line."""
