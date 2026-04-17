"""Offline pipeline to generate per-topic practice question banks.

Pipeline per guideline:
  1. Load explanation cards (variant A) for concept grounding.
  2. LLM generates 30-40 diverse questions across 12 formats.
  3. review_rounds of correctness-focused review-refine (fail-open).
  4. Structural validation (format constraints, FF count 0-3, dedup).
  5. Top-up additional generation passes if valid count < 30 (up to 3 total).
  6. Delete old bank (if force) + bulk insert.

Decoupled from runtime — the student's practice session reads the bank via
PracticeQuestionRepository.list_by_guideline(). Mutable — admin re-sync with
force=True wipes and regenerates the bank.
"""
import json
import logging
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, Field

from shared.models.entities import TeachingGuideline
from shared.repositories.explanation_repository import ExplanationRepository
from shared.repositories.practice_question_repository import PracticeQuestionRepository
from shared.services.llm_service import LLMService, LLMServiceError
from book_ingestion_v2.services.check_in_enrichment_service import (
    MatchPairOutput,
    BucketItemOutput,
    MIN_OPTIONS,
    MAX_OPTIONS,
    MIN_PAIRS,
    MAX_PAIRS,
    MIN_BUCKET_ITEMS,
    MAX_BUCKET_ITEMS,
    MIN_SEQUENCE_ITEMS,
    MAX_SEQUENCE_ITEMS,
    MIN_ERROR_STEPS,
    MAX_ERROR_STEPS,
    MIN_ODD_ITEMS,
    MAX_ODD_ITEMS,
    MIN_ELIMINATE_OPTIONS,
    MAX_ELIMINATE_OPTIONS,
    MIN_SWIPE_ITEMS,
    MAX_SWIPE_ITEMS,
)

from sqlalchemy.orm import Session as DBSession

logger = logging.getLogger(__name__)


# ─── Prompts ──────────────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_GENERATION_PROMPT = (_PROMPTS_DIR / "practice_bank_generation.txt").read_text()
_REVIEW_REFINE_PROMPT = (_PROMPTS_DIR / "practice_bank_review_refine.txt").read_text()


# ─── Pydantic output models ───────────────────────────────────────────────

FORMAT_TYPES = (
    "pick_one", "true_false", "fill_blank", "match_pairs", "sort_buckets", "sequence",
    "spot_the_error", "odd_one_out", "predict_then_reveal", "swipe_classify",
    "tap_to_eliminate", "free_form",
)


class PracticeQuestionOutput(BaseModel):
    """LLM output: one practice question. Flat — fill only fields relevant to format."""
    format: Literal[
        "pick_one", "true_false", "fill_blank", "match_pairs", "sort_buckets",
        "sequence", "spot_the_error", "odd_one_out", "predict_then_reveal",
        "swipe_classify", "tap_to_eliminate", "free_form",
    ]
    difficulty: Literal["easy", "medium", "hard"]
    concept_tag: str = Field(description="Short snake_case tag for the sub-concept tested")
    question_text: str = Field(description="Question shown to the student")
    explanation_why: str = Field(description="One sentence: why the correct answer is correct")

    # pick_one / fill_blank / predict_then_reveal / tap_to_eliminate
    options: list[str] = Field(default_factory=list)
    correct_index: int = 0

    # true_false
    statement: str = ""
    correct_answer_bool: bool = True

    # match_pairs
    pairs: list[MatchPairOutput] = Field(default_factory=list)

    # sort_buckets / swipe_classify
    bucket_names: list[str] = Field(default_factory=list)
    bucket_items: list[BucketItemOutput] = Field(default_factory=list)

    # sequence
    sequence_items: list[str] = Field(default_factory=list)

    # spot_the_error
    error_steps: list[str] = Field(default_factory=list)
    error_index: int = 0

    # odd_one_out
    odd_items: list[str] = Field(default_factory=list)
    odd_index: int = 0

    # predict_then_reveal
    reveal_text: str = ""

    # free_form
    expected_answer: str = ""
    grading_rubric: str = ""


class PracticeBankOutput(BaseModel):
    questions: list[PracticeQuestionOutput]


# ─── Constants ────────────────────────────────────────────────────────────

DEFAULT_REVIEW_ROUNDS = 1
TARGET_BANK_SIZE = 30
MAX_BANK_SIZE = 40
MAX_GENERATION_ATTEMPTS = 3  # Initial attempt + up to 2 top-up attempts
MAX_FREE_FORM = 3
MIN_FREE_FORM = 0  # Q6 resolution: procedural topics may have 0 FFs


class PracticeBankGeneratorService:
    """Generates the offline practice question bank for a topic.

    Depends on explanation cards being generated — used for concept grounding
    in the generation prompt. Enforces a chapter-level job lock via
    V2JobType.PRACTICE_BANK_GENERATION (acquired by the caller in sync_routes).
    """

    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.llm = llm_service
        self.explanation_repo = ExplanationRepository(db)
        self.question_repo = PracticeQuestionRepository(db)

        self._generation_schema = LLMService.make_schema_strict(
            PracticeBankOutput.model_json_schema()
        )

    def _refresh_db_session(self):
        """Get a fresh DB session after long-running LLM calls."""
        from database import get_db_manager
        try:
            self.db.close()
        except Exception:
            pass
        self.db = get_db_manager().get_session()
        self.explanation_repo = ExplanationRepository(self.db)
        self.question_repo = PracticeQuestionRepository(self.db)

    # ─── Public API ─────────────────────────────────────────────────────

    def enrich_guideline(
        self,
        guideline: TeachingGuideline,
        force: bool = False,
        review_rounds: int = DEFAULT_REVIEW_ROUNDS,
        heartbeat_fn: Optional[callable] = None,
    ) -> dict:
        """Generate the practice bank for one topic.

        Returns: {"generated": int, "skipped": int, "failed": int, "errors": [str]}
            generated: 1 if a new bank was inserted, 0 otherwise.
            skipped:   1 if an existing non-empty bank was kept (no force), 0 otherwise.
            failed:    1 if generation failed (explanation prereq missing, no valid questions), 0 otherwise.
        """
        review_rounds = max(0, min(review_rounds, 5))
        topic = guideline.topic_title or guideline.topic
        result = {"generated": 0, "skipped": 0, "failed": 0, "errors": []}

        try:
            if heartbeat_fn:
                heartbeat_fn()

            explanation_cards = self._load_explanation_cards(guideline)
            if not explanation_cards:
                result["failed"] = 1
                result["errors"].append(
                    f"{topic}: explanations not generated yet — run explanation generation first"
                )
                return result

            self._check_no_conflicting_jobs(guideline)

            existing_count = self.question_repo.count_by_guideline(guideline.id)
            if existing_count > 0 and not force:
                logger.info(f"Practice bank already exists for {topic} ({existing_count} questions), skipping")
                result["skipped"] = 1
                return result

            valid_questions = self._generate_and_refine_bank(
                guideline, explanation_cards, review_rounds, heartbeat_fn,
            )

            if len(valid_questions) < TARGET_BANK_SIZE:
                # Last-resort: if still short but >= 10 usable, the admin can inspect
                # and force-regenerate. For now: fail — operations aborts insert.
                msg = (
                    f"{topic}: only {len(valid_questions)} valid questions after "
                    f"{MAX_GENERATION_ATTEMPTS} attempts (need {TARGET_BANK_SIZE})"
                )
                logger.warning(msg)
                result["failed"] = 1
                result["errors"].append(msg)
                return result

            # Cap at MAX_BANK_SIZE before insert
            if len(valid_questions) > MAX_BANK_SIZE:
                valid_questions = valid_questions[:MAX_BANK_SIZE]

            # Force-regenerate: wipe the old bank first
            if force and existing_count > 0:
                deleted = self.question_repo.delete_by_guideline(guideline.id)
                logger.info(f"Deleted {deleted} old questions before regenerating {topic}")

            inserted = self.question_repo.bulk_insert(
                guideline.id,
                [self._to_storage_dict(q) for q in valid_questions],
                generator_model=self._current_model_id(),
            )
            logger.info(f"Inserted {inserted} practice questions for {topic}")
            result["generated"] = 1

        except Exception as e:
            logger.exception(f"Practice bank generation failed for {topic}")
            result["failed"] = 1
            result["errors"].append(f"{topic}: {e}")

        return result

    def enrich_chapter(
        self,
        book_id: str,
        chapter_id: Optional[str] = None,
        force: bool = False,
        review_rounds: int = DEFAULT_REVIEW_ROUNDS,
        job_service=None,
        job_id: Optional[str] = None,
    ) -> dict:
        """Generate practice banks for every non-refresher topic in a chapter."""
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

        totals = {"generated": 0, "skipped": 0, "failed": 0, "errors": []}

        for guideline in guidelines:
            topic = guideline.topic_title or guideline.topic
            if job_service and job_id:
                job_service.update_progress(
                    job_id, current_item=topic,
                    completed=totals["generated"], failed=totals["failed"],
                )

            hb = None
            if job_service and job_id:
                hb = lambda t=topic: job_service.update_progress(
                    job_id, current_item=t,
                    completed=totals["generated"], failed=totals["failed"],
                )

            result = self.enrich_guideline(
                guideline, force=force, review_rounds=review_rounds, heartbeat_fn=hb,
            )
            self._refresh_db_session()
            totals["generated"] += result["generated"]
            totals["skipped"] += result["skipped"]
            totals["failed"] += result["failed"]
            totals["errors"].extend(result["errors"])

        if job_service and job_id:
            job_service.update_progress(
                job_id, current_item=None,
                completed=totals["generated"], failed=totals["failed"],
                detail=json.dumps(totals),
            )

        return totals

    # ─── Internal pipeline ──────────────────────────────────────────────

    def _load_explanation_cards(self, guideline: TeachingGuideline) -> list[dict]:
        """Load explanation cards from variant A (primary pedagogical approach).
        Returns only content fields — visual/audio stripped to save prompt tokens.
        """
        explanations = self.explanation_repo.get_by_guideline_id(guideline.id)
        if not explanations:
            return []
        primary = explanations[0]  # variant_key order: A < B < C
        cards = primary.cards_json or []
        return [
            {k: v for k, v in c.items() if k in ("card_idx", "card_type", "title", "content")}
            for c in cards
        ]

    def _check_no_conflicting_jobs(self, guideline: TeachingGuideline):
        """Pre-flight: fail fast if a prerequisite pipeline is still running."""
        from book_ingestion_v2.services.chapter_job_service import ChapterJobService
        from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
        from book_ingestion_v2.constants import V2JobType

        job_service = ChapterJobService(self.db)

        chapter_key = guideline.chapter_key
        if not chapter_key:
            return
        chapters = ChapterRepository(self.db).get_by_book_id(guideline.book_id)
        chapter_ids = [c.id for c in chapters if f"chapter-{c.chapter_number}" == chapter_key]

        conflict_types = [
            V2JobType.EXPLANATION_GENERATION.value,
            V2JobType.VISUAL_ENRICHMENT.value,
            V2JobType.CHECK_IN_ENRICHMENT.value,
        ]
        for chapter_id in chapter_ids:
            for jt in conflict_types:
                try:
                    job = job_service.get_latest_job(chapter_id, job_type=jt)
                    if job and job.status in ("pending", "running"):
                        raise RuntimeError(
                            f"Cannot run practice bank generation: {jt} job is {job.status} "
                            f"for chapter {chapter_id}"
                        )
                except Exception as e:
                    if "Cannot run" in str(e):
                        raise

    def _generate_and_refine_bank(
        self,
        guideline: TeachingGuideline,
        explanation_cards: list[dict],
        review_rounds: int,
        heartbeat_fn: Optional[callable],
    ) -> list[PracticeQuestionOutput]:
        """Full per-guideline pipeline: generate → review/refine → validate →
        top-up to TARGET_BANK_SIZE if needed (up to MAX_GENERATION_ATTEMPTS total).
        Returns the list of validated questions (may be < TARGET_BANK_SIZE if LLM can't produce enough).
        """
        topic = guideline.topic_title or guideline.topic

        output = self._generate_bank(guideline, explanation_cards)
        if output is None or not output.questions:
            logger.warning(f"Initial bank generation returned nothing for {topic}")
            return []

        for round_num in range(1, review_rounds + 1):
            if heartbeat_fn:
                heartbeat_fn()
            logger.info(f"Practice bank review-refine round {round_num}/{review_rounds} for {topic}")
            refined = self._review_and_refine_bank(output.questions, guideline, explanation_cards)
            self._refresh_db_session()
            if refined and refined.questions:
                output = refined
            else:
                logger.warning(f"Review round {round_num} returned nothing for {topic}; keeping prior output")
                break

        valid = self._validate_bank(output.questions)
        logger.info(f"Initial valid count for {topic}: {len(valid)}")

        # Top-up loop — up to MAX_GENERATION_ATTEMPTS - 1 additional passes
        attempts_used = 1
        while len(valid) < TARGET_BANK_SIZE and attempts_used < MAX_GENERATION_ATTEMPTS:
            if heartbeat_fn:
                heartbeat_fn()
            logger.info(
                f"Topping up {topic} — have {len(valid)}, need {TARGET_BANK_SIZE} "
                f"(attempt {attempts_used + 1}/{MAX_GENERATION_ATTEMPTS})"
            )
            extra = self._generate_bank(guideline, explanation_cards)
            self._refresh_db_session()
            if extra and extra.questions:
                more_valid = self._validate_bank(extra.questions, existing=valid)
                valid.extend(more_valid)
            attempts_used += 1

        return valid

    def _generate_bank(
        self,
        guideline: TeachingGuideline,
        explanation_cards: list[dict],
    ) -> Optional[PracticeBankOutput]:
        """Single LLM call: generate 30-40 questions."""
        topic = guideline.topic_title or guideline.topic
        subject = guideline.subject or "Mathematics"
        grade = str(guideline.grade) if guideline.grade else "3"
        guideline_text = guideline.guideline or guideline.description or ""

        prompt = _GENERATION_PROMPT.replace(
            "{grade}", grade,
        ).replace(
            "{subject}", subject,
        ).replace(
            "{topic_title}", topic,
        ).replace(
            "{guideline_text}", guideline_text,
        ).replace(
            "{explanation_cards_json}", json.dumps(explanation_cards, indent=2),
        ).replace(
            "{output_schema}", json.dumps(PracticeBankOutput.model_json_schema(), indent=2),
        )

        try:
            response = self.llm.call(
                prompt=prompt,
                reasoning_effort="medium",
                json_schema=self._generation_schema,
                schema_name="PracticeBankOutput",
            )
            parsed = self.llm.parse_json_response(response["output_text"])
            return PracticeBankOutput.model_validate(parsed)
        except (LLMServiceError, json.JSONDecodeError, Exception) as e:
            logger.error(f"Practice bank generation LLM call failed for {topic}: {e}")
            return None

    def _review_and_refine_bank(
        self,
        questions: list[PracticeQuestionOutput],
        guideline: TeachingGuideline,
        explanation_cards: list[dict],
    ) -> Optional[PracticeBankOutput]:
        """Correctness-focused review pass. Returns None on error; caller keeps prior output."""
        topic = guideline.topic_title or guideline.topic
        subject = guideline.subject or "Mathematics"
        grade = str(guideline.grade) if guideline.grade else "3"
        guideline_text = guideline.guideline or guideline.description or ""

        questions_json = json.dumps([q.model_dump() for q in questions], indent=2)
        prompt = _REVIEW_REFINE_PROMPT.replace(
            "{grade}", grade,
        ).replace(
            "{subject}", subject,
        ).replace(
            "{topic_title}", topic,
        ).replace(
            "{guideline_text}", guideline_text,
        ).replace(
            "{explanation_cards_json}", json.dumps(explanation_cards, indent=2),
        ).replace(
            "{questions_json}", questions_json,
        ).replace(
            "{output_schema}", json.dumps(PracticeBankOutput.model_json_schema(), indent=2),
        )

        try:
            response = self.llm.call(
                prompt=prompt,
                reasoning_effort="medium",
                json_schema=self._generation_schema,
                schema_name="PracticeBankOutput",
            )
            parsed = self.llm.parse_json_response(response["output_text"])
            return PracticeBankOutput.model_validate(parsed)
        except Exception as e:
            logger.error(f"Practice bank review-refine failed for {topic}: {e}")
            return None

    def _validate_bank(
        self,
        questions: list[PracticeQuestionOutput],
        existing: Optional[list[PracticeQuestionOutput]] = None,
    ) -> list[PracticeQuestionOutput]:
        """Structural validation. Drops invalid questions, dedupes against `existing`,
        and enforces 0 ≤ FF count ≤ 3 (Q6 resolution: purely procedural topics may have 0).
        """
        existing = existing or []
        seen_texts = {q.question_text.strip().lower() for q in existing}
        existing_ff_count = sum(1 for q in existing if q.format == "free_form")

        valid: list[PracticeQuestionOutput] = []
        new_ff_count = 0

        for q in questions:
            label = f"question ({q.format}, {q.difficulty})"

            if q.format not in FORMAT_TYPES:
                logger.warning(f"{label}: unknown format, dropping")
                continue

            if not q.question_text.strip():
                logger.warning(f"{label}: empty question_text, dropping")
                continue

            if not q.explanation_why.strip():
                logger.warning(f"{label}: empty explanation_why, dropping")
                continue

            if not q.concept_tag.strip():
                logger.warning(f"{label}: empty concept_tag, dropping")
                continue

            dedup_key = q.question_text.strip().lower()
            if dedup_key in seen_texts:
                logger.info(f"{label}: duplicate question_text, dropping")
                continue

            if q.format == "free_form":
                # Cap total FFs across existing + new at MAX_FREE_FORM
                if existing_ff_count + new_ff_count >= MAX_FREE_FORM:
                    logger.info(f"{label}: already at max {MAX_FREE_FORM} free-form, dropping")
                    continue
                if not q.expected_answer.strip():
                    logger.warning(f"{label}: empty expected_answer, dropping")
                    continue
                if not q.grading_rubric.strip():
                    logger.warning(f"{label}: empty grading_rubric, dropping")
                    continue
                new_ff_count += 1
            else:
                if not self._validate_structured(q, label):
                    continue

            seen_texts.add(dedup_key)
            valid.append(q)

        return valid

    def _validate_structured(self, q: PracticeQuestionOutput, label: str) -> bool:
        """Per-format constraint check for structured questions."""
        fmt = q.format

        if fmt in ("pick_one", "fill_blank"):
            if not (MIN_OPTIONS <= len(q.options) <= MAX_OPTIONS):
                logger.warning(f"{label}: {len(q.options)} options (need {MIN_OPTIONS}-{MAX_OPTIONS}), dropping")
                return False
            if not (0 <= q.correct_index < len(q.options)):
                logger.warning(f"{label}: correct_index {q.correct_index} out of range, dropping")
                return False
            opts = [o.strip().lower() for o in q.options]
            if len(set(opts)) != len(opts):
                logger.warning(f"{label}: duplicate options, dropping")
                return False

        elif fmt == "true_false":
            if not q.statement.strip():
                logger.warning(f"{label}: empty statement, dropping")
                return False

        elif fmt == "match_pairs":
            if not (MIN_PAIRS <= len(q.pairs) <= MAX_PAIRS):
                logger.warning(f"{label}: {len(q.pairs)} pairs (need {MIN_PAIRS}-{MAX_PAIRS}), dropping")
                return False
            lefts = [p.left.strip().lower() for p in q.pairs]
            rights = [p.right.strip().lower() for p in q.pairs]
            if len(set(lefts)) != len(lefts) or len(set(rights)) != len(rights):
                logger.warning(f"{label}: duplicate left/right items, dropping")
                return False

        elif fmt == "sort_buckets":
            if len(q.bucket_names) != 2:
                logger.warning(f"{label}: need exactly 2 bucket_names, dropping")
                return False
            if not (MIN_BUCKET_ITEMS <= len(q.bucket_items) <= MAX_BUCKET_ITEMS):
                logger.warning(f"{label}: {len(q.bucket_items)} items (need {MIN_BUCKET_ITEMS}-{MAX_BUCKET_ITEMS}), dropping")
                return False
            if any(bi.correct_bucket not in (0, 1) for bi in q.bucket_items):
                logger.warning(f"{label}: correct_bucket must be 0 or 1, dropping")
                return False
            if len({bi.correct_bucket for bi in q.bucket_items}) < 2:
                logger.warning(f"{label}: all items in one bucket, dropping")
                return False

        elif fmt == "sequence":
            if not (MIN_SEQUENCE_ITEMS <= len(q.sequence_items) <= MAX_SEQUENCE_ITEMS):
                logger.warning(f"{label}: {len(q.sequence_items)} items (need {MIN_SEQUENCE_ITEMS}-{MAX_SEQUENCE_ITEMS}), dropping")
                return False
            items = [s.strip().lower() for s in q.sequence_items]
            if len(set(items)) != len(items):
                logger.warning(f"{label}: duplicate sequence items, dropping")
                return False

        elif fmt == "spot_the_error":
            if not (MIN_ERROR_STEPS <= len(q.error_steps) <= MAX_ERROR_STEPS):
                logger.warning(f"{label}: {len(q.error_steps)} steps (need {MIN_ERROR_STEPS}-{MAX_ERROR_STEPS}), dropping")
                return False
            if not (0 <= q.error_index < len(q.error_steps)):
                logger.warning(f"{label}: error_index out of range, dropping")
                return False

        elif fmt == "odd_one_out":
            if not (MIN_ODD_ITEMS <= len(q.odd_items) <= MAX_ODD_ITEMS):
                logger.warning(f"{label}: {len(q.odd_items)} items (need {MIN_ODD_ITEMS}-{MAX_ODD_ITEMS}), dropping")
                return False
            if not (0 <= q.odd_index < len(q.odd_items)):
                logger.warning(f"{label}: odd_index out of range, dropping")
                return False

        elif fmt == "predict_then_reveal":
            if not (MIN_OPTIONS <= len(q.options) <= MAX_OPTIONS):
                logger.warning(f"{label}: {len(q.options)} options (need {MIN_OPTIONS}-{MAX_OPTIONS}), dropping")
                return False
            if not (0 <= q.correct_index < len(q.options)):
                logger.warning(f"{label}: correct_index out of range, dropping")
                return False
            if not q.reveal_text.strip():
                logger.warning(f"{label}: empty reveal_text, dropping")
                return False

        elif fmt == "swipe_classify":
            if len(q.bucket_names) != 2:
                logger.warning(f"{label}: need exactly 2 category labels, dropping")
                return False
            if not (MIN_SWIPE_ITEMS <= len(q.bucket_items) <= MAX_SWIPE_ITEMS):
                logger.warning(f"{label}: {len(q.bucket_items)} items (need {MIN_SWIPE_ITEMS}-{MAX_SWIPE_ITEMS}), dropping")
                return False
            if any(bi.correct_bucket not in (0, 1) for bi in q.bucket_items):
                logger.warning(f"{label}: correct_bucket must be 0 or 1, dropping")
                return False
            if len({bi.correct_bucket for bi in q.bucket_items}) < 2:
                logger.warning(f"{label}: all items in one category, dropping")
                return False

        elif fmt == "tap_to_eliminate":
            if not (MIN_ELIMINATE_OPTIONS <= len(q.options) <= MAX_ELIMINATE_OPTIONS):
                logger.warning(f"{label}: {len(q.options)} options (need {MIN_ELIMINATE_OPTIONS}-{MAX_ELIMINATE_OPTIONS}), dropping")
                return False
            if not (0 <= q.correct_index < len(q.options)):
                logger.warning(f"{label}: correct_index out of range, dropping")
                return False
            opts = [o.strip().lower() for o in q.options]
            if len(set(opts)) != len(opts):
                logger.warning(f"{label}: duplicate options, dropping")
                return False

        return True

    def _to_storage_dict(self, q: PracticeQuestionOutput) -> dict:
        """Convert a validated question to the dict shape expected by
        PracticeQuestionRepository.bulk_insert: top-level format/difficulty/
        concept_tag + JSONB question_json containing only fields relevant to
        the chosen format.
        """
        return {
            "format": q.format,
            "difficulty": q.difficulty,
            "concept_tag": q.concept_tag,
            "question_json": self._build_question_json(q),
        }

    def _build_question_json(self, q: PracticeQuestionOutput) -> dict:
        """Build the stored JSONB payload — only fields relevant to the format,
        plus the universal question_text + explanation_why."""
        base: dict = {
            "question_text": q.question_text,
            "explanation_why": q.explanation_why,
        }
        fmt = q.format

        if fmt in ("pick_one", "fill_blank", "tap_to_eliminate"):
            base["options"] = q.options
            base["correct_index"] = q.correct_index
        elif fmt == "predict_then_reveal":
            base["options"] = q.options
            base["correct_index"] = q.correct_index
            base["reveal_text"] = q.reveal_text
        elif fmt == "true_false":
            base["statement"] = q.statement
            base["correct_answer_bool"] = q.correct_answer_bool
        elif fmt == "match_pairs":
            base["pairs"] = [{"left": p.left, "right": p.right} for p in q.pairs]
        elif fmt in ("sort_buckets", "swipe_classify"):
            base["bucket_names"] = q.bucket_names
            base["bucket_items"] = [
                {"text": bi.text, "correct_bucket": bi.correct_bucket}
                for bi in q.bucket_items
            ]
        elif fmt == "sequence":
            base["sequence_items"] = q.sequence_items
        elif fmt == "spot_the_error":
            base["error_steps"] = q.error_steps
            base["error_index"] = q.error_index
        elif fmt == "odd_one_out":
            base["odd_items"] = q.odd_items
            base["odd_index"] = q.odd_index
        elif fmt == "free_form":
            base["expected_answer"] = q.expected_answer
            base["grading_rubric"] = q.grading_rubric

        return base

    def _current_model_id(self) -> Optional[str]:
        """Best-effort lookup of the LLM model currently configured for
        practice_bank_generator — for storing in PracticeQuestion.generator_model.
        """
        try:
            return self.llm.model_id
        except AttributeError:
            return None
