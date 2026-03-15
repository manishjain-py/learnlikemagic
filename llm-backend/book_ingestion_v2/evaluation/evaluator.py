"""
Book Ingestion Evaluator

Uses OpenAI Responses API (gpt-5.2) or Anthropic Messages API (claude-opus-4-6)
to evaluate topic extraction quality across 3 dimensions:
granularity, coverage depth, and copyright safety.
"""

import json
from pathlib import Path
from openai import OpenAI

from book_ingestion_v2.evaluation.config import IngestionEvalConfig

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
        self.provider = config.evaluator_provider

        if self.provider == "anthropic":
            import anthropic
            self.anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        else:
            self.client = OpenAI(api_key=config.openai_api_key)

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

    def _evaluate_openai(self, user_message: str) -> dict:
        judge_prompt = _load_judge_prompt()
        response = self.client.responses.create(
            model=self.config.evaluator_model,
            instructions=judge_prompt,
            input=user_message,
            reasoning={"effort": self.config.evaluator_reasoning_effort},
            text={"format": {"type": "json_object"}},
        )
        return json.loads(response.output_text)

    def _evaluate_anthropic(self, user_message: str) -> dict:
        judge_prompt = _load_judge_prompt()
        thinking_budget = self.config.anthropic_evaluator_thinking_budget
        max_tokens = max(thinking_budget + 8192, 25000)

        with self.anthropic_client.messages.stream(
            model=self.config.anthropic_evaluator_model,
            max_tokens=max_tokens,
            system=judge_prompt,
            thinking={
                "type": "enabled",
                "budget_tokens": thinking_budget,
            },
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for event in stream:
                pass
            response = stream.get_final_message()

        for block in response.content:
            if block.type == "text":
                text = block.text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()
                return json.loads(text)

        raise ValueError("No text block found in Anthropic response")

    def evaluate(self, pipeline_output: dict) -> dict:
        """Evaluate a pipeline extraction result."""
        user_message = self._build_user_message(pipeline_output)

        if self.provider == "anthropic":
            return self._evaluate_anthropic(user_message)
        return self._evaluate_openai(user_message)
