"""
Pedagogical Sequencing Service

Determines optimal teaching order for subtopics within a topic
and topics within a book using LLM analysis.

Single Responsibility Principle:
- Only handles pedagogical sequencing logic
- Delegates LLM calls to injected client
"""

import logging
import json
import time
from pathlib import Path
from typing import List, Tuple, Optional

from openai import OpenAI

from ..models.guideline_models import SubtopicShard

logger = logging.getLogger(__name__)


class PedagogicalSequencingService:
    """
    LLM-based pedagogical sequencing for subtopics and topics.

    Two methods:
    - sequence_subtopics: Order subtopics within a topic + generate storyline
    - sequence_topics: Order topics within a book
    """

    def __init__(self, openai_client: Optional[OpenAI] = None, *, model: str):
        self.client = openai_client or OpenAI()
        self.model = model
        self.subtopic_prompt_template = self._load_prompt("subtopic_sequencing.txt")
        self.topic_prompt_template = self._load_prompt("topic_sequencing.txt")

    def _load_prompt(self, filename: str) -> str:
        prompt_path = Path(__file__).parent.parent / "prompts" / filename
        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.error(f"Prompt template not found: {prompt_path}")
            raise

    def sequence_subtopics(
        self,
        topic_title: str,
        subtopics: List[SubtopicShard],
        grade: int,
        subject: str
    ) -> Tuple[List[Tuple[str, int]], str]:
        """
        Determine pedagogical order for subtopics within a topic.

        Args:
            topic_title: Human-readable topic name
            subtopics: All shards belonging to this topic
            grade: Grade level
            subject: Subject name

        Returns:
            Tuple of:
            - List of (subtopic_key, sequence_number) pairs
            - topic_storyline string
        """
        if not subtopics:
            return [], ""

        if len(subtopics) == 1:
            return [(subtopics[0].subtopic_key, 1)], f"{topic_title} covers {subtopics[0].subtopic_title}."

        # Build subtopics info for prompt
        subtopics_info_lines = []
        for shard in subtopics:
            guidelines_preview = shard.guidelines[:500] + "..." if len(shard.guidelines) > 500 else shard.guidelines
            subtopics_info_lines.append(
                f"Key: {shard.subtopic_key}\n"
                f"Title: {shard.subtopic_title}\n"
                f"Summary: {shard.subtopic_summary}\n"
                f"Pages: {shard.source_page_start}-{shard.source_page_end}\n"
                f"Guidelines Preview: {guidelines_preview}\n"
            )

        prompt = self.subtopic_prompt_template.format(
            grade=grade,
            subject=subject,
            topic_title=topic_title,
            subtopics_info="\n---\n".join(subtopics_info_lines)
        )

        try:
            start_time = time.time()
            logger.info(json.dumps({
                "step": "SUBTOPIC_SEQUENCING",
                "status": "starting",
                "input": {"topic": topic_title, "subtopics_count": len(subtopics)}
            }))

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a pedagogical expert who determines optimal teaching order."},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=1500,
                temperature=0.2,
                response_format={"type": "json_object"}
            )

            raw = response.choices[0].message.content.strip()
            result = json.loads(raw)

            # Extract sequence pairs
            sequence_pairs = [
                (item["subtopic_key"], item["sequence"])
                for item in result.get("subtopics", [])
            ]
            storyline = result.get("topic_storyline", "")

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(json.dumps({
                "step": "SUBTOPIC_SEQUENCING",
                "status": "complete",
                "output": {"topic": topic_title, "pairs": len(sequence_pairs)},
                "duration_ms": duration_ms
            }))

            return sequence_pairs, storyline

        except Exception as e:
            logger.error(f"Subtopic sequencing failed for {topic_title}: {e}")
            # Fallback: sort by source_page_start
            fallback = sorted(subtopics, key=lambda s: s.source_page_start)
            pairs = [(s.subtopic_key, i + 1) for i, s in enumerate(fallback)]
            return pairs, ""

    def sequence_topics(
        self,
        topics_with_info: List[dict],
        grade: int,
        subject: str
    ) -> List[Tuple[str, int]]:
        """
        Determine pedagogical order for topics within a book.

        Args:
            topics_with_info: List of dicts with keys:
                topic_key, topic_title, topic_summary, subtopic_count,
                page_range, topic_storyline
            grade: Grade level
            subject: Subject name

        Returns:
            List of (topic_key, sequence_number) pairs
        """
        if not topics_with_info:
            return []

        if len(topics_with_info) == 1:
            return [(topics_with_info[0]["topic_key"], 1)]

        # Build topics info for prompt
        topics_info_lines = []
        for info in topics_with_info:
            topics_info_lines.append(
                f"Key: {info['topic_key']}\n"
                f"Title: {info['topic_title']}\n"
                f"Summary: {info.get('topic_summary', '')}\n"
                f"Subtopics: {info.get('subtopic_count', 0)}\n"
                f"Pages: {info.get('page_range', '')}\n"
                f"Storyline: {info.get('topic_storyline', '')}\n"
            )

        prompt = self.topic_prompt_template.format(
            grade=grade,
            subject=subject,
            topics_info="\n---\n".join(topics_info_lines)
        )

        try:
            start_time = time.time()
            logger.info(json.dumps({
                "step": "TOPIC_SEQUENCING",
                "status": "starting",
                "input": {"topics_count": len(topics_with_info)}
            }))

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a pedagogical expert who determines optimal teaching order."},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=1000,
                temperature=0.2,
                response_format={"type": "json_object"}
            )

            raw = response.choices[0].message.content.strip()
            result = json.loads(raw)

            pairs = [
                (item["topic_key"], item["sequence"])
                for item in result.get("topics", [])
            ]

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(json.dumps({
                "step": "TOPIC_SEQUENCING",
                "status": "complete",
                "output": {"pairs": len(pairs)},
                "duration_ms": duration_ms
            }))

            return pairs

        except Exception as e:
            logger.error(f"Topic sequencing failed: {e}")
            # Fallback: use provided order (which is typically page order)
            return [(info["topic_key"], i + 1) for i, info in enumerate(topics_with_info)]
