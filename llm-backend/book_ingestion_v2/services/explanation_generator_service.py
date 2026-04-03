"""Multi-pass LLM generation of pre-computed explanation variants for teaching guidelines."""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

from shared.services import LLMService
from shared.models.entities import TeachingGuideline, TopicExplanation
from shared.repositories.explanation_repository import ExplanationRepository

from sqlalchemy.orm import Session as DBSession

logger = logging.getLogger(__name__)

# ─── Prompt templates ───────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_GENERATION_PROMPT = (_PROMPTS_DIR / "explanation_generation.txt").read_text()
_REVIEW_REFINE_PROMPT = (_PROMPTS_DIR / "explanation_review_refine.txt").read_text()

# ─── Pydantic models for structured LLM output ─────────────────────────────


class ExplanationCardOutput(BaseModel):
    """A single explanation card returned by the LLM."""
    card_idx: int = Field(description="1-based card index")
    card_type: str = Field(description="concept, example, visual, analogy, or summary")
    title: str = Field(description="Short heading for the card")
    content: str = Field(description="Explanation text — simple language, short sentences")
    visual: Optional[str] = Field(default=None, description="Optional ASCII diagram or formatted visual")
    audio_text: str = Field(
        description="Short spoken version of this card for TTS audio playback. "
        "PURE SPOKEN WORDS ONLY — zero symbols, zero markdown, zero emoji. "
        "Write math as natural speech ('five plus three is eight', never '5 + 3 = 8'). "
        "Skip content that only works visually (diagrams, tables, ASCII art). "
        "Shorter than content — just the key idea in a warm, conversational tone. "
        "The student reads the full card on screen, this is a quick spoken companion."
    )


class ExplanationSummaryOutput(BaseModel):
    """Structured summary metadata returned alongside cards."""
    key_analogies: list[str] = Field(default_factory=list, description="Main analogies used")
    key_examples: list[str] = Field(default_factory=list, description="Main examples used")
    teaching_notes: str = Field(default="", description="2-3 sentence narrative: what was explained, how, key conceptual progression")


class GenerationOutput(BaseModel):
    """Full structured output from the generation prompt."""
    cards: list[ExplanationCardOutput] = Field(description="Ordered list of explanation cards")
    summary: ExplanationSummaryOutput = Field(description="Key analogies and examples used")


# ─── Variant configurations ────────────────────────────────────────────────

VARIANT_CONFIGS = [
    {"key": "A", "label": "Everyday Analogies", "approach": "analogy-driven with real-world examples"},
    {"key": "B", "label": "Visual Walkthrough", "approach": "diagram-heavy with visual step-by-step"},
    {"key": "C", "label": "Step-by-Step Procedure", "approach": "procedural walkthrough"},
]

# ─── Constants ──────────────────────────────────────────────────────────────

MIN_CARDS = 3
MAX_CARDS = 15
DEFAULT_VARIANT_COUNT = 1     # How many variants to generate per topic (1-3)
DEFAULT_REVIEW_ROUNDS = 1     # How many review-and-refine passes per variant


class ExplanationGeneratorService:
    """Generates pre-computed explanations for a teaching guideline.

    Pipeline: generate → review-and-refine (N rounds) → validate → store.
    """

    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.llm = llm_service
        self.repo = ExplanationRepository(db)

        # Pre-compute strict schema for structured output (shared by generation and review-refine)
        self._generation_schema = LLMService.make_schema_strict(
            GenerationOutput.model_json_schema()
        )

    def _refresh_db_session(self):
        """Get a fresh DB session after long-running LLM calls."""
        from database import get_db_manager
        try:
            self.db.close()
        except Exception:
            pass
        self.db = get_db_manager().get_session()
        self.repo = ExplanationRepository(self.db)

    def generate_for_guideline(
        self,
        guideline: TeachingGuideline,
        variant_keys: Optional[list[str]] = None,
        variant_count: int = DEFAULT_VARIANT_COUNT,
        review_rounds: int = DEFAULT_REVIEW_ROUNDS,
        stage_collector: list | None = None,
    ) -> list[TopicExplanation]:
        """Generate explanation variants for a guideline.

        Args:
            guideline: The teaching guideline to generate explanations for
            variant_keys: Explicit variant keys to generate (overrides variant_count)
            variant_count: Number of variants to generate (default: DEFAULT_VARIANT_COUNT)
            review_rounds: Number of review-and-refine passes (default: DEFAULT_REVIEW_ROUNDS)
            stage_collector: Optional list to collect intermediate stage snapshots

        Returns:
            List of successfully stored TopicExplanation records
        """
        if variant_keys:
            configs = [c for c in VARIANT_CONFIGS if c["key"] in variant_keys]
        else:
            configs = VARIANT_CONFIGS[:variant_count]

        topic = guideline.topic_title or guideline.topic
        results = []

        for config in configs:
            try:
                logger.info(json.dumps({
                    "step": "EXPLANATION_GENERATION",
                    "status": "starting",
                    "guideline_id": guideline.id,
                    "topic": topic,
                    "variant": config["key"],
                    "model": self.llm.model_id,
                }))

                cards, summary_json = self._generate_variant(
                    guideline, config,
                    review_rounds=review_rounds,
                    stage_collector=stage_collector,
                )

                if cards is None:
                    logger.warning(f"Variant {config['key']} skipped for {topic}: failed validation")
                    continue

                explanation = self.repo.upsert(
                    guideline_id=guideline.id,
                    variant_key=config["key"],
                    variant_label=config["label"],
                    cards_json=[c.model_dump() for c in cards],
                    summary_json=summary_json,
                    generator_model=self.llm.model_id,
                )
                results.append(explanation)

                logger.info(json.dumps({
                    "step": "EXPLANATION_GENERATION",
                    "status": "complete",
                    "guideline_id": guideline.id,
                    "variant": config["key"],
                    "cards_count": len(cards),
                }))

            except Exception as e:
                logger.error(f"Failed to generate variant {config['key']} for {topic}: {e}")
                continue

        return results

    def _generate_variant(
        self,
        guideline: TeachingGuideline,
        variant_config: dict,
        review_rounds: int = DEFAULT_REVIEW_ROUNDS,
        stage_collector: list | None = None,
    ) -> tuple[Optional[list[ExplanationCardOutput]], Optional[dict]]:
        """Generate → review-and-refine N rounds. Returns (cards, summary_json) or (None, None)."""
        topic = guideline.topic_title or guideline.topic

        # Step 1: Generate cards
        gen_output = self._generate_cards(guideline, variant_config)
        self._refresh_db_session()
        cards = gen_output.cards

        # Capture initial stage
        if stage_collector is not None:
            stage_collector.append({
                "guideline_id": guideline.id,
                "topic_title": topic,
                "variant_key": variant_config["key"],
                "stage": "initial",
                "cards": [c.model_dump() for c in cards],
                "timestamp": datetime.utcnow().isoformat(),
            })

        # Validate card count
        if len(cards) < MIN_CARDS:
            logger.warning(f"Generated only {len(cards)} cards (min {MIN_CARDS}), skipping variant")
            return None, None
        if len(cards) > MAX_CARDS:
            cards = cards[:MAX_CARDS]

        # Step 2: Review-and-refine for N rounds
        for round_num in range(1, review_rounds + 1):
            logger.info(f"Review-refine round {round_num}/{review_rounds}")
            refined_output = self._review_and_refine(cards, guideline)
            self._refresh_db_session()
            cards = refined_output.cards
            gen_output = refined_output

            # Capture refine stage
            if stage_collector is not None:
                stage_collector.append({
                    "guideline_id": guideline.id,
                    "topic_title": topic,
                    "variant_key": variant_config["key"],
                    "stage": f"refine_{round_num}",
                    "cards": [c.model_dump() for c in cards],
                    "timestamp": datetime.utcnow().isoformat(),
                })

            # Re-validate after each round
            if len(cards) < MIN_CARDS:
                logger.warning(f"Round {round_num}: only {len(cards)} cards (min {MIN_CARDS}), skipping")
                return None, None
            if len(cards) > MAX_CARDS:
                cards = cards[:MAX_CARDS]

        # Step 3: Build summary_json
        summary_json = self._build_summary(gen_output, variant_config)

        return cards, summary_json

    def _generate_cards(
        self,
        guideline: TeachingGuideline,
        variant_config: dict,
    ) -> GenerationOutput:
        """LLM call: generate explanation cards for one variant."""
        topic = guideline.topic_title or guideline.topic
        guideline_text = guideline.guideline or guideline.description or ""

        # Build prior topics section
        prior_topics_section = ""
        if guideline.prior_topics_context:
            prior_topics_section = (
                f"PRIOR TOPICS CONTEXT (what the student has seen earlier in this chapter):\n"
                f"{guideline.prior_topics_context}\n"
                f"Weave natural references to these earlier topics where relevant."
            )

        # Build output schema description for the prompt
        output_schema = json.dumps({
            "cards": [
                {
                    "card_idx": 1,
                    "card_type": "concept | example | visual | analogy | summary",
                    "title": "short heading",
                    "content": "explanation text, simple language",
                    "visual": "optional ASCII/formatted visual or null",
                    "audio_text": "short spoken version for TTS — pure words, no symbols/markdown, math as speech"
                }
            ],
            "summary": {
                "key_analogies": ["analogy1", "analogy2"],
                "key_examples": ["example1", "example2"],
                "teaching_notes": "2-3 sentence narrative of what was explained and how"
            }
        }, indent=2)

        prompt = _GENERATION_PROMPT.format(
            topic_name=topic,
            subject=guideline.subject,
            grade=guideline.grade,
            guideline_text=guideline_text,
            prior_topics_section=prior_topics_section,
            variant_approach=variant_config["approach"],
            output_schema=output_schema,
        )

        response = self.llm.call(
            prompt=prompt,
            reasoning_effort="high",
            json_schema=self._generation_schema,
            schema_name="GenerationOutput",
        )

        parsed = self.llm.parse_json_response(response["output_text"])
        return GenerationOutput.model_validate(parsed)

    def _review_and_refine(
        self,
        cards: list[ExplanationCardOutput],
        guideline: TeachingGuideline,
    ) -> GenerationOutput:
        """LLM call: review cards from a student's perspective and fix directly."""
        topic = guideline.topic_title or guideline.topic
        guideline_text = guideline.guideline or guideline.description or ""

        cards_json = json.dumps([c.model_dump() for c in cards], indent=2)

        prior_topics_section = ""
        if guideline.prior_topics_context:
            prior_topics_section = (
                f"PRIOR TOPICS CONTEXT (what the student has seen earlier in this chapter):\n"
                f"{guideline.prior_topics_context}\n"
                f"Weave natural references to these earlier topics where relevant."
            )

        output_schema = json.dumps({
            "cards": [
                {
                    "card_idx": 1,
                    "card_type": "concept | example | visual | analogy | summary",
                    "title": "short heading",
                    "content": "explanation text, simple language",
                    "visual": "optional ASCII/formatted visual or null",
                    "audio_text": "short spoken version for TTS — pure words, no symbols/markdown, math as speech"
                }
            ],
            "summary": {
                "key_analogies": ["analogy1", "analogy2"],
                "key_examples": ["example1", "example2"],
                "teaching_notes": "2-3 sentence narrative of what was explained and how"
            }
        }, indent=2)

        prompt = _REVIEW_REFINE_PROMPT.format(
            topic_name=topic,
            subject=guideline.subject,
            grade=guideline.grade,
            guideline_text=guideline_text,
            prior_topics_section=prior_topics_section,
            cards_json=cards_json,
            output_schema=output_schema,
        )

        response = self.llm.call(
            prompt=prompt,
            reasoning_effort="high",
            json_schema=self._generation_schema,
            schema_name="GenerationOutput",
        )

        parsed = self.llm.parse_json_response(response["output_text"])
        return GenerationOutput.model_validate(parsed)

    def _build_summary(self, gen_output: GenerationOutput, variant_config: dict) -> dict:
        """Build summary_json from LLM-returned structured metadata (not parsed from freeform text)."""
        return {
            "card_titles": [c.title for c in gen_output.cards],
            "key_analogies": gen_output.summary.key_analogies,
            "key_examples": gen_output.summary.key_examples,
            "approach_label": variant_config["label"],
            "teaching_notes": gen_output.summary.teaching_notes,
        }

    def refine_only_for_guideline(
        self,
        guideline: TeachingGuideline,
        review_rounds: int = DEFAULT_REVIEW_ROUNDS,
        stage_collector: list | None = None,
    ) -> list[TopicExplanation]:
        """Load existing explanation cards from DB, run review-refine only, save back."""
        existing = self.repo.get_by_guideline_id(guideline.id)
        if not existing:
            logger.warning(f"No existing explanations for {guideline.id}, skipping refine-only")
            return []

        topic = guideline.topic_title or guideline.topic
        results = []

        for explanation in existing:
            try:
                cards = [ExplanationCardOutput(**c) for c in explanation.cards_json]
                variant_config = {"key": explanation.variant_key, "label": explanation.variant_label}

                # Snapshot the existing state
                if stage_collector is not None:
                    stage_collector.append({
                        "guideline_id": guideline.id,
                        "topic_title": topic,
                        "variant_key": explanation.variant_key,
                        "stage": "existing",
                        "cards": explanation.cards_json,
                        "timestamp": datetime.utcnow().isoformat(),
                    })

                # Run N rounds of review-refine
                gen_output = None
                for round_num in range(1, review_rounds + 1):
                    logger.info(f"Refine-only round {round_num}/{review_rounds} for {topic}")
                    gen_output = self._review_and_refine(cards, guideline)
                    self._refresh_db_session()
                    cards = gen_output.cards

                    if stage_collector is not None:
                        stage_collector.append({
                            "guideline_id": guideline.id,
                            "topic_title": topic,
                            "variant_key": explanation.variant_key,
                            "stage": f"refine_{round_num}",
                            "cards": [c.model_dump() for c in cards],
                            "timestamp": datetime.utcnow().isoformat(),
                        })

                    if len(cards) < MIN_CARDS:
                        logger.warning(f"Refine round {round_num}: only {len(cards)} cards, skipping")
                        break
                    if len(cards) > MAX_CARDS:
                        cards = cards[:MAX_CARDS]

                if gen_output is None or len(cards) < MIN_CARDS:
                    continue

                # Save refined cards back
                summary_json = self._build_summary(gen_output, variant_config)
                updated = self.repo.upsert(
                    guideline_id=guideline.id,
                    variant_key=explanation.variant_key,
                    variant_label=explanation.variant_label,
                    cards_json=[c.model_dump() for c in cards],
                    summary_json=summary_json,
                    generator_model=self.llm.model_id,
                )
                results.append(updated)

            except Exception as e:
                logger.error(f"Refine-only failed for {topic} variant {explanation.variant_key}: {e}")
                continue

        return results

    def refine_only_for_chapter(
        self,
        book_id: str,
        chapter_id: str | None = None,
        review_rounds: int = DEFAULT_REVIEW_ROUNDS,
        job_service=None,
        job_id: str | None = None,
    ) -> dict:
        """Run refine-only for all topics in a chapter."""
        query = self.db.query(TeachingGuideline).filter(
            TeachingGuideline.book_id == book_id,
            TeachingGuideline.review_status == "APPROVED",
        )
        if chapter_id:
            from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
            chapter = ChapterRepository(self.db).get_by_id(chapter_id)
            if chapter:
                chapter_key = f"chapter-{chapter.chapter_number}"
                query = query.filter(TeachingGuideline.chapter_key == chapter_key)
            else:
                return {"generated": 0, "skipped": 0, "failed": 0, "errors": [f"Chapter {chapter_id} not found"]}

        guidelines = query.order_by(TeachingGuideline.topic_sequence).all()
        refined = 0
        skipped = 0
        failed = 0
        errors = []

        for guideline in guidelines:
            topic = guideline.topic_title or guideline.topic
            try:
                if job_service and job_id:
                    job_service.update_progress(job_id, current_item=topic, completed=refined, failed=failed)

                if not self.repo.has_explanations(guideline.id):
                    skipped += 1
                    continue

                stage_collector = []
                results = self.refine_only_for_guideline(
                    guideline, review_rounds=review_rounds, stage_collector=stage_collector,
                )

                if job_service and job_id and stage_collector:
                    job_service.append_stage_snapshots(job_id, stage_collector)

                if results:
                    refined += 1
                else:
                    failed += 1
                    errors.append(f"{topic}: refine-only produced no valid output")

            except Exception as e:
                failed += 1
                errors.append(f"{topic}: {str(e)}")
                logger.error(f"Refine-only failed for {topic}: {e}")

        if job_service and job_id:
            job_service.update_progress(
                job_id, current_item=None, completed=refined, failed=failed,
                detail=json.dumps({"refined": refined, "skipped": skipped, "failed": failed, "errors": errors}),
            )

        return {"generated": refined, "skipped": skipped, "failed": failed, "errors": errors}

    def generate_for_chapter(
        self,
        book_id: str,
        chapter_id: Optional[str] = None,
        job_service=None,
        job_id: Optional[str] = None,
        force: bool = False,
        review_rounds: int = DEFAULT_REVIEW_ROUNDS,
    ) -> dict:
        """Generate explanations for all synced guidelines in a chapter (or book).

        Args:
            book_id: The book to generate for.
            chapter_id: Optional chapter UUID to scope generation.
            job_service: Optional ChapterJobService for progress tracking.
            job_id: Optional job ID for progress tracking.
            force: If True, delete existing explanations and regenerate instead of skipping.
            review_rounds: Number of review-and-refine passes per topic.

        Returns:
            Dict with generated, skipped, failed counts and error messages.
        """
        query = self.db.query(TeachingGuideline).filter(
            TeachingGuideline.book_id == book_id,
            TeachingGuideline.review_status == "APPROVED",
        )
        if chapter_id:
            from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
            chapter = ChapterRepository(self.db).get_by_id(chapter_id)
            if chapter:
                chapter_key = f"chapter-{chapter.chapter_number}"
                query = query.filter(TeachingGuideline.chapter_key == chapter_key)
            else:
                logger.warning(f"Chapter {chapter_id} not found")
                return {"generated": 0, "skipped": 0, "failed": 0, "errors": [f"Chapter {chapter_id} not found"]}

        guidelines = query.order_by(TeachingGuideline.topic_sequence).all()

        generated = 0
        skipped = 0
        failed = 0
        errors = []

        for guideline in guidelines:
            topic = guideline.topic_title or guideline.topic
            try:
                if job_service and job_id:
                    job_service.update_progress(
                        job_id, current_item=topic, completed=generated, failed=failed,
                    )

                # Check if explanations already exist
                if self.repo.has_explanations(guideline.id):
                    if force:
                        logger.info(f"Force mode: deleting existing explanations for {topic}")
                        self.repo.delete_by_guideline_id(guideline.id)
                    else:
                        logger.info(f"Explanations already exist for {topic}, skipping")
                        skipped += 1
                        continue

                stage_collector = []
                results = self.generate_for_guideline(
                    guideline, review_rounds=review_rounds, stage_collector=stage_collector,
                )

                # Flush stage snapshots to job
                if job_service and job_id and stage_collector:
                    job_service.append_stage_snapshots(job_id, stage_collector)
                if results:
                    generated += 1
                else:
                    failed += 1
                    errors.append(f"{topic}: no variants passed validation")

            except Exception as e:
                failed += 1
                errors.append(f"{topic}: {str(e)}")
                logger.error(f"Explanation generation failed for {topic}: {e}")

        # Final progress update with result summary in detail
        if job_service and job_id:
            import json
            job_service.update_progress(
                job_id,
                current_item=None,
                completed=generated,
                failed=failed,
                detail=json.dumps({
                    "generated": generated,
                    "skipped": skipped,
                    "failed": failed,
                    "errors": errors,
                }),
            )

        return {
            "generated": generated,
            "skipped": skipped,
            "failed": failed,
            "errors": errors,
        }

    def generate_for_book(self, book_id: str) -> dict:
        """Generate explanations for all synced guidelines in a book."""
        return self.generate_for_chapter(book_id, chapter_id=None)
