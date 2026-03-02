"""
Chunk processor service — processes a single 3-page chunk through the LLM.

Core V2 logic: builds prompt, calls LLM, parses structured JSON response.
"""
import json
import hashlib
import logging
import time
from pathlib import Path
from typing import Dict, Any

from book_ingestion_v2.constants import CHUNK_MAX_RETRIES
from book_ingestion_v2.models.processing_models import (
    ChunkInput,
    ChunkExtractionOutput,
    TopicAccumulator,
)
from shared.services.llm_service import LLMService

logger = logging.getLogger(__name__)

# Load prompt template once
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "chunk_topic_extraction.txt"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text()


class ChunkProcessorService:
    """Processes a single chunk through the LLM and returns structured output."""

    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service

    def process_chunk(self, chunk_input: ChunkInput) -> ChunkExtractionOutput:
        """
        Process a single chunk. Retries on failure up to CHUNK_MAX_RETRIES.

        Args:
            chunk_input: Full input for this chunk.

        Returns:
            Parsed ChunkExtractionOutput.

        Raises:
            ValueError: If all retries fail.
        """
        prompt = self._build_prompt(chunk_input)
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:12]

        last_error = None
        for attempt in range(1, CHUNK_MAX_RETRIES + 1):
            try:
                start_ms = time.time()
                result = self.llm_service.call(
                    prompt=prompt,
                    json_mode=True,
                    reasoning_effort="none",
                )
                latency_ms = int((time.time() - start_ms) * 1000)

                output_text = result.get("output_text", "")
                parsed = self._parse_response(output_text)

                logger.info(json.dumps({
                    "step": "CHUNK_PROCESSED",
                    "attempt": attempt,
                    "latency_ms": latency_ms,
                    "topics_detected": len(parsed.topics),
                    "prompt_hash": prompt_hash,
                }))

                return parsed

            except Exception as e:
                last_error = e
                delay = 2 ** (attempt - 1)  # 1s, 2s, 4s
                logger.warning(
                    f"Chunk processing attempt {attempt}/{CHUNK_MAX_RETRIES} failed: {e}. "
                    f"Retrying in {delay}s..."
                )
                if attempt < CHUNK_MAX_RETRIES:
                    time.sleep(delay)

        raise ValueError(
            f"Chunk processing failed after {CHUNK_MAX_RETRIES} attempts: {last_error}"
        )

    def get_prompt_hash(self) -> str:
        """Return hash of the prompt template for audit."""
        return hashlib.md5(_PROMPT_TEMPLATE.encode()).hexdigest()[:12]

    def _build_prompt(self, chunk_input: ChunkInput) -> str:
        """Build the LLM prompt from the chunk input."""
        # Format current pages
        current_pages_lines = []
        for page in chunk_input.current_pages:
            current_pages_lines.append(
                f"--- Page {page['page_number']} ---\n{page['text']}"
            )
        current_pages_text = "\n\n".join(current_pages_lines)

        # Format topics so far
        if chunk_input.topics_so_far:
            topics_lines = []
            for t in chunk_input.topics_so_far:
                topics_lines.append(
                    f"- {t.topic_key}: \"{t.topic_title}\" "
                    f"(pages {t.source_page_start}-{t.source_page_end})"
                )
            topics_so_far_text = "\n".join(topics_lines)
        else:
            topics_so_far_text = "(No topics detected yet — this is the first chunk)"

        return _PROMPT_TEMPLATE.format(
            book_title=chunk_input.book_metadata.get("title", ""),
            subject=chunk_input.book_metadata.get("subject", ""),
            grade=chunk_input.book_metadata.get("grade", ""),
            board=chunk_input.book_metadata.get("board", ""),
            chapter_number=chunk_input.chapter_metadata.get("number", ""),
            chapter_title=chunk_input.chapter_metadata.get("title", ""),
            chapter_page_range=chunk_input.chapter_metadata.get("page_range", ""),
            current_pages_text=current_pages_text,
            previous_page_context=chunk_input.previous_page_context or "(First chunk — no previous page)",
            chapter_summary_so_far=chunk_input.chapter_summary_so_far or "(Empty — this is the first chunk)",
            topics_so_far_text=topics_so_far_text,
        )

    def _parse_response(self, output_text: str) -> ChunkExtractionOutput:
        """Parse LLM response into structured output."""
        # Strip markdown code blocks if present
        text = output_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        data = json.loads(text)
        return ChunkExtractionOutput(**data)
