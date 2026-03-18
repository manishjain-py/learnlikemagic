"""
Book Ingestion Evaluator

Uses LLMService (supports openai, anthropic, claude_code providers)
to evaluate topic extraction quality across 3 dimensions:
granularity, coverage depth, and copyright safety.
"""

import json
from pathlib import Path

from autoresearch.book_ingestion_quality.evaluation.config import IngestionEvalConfig

EVALUATION_DIMENSIONS = [
    "granularity",
    "coverage_depth",
    "copyright_safety",
]

ROOT_CAUSE_CATEGORIES = [
    "over_splitting",
    "under_splitting",
    "missing_coverage",
    "shallow_guidelines",
    "verbatim_copy",
    "paraphrase_copy",
    "wrong_scope",
    "missing_prerequisites",
    "missing_misconceptions",
    "sequence_error",
    "other",
]

JUDGE_PROMPT_PATH = Path(__file__).parent / "prompts" / "judge.txt"


def _load_judge_prompt() -> str:
    return JUDGE_PROMPT_PATH.read_text()


class IngestionEvaluator:
    """Evaluates topic extraction output using an LLM judge."""

    def __init__(self, config: IngestionEvalConfig):
        self.config = config
        self.llm = config.create_llm_service()

    def _build_user_message(self, pipeline_output: dict) -> str:
        """Build the user message from pipeline output."""
        chapter = pipeline_output["chapter"]
        book = pipeline_output["book_metadata"]
        topics = pipeline_output["topics"]
        pages = pipeline_output.get("original_pages", [])

        lines = []

        # Book + chapter context
        lines.append("## BOOK METADATA")
        lines.append(f"Title: {book['title']}")
        lines.append(f"Subject: {book['subject']}")
        lines.append(f"Grade: {book['grade']}")
        lines.append(f"Board: {book['board']}")
        lines.append("")

        lines.append("## CHAPTER")
        lines.append(f"Chapter {chapter['chapter_number']}: {chapter['chapter_title']}")
        lines.append(f"Pages: {chapter.get('start_page', '?')} - {chapter.get('end_page', '?')}")
        lines.append(f"Status: {chapter.get('status', '?')}")
        lines.append("")

        # Original page texts (for copyright checking)
        if pages:
            lines.append("## ORIGINAL PAGE TEXTS")
            lines.append("(OCR'd text from each page — use to check for verbatim copying)")
            lines.append("")
            for page in pages:
                lines.append(f"### Page {page['page_number']}")
                lines.append(page["text"])
                lines.append("")

        # Extracted topics
        lines.append("## EXTRACTED TOPICS")
        lines.append(f"Total topics extracted: {len(topics)}")
        lines.append("")

        for i, topic in enumerate(topics, 1):
            lines.append(f"### Topic {i}: {topic['topic_title']} ({topic['topic_key']})")
            lines.append(f"- Sequence order: {topic.get('sequence_order', '?')}")
            lines.append(f"- Source pages: {topic.get('source_page_start', '?')} - {topic.get('source_page_end', '?')}")
            lines.append(f"- Status: {topic.get('status', '?')}")
            lines.append("")
            lines.append("**Guidelines:**")
            lines.append(topic.get("guidelines", "(no guidelines)"))
            lines.append("")
            if topic.get("summary"):
                lines.append("**Summary:**")
                lines.append(topic["summary"])
                lines.append("")

        lines.append("---")
        lines.append("Please evaluate this topic extraction according to the rubric. Return your evaluation as JSON.")

        return "\n".join(lines)

    def evaluate(self, pipeline_output: dict) -> dict:
        """Evaluate a pipeline extraction result."""
        judge_prompt = _load_judge_prompt()
        user_message = self._build_user_message(pipeline_output)
        prompt = f"{judge_prompt}\n\n{user_message}"

        result = self.llm.call(prompt=prompt, reasoning_effort="high", json_mode=True)
        parsed = result.get("parsed") or self.llm.parse_json_response(result["output_text"])
        return parsed
