"""Stage: baatcheet_visuals — fill the `visual_explanation` slot on Baatcheet
dialogue cards with PixiJS code.

V2 path (dialogue.plan_json present): an LLM selector picks 12-18 cards
from the lesson plan + dialogue based on the plan's `visual_required` flags
and a default-generate rule, returning `visual_intent` per selected card.
PixiCodeGenerator turns each intent into runnable PixiJS code.

V1 fallback (dialogue.plan_json missing): iterate cards where
`card_type == "visual"` — V1 dialogues already named those out and
attached `visual_intent`. Kept so legacy dialogues don't silently
regress when this stage runs against them.

Idempotent per (guideline_id, card_idx): cards that already have
`visual_explanation.pixi_code` are skipped unless `force=True`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
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
_VISUAL_PASS_SYSTEM_TEMPLATE = (
    _PROMPTS_DIR / "baatcheet_visual_pass_system.txt"
).read_text()
_VISUAL_PASS_USER_TEMPLATE = (
    _PROMPTS_DIR / "baatcheet_visual_pass.txt"
).read_text()


class BaatcheetVisualEnrichmentService:
    """Convert plan + dialogue → PixiJS code on the dialogue's selected cards."""

    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.llm_service = llm_service
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
        """Generate PixiJS for every selected card on this guideline's dialogue.

        Returns: {selected_count, enriched, skipped, failed, errors[],
                  cards_with_visuals_total}.
        """
        result = {
            "selected_count": 0,
            "enriched": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
            "cards_with_visuals_total": 0,
        }
        dialogue = self.repo.get_by_guideline_id(guideline.id)
        if not dialogue or not dialogue.cards_json:
            logger.info(f"No dialogue for {guideline.id} — Stage 5c skipped")
            return result

        topic = guideline.topic_title or guideline.topic
        cards = list(dialogue.cards_json)

        # Selection step. V2 dialogues run the LLM selector against the plan +
        # dialogue cards; V1 dialogues fall back to `card_type=="visual"` cards
        # that already carry visual_intent.
        if dialogue.plan_json:
            try:
                selections = self._run_visual_selector(guideline, dialogue, cards)
            except Exception as e:
                logger.exception(
                    f"Stage 5c visual selector failed for {guideline.id}"
                )
                result["failed"] += 1
                result["errors"].append(f"{topic}: selector failed: {e}")
                return result
        else:
            selections = self._derive_v1_selections(cards)

        result["selected_count"] = len(selections)
        by_idx = {
            sel["card_idx"]: sel
            for sel in selections
            if isinstance(sel, dict) and "card_idx" in sel
        }
        if not by_idx:
            logger.warning(
                f"Stage 5c selector picked nothing for {guideline.id} — "
                f"selector returned {len(selections)} entries"
            )
            return result

        modified = False
        for card in cards:
            if heartbeat_fn:
                try:
                    heartbeat_fn()
                except Exception:
                    pass

            if not isinstance(card, dict):
                continue
            card_idx = card.get("card_idx")
            if card_idx is None or card_idx not in by_idx:
                continue

            result["cards_with_visuals_total"] += 1
            existing = card.get("visual_explanation") or {}
            if existing.get("pixi_code") and not force:
                result["skipped"] += 1
                continue

            intent = (by_idx[card_idx].get("visual_intent") or "").strip()
            if not intent:
                logger.warning(
                    f"Selection for card {card_idx} on {guideline.id} has "
                    f"empty visual_intent — skipping"
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

                # Surface intent on the card too — read paths and admin
                # diff tooling lean on it for "why was this drawn".
                card["visual_intent"] = intent
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
                        "card_idx": card_idx,
                        "card_id": card.get("card_id"),
                        "visual_intent": intent,
                        "pixi_code_chars": len(pixi_code),
                    })

            except Exception as e:
                logger.error(
                    f"Stage 5c PixiJS gen failed for {guideline.id} "
                    f"card {card_idx}: {e}"
                )
                result["failed"] += 1
                result["errors"].append(f"{topic} card {card_idx}: {e}")

        if modified:
            # `repo.upsert` is delete-then-insert — we reuse it instead of
            # touching the row in place because it preserves the schema
            # contract (single source of validation) and SQLAlchemy doesn't
            # see in-place dict mutations on JSONB columns without
            # `flag_modified` anyway.
            self.repo.upsert(
                guideline_id=guideline.id,
                cards_json=cards,
                generator_model=dialogue.generator_model,
                source_variant_key=dialogue.source_variant_key,
                source_explanation_id=dialogue.source_explanation_id,
                source_content_hash=dialogue.source_content_hash,
                plan_json=dialogue.plan_json,
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

    # ─── Selector internals ────────────────────────────────────────────────

    def _run_visual_selector(
        self,
        guideline: TeachingGuideline,
        dialogue: TopicDialogue,
        cards: list[dict],
    ) -> list[dict]:
        """Call the LLM with visual_pass prompts → list of selections.

        Each selection: `{card_idx, visual_intent, why?}`. Selector picks
        cards based on the plan's `visual_required` flags + default-generate
        logic; production discards any `svg`/`pixi_code` fields the LLM
        might still emit and routes intent through PixiCodeGenerator.
        """
        slim_cards = self._slim_cards_for_prompt(cards)
        ctx = {
            "topic_name": guideline.topic_title or guideline.topic or "",
            "subject": guideline.subject or "",
            "grade": str(guideline.grade or ""),
            "lesson_plan_json": json.dumps(dialogue.plan_json, indent=2),
            "dialogue_cards_json": json.dumps(slim_cards, indent=2),
        }
        user_prompt = _fill_template(_VISUAL_PASS_USER_TEMPLATE, ctx)
        system_prompt = _fill_template(
            _VISUAL_PASS_SYSTEM_TEMPLATE, {"grade": ctx["grade"]}
        )

        # Combined prompt because LLMService.call doesn't take a system
        # prompt arg by default; the system text is just instructions
        # consumed by the same model in front of the user task.
        result = self.llm_service.call(
            prompt=system_prompt + "\n\n" + user_prompt,
            json_mode=True,
        )

        parsed = result.get("parsed")
        if parsed is None:
            parsed = _extract_json(result.get("output_text", "") or "")
        if parsed is None:
            raise RuntimeError(
                "Visual selector returned unparseable response — "
                "expected JSON object with `visualizations` array"
            )

        viz = parsed.get("visualizations") if isinstance(parsed, dict) else None
        if not isinstance(viz, list):
            raise RuntimeError(
                f"Visual selector response missing list `visualizations` "
                f"(got {type(viz).__name__})"
            )
        return viz

    @staticmethod
    def _slim_cards_for_prompt(cards: list) -> list[dict]:
        """Trim cards to the fields the selector needs.

        Mirrors the experiment harness shape so the validated prompt
        behaves identically here.
        """
        out: list[dict] = []
        for c in cards:
            if not isinstance(c, dict):
                continue
            slim = {
                "card_idx": c.get("card_idx"),
                "card_type": c.get("card_type"),
                "speaker": c.get("speaker"),
                "speaker_name": c.get("speaker_name"),
                "lines": [
                    {"display": (l or {}).get("display", "")}
                    for l in (c.get("lines") or [])
                ],
            }
            if c.get("visual_intent"):
                slim["existing_visual_intent"] = c["visual_intent"]
            out.append(slim)
        return out

    @staticmethod
    def _derive_v1_selections(cards: list) -> list[dict]:
        """V1 fallback: cards with `card_type=="visual"` already carry intent."""
        return [
            {
                "card_idx": c.get("card_idx"),
                "visual_intent": (c.get("visual_intent") or "").strip(),
            }
            for c in cards
            if isinstance(c, dict)
            and c.get("card_type") == "visual"
            and (c.get("visual_intent") or "").strip()
        ]

    @staticmethod
    def _build_pixi_prompt(intent: str, guideline: TeachingGuideline) -> str:
        return (_VISUAL_INTENT_TEMPLATE
            .replace("{grade}", str(guideline.grade or ""))
            .replace("{topic_name}", guideline.topic_title or guideline.topic or "")
            .replace("{visual_intent}", intent)
        )


# ─── Module helpers ────────────────────────────────────────────────────────


def _fill_template(template: str, ctx: dict) -> str:
    out = template
    for key, val in ctx.items():
        out = out.replace("{" + key + "}", str(val))
    return out


def _extract_json(text: str) -> Optional[dict]:
    """Best-effort JSON extractor for selector responses without json_mode."""
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        first = text.find("{")
        last = text.rfind("}")
        if first == -1 or last == -1:
            return None
        candidate = text[first:last + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None
