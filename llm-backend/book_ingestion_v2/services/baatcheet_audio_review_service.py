"""Opt-in audio text review for Baatcheet dialogues.

Wraps `AudioTextReviewService` so the existing review LLM logic, drift guard,
and `_apply_revisions` machinery are reused verbatim. Only the iteration
target changes — instead of walking variant A explanations, this service
walks the single dialogue row in `topic_dialogues`.

Triggered manually via the admin "Review Baatcheet audio" button. Not part
of the default pipeline (V1) — the Stage 5b validators already enforce the
deterministic audio defects (markdown/equals/emoji), and the admin button
is the safety valve for subtle defects an LLM reviewer would catch.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import attributes

from shared.models.entities import TeachingGuideline
from shared.repositories.dialogue_repository import DialogueRepository
from shared.services.llm_service import LLMService
from book_ingestion_v2.services.audio_text_review_service import (
    AudioTextReviewService,
    DEFAULT_LANGUAGE,
)

logger = logging.getLogger(__name__)


class BaatcheetAudioReviewService:
    """Run the existing audio text review against `topic_dialogues.cards_json`.

    Reuses `AudioTextReviewService._review_card` and `_apply_revisions` —
    the per-card prompt and revision contract are identical to the variant A
    review.
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
        self.dialogue_repo = DialogueRepository(db)
        self._inner = AudioTextReviewService(db, llm_service, language=language)

    def review_guideline(
        self,
        guideline: TeachingGuideline,
        *,
        heartbeat_fn: Optional[Callable] = None,
        stage_collector: Optional[list] = None,
        force: bool = False,
    ) -> dict:
        """Review every card in this guideline's dialogue.

        Returns the same shape as `AudioTextReviewService.review_guideline`
        so callers can aggregate identically.

        `force=True` clears every `audio_url` on the dialogue up front (via
        `AudioTextReviewService._clear_audio_urls_in_place`) so the
        downstream `baatcheet_audio_synthesis` run regenerates the full
        clip set instead of only re-synthesizing the lines this pass
        happens to revise.
        """
        result = {
            "cards_reviewed": 0,
            "cards_revised": 0,
            "failed": 0,
            "errors": [],
        }
        dialogue = self.dialogue_repo.get_by_guideline_id(guideline.id)
        if not dialogue or not dialogue.cards_json:
            return result

        cards = dialogue.cards_json
        topic = guideline.topic_title or guideline.topic
        any_change = False

        if force:
            for card in cards:
                self._inner._clear_audio_urls_in_place(card)
            any_change = True

        for card in cards:
            if heartbeat_fn:
                try:
                    heartbeat_fn()
                except Exception:
                    pass

            try:
                card_output = self._inner._review_card(card, guideline)
                result["cards_reviewed"] += 1

                if card_output is None:
                    self._collect_snapshot(
                        stage_collector, guideline, card,
                        revisions=[], applied_count=0, error="llm_error",
                    )
                    continue

                valid = [
                    r for r in card_output.revisions
                    if self._inner._validate_revision(r)
                ]
                applied = self._inner._apply_revisions(card, valid)
                if applied > 0:
                    result["cards_revised"] += 1
                    any_change = True

                self._collect_snapshot(
                    stage_collector, guideline, card,
                    revisions=card_output.revisions, applied_count=applied,
                )
            except Exception as e:
                result["failed"] += 1
                result["errors"].append(
                    f"{topic} card {card.get('card_idx')}: {e}"
                )
                logger.exception(
                    f"Baatcheet audio review failed for {guideline.id} "
                    f"card {card.get('card_idx')}"
                )

        if any_change:
            # The dialogue row's cards_json was mutated in place by
            # _apply_revisions. Persist via upsert (preserves content_hash and
            # source_explanation_id) and flag the JSONB column as modified
            # before commit so SQLAlchemy ships the new payload.
            attributes.flag_modified(dialogue, "cards_json")
            self.db.commit()

        return result

    @staticmethod
    def _collect_snapshot(
        stage_collector: Optional[list],
        guideline: TeachingGuideline,
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
            "card_idx": card.get("card_idx"),
            "card_id": card.get("card_id"),
            "card_type": card.get("card_type"),
            "stage": "baatcheet_audio_review",
            "revisions_proposed": [
                r.model_dump() if hasattr(r, "model_dump") else r
                for r in revisions
            ],
            "revisions_applied": applied_count,
        }
        if error:
            entry["error"] = error
        stage_collector.append(entry)
