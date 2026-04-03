"""Generate a 'Get Ready' refresher topic for a chapter's prerequisite knowledge."""
import json
import logging
import uuid
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

from shared.services import LLMService
from shared.models.entities import TeachingGuideline, TopicExplanation
from shared.repositories.explanation_repository import ExplanationRepository
from book_ingestion_v2.services.explanation_generator_service import ExplanationCardOutput

from sqlalchemy.orm import Session as DBSession

logger = logging.getLogger(__name__)

# ─── Prompt template ──────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_REFRESHER_PROMPT = (_PROMPTS_DIR / "refresher_topic_generation.txt").read_text()

# ─── Pydantic models for structured LLM output ───────────────────────────


class PrerequisiteConcept(BaseModel):
    concept: str
    why_needed: str


class RefresherOutput(BaseModel):
    skip_refresher: bool
    skip_reason: Optional[str] = None
    prerequisite_concepts: list[PrerequisiteConcept] = Field(default_factory=list)
    refresher_guideline: str = ""
    topic_summary: str = ""
    cards: list[ExplanationCardOutput] = Field(default_factory=list)


class RefresherTopicGeneratorService:
    """Generates a prerequisite refresher topic for a chapter.

    Analyzes all topics in a chapter, identifies foundational knowledge gaps,
    and produces a 'Get Ready' topic with explanation cards.
    """

    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.llm = llm_service
        self.repo = ExplanationRepository(db)

        self._refresher_schema = LLMService.make_schema_strict(
            RefresherOutput.model_json_schema()
        )

    def generate_for_chapter(self, book_id: str, chapter_key: str) -> Optional[str]:
        """Generate refresher topic. Returns guideline_id or None if skipped."""
        # 1. Load all existing guidelines for the chapter (exclude existing refresher)
        guidelines = self._load_chapter_guidelines(book_id, chapter_key)
        if not guidelines:
            return None

        # 2. Load explanation cards for those guidelines
        explanation_cards = self._load_explanation_cards(guidelines)

        # 3. Delete any existing refresher for this chapter (idempotent)
        self._delete_existing_refresher(book_id, chapter_key)

        # 4. Build context for LLM
        chapter_context = self._build_chapter_context(guidelines, explanation_cards)

        # 5. Load other chapters' topics for cross-referencing
        other_chapters_context = self._build_cross_chapter_context(book_id, chapter_key)

        # 6. Call LLM to identify prerequisites and generate refresher
        result = self._generate_refresher(chapter_context, other_chapters_context, guidelines[0])
        if not result or result.skip_refresher:
            return None

        # 7. Store TeachingGuideline + TopicExplanation
        guideline_id = self._store_guideline(guidelines[0], result)
        self._store_explanation_cards(guideline_id, result.cards)
        return guideline_id

    # ─── Private helpers ──────────────────────────────────────────────────

    def _load_chapter_guidelines(self, book_id: str, chapter_key: str) -> list[TeachingGuideline]:
        return (
            self.db.query(TeachingGuideline)
            .filter(
                TeachingGuideline.book_id == book_id,
                TeachingGuideline.chapter_key == chapter_key,
                TeachingGuideline.topic_key != "get-ready",
            )
            .order_by(TeachingGuideline.topic_sequence)
            .all()
        )

    def _load_explanation_cards(self, guidelines: list[TeachingGuideline]) -> dict[str, list[dict]]:
        result = {}
        for g in guidelines:
            explanations = self.repo.get_by_guideline_id(g.id)
            cards = []
            for exp in explanations:
                if exp.cards_json:
                    cards.extend(exp.cards_json)
            result[g.id] = cards
        return result

    def _delete_existing_refresher(self, book_id: str, chapter_key: str):
        existing = (
            self.db.query(TeachingGuideline)
            .filter(
                TeachingGuideline.book_id == book_id,
                TeachingGuideline.chapter_key == chapter_key,
                TeachingGuideline.topic_key == "get-ready",
            )
            .all()
        )
        for g in existing:
            # TopicExplanation cascades on delete
            self.db.delete(g)
        if existing:
            self.db.commit()

    def _build_chapter_context(
        self,
        guidelines: list[TeachingGuideline],
        explanation_cards: dict[str, list[dict]],
    ) -> str:
        parts = []
        for g in guidelines:
            topic_title = g.topic_title or g.topic
            topic_summary = g.topic_summary or ""
            guideline_text = (g.guideline or g.description or "")[:500]
            card_titles = [c.get("title", "") for c in explanation_cards.get(g.id, [])]
            card_titles_str = ", ".join(card_titles) if card_titles else "(no cards)"

            parts.append(
                f"- Topic: {topic_title}\n"
                f"  Summary: {topic_summary}\n"
                f"  Guideline excerpt: {guideline_text}\n"
                f"  Card titles: {card_titles_str}"
            )
        return "\n".join(parts)

    def _build_cross_chapter_context(self, book_id: str, chapter_key: str) -> str:
        other_guidelines = (
            self.db.query(TeachingGuideline)
            .filter(
                TeachingGuideline.book_id == book_id,
                TeachingGuideline.chapter_key != chapter_key,
                TeachingGuideline.topic_key != "get-ready",
            )
            .order_by(TeachingGuideline.chapter_sequence, TeachingGuideline.topic_sequence)
            .all()
        )

        chapters: dict[str, list[str]] = {}
        for g in other_guidelines:
            ch_title = g.chapter_title or g.chapter_key or g.chapter
            topic_title = g.topic_title or g.topic
            chapters.setdefault(ch_title, []).append(topic_title)

        if not chapters:
            return "(no other chapters in this book)"

        parts = []
        for ch_title, topics in chapters.items():
            topics_str = ", ".join(topics)
            parts.append(f"- {ch_title}: {topics_str}")
        return "\n".join(parts)

    def _generate_refresher(
        self,
        chapter_context: str,
        other_chapters_context: str,
        sample_guideline: TeachingGuideline,
    ) -> Optional[RefresherOutput]:
        chapter_title = sample_guideline.chapter_title or sample_guideline.chapter
        chapter_summary = sample_guideline.chapter_summary or ""

        output_schema = json.dumps({
            "skip_refresher": False,
            "skip_reason": "null or reason string",
            "prerequisite_concepts": [
                {"concept": "concept name", "why_needed": "why this chapter needs it"}
            ],
            "refresher_guideline": "teaching guideline text for the refresher topic",
            "topic_summary": "15-30 word summary of the refresher topic",
            "cards": [
                {
                    "card_idx": 1,
                    "card_type": "concept | example | visual | analogy | summary",
                    "title": "short heading",
                    "content": "explanation text, simple language",
                    "visual": "optional ASCII/formatted visual or null",
                    "audio_text": "short spoken version for TTS — pure words, no symbols/markdown, math as speech"
                }
            ]
        }, indent=2)

        prompt = _REFRESHER_PROMPT.format(
            subject=sample_guideline.subject,
            grade=sample_guideline.grade,
            chapter_title=chapter_title,
            chapter_summary=chapter_summary,
            topics_context=chapter_context,
            other_chapters_context=other_chapters_context,
            output_schema=output_schema,
        )

        response = self.llm.call(
            prompt=prompt,
            reasoning_effort="high",
            json_schema=self._refresher_schema,
            schema_name="RefresherOutput",
        )

        parsed = self.llm.parse_json_response(response["output_text"])
        return RefresherOutput.model_validate(parsed)

    def _store_guideline(self, sample: TeachingGuideline, result: RefresherOutput) -> str:
        chapter_title = sample.chapter_title or sample.chapter
        guideline_id = str(uuid.uuid4())

        guideline = TeachingGuideline(
            id=guideline_id,
            book_id=sample.book_id,
            country=sample.country,
            board=sample.board,
            grade=sample.grade,
            subject=sample.subject,
            chapter=sample.chapter,
            chapter_key=sample.chapter_key,
            chapter_title=chapter_title,
            chapter_sequence=sample.chapter_sequence,
            topic="Get Ready",
            topic_key="get-ready",
            topic_title=f"Get Ready for {chapter_title}",
            topic_sequence=0,
            topic_summary=result.topic_summary,
            guideline=result.refresher_guideline,
            metadata_json=json.dumps({
                "is_refresher": True,
                "prerequisite_concepts": [c.model_dump() for c in result.prerequisite_concepts],
            }),
            status="approved",
            review_status="APPROVED",
        )
        self.db.add(guideline)
        self.db.commit()
        self.db.refresh(guideline)
        return guideline_id

    def _store_explanation_cards(self, guideline_id: str, cards: list[ExplanationCardOutput]):
        self.repo.upsert(
            guideline_id=guideline_id,
            variant_key="A",
            variant_label="Prerequisite Refresher",
            cards_json=[card.model_dump() for card in cards],
            summary_json={
                "key_analogies": [],
                "key_examples": [],
                "teaching_notes": "Prerequisite refresher for the chapter",
            },
            generator_model=self.llm.model_id,
        )
