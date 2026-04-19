"""Review audio text strings in explanation and check-in cards.

Surgical rewrites only: no display edits, no line reshape. Runs after stage 5
(explanations) and stage 8 (check-ins), before stage 10 (MP3 synthesis).

Per-card LLM call -> revisions list -> drop invalid revisions -> apply valid ones ->
clear audio_url on changed lines so next synth run re-synthesizes only those.

Constructor takes an injected LLMService (same pattern as CheckInEnrichmentService).
Route code builds the LLMService via LLMConfigService.
"""
import copy
import json
import logging
import re
from pathlib import Path
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import attributes

from shared.models.entities import TeachingGuideline, TopicExplanation
from shared.repositories.explanation_repository import ExplanationRepository
from shared.services.llm_service import LLMService

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_REVIEW_PROMPT = (_PROMPTS_DIR / "audio_text_review.txt").read_text()
_REVIEW_SYSTEM_FILE = str(_PROMPTS_DIR / "audio_text_review_system.txt")

DEFAULT_LANGUAGE = "en"

_BANNED_PATTERNS = [
    re.compile(r"\*\*"),
    re.compile(r"(?<![a-zA-Z])=(?![a-zA-Z])"),
    re.compile(r"[\u2600-\u27BF\U0001F300-\U0001FAFF]"),
]


class AudioLineRevision(BaseModel):
    card_idx: int = Field(description="1-based card index")
    line_idx: Optional[int] = Field(
        default=None,
        description="0-based line index within the card. NULL for check-in cards.",
    )
    kind: Literal["line", "check_in_text"] = Field(
        description="'line' = entry in card.lines[].audio; 'check_in_text' = top-level audio_text on a check_in card"
    )
    original_audio: str = Field(description="Current audio string (for drift guard)")
    revised_audio: str = Field(description="New audio string")
    reason: str = Field(description="Why this revision — cite the defect class")


class CardReviewOutput(BaseModel):
    card_idx: int = Field(description="1-based card index")
    revisions: list[AudioLineRevision] = Field(
        default_factory=list,
        description="Empty list if card is clean; otherwise one entry per changed line.",
    )
    notes: str = Field(default="", description="Optional free-form reviewer commentary")


class AudioTextReviewService:
    """Service entry point for the audio text review stage.

    Route code must build LLMService via LLMConfigService and inject it here —
    same pattern as CheckInEnrichmentService. The service does NOT build its own
    LLMService.
    """

    def __init__(
        self,
        db: DBSession,
        llm_service: LLMService,
        *,
        language: str = DEFAULT_LANGUAGE,
    ):
        self.db = db
        self.llm = llm_service
        self.language = language
        self.repo = ExplanationRepository(db)
        self._review_schema = LLMService.make_schema_strict(
            CardReviewOutput.model_json_schema()
        )

    def review_guideline(
        self,
        guideline: TeachingGuideline,
        *,
        variant_keys: Optional[list[str]] = None,
        heartbeat_fn: Optional[Callable] = None,
        stage_collector: Optional[list] = None,
    ) -> dict:
        """Review all variants (or a subset) for a single guideline."""
        explanations = self.repo.get_by_guideline_id(guideline.id)
        if variant_keys:
            explanations = [e for e in explanations if e.variant_key in variant_keys]

        result = {
            "cards_reviewed": 0,
            "cards_revised": 0,
            "failed": 0,
            "errors": [],
        }
        for explanation in explanations:
            try:
                per_variant = self._review_variant(
                    explanation,
                    guideline,
                    heartbeat_fn=heartbeat_fn,
                    stage_collector=stage_collector,
                )
                result["cards_reviewed"] += per_variant["cards_reviewed"]
                result["cards_revised"] += per_variant["cards_revised"]
            except Exception as e:
                result["failed"] += 1
                topic = guideline.topic_title or guideline.topic
                result["errors"].append(f"{topic}/{explanation.variant_key}: {e}")
                logger.exception(
                    f"Audio text review failed for {guideline.id}/{explanation.variant_key}"
                )
        return result

    def review_chapter(
        self,
        book_id: str,
        chapter_id: Optional[str] = None,
        *,
        job_service=None,
        job_id: Optional[str] = None,
    ) -> dict:
        """Review every approved guideline in a chapter (or book)."""
        query = self.db.query(TeachingGuideline).filter(
            TeachingGuideline.book_id == book_id,
            TeachingGuideline.review_status == "APPROVED",
        )
        if chapter_id:
            from shared.repositories.chapter_repository import ChapterRepository
            chapter = ChapterRepository(self.db).get_by_id(chapter_id)
            if chapter:
                query = query.filter(
                    TeachingGuideline.chapter_key == f"chapter-{chapter.chapter_number}"
                )
        guidelines = query.all()

        stage_collector: list = []
        completed = 0
        failed = 0
        errors: list[str] = []
        total_cards_reviewed = 0
        total_cards_revised = 0
        current_topic = ""

        def _hb():
            if job_service and job_id:
                try:
                    job_service.update_progress(
                        job_id, current_item=current_topic,
                        completed=completed, failed=failed,
                    )
                except Exception:
                    pass

        for guideline in guidelines:
            current_topic = guideline.topic_title or guideline.topic
            if job_service and job_id:
                job_service.update_progress(
                    job_id, current_item=current_topic,
                    completed=completed, failed=failed,
                )
            try:
                per_guideline = self.review_guideline(
                    guideline,
                    heartbeat_fn=_hb,
                    stage_collector=stage_collector,
                )
                total_cards_reviewed += per_guideline["cards_reviewed"]
                total_cards_revised += per_guideline["cards_revised"]
                if per_guideline["failed"] > 0:
                    failed += 1
                    errors.extend(per_guideline["errors"])
                else:
                    completed += 1
            except Exception as e:
                failed += 1
                errors.append(f"{current_topic}: {e}")
                logger.exception(
                    f"Audio text review failed for guideline {guideline.id}"
                )

        if job_service and job_id and stage_collector:
            try:
                job_service.append_stage_snapshots(job_id, stage_collector)
            except Exception as e:
                logger.warning(
                    f"append_stage_snapshots failed for job {job_id}: {e}"
                )

        return {
            "completed": completed,
            "failed": failed,
            "errors": errors[:10],
            "cards_reviewed": total_cards_reviewed,
            "cards_revised": total_cards_revised,
            "stage_snapshot_count": len(stage_collector),
        }

    # --- Internals ---------------------------------------------------------

    def _review_variant(
        self,
        explanation: TopicExplanation,
        guideline: TeachingGuideline,
        *,
        heartbeat_fn: Optional[Callable] = None,
        stage_collector: Optional[list] = None,
    ) -> dict:
        cards = explanation.cards_json or []
        cards_reviewed = 0
        cards_revised = 0
        any_change = False

        for card in cards:
            if heartbeat_fn:
                try:
                    heartbeat_fn()
                except Exception:
                    pass

            card_output = self._review_card(card, guideline)
            cards_reviewed += 1

            if card_output is None:
                self._collect_snapshot(
                    stage_collector, guideline, explanation, card,
                    revisions=[], applied_count=0, error="llm_error",
                )
                continue

            valid = [r for r in card_output.revisions if self._validate_revision(r)]
            applied = self._apply_revisions(card, valid)
            if applied > 0:
                cards_revised += 1
                any_change = True

            self._collect_snapshot(
                stage_collector, guideline, explanation, card,
                revisions=card_output.revisions, applied_count=applied,
            )

        if any_change:
            attributes.flag_modified(explanation, "cards_json")
            self.db.commit()

        return {"cards_reviewed": cards_reviewed, "cards_revised": cards_revised}

    def _review_card(
        self,
        card: dict,
        guideline: TeachingGuideline,
    ) -> Optional[CardReviewOutput]:
        topic = guideline.topic_title or guideline.topic
        grade = str(guideline.grade) if guideline.grade else "3"

        card_for_prompt = self._strip_audio_urls(card)

        prompt = (
            _REVIEW_PROMPT
            .replace("{topic_title}", topic)
            .replace("{grade}", grade)
            .replace("{language}", self.language)
            .replace("{card_json}", json.dumps(card_for_prompt, indent=2))
            .replace(
                "{output_schema}",
                json.dumps(CardReviewOutput.model_json_schema(), indent=2),
            )
        )

        system_file = _REVIEW_SYSTEM_FILE if self.llm.provider == "claude_code" else None

        try:
            response = self.llm.call(
                prompt=prompt,
                reasoning_effort="medium",
                json_schema=self._review_schema,
                schema_name="CardReviewOutput",
                system_prompt_file=system_file,
            )
            parsed = self.llm.parse_json_response(response["output_text"])
            return CardReviewOutput.model_validate(parsed)
        except Exception as e:
            logger.error(
                f"Audio text review LLM call failed for {topic} "
                f"card {card.get('card_idx')}: {e}"
            )
            return None

    def _validate_revision(self, rev: AudioLineRevision) -> bool:
        text = rev.revised_audio.strip()
        if not text:
            logger.info(
                f"Dropping revision card_idx={rev.card_idx} line_idx={rev.line_idx} "
                f"— revised_audio is empty"
            )
            return False
        for pattern in _BANNED_PATTERNS:
            if pattern.search(text):
                logger.info(
                    f"Dropping revision card_idx={rev.card_idx} line_idx={rev.line_idx} "
                    f"— banned pattern in revised_audio (pattern={pattern.pattern})"
                )
                return False
        return True

    def _apply_revisions(
        self, card: dict, revisions: list[AudioLineRevision]
    ) -> int:
        applied = 0
        for rev in revisions:
            if rev.kind == "check_in_text":
                if card.get("card_type") != "check_in":
                    logger.info(
                        f"Dropping revision card_idx={rev.card_idx} kind=check_in_text — "
                        f"card_type is '{card.get('card_type')}', not 'check_in'"
                    )
                    continue
                if card.get("audio_text") != rev.original_audio:
                    logger.info(
                        f"Dropping revision card_idx={rev.card_idx} kind=check_in_text — "
                        f"drift detected (original_audio mismatch)"
                    )
                    continue
                card["audio_text"] = rev.revised_audio
                applied += 1
            else:  # "line"
                lines = card.get("lines") or []
                if rev.line_idx is None or rev.line_idx < 0 or rev.line_idx >= len(lines):
                    logger.info(
                        f"Dropping revision card_idx={rev.card_idx} line_idx={rev.line_idx} "
                        f"— line index out of range (card has {len(lines)} lines)"
                    )
                    continue
                line = lines[rev.line_idx]
                if line.get("audio") != rev.original_audio:
                    logger.info(
                        f"Dropping revision card_idx={rev.card_idx} line_idx={rev.line_idx} "
                        f"— drift detected (original_audio mismatch)"
                    )
                    continue
                line["audio"] = rev.revised_audio
                line["audio_url"] = None
                applied += 1
        return applied

    def _strip_audio_urls(self, card: dict) -> dict:
        out = copy.deepcopy(card)
        for line in (out.get("lines") or []):
            line.pop("audio_url", None)
        return out

    def _collect_snapshot(
        self,
        stage_collector: Optional[list],
        guideline: TeachingGuideline,
        explanation: TopicExplanation,
        card: dict,
        *,
        revisions: list,
        applied_count: int,
        error: Optional[str] = None,
    ) -> None:
        if stage_collector is None:
            return
        entry = {
            "guideline_id": guideline.id,
            "topic_title": guideline.topic_title or guideline.topic,
            "variant_key": explanation.variant_key,
            "card_idx": card.get("card_idx"),
            "card_type": card.get("card_type"),
            "stage": "audio_text_review",
            "revisions_proposed": [
                r.model_dump() if hasattr(r, "model_dump") else r
                for r in revisions
            ],
            "revisions_applied": applied_count,
        }
        if error:
            entry["error"] = error
        stage_collector.append(entry)
