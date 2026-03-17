"""Multi-pass LLM generation of pre-computed explanation variants for teaching guidelines."""
import json
import logging
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
_CRITIQUE_PROMPT = (_PROMPTS_DIR / "explanation_critique.txt").read_text()

# ─── Pydantic models for structured LLM output ─────────────────────────────


class ExplanationCardOutput(BaseModel):
    """A single explanation card returned by the LLM."""
    card_idx: int = Field(description="1-based card index")
    card_type: str = Field(description="concept, example, visual, analogy, or summary")
    title: str = Field(description="Short heading for the card")
    content: str = Field(description="Explanation text — simple language, short sentences")
    visual: Optional[str] = Field(default=None, description="Optional ASCII diagram or formatted visual")


class ExplanationSummaryOutput(BaseModel):
    """Structured summary metadata returned alongside cards."""
    key_analogies: list[str] = Field(default_factory=list, description="Main analogies used")
    key_examples: list[str] = Field(default_factory=list, description="Main examples used")


class GenerationOutput(BaseModel):
    """Full structured output from the generation prompt."""
    cards: list[ExplanationCardOutput] = Field(description="Ordered list of explanation cards")
    summary: ExplanationSummaryOutput = Field(description="Key analogies and examples used")


class CritiqueIssue(BaseModel):
    """A single issue found during critique."""
    card_idx: int = Field(description="Which card has the issue (1-based)")
    principle_violated: str = Field(description="Which explanation principle is violated")
    description: str = Field(description="What the issue is")


class CritiqueSuggestion(BaseModel):
    """A suggestion for improving a card."""
    card_idx: int = Field(description="Which card to improve (1-based)")
    suggestion: str = Field(description="What to change")


class CritiqueOutput(BaseModel):
    """Structured output from the critique prompt."""
    issues: list[CritiqueIssue] = Field(default_factory=list, description="Issues found")
    suggestions: list[CritiqueSuggestion] = Field(default_factory=list, description="Improvement suggestions")
    overall_quality: str = Field(description="good, needs_improvement, or poor")


# ─── Variant configurations ────────────────────────────────────────────────

VARIANT_CONFIGS = [
    {"key": "A", "label": "Everyday Analogies", "approach": "analogy-driven with real-world examples"},
    {"key": "B", "label": "Visual Walkthrough", "approach": "diagram-heavy with visual step-by-step"},
    {"key": "C", "label": "Step-by-Step Procedure", "approach": "procedural walkthrough"},
]

# ─── Constants ──────────────────────────────────────────────────────────────

MIN_CARDS = 3
MAX_CARDS = 15


class ExplanationGeneratorService:
    """Generates multi-variant pre-computed explanations for a teaching guideline.

    Pipeline per variant: generate → critique → refine (if needed) → validate → store.
    """

    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.llm = llm_service
        self.repo = ExplanationRepository(db)

        # Pre-compute strict schemas for structured output
        self._generation_schema = LLMService.make_schema_strict(
            GenerationOutput.model_json_schema()
        )
        self._critique_schema = LLMService.make_schema_strict(
            CritiqueOutput.model_json_schema()
        )

    def generate_for_guideline(
        self,
        guideline: TeachingGuideline,
        variant_keys: Optional[list[str]] = None,
    ) -> list[TopicExplanation]:
        """Generate explanation variants for a guideline. Multi-pass per variant.

        Args:
            guideline: The teaching guideline to generate explanations for
            variant_keys: Optional list of variant keys to generate (default: all)

        Returns:
            List of successfully stored TopicExplanation records
        """
        configs = VARIANT_CONFIGS
        if variant_keys:
            configs = [c for c in VARIANT_CONFIGS if c["key"] in variant_keys]

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

                cards, summary_json = self._generate_variant(guideline, config)

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
    ) -> tuple[Optional[list[ExplanationCardOutput]], Optional[dict]]:
        """Single variant: generate → critique → refine. Returns (cards, summary_json) or (None, None)."""

        # Step 1: Generate cards
        gen_output = self._generate_cards(guideline, variant_config)
        cards = gen_output.cards

        # Step 2: Validate card count
        if len(cards) < MIN_CARDS:
            logger.warning(f"Generated only {len(cards)} cards (min {MIN_CARDS}), skipping variant")
            return None, None

        # Trim if too many
        if len(cards) > MAX_CARDS:
            logger.info(f"Trimming {len(cards)} cards to {MAX_CARDS}")
            cards = cards[:MAX_CARDS]

        # Step 3: Critique
        critique = self._critique_cards(cards, guideline, variant_config)

        # Step 4: Refine if needed
        if critique.overall_quality == "needs_improvement":
            cards_dicts = [c.model_dump() for c in cards]
            refined_output = self._refine_cards(cards_dicts, critique, guideline, variant_config)
            cards = refined_output.cards

            # Re-validate after refinement
            if len(cards) < MIN_CARDS:
                logger.warning(f"Refined cards only {len(cards)} (min {MIN_CARDS}), skipping variant")
                return None, None
            if len(cards) > MAX_CARDS:
                cards = cards[:MAX_CARDS]

            # Rebuild summary from refined output (not the original gen_output)
            gen_output = refined_output

        elif critique.overall_quality == "poor":
            logger.warning(f"Critique rated quality as 'poor', skipping variant")
            return None, None

        # Step 5: Build summary_json
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
                    "visual": "optional ASCII/formatted visual or null"
                }
            ],
            "summary": {
                "key_analogies": ["analogy1", "analogy2"],
                "key_examples": ["example1", "example2"]
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

    def _critique_cards(
        self,
        cards: list[ExplanationCardOutput],
        guideline: TeachingGuideline,
        variant_config: dict,
    ) -> CritiqueOutput:
        """LLM call: critique cards against how-to-explain principles."""
        topic = guideline.topic_title or guideline.topic
        guideline_text = guideline.guideline or guideline.description or ""

        cards_json = json.dumps([c.model_dump() for c in cards], indent=2)

        output_schema = json.dumps({
            "issues": [
                {"card_idx": 2, "principle_violated": "One Idea Per Card", "description": "..."}
            ],
            "suggestions": [
                {"card_idx": 3, "suggestion": "Add a concrete example before the rule"}
            ],
            "overall_quality": "good | needs_improvement | poor"
        }, indent=2)

        prompt = _CRITIQUE_PROMPT.format(
            topic_name=topic,
            subject=guideline.subject,
            grade=guideline.grade,
            guideline_text=guideline_text,
            cards_json=cards_json,
            output_schema=output_schema,
        )

        response = self.llm.call(
            prompt=prompt,
            reasoning_effort="medium",
            json_schema=self._critique_schema,
            schema_name="CritiqueOutput",
        )

        parsed = self.llm.parse_json_response(response["output_text"])
        return CritiqueOutput.model_validate(parsed)

    def _refine_cards(
        self,
        cards_dicts: list[dict],
        critique: CritiqueOutput,
        guideline: TeachingGuideline,
        variant_config: dict,
    ) -> GenerationOutput:
        """LLM call: refine cards based on critique feedback."""
        topic = guideline.topic_title or guideline.topic
        guideline_text = guideline.guideline or guideline.description or ""

        # Build a refinement prompt that includes the original cards + critique
        critique_text = ""
        if critique.issues:
            critique_text += "ISSUES FOUND:\n"
            for issue in critique.issues:
                critique_text += f"- Card {issue.card_idx}: {issue.principle_violated} — {issue.description}\n"
        if critique.suggestions:
            critique_text += "\nSUGGESTIONS:\n"
            for s in critique.suggestions:
                critique_text += f"- Card {s.card_idx}: {s.suggestion}\n"

        # Build prior topics section
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
                    "visual": "optional ASCII/formatted visual or null"
                }
            ],
            "summary": {
                "key_analogies": ["analogy1", "analogy2"],
                "key_examples": ["example1", "example2"]
            }
        }, indent=2)

        refinement_prompt = f"""You are refining a set of explanation cards based on quality feedback.

TOPIC: {topic}
SUBJECT: {guideline.subject}, Grade {guideline.grade}
TEACHING GUIDELINE:
{guideline_text}

{prior_topics_section}

VARIANT APPROACH: {variant_config["approach"]}

ORIGINAL CARDS:
{json.dumps(cards_dicts, indent=2)}

CRITIQUE FEEDBACK:
{critique_text}

TASK:
Revise the cards to address the issues and incorporate the suggestions. Keep the same variant approach. You may add, remove, reorder, or rewrite cards as needed. Maintain all 12 explanation principles.

OUTPUT FORMAT — respond with valid JSON only, no other text:
{output_schema}"""

        response = self.llm.call(
            prompt=refinement_prompt,
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
        }

    def generate_for_chapter(self, book_id: str, chapter_id: Optional[str] = None) -> dict:
        """Generate explanations for all synced guidelines in a chapter (or book).

        Returns:
            Dict with generated, skipped, failed counts and error messages.
        """
        query = self.db.query(TeachingGuideline).filter(
            TeachingGuideline.book_id == book_id,
            TeachingGuideline.review_status == "APPROVED",
        )
        if chapter_id:
            # chapter_id is a UUID from book_chapters. Sync service sets
            # chapter_key = f"chapter-{chapter_number}" on guidelines.
            # Look up the chapter to get its number, then filter by chapter_key.
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
                # Check if explanations already exist
                if self.repo.has_explanations(guideline.id):
                    logger.info(f"Explanations already exist for {topic}, skipping")
                    skipped += 1
                    continue

                results = self.generate_for_guideline(guideline)
                if results:
                    generated += 1
                else:
                    failed += 1
                    errors.append(f"{topic}: no variants passed validation")

            except Exception as e:
                failed += 1
                errors.append(f"{topic}: {str(e)}")
                logger.error(f"Explanation generation failed for {topic}: {e}")

        return {
            "generated": generated,
            "skipped": skipped,
            "failed": failed,
            "errors": errors,
        }

    def generate_for_book(self, book_id: str) -> dict:
        """Generate explanations for all synced guidelines in a book."""
        return self.generate_for_chapter(book_id, chapter_id=None)
