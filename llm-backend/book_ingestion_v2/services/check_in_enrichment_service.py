"""Offline pipeline to enrich explanation cards with interactive check-in activities.

Pipeline per variant: LLM analyzes cards → generates diverse check-in activities at
concept boundaries → validates → inserts into cards_json.

Supports 11 activity types: pick_one, true_false, fill_blank, match_pairs,
sort_buckets, sequence, spot_the_error, odd_one_out, predict_then_reveal,
swipe_classify, estimation_slider. Check-ins are generated in light+heavy pairs.

Fully decoupled from explanation generation — runs after explanations (and
optionally visuals) exist. Reads/writes same topic_explanations table.
"""
import json
import logging
from pathlib import Path
from typing import Literal, Optional
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

ACTIVITY_TYPES = (
    "pick_one", "true_false", "fill_blank", "match_pairs", "sort_buckets", "sequence",
    "spot_the_error", "odd_one_out", "predict_then_reveal", "swipe_classify", "estimation_slider",
)

# Light types (~5-10s, recall/understand) — used as first in a pair
LIGHT_TYPES = {"pick_one", "true_false", "fill_blank", "odd_one_out"}
# Heavy types (~15-25s, analyze/evaluate) — used as second in a pair
HEAVY_TYPES = {"match_pairs", "sort_buckets", "sequence", "spot_the_error", "swipe_classify", "estimation_slider", "predict_then_reveal"}


class MatchPairOutput(BaseModel):
    left: str
    right: str


class BucketItemOutput(BaseModel):
    text: str
    correct_bucket: int = Field(description="0 or 1 — index into bucket_names")


class CheckInDecision(BaseModel):
    """LLM output: one check-in to insert. Flat model — fill only the fields
    relevant to the chosen activity_type."""
    insert_after_card_idx: int = Field(description="Insert after this card (1-based card_idx)")
    activity_type: str = Field(description="One of the 11 activity types")
    title: str = Field(description="Short heading, e.g. 'Quick check!'")
    instruction: str = Field(description="Main text shown to student")
    hint: str = Field(description="One-sentence nudge (no spoilers)")
    success_message: str = Field(description="Warm confirmation after correct answer")
    audio_text: str = Field(description="Spoken version — plain words, no symbols")

    # pick_one / fill_blank / predict_then_reveal
    options: list[str] = Field(default_factory=list, description="2-3 answer choices")
    correct_index: int = Field(default=0, description="Index of correct option in options[]")

    # true_false
    statement: str = Field(default="", description="Statement to judge true/false")
    correct_answer: bool = Field(default=True, description="Whether statement is true")

    # match_pairs
    pairs: list[MatchPairOutput] = Field(default_factory=list, description="Left-right pairs (2-3)")

    # sort_buckets / swipe_classify
    bucket_names: list[str] = Field(default_factory=list, description="Two category labels")
    bucket_items: list[BucketItemOutput] = Field(default_factory=list, description="4-6 items to classify")

    # sequence
    sequence_items: list[str] = Field(default_factory=list, description="Items in correct order (3-4)")

    # spot_the_error
    error_steps: list[str] = Field(default_factory=list, description="3-5 steps in a worked solution, one is wrong")
    error_index: int = Field(default=0, description="Index of the wrong step in error_steps[]")

    # odd_one_out
    odd_items: list[str] = Field(default_factory=list, description="3-4 items, one doesn't belong")
    odd_index: int = Field(default=0, description="Index of the odd item in odd_items[]")

    # predict_then_reveal (also uses options + correct_index)
    reveal_text: str = Field(default="", description="Explanation shown after student predicts")

    # estimation_slider
    slider_min: int = Field(default=0, description="Minimum slider value")
    slider_max: int = Field(default=100, description="Maximum slider value")
    correct_value: int = Field(default=0, description="Correct answer on the slider")
    tolerance: int = Field(default=5, description="Acceptable range +/- from correct_value")


class CheckInGenerationOutput(BaseModel):
    """Full structured output from the generation prompt."""
    check_ins: list[CheckInDecision]


# ─── Constants ────────────────────────────────────────────────────────────

# match_pairs
MIN_PAIRS = 2
MAX_PAIRS = 3

# pick_one / fill_blank
MIN_OPTIONS = 2
MAX_OPTIONS = 3

# sort_buckets
MIN_BUCKET_ITEMS = 4
MAX_BUCKET_ITEMS = 6

# sequence
MIN_SEQUENCE_ITEMS = 3
MAX_SEQUENCE_ITEMS = 4

# spot_the_error
MIN_ERROR_STEPS = 3
MAX_ERROR_STEPS = 5

# odd_one_out
MIN_ODD_ITEMS = 3
MAX_ODD_ITEMS = 4

# estimation_slider
MIN_SLIDER_RANGE = 10  # slider_max - slider_min must be at least this

# swipe_classify (reuses bucket constants)
MIN_SWIPE_ITEMS = 4
MAX_SWIPE_ITEMS = 8

# Placement — pairs allowed at same position, gap>=2 between different positions
PAIR_SIZE = 2  # Max check-ins at same insert position
MIN_GAP_BETWEEN_PAIRS = 2  # Min content-card gap between different insert positions


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
        from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
        from book_ingestion_v2.constants import V2JobType

        job_service = ChapterJobService(self.db)

        # Find the actual chapter_id(s) for this guideline's chapter
        chapter_key = guideline.chapter_key
        if not chapter_key:
            return  # No chapter context — skip check
        chapters = ChapterRepository(self.db).get_by_book_id(guideline.book_id)
        chapter_ids = [c.id for c in chapters if f"chapter-{c.chapter_number}" == chapter_key]

        for chapter_id in chapter_ids:
            for jt in [V2JobType.EXPLANATION_GENERATION.value, V2JobType.VISUAL_ENRICHMENT.value]:
                try:
                    job = job_service.get_latest_job(chapter_id, job_type=jt)
                    if job and job.status in ("pending", "running"):
                        raise RuntimeError(
                            f"Cannot run check-in enrichment: {jt} job is {job.status} "
                            f"for chapter {chapter_id}"
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

        prompt = _CHECK_IN_PROMPT.replace(
            "{grade}", grade
        ).replace(
            "{topic_title}", topic
        ).replace(
            "{subject}", subject
        ).replace(
            "{cards_json}", json.dumps(cards_for_prompt, indent=2)
        ).replace(
            "{output_schema}", json.dumps(
                CheckInGenerationOutput.model_json_schema(), indent=2
            )
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
            label = f"check-in ({ci.activity_type}) after card {ci.insert_after_card_idx}"

            # Activity type must be recognized
            if ci.activity_type not in ACTIVITY_TYPES:
                logger.warning(f"{label}: unknown activity_type, dropping")
                continue

            # Must reference a valid non-summary card
            if ci.insert_after_card_idx not in valid_card_idxs:
                logger.warning(f"{label}: invalid card_idx, dropping")
                continue
            if ci.insert_after_card_idx in summary_idxs:
                logger.warning(f"{label}: after summary card, dropping")
                continue
            # Minimum position — student needs content before a check-in
            if ci.insert_after_card_idx < MIN_POSITION:
                logger.warning(f"{label}: too early (< {MIN_POSITION}), dropping")
                continue

            # hint and success_message non-empty
            if not ci.hint.strip() or not ci.success_message.strip():
                logger.warning(f"{label}: missing hint or success_message, dropping")
                continue

            # Type-specific validation
            if not self._validate_activity_content(ci, label):
                continue

            # Pairing logic: allow up to PAIR_SIZE at same position,
            # require MIN_GAP_BETWEEN_PAIRS between different positions
            if valid:
                last = valid[-1]
                if ci.insert_after_card_idx == last.insert_after_card_idx:
                    same_pos_count = sum(
                        1 for v in valid if v.insert_after_card_idx == ci.insert_after_card_idx
                    )
                    if same_pos_count >= PAIR_SIZE:
                        logger.warning(f"{label}: already {PAIR_SIZE} check-ins at position {ci.insert_after_card_idx}, dropping")
                        continue
                else:
                    gap = ci.insert_after_card_idx - last.insert_after_card_idx
                    if gap < MIN_GAP_BETWEEN_PAIRS:
                        logger.warning(f"{label}: too close to previous pair (gap={gap}), dropping")
                        continue

            valid.append(ci)

        return valid

    def _validate_activity_content(self, ci: CheckInDecision, label: str) -> bool:
        """Validate type-specific fields for a check-in. Returns True if valid."""
        at = ci.activity_type

        if at == "pick_one" or at == "fill_blank":
            if len(ci.options) < MIN_OPTIONS or len(ci.options) > MAX_OPTIONS:
                logger.warning(f"{label}: {len(ci.options)} options (need {MIN_OPTIONS}-{MAX_OPTIONS}), dropping")
                return False
            if ci.correct_index < 0 or ci.correct_index >= len(ci.options):
                logger.warning(f"{label}: correct_index {ci.correct_index} out of range, dropping")
                return False
            # No duplicate options
            opts_lower = [o.strip().lower() for o in ci.options]
            if len(set(opts_lower)) != len(opts_lower):
                logger.warning(f"{label}: duplicate options, dropping")
                return False

        elif at == "true_false":
            if not ci.statement.strip():
                logger.warning(f"{label}: empty statement, dropping")
                return False

        elif at == "match_pairs":
            if len(ci.pairs) < MIN_PAIRS or len(ci.pairs) > MAX_PAIRS:
                logger.warning(f"{label}: {len(ci.pairs)} pairs (need {MIN_PAIRS}-{MAX_PAIRS}), dropping")
                return False
            lefts = [p.left.strip().lower() for p in ci.pairs]
            rights = [p.right.strip().lower() for p in ci.pairs]
            if len(set(lefts)) != len(lefts) or len(set(rights)) != len(rights):
                logger.warning(f"{label}: duplicate left/right items, dropping")
                return False

        elif at == "sort_buckets":
            if len(ci.bucket_names) != 2:
                logger.warning(f"{label}: need exactly 2 bucket_names, got {len(ci.bucket_names)}, dropping")
                return False
            if len(ci.bucket_items) < MIN_BUCKET_ITEMS or len(ci.bucket_items) > MAX_BUCKET_ITEMS:
                logger.warning(f"{label}: {len(ci.bucket_items)} items (need {MIN_BUCKET_ITEMS}-{MAX_BUCKET_ITEMS}), dropping")
                return False
            if any(bi.correct_bucket not in (0, 1) for bi in ci.bucket_items):
                logger.warning(f"{label}: correct_bucket must be 0 or 1, dropping")
                return False
            # At least one item per bucket
            buckets_used = {bi.correct_bucket for bi in ci.bucket_items}
            if len(buckets_used) < 2:
                logger.warning(f"{label}: all items in one bucket, dropping")
                return False

        elif at == "sequence":
            if len(ci.sequence_items) < MIN_SEQUENCE_ITEMS or len(ci.sequence_items) > MAX_SEQUENCE_ITEMS:
                logger.warning(f"{label}: {len(ci.sequence_items)} items (need {MIN_SEQUENCE_ITEMS}-{MAX_SEQUENCE_ITEMS}), dropping")
                return False
            items_lower = [s.strip().lower() for s in ci.sequence_items]
            if len(set(items_lower)) != len(items_lower):
                logger.warning(f"{label}: duplicate sequence items, dropping")
                return False

        elif at == "spot_the_error":
            if len(ci.error_steps) < MIN_ERROR_STEPS or len(ci.error_steps) > MAX_ERROR_STEPS:
                logger.warning(f"{label}: {len(ci.error_steps)} steps (need {MIN_ERROR_STEPS}-{MAX_ERROR_STEPS}), dropping")
                return False
            if ci.error_index < 0 or ci.error_index >= len(ci.error_steps):
                logger.warning(f"{label}: error_index {ci.error_index} out of range, dropping")
                return False

        elif at == "odd_one_out":
            if len(ci.odd_items) < MIN_ODD_ITEMS or len(ci.odd_items) > MAX_ODD_ITEMS:
                logger.warning(f"{label}: {len(ci.odd_items)} items (need {MIN_ODD_ITEMS}-{MAX_ODD_ITEMS}), dropping")
                return False
            if ci.odd_index < 0 or ci.odd_index >= len(ci.odd_items):
                logger.warning(f"{label}: odd_index {ci.odd_index} out of range, dropping")
                return False

        elif at == "predict_then_reveal":
            if len(ci.options) < MIN_OPTIONS or len(ci.options) > MAX_OPTIONS:
                logger.warning(f"{label}: {len(ci.options)} options (need {MIN_OPTIONS}-{MAX_OPTIONS}), dropping")
                return False
            if ci.correct_index < 0 or ci.correct_index >= len(ci.options):
                logger.warning(f"{label}: correct_index out of range, dropping")
                return False
            if not ci.reveal_text.strip():
                logger.warning(f"{label}: empty reveal_text, dropping")
                return False

        elif at == "swipe_classify":
            if len(ci.bucket_names) != 2:
                logger.warning(f"{label}: need exactly 2 category labels, got {len(ci.bucket_names)}, dropping")
                return False
            if len(ci.bucket_items) < MIN_SWIPE_ITEMS or len(ci.bucket_items) > MAX_SWIPE_ITEMS:
                logger.warning(f"{label}: {len(ci.bucket_items)} items (need {MIN_SWIPE_ITEMS}-{MAX_SWIPE_ITEMS}), dropping")
                return False
            if any(bi.correct_bucket not in (0, 1) for bi in ci.bucket_items):
                logger.warning(f"{label}: correct_bucket must be 0 or 1, dropping")
                return False
            buckets_used = {bi.correct_bucket for bi in ci.bucket_items}
            if len(buckets_used) < 2:
                logger.warning(f"{label}: all items in one category, dropping")
                return False

        elif at == "estimation_slider":
            slider_range = ci.slider_max - ci.slider_min
            if slider_range < MIN_SLIDER_RANGE:
                logger.warning(f"{label}: slider range too small ({slider_range}), dropping")
                return False
            if ci.correct_value < ci.slider_min or ci.correct_value > ci.slider_max:
                logger.warning(f"{label}: correct_value {ci.correct_value} outside slider range, dropping")
                return False
            if ci.tolerance < 0 or ci.tolerance > slider_range:
                logger.warning(f"{label}: tolerance {ci.tolerance} invalid, dropping")
                return False

        return True

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
                merged.append(self._build_check_in_card(ci))

        return merged

    def _build_check_in_card(self, ci: CheckInDecision) -> dict:
        """Build a card dict from a CheckInDecision."""
        check_in_data: dict = {
            "activity_type": ci.activity_type,
            "instruction": ci.instruction,
            "hint": ci.hint,
            "success_message": ci.success_message,
            "audio_text": ci.audio_text,
        }

        if ci.activity_type == "pick_one":
            check_in_data["options"] = ci.options
            check_in_data["correct_index"] = ci.correct_index

        elif ci.activity_type == "true_false":
            check_in_data["statement"] = ci.statement
            check_in_data["correct_answer"] = ci.correct_answer

        elif ci.activity_type == "fill_blank":
            check_in_data["options"] = ci.options
            check_in_data["correct_index"] = ci.correct_index

        elif ci.activity_type == "match_pairs":
            check_in_data["pairs"] = [{"left": p.left, "right": p.right} for p in ci.pairs]

        elif ci.activity_type == "sort_buckets":
            check_in_data["bucket_names"] = ci.bucket_names
            check_in_data["bucket_items"] = [
                {"text": bi.text, "correct_bucket": bi.correct_bucket}
                for bi in ci.bucket_items
            ]

        elif ci.activity_type == "sequence":
            check_in_data["sequence_items"] = ci.sequence_items

        elif ci.activity_type == "spot_the_error":
            check_in_data["error_steps"] = ci.error_steps
            check_in_data["error_index"] = ci.error_index

        elif ci.activity_type == "odd_one_out":
            check_in_data["odd_items"] = ci.odd_items
            check_in_data["odd_index"] = ci.odd_index

        elif ci.activity_type == "predict_then_reveal":
            check_in_data["options"] = ci.options
            check_in_data["correct_index"] = ci.correct_index
            check_in_data["reveal_text"] = ci.reveal_text

        elif ci.activity_type == "swipe_classify":
            check_in_data["bucket_names"] = ci.bucket_names
            check_in_data["bucket_items"] = [
                {"text": bi.text, "correct_bucket": bi.correct_bucket}
                for bi in ci.bucket_items
            ]

        elif ci.activity_type == "estimation_slider":
            check_in_data["slider_min"] = ci.slider_min
            check_in_data["slider_max"] = ci.slider_max
            check_in_data["correct_value"] = ci.correct_value
            check_in_data["tolerance"] = ci.tolerance

        return {
            "card_id": str(uuid4()),
            "card_idx": 0,  # Will be re-numbered
            "card_type": "check_in",
            "title": ci.title,
            "content": ci.instruction,  # content field for compatibility
            "audio_text": ci.audio_text,
            "check_in": check_in_data,
        }
