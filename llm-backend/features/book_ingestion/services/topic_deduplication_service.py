"""
Topic Deduplication Service (V2)

V2 Innovation: End-of-book deduplication pass to catch over-segmentation.

Single Responsibility Principle:
- Only handles identification of duplicate topics/subtopics
- Uses LLM to analyze all topics holistically
- Delegates LLM calls to injected client
"""

import logging
import json
from pathlib import Path
from typing import List, Tuple, Optional

from openai import OpenAI

from ..models.guideline_models import SubtopicShard

logger = logging.getLogger(__name__)


class TopicDeduplicationService:
    """
    V2 service for end-of-book topic/subtopic deduplication.

    After all pages processed, identify duplicate topics (e.g., "Data Handling" vs "data-handling-basics")
    and merge them.
    """

    def __init__(self, openai_client: Optional[OpenAI] = None):
        """
        Initialize topic deduplication service.

        Args:
            openai_client: Optional OpenAI client (if None, creates new one)
        """
        self.client = openai_client or OpenAI()
        self.model = "gpt-4o-mini"
        self.max_tokens = 2000  # Need space for analyzing many topics
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load topic deduplication prompt template"""
        prompt_path = Path(__file__).parent.parent / "prompts" / "topic_deduplication_v2.txt"

        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.error(f"Prompt template not found: {prompt_path}")
            raise

    def deduplicate(
        self,
        all_shards: List[SubtopicShard],
        grade: int,
        subject: str
    ) -> List[Tuple[str, str, str, str]]:
        """
        Identify duplicate topics/subtopics.

        Args:
            all_shards: All subtopic shards from the book
            grade: Grade level
            subject: Subject

        Returns:
            List of tuples: (topic_key1, subtopic_key1, topic_key2, subtopic_key2)
            Each tuple represents a duplicate pair that should be merged.

        Raises:
            ValueError: If deduplication analysis fails
        """
        if not all_shards:
            logger.info("No shards to deduplicate")
            return []

        if len(all_shards) == 1:
            logger.info("Only one shard, no deduplication needed")
            return []

        # Build summary of all topics
        topics_summary = self._build_topics_summary(all_shards)

        # Build prompt
        prompt = self._build_prompt(topics_summary, grade, subject)

        try:
            # Call LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a curriculum structure analyzer specializing in identifying duplicate topics."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=self.max_tokens,
                temperature=0.2,  # Low temperature for consistent analysis
                response_format={"type": "json_object"}  # Force JSON response
            )

            # Parse response
            raw_response = response.choices[0].message.content.strip()
            result = json.loads(raw_response)

            # Extract duplicates
            duplicates = []
            for dup in result.get("duplicates", []):
                duplicates.append((
                    dup["topic_key1"],
                    dup["subtopic_key1"],
                    dup["topic_key2"],
                    dup["subtopic_key2"]
                ))

            logger.info(f"Found {len(duplicates)} duplicate topic/subtopic pairs")

            return duplicates

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse deduplication response as JSON: {str(e)}")
            logger.error(f"Raw response: {raw_response}")
            return []  # Safe fallback: no duplicates

        except Exception as e:
            logger.error(f"Deduplication analysis failed: {str(e)}")
            return []  # Safe fallback: no duplicates

    def _build_topics_summary(self, shards: List[SubtopicShard]) -> str:
        """
        Build a summary of all topics for LLM analysis.

        Args:
            shards: List of subtopic shards

        Returns:
            Formatted summary string
        """
        summary_lines = []

        for shard in shards:
            guidelines_preview = shard.guidelines[:200] + "..." if len(shard.guidelines) > 200 else shard.guidelines

            summary_lines.append(
                f"\nTopic: {shard.topic_title} ({shard.topic_key})\n"
                f"Subtopic: {shard.subtopic_title} ({shard.subtopic_key})\n"
                f"Pages: {shard.source_page_start}-{shard.source_page_end}\n"
                f"Guidelines Preview: {guidelines_preview}\n"
            )

        return "\n".join(summary_lines)

    def _build_prompt(self, topics_summary: str, grade: int, subject: str) -> str:
        """
        Build topic deduplication prompt.

        Args:
            topics_summary: Formatted summary of all topics
            grade: Grade level
            subject: Subject

        Returns:
            Formatted prompt string
        """
        return self.prompt_template.format(
            grade=grade,
            subject=subject,
            topics_summary=topics_summary
        )
