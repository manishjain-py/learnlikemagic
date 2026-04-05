"""Offline pipeline to enrich explanation cards with interactive check-in activities.

Pipeline per variant: LLM analyzes cards → generates match-pairs check-ins at
concept boundaries → validates → inserts into cards_json.

Fully decoupled from explanation generation — runs after explanations (and
optionally visuals) exist. Reads/writes same topic_explanations table.
"""
import json
import logging
from pathlib import Path
from typing import Optional
from uuid import uuid4
from pydantic import BaseModel, Field

from shared.services.llm_service import LLMService, LLMServiceError
from shared.models.entities import TeachingGuideline, TopicExplanation
from shared.repositories.explanation_repository import ExplanationRepository

from sqlalchemy.orm import Session as DBSession

logger = logging.getLogger(__name__)

# ─── Prompt template ──────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_CHECK_IN_PROMPT = (_PROMPTS_DIR / "check_in_generation.txt").read_text()

# ─── Pydantic models for structured LLM output ───────────────────────────


class MatchPairOutput(BaseModel):
    left: str
    right: str


class CheckInDecision(BaseModel):
    """LLM output: one check-in to insert."""
    insert_after_card_idx: int = Field(description="Insert after this card (1-based card_idx)")
    title: str
    instruction: str
    pairs: list[MatchPairOutput]
    hint: str
    success_message: str
    audio_text: str


class CheckInGenerationOutput(BaseModel):
    """Full structured output from the generation prompt."""
    check_ins: list[CheckInDecision]


# ─── Constants ────────────────────────────────────────────────────────────

MIN_PAIRS = 2
MAX_PAIRS = 4


class CheckInEnrichmentService:
    """Enriches explanation cards with interactive check-in activities.

    Pipeline per variant: analyze → generate check-ins → validate → insert → store.
    """

    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.llm = llm_service
        self.repo = ExplanationRepository(db)

        self._generation_schema = LLMService.make_schema_strict(
            CheckInGenerationOutput.model_json_schema()
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

    # ─── Public API ─────────────────────────────────────────────────────

    def enrich_guideline(
        self,
        guideline: TeachingGuideline,
        force: bool = False,
        variant_keys: Optional[list[str]] = None,
        heartbeat_fn: Optional[callable] = None,
    ) -> dict:
        """Enrich all variants for a guideline with check-in cards.

        Returns: {"enriched": int, "skipped": int, "failed": int, "errors": [str]}
        """
        explanations = self.repo.get_by_guideline_id(guideline.id)
        if not explanations:
            return {"enriched": 0, "skipped": 0, "failed": 0, "errors": []}

        # Pre-flight: fail fast if another enrichment pipeline is running
        self._check_no_conflicting_jobs(guideline)

        if variant_keys:
            explanations = [e for e in explanations if e.variant_key in variant_keys]

        topic = guideline.topic_title or guideline.topic
        result = {"enriched": 0, "skipped": 0, "failed": 0, "errors": []}

        for explanation in explanations:
            try:
                if heartbeat_fn:
                    heartbeat_fn()
                enriched = self._enrich_variant(explanation, guideline, force=force)
                self._refresh_db_session()
                if enriched:
                    result["enriched"] += 1
                else:
                    result["skipped"] += 1
            except Exception as e:
                logger.error(f"Check-in enrichment failed for {topic} variant {explanation.variant_key}: {e}")
                result["failed"] += 1
                result["errors"].append(f"{topic} variant {explanation.variant_key}: {e}")

        return result

    def enrich_chapter(
        self,
        book_id: str,
        chapter_id: Optional[str] = None,
        force: bool = False,
        job_service=None,
        job_id: Optional[str] = None,
    ) -> dict:
        """Enrich all guidelines in a chapter (or book) with check-in cards."""
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

        guidelines = query.order_by(TeachingGuideline.topic_sequence).all()

        totals = {"enriched": 0, "skipped": 0, "failed": 0, "errors": []}

        for guideline in guidelines:
            topic = guideline.topic_title or guideline.topic
            if job_service and job_id:
                job_service.update_progress(
                    job_id, current_item=topic,
                    completed=totals["enriched"], failed=totals["failed"],
                )

            hb = None
            if job_service and job_id:
                hb = lambda t=topic: job_service.update_progress(
                    job_id, current_item=t,
                    completed=totals["enriched"], failed=totals["failed"],
                )
            result = self.enrich_guideline(guideline, force=force, heartbeat_fn=hb)
            totals["enriched"] += result["enriched"]
            totals["skipped"] += result["skipped"]
            totals["failed"] += result["failed"]
            totals["errors"].extend(result["errors"])

        if job_service and job_id:
            job_service.update_progress(
                job_id, current_item=None,
                completed=totals["enriched"], failed=totals["failed"],
                detail=json.dumps(totals),
            )

        return totals

    # ─── Internal pipeline ──────────────────────────────────────────────

    def _check_no_conflicting_jobs(self, guideline: TeachingGuideline):
        """Pre-flight: fail fast if another enrichment pipeline is running for this chapter."""
        from book_ingestion_v2.services.chapter_job_service import ChapterJobService
        from book_ingestion_v2.constants import V2JobType
        job_service = ChapterJobService(self.db)
        for jt in [V2JobType.EXPLANATION_GENERATION.value, V2JobType.VISUAL_ENRICHMENT.value]:
            try:
                job = job_service.get_latest_job(guideline.book_id, job_type=jt)
                if job and job.status in ("pending", "running"):
                    raise RuntimeError(
                        f"Cannot run check-in enrichment: {jt} job is {job.status} "
                        f"for book {guideline.book_id}"
                    )
            except Exception as e:
                if "Cannot run" in str(e):
                    raise
                # get_latest_job may raise if no jobs exist — that's fine

    def _enrich_variant(
        self,
        explanation: TopicExplanation,
        guideline: TeachingGuideline,
        force: bool = False,
    ) -> bool:
        """Enrich a single variant with check-in cards. Returns True if enriched."""
        cards = explanation.cards_json
        if not cards:
            return False

        # Check if already enriched (skip unless force)
        has_check_ins = any(c.get("card_type") == "check_in" for c in cards)
        if has_check_ins and not force:
            logger.info(f"Variant {explanation.variant_key} already has check-ins, skipping")
            return False

        topic = guideline.topic_title or guideline.topic

        # Strip existing check-ins before (re)generating
        explanation_cards = [c for c in cards if c.get("card_type") != "check_in"]

        if len(explanation_cards) < 3:
            logger.info(f"Too few cards ({len(explanation_cards)}) for check-ins in {topic}")
            return False

        # LLM call
        output = self._generate_check_ins(explanation_cards, guideline)
        if not output or not output.check_ins:
            logger.warning(f"No check-ins generated for {topic} variant {explanation.variant_key}")
            return False

        # Validate
        valid_check_ins = self._validate_check_ins(output.check_ins, explanation_cards)
        if not valid_check_ins:
            logger.warning(f"All check-ins failed validation for {topic} variant {explanation.variant_key}")
            return False

        # Assign card_ids to existing cards (if missing)
        for card in explanation_cards:
            if not card.get("card_id"):
                card["card_id"] = str(uuid4())

        # Insert check-in cards at correct positions
        merged = self._insert_check_ins(explanation_cards, valid_check_ins)

        # Re-number card_idx (1-based, matching ExplanationCardOutput convention)
        for i, card in enumerate(merged):
            card["card_idx"] = i + 1

        # Write back
        self.db.query(TopicExplanation).filter(
            TopicExplanation.id == explanation.id
        ).update({"cards_json": merged})
        self.db.commit()

        logger.info(
            f"Inserted {len(valid_check_ins)} check-in(s) into {topic} "
            f"variant {explanation.variant_key} (total cards: {len(merged)})"
        )
        return True

    def _generate_check_ins(
        self,
        cards: list[dict],
        guideline: TeachingGuideline,
    ) -> Optional[CheckInGenerationOutput]:
        """LLM call: generate check-in activities for card sequence."""
        topic = guideline.topic_title or guideline.topic
        subject = guideline.subject or "Mathematics"
        grade = str(guideline.grade) if guideline.grade else "3"

        # Build cards for prompt (strip visual_explanation/audio_text to save tokens)
        cards_for_prompt = [
            {k: v for k, v in c.items() if k in ("card_idx", "card_type", "title", "content")}
            for c in cards
        ]

        output_schema = json.dumps({
            "check_ins": [
                {
                    "insert_after_card_idx": 3,
                    "title": "Let's check!",
                    "instruction": "Match each ... to its ...",
                    "pairs": [{"left": "...", "right": "..."}],
                    "hint": "one sentence nudge",
                    "success_message": "warm confirmation + reinforcement",
                    "audio_text": "spoken instruction, no symbols"
                }
            ]
        }, indent=2)

        prompt = _CHECK_IN_PROMPT.replace(
            "{grade}", grade
        ).replace(
            "{topic_title}", topic
        ).replace(
            "{subject}", subject
        ).replace(
            "{cards_json}", json.dumps(cards_for_prompt, indent=2)
        ).replace(
            "{output_schema}", output_schema
        )

        try:
            response = self.llm.call(
                prompt=prompt,
                reasoning_effort="medium",
                json_schema=self._generation_schema,
                schema_name="CheckInGenerationOutput",
            )
            parsed = self.llm.parse_json_response(response["output_text"])
            return CheckInGenerationOutput.model_validate(parsed)
        except (LLMServiceError, json.JSONDecodeError, Exception) as e:
            logger.error(f"Check-in generation failed for {topic}: {e}")
            return None

    def _validate_check_ins(
        self,
        check_ins: list[CheckInDecision],
        cards: list[dict],
    ) -> list[CheckInDecision]:
        """Validate check-ins, returning only valid ones (fail-open)."""
        valid_card_idxs = {c["card_idx"] for c in cards}
        summary_idxs = {c["card_idx"] for c in cards if c.get("card_type") == "summary"}
        valid = []

        MIN_POSITION = 3  # Never before card_idx 3 (student needs content first)

        for ci in check_ins:
            # Must reference a valid non-summary card
            if ci.insert_after_card_idx not in valid_card_idxs:
                logger.warning(f"Check-in references invalid card_idx {ci.insert_after_card_idx}, dropping")
                continue
            if ci.insert_after_card_idx in summary_idxs:
                logger.warning(f"Check-in after summary card {ci.insert_after_card_idx}, dropping")
                continue
            # Minimum position — student needs content before a check-in
            if ci.insert_after_card_idx < MIN_POSITION:
                logger.warning(f"Check-in too early (card_idx {ci.insert_after_card_idx} < {MIN_POSITION}), dropping")
                continue

            # Pair count
            if len(ci.pairs) < MIN_PAIRS or len(ci.pairs) > MAX_PAIRS:
                logger.warning(f"Check-in has {len(ci.pairs)} pairs (need {MIN_PAIRS}-{MAX_PAIRS}), dropping")
                continue

            # No duplicate items
            lefts = [p.left.strip().lower() for p in ci.pairs]
            rights = [p.right.strip().lower() for p in ci.pairs]
            if len(set(lefts)) != len(lefts) or len(set(rights)) != len(rights):
                logger.warning("Check-in has duplicate left/right items, dropping")
                continue

            # hint and success_message non-empty
            if not ci.hint.strip() or not ci.success_message.strip():
                logger.warning("Check-in missing hint or success_message, dropping")
                continue

            # Minimum gap of 2 explanation cards between consecutive check-ins
            if valid:
                gap = ci.insert_after_card_idx - valid[-1].insert_after_card_idx
                if gap < 2:
                    logger.warning(f"Check-ins too close (gap={gap}, need >=2), dropping")
                    continue

            valid.append(ci)

        return valid

    def _insert_check_ins(
        self,
        cards: list[dict],
        check_ins: list[CheckInDecision],
    ) -> list[dict]:
        """Insert check-in cards into the card list at correct positions."""
        # Build insertion map: card_idx -> list of check-ins to insert after it
        insert_map: dict[int, list[CheckInDecision]] = {}
        for ci in check_ins:
            insert_map.setdefault(ci.insert_after_card_idx, []).append(ci)

        merged = []
        for card in cards:
            merged.append(card)
            # Insert any check-ins that go after this card
            for ci in insert_map.get(card["card_idx"], []):
                merged.append({
                    "card_id": str(uuid4()),
                    "card_idx": 0,  # Will be re-numbered
                    "card_type": "check_in",
                    "title": ci.title,
                    "content": ci.instruction,  # content field for compatibility
                    "audio_text": ci.audio_text,
                    "check_in": {
                        "activity_type": "match_pairs",
                        "instruction": ci.instruction,
                        "pairs": [{"left": p.left, "right": p.right} for p in ci.pairs],
                        "hint": ci.hint,
                        "success_message": ci.success_message,
                        "audio_text": ci.audio_text,
                    },
                })

        return merged
