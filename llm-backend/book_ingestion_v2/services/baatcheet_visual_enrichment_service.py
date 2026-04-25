"""Stage 5c — fill the `visual_explanation` slot on Baatcheet visual cards.

Far simpler than `AnimationEnrichmentService` because Stage 5b already decided
*which* cards are visuals and produced a `visual_intent` description. This
stage just turns each intent into PixiJS code.

No review-refine pass in V1 — Baatcheet visuals are accents (PRD §15 punts
illustrated avatars to V2). If quality drifts post-launch, copy review-refine
rounds from `AnimationEnrichmentService`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from shared.models.entities import TeachingGuideline, TopicDialogue
from shared.repositories.dialogue_repository import DialogueRepository
from shared.services.llm_service import LLMService
from tutor.services.pixi_code_generator import PixiCodeGenerator

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_VISUAL_INTENT_TEMPLATE = (_PROMPTS_DIR / "baatcheet_visual_intent.txt").read_text()


class BaatcheetVisualEnrichmentService:
    """Convert visual_intent → PixiJS code for every visual card on the dialogue.

    Idempotent per (guideline_id, card_id): cards that already have
    `visual_explanation.pixi_code` are skipped unless `force=True`.
    """

    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.repo = DialogueRepository(db)
        # Reuses the existing PixiCodeGenerator wholesale (PRD §FR-24).
        self.pixi_gen = PixiCodeGenerator(llm_service)

    # ─── Public API ────────────────────────────────────────────────────────

    def enrich_guideline(
        self,
        guideline: TeachingGuideline,
        force: bool = False,
        heartbeat_fn=None,
        stage_collector: Optional[list] = None,
    ) -> dict:
        """Generate PixiJS for every `visual` card on this guideline's dialogue.

        Returns: {enriched, skipped, failed, errors[], cards_with_visuals_total}.
        """
        result = {
            "enriched": 0, "skipped": 0, "failed": 0,
            "errors": [], "cards_with_visuals_total": 0,
        }
        dialogue = self.repo.get_by_guideline_id(guideline.id)
        if not dialogue or not dialogue.cards_json:
            logger.info(f"No dialogue for {guideline.id} — Stage 5c skipped")
            return result

        topic = guideline.topic_title or guideline.topic
        cards = list(dialogue.cards_json)
        modified = False

        for card in cards:
            if heartbeat_fn:
                try:
                    heartbeat_fn()
                except Exception:
                    pass

            if card.get("card_type") != "visual":
                continue
            result["cards_with_visuals_total"] += 1

            existing = card.get("visual_explanation") or {}
            if existing.get("pixi_code") and not force:
                result["skipped"] += 1
                continue

            intent = (card.get("visual_intent") or "").strip()
            if not intent:
                # Nothing for the generator to act on. Quietly drop.
                logger.warning(
                    f"Baatcheet visual card {card.get('card_idx')} on "
                    f"{guideline.id} has no visual_intent — skipping"
                )
                result["skipped"] += 1
                continue

            try:
                visual_prompt = self._build_pixi_prompt(intent, guideline)
                pixi_code = asyncio.run(
                    self.pixi_gen.generate(visual_prompt, output_type="image")
                )
                if not pixi_code:
                    raise RuntimeError("Pixi code generator returned empty output")

                card["visual_explanation"] = {
                    "output_type": "static_visual",
                    "title": card.get("title"),
                    "visual_summary": intent,
                    "visual_spec": intent,
                    "pixi_code": pixi_code,
                }
                modified = True
                result["enriched"] += 1

                if stage_collector is not None:
                    stage_collector.append({
                        "guideline_id": guideline.id,
                        "topic_title": topic,
                        "stage": "baatcheet_visual_enrichment",
                        "card_idx": card.get("card_idx"),
                        "card_id": card.get("card_id"),
                        "visual_intent": intent,
                        "pixi_code_chars": len(pixi_code),
                    })

            except Exception as e:
                logger.error(
                    f"Stage 5c PixiJS gen failed for {guideline.id} "
                    f"card {card.get('card_idx')}: {e}"
                )
                result["failed"] += 1
                result["errors"].append(
                    f"{topic} card {card.get('card_idx')}: {e}"
                )

        if modified:
            self.repo.upsert(
                guideline_id=guideline.id,
                cards_json=cards,
                generator_model=dialogue.generator_model,
                source_variant_key=dialogue.source_variant_key,
                source_explanation_id=dialogue.source_explanation_id,
                source_content_hash=dialogue.source_content_hash,
            )

        return result

    def enrich_chapter(
        self,
        book_id: str,
        chapter_id: Optional[str] = None,
        force: bool = False,
        job_service=None,
        job_id: Optional[str] = None,
    ) -> dict:
        """Enrich every approved guideline in a chapter (or book)."""
        from shared.models.entities import TeachingGuideline as TG

        query = self.db.query(TG).filter(
            TG.book_id == book_id,
            TG.review_status == "APPROVED",
        )
        if chapter_id:
            from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
            chapter = ChapterRepository(self.db).get_by_id(chapter_id)
            if chapter:
                query = query.filter(
                    TG.chapter_key == f"chapter-{chapter.chapter_number}"
                )

        guidelines = query.order_by(TG.topic_sequence).all()
        completed = 0
        failed = 0
        skipped = 0
        errors: list[str] = []
        total_enriched_cards = 0

        for guideline in guidelines:
            topic = guideline.topic_title or guideline.topic
            if job_service and job_id:
                job_service.update_progress(
                    job_id, current_item=topic, completed=completed, failed=failed,
                )
            try:
                per = self.enrich_guideline(guideline, force=force)
                total_enriched_cards += per["enriched"]
                if per["failed"] > 0:
                    failed += 1
                    errors.extend(per["errors"][:3])
                elif per["cards_with_visuals_total"] == 0:
                    skipped += 1
                else:
                    completed += 1
            except Exception as e:
                failed += 1
                errors.append(f"{topic}: {e}")
                logger.exception(f"Stage 5c failed for guideline {guideline.id}")

        if job_service and job_id:
            job_service.update_progress(
                job_id, current_item=None, completed=completed, failed=failed,
                detail=json.dumps({
                    "completed": completed, "skipped": skipped, "failed": failed,
                    "cards_enriched": total_enriched_cards, "errors": errors[:10],
                }),
            )

        return {
            "completed": completed, "skipped": skipped, "failed": failed,
            "cards_enriched": total_enriched_cards, "errors": errors[:10],
        }

    # ─── Internals ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_pixi_prompt(intent: str, guideline: TeachingGuideline) -> str:
        return (_VISUAL_INTENT_TEMPLATE
            .replace("{grade}", str(guideline.grade or ""))
            .replace("{topic_name}", guideline.topic_title or guideline.topic)
            .replace("{visual_intent}", intent)
        )
