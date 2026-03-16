"""
Chapter topic planner service — plans chapter-level topic structure.

Analyzes full chapter content and produces a topic skeleton before
chunk-by-chunk extraction begins.
"""
import json
import hashlib
import logging
import time
from pathlib import Path
from typing import List, Dict, Any

from book_ingestion_v2.constants import CHUNK_MAX_RETRIES
from book_ingestion_v2.models.processing_models import (
    ChapterTopicPlan,
    PlannedTopic,
)
from shared.services.llm_service import LLMService

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "chapter_topic_planning.txt"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text()


class ChapterTopicPlannerService:
    """Plans chapter-level topic structure before chunk extraction."""

    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service

    def plan_chapter(
        self,
        book_metadata: dict,
        chapter_metadata: dict,
        page_texts: List[dict],
    ) -> ChapterTopicPlan:
        """
        Analyze full chapter content and produce a topic skeleton.

        Uses higher reasoning effort than chunk extraction since this
        makes structural decisions for the entire chapter.
        """
        prompt = self._build_prompt(book_metadata, chapter_metadata, page_texts)

        last_error = None
        for attempt in range(1, CHUNK_MAX_RETRIES + 1):
            try:
                start_ms = time.time()
                result = self.llm_service.call(
                    prompt=prompt,
                    json_mode=True,
                    reasoning_effort="high",
                )
                latency_ms = int((time.time() - start_ms) * 1000)

                output_text = result.get("output_text", "")
                parsed = self._parse_response(output_text)

                logger.info(json.dumps({
                    "step": "CHAPTER_PLANNED",
                    "attempt": attempt,
                    "latency_ms": latency_ms,
                    "topics_planned": len(parsed.topics),
                }))

                return parsed

            except Exception as e:
                last_error = e
                delay = 2 ** (attempt - 1)
                logger.warning(
                    f"Chapter planning attempt {attempt}/{CHUNK_MAX_RETRIES} failed: {e}. "
                    f"Retrying in {delay}s..."
                )
                if attempt < CHUNK_MAX_RETRIES:
                    time.sleep(delay)

        raise ValueError(
            f"Chapter planning failed after {CHUNK_MAX_RETRIES} attempts: {last_error}"
        )

    def _build_prompt(
        self,
        book_metadata: dict,
        chapter_metadata: dict,
        page_texts: List[dict],
    ) -> str:
        """Build the planning prompt from chapter content."""
        # Format all pages
        pages_lines = []
        for page in page_texts:
            pages_lines.append(
                f"--- Page {page['page_number']} ---\n{page['text']}"
            )
        all_pages_text = "\n\n".join(pages_lines)

        return _PROMPT_TEMPLATE.format(
            book_title=book_metadata.get("title", ""),
            subject=book_metadata.get("subject", ""),
            grade=book_metadata.get("grade", ""),
            board=book_metadata.get("board", ""),
            chapter_number=chapter_metadata.get("number", ""),
            chapter_title=chapter_metadata.get("title", ""),
            chapter_page_range=chapter_metadata.get("page_range", ""),
            all_pages_text=all_pages_text,
        )

    def _parse_response(self, output_text: str) -> ChapterTopicPlan:
        """Parse LLM response into structured output."""
        text = output_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        data = json.loads(text)
        return ChapterTopicPlan(**data)
