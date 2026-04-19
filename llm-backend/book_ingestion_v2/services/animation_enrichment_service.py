"""Offline pipeline to enrich explanation cards with pre-computed PixiJS visuals.

Pipeline per variant: decide which cards get visuals (with specs) → generate
PixiJS code from specs → validate → store back into cards_json.

Fully decoupled from explanation generation — runs after, reads/writes same
topic_explanations table.
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

from shared.services.llm_service import LLMService
from shared.models.entities import TeachingGuideline, TopicExplanation
from shared.repositories.explanation_repository import ExplanationRepository

from sqlalchemy.orm import Session as DBSession

logger = logging.getLogger(__name__)

# ─── Prompt templates ───────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_DECISION_PROMPT = (_PROMPTS_DIR / "visual_decision_and_spec.txt").read_text()
_DECISION_SYSTEM_FILE = str(_PROMPTS_DIR / "visual_decision_and_spec_system.txt")
_CODE_GEN_PROMPT = (_PROMPTS_DIR / "visual_code_generation.txt").read_text()
_REVIEW_REFINE_PROMPT = (_PROMPTS_DIR / "visual_code_review_refine.txt").read_text()

DEFAULT_REVIEW_ROUNDS = 1

# ─── Pydantic models for structured LLM output ─────────────────────────────


class VisualDecision(BaseModel):
    """LLM decision for a single card."""
    card_idx: int
    decision: str = Field(description="no_visual, static_visual, or animated_visual")
    title: Optional[str] = None
    visual_summary: Optional[str] = None
    visual_spec: Optional[str] = None


class DecisionOutput(BaseModel):
    """Full structured output from the decision prompt."""
    decisions: list[VisualDecision]


# ─── Constants ──────────────────────────────────────────────────────────────

MAX_CODE_LENGTH = 5000


class AnimationEnrichmentService:
    """Enriches explanation cards with pre-computed PixiJS visuals.

    Pipeline per variant: decide → generate code from spec → validate → store.
    """

    def __init__(self, db: DBSession, llm_service: LLMService, code_gen_llm: Optional[LLMService] = None):
        """
        Args:
            db: Database session
            llm_service: LLM for decision+spec generation (can be lightweight model)
            code_gen_llm: LLM for PixiJS code generation (heavier model). Falls back to llm_service.
        """
        self.db = db
        self.llm = llm_service
        self.code_llm = code_gen_llm or llm_service
        self.repo = ExplanationRepository(db)
        self._preflight_done = False

        self._decision_schema = LLMService.make_schema_strict(
            DecisionOutput.model_json_schema()
        )

    def _ensure_preflight(self) -> None:
        """Check the frontend dev server is reachable — needed by the stage-7
        overlap gate. Idempotent per service instance. Raises RuntimeError with
        a human-actionable message if unreachable so both enrich_chapter and
        enrich_guideline fail fast rather than silently passing every card
        through an unrunning overlap check (layout_warning would be meaningless).
        """
        if self._preflight_done:
            return
        from book_ingestion_v2.services.visual_render_harness import (
            VisualRenderHarness, FRONTEND_URL,
        )
        ok, err = VisualRenderHarness.preflight()
        if not ok:
            raise RuntimeError(
                f"Visual enrichment requires the frontend dev server at "
                f"{FRONTEND_URL} (needed for the stage-7 overlap gate). "
                f"Start it with `cd llm-frontend && npm run dev`, then retry. "
                f"Preflight error: {err}"
            )
        self._preflight_done = True

    # ─── Public API ─────────────────────────────────────────────────────

    def enrich_guideline(
        self,
        guideline: TeachingGuideline,
        force: bool = False,
        variant_keys: Optional[list[str]] = None,
        heartbeat_fn: Optional[callable] = None,
        review_rounds: int = DEFAULT_REVIEW_ROUNDS,
        stage_collector: Optional[list] = None,
    ) -> dict:
        """Enrich all variants for a guideline with visuals.

        Args:
            review_rounds: number of review-and-refine passes over generated PixiJS code (0-5).
            stage_collector: optional list to collect per-card per-round snapshots for admin viewing.

        Returns: {"enriched": int, "skipped": int, "failed": int, "errors": [str]}
        """
        review_rounds = max(0, min(review_rounds, 5))
        self._ensure_preflight()
        explanations = self.repo.get_by_guideline_id(guideline.id)
        if not explanations:
            return {"enriched": 0, "skipped": 0, "failed": 0, "errors": []}

        if variant_keys:
            explanations = [e for e in explanations if e.variant_key in variant_keys]

        topic = guideline.topic_title or guideline.topic
        result = {"enriched": 0, "skipped": 0, "failed": 0, "errors": []}

        for explanation in explanations:
            try:
                enriched = self._enrich_variant(
                    explanation, guideline, force=force, heartbeat_fn=heartbeat_fn,
                    review_rounds=review_rounds, stage_collector=stage_collector,
                )
                if enriched:
                    result["enriched"] += 1
                else:
                    result["skipped"] += 1
            except Exception as e:
                logger.error(f"Failed to enrich variant {explanation.variant_key} for {topic}: {e}")
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
        review_rounds: int = DEFAULT_REVIEW_ROUNDS,
    ) -> dict:
        """Enrich all guidelines in a chapter (or book) with visuals."""
        review_rounds = max(0, min(review_rounds, 5))
        self._ensure_preflight()

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

        for i, guideline in enumerate(guidelines):
            topic = guideline.topic_title or guideline.topic
            if job_service and job_id:
                job_service.update_progress(
                    job_id, current_item=topic,
                    completed=totals["enriched"], failed=totals["failed"],
                )

            hb = None
            if job_service and job_id:
                hb = lambda: job_service.update_progress(
                    job_id, current_item=topic,
                    completed=totals["enriched"], failed=totals["failed"],
                )

            stage_collector = [] if (job_service and job_id) else None
            result = self.enrich_guideline(
                guideline, force=force, heartbeat_fn=hb,
                review_rounds=review_rounds, stage_collector=stage_collector,
            )
            if job_service and job_id and stage_collector:
                job_service.append_stage_snapshots(job_id, stage_collector)

            totals["enriched"] += result["enriched"]
            totals["skipped"] += result["skipped"]
            totals["failed"] += result["failed"]
            totals["errors"].extend(result["errors"])

        return totals

    # ─── Internal pipeline ──────────────────────────────────────────────

    def _enrich_variant(
        self,
        explanation: TopicExplanation,
        guideline: TeachingGuideline,
        force: bool = False,
        heartbeat_fn: Optional[callable] = None,
        review_rounds: int = DEFAULT_REVIEW_ROUNDS,
        stage_collector: Optional[list] = None,
    ) -> bool:
        """Enrich a single variant. Returns True if any cards were enriched.

        Retry semantics: when force=False, cards that already have a valid
        visual_explanation.pixi_code are skipped per-card (partial-failure
        recovery). When force=True, every selected card is regenerated.
        """
        cards = explanation.cards_json
        if not cards:
            return False

        def _already_enriched(card: dict) -> bool:
            ve = card.get("visual_explanation")
            return isinstance(ve, dict) and bool(ve.get("pixi_code"))

        # Retry-mode short-circuit: if every card is enriched, nothing to do.
        if not force and all(_already_enriched(c) for c in cards):
            logger.info(f"Variant {explanation.variant_key} fully enriched, skipping")
            return False

        topic = guideline.topic_title or guideline.topic
        variant_label = explanation.variant_label or explanation.variant_key

        # Step 1: Decision + spec
        if heartbeat_fn:
            heartbeat_fn()
        decisions = self._decide_and_spec(cards, guideline, variant_label)
        selected = [d for d in decisions if d.decision != "no_visual"]

        if not selected:
            logger.info(f"No cards selected for visuals in {topic} variant {explanation.variant_key}")
            return False

        logger.info(f"Selected {len(selected)} cards for visuals in {topic} variant {explanation.variant_key}")

        # Step 2: Generate code (then review-refine N rounds) for each selected card
        enriched_count = 0
        for decision in selected:
            if heartbeat_fn:
                heartbeat_fn()

            card = next((c for c in cards if c["card_idx"] == decision.card_idx), None)
            if not card:
                continue

            # Per-card retry skip: leave already-enriched cards untouched when not force.
            if not force and _already_enriched(card):
                logger.info(
                    f"Card {decision.card_idx} already enriched in {topic} variant "
                    f"{explanation.variant_key}, skipping (retry mode)"
                )
                continue

            pixi_code = self._generate_and_validate_code(
                decision, card, guideline,
            )

            if not pixi_code:
                logger.warning(
                    f"Code generation failed for card {decision.card_idx} in "
                    f"{topic} variant {explanation.variant_key}"
                )
                continue

            self._collect_snapshot(
                stage_collector, guideline, explanation, decision, pixi_code, stage="initial",
            )

            # Review-refine N rounds
            for round_num in range(1, review_rounds + 1):
                if heartbeat_fn:
                    heartbeat_fn()
                logger.info(
                    f"Visual review-refine round {round_num}/{review_rounds} for "
                    f"{topic} variant {explanation.variant_key} card {decision.card_idx}"
                )
                refined = self._review_and_refine_code(decision, card, guideline, pixi_code)
                if refined and self._validate_code(refined):
                    pixi_code = refined
                else:
                    logger.info(
                        f"Review-refine round {round_num} returned no improvement; keeping prior code"
                    )

                self._collect_snapshot(
                    stage_collector, guideline, explanation, decision, pixi_code,
                    stage=f"refine_{round_num}",
                )

            # Post-refine overlap gate — render in headless Chromium, walk the
            # Pixi display tree, compute bbox overlaps. If overlap, one extra
            # targeted refine round with the collision report. If overlap
            # persists, store with layout_warning=true so the student-facing
            # chip renders.
            pixi_code, layout_warning = self._overlap_gate(
                pixi_code, decision, card, guideline,
                explanation=explanation, stage_collector=stage_collector,
            )

            card["visual_explanation"] = {
                "output_type": decision.decision,
                "title": decision.title,
                "visual_summary": decision.visual_summary,
                "visual_spec": decision.visual_spec,
                "pixi_code": pixi_code,
                "layout_warning": layout_warning,
            }
            enriched_count += 1

        if enriched_count == 0:
            return False

        # Step 3: Write updated cards back to DB
        self.db.query(TopicExplanation).filter(
            TopicExplanation.id == explanation.id
        ).update({"cards_json": cards})
        self.db.commit()

        logger.info(
            f"Enriched {enriched_count} cards in {topic} variant {explanation.variant_key}"
        )
        return True

    def _collect_snapshot(
        self,
        stage_collector: Optional[list],
        guideline: TeachingGuideline,
        explanation: TopicExplanation,
        decision: VisualDecision,
        pixi_code: str,
        stage: str,
    ) -> None:
        """Append a per-card per-stage snapshot for admin stage viewer."""
        if stage_collector is None:
            return
        stage_collector.append({
            "guideline_id": guideline.id,
            "topic_title": guideline.topic_title or guideline.topic,
            "variant_key": explanation.variant_key,
            "card_idx": decision.card_idx,
            "output_type": decision.decision,
            "stage": stage,
            "pixi_code": pixi_code,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def _review_and_refine_code(
        self,
        decision: VisualDecision,
        card: dict,
        guideline: TeachingGuideline,
        current_code: str,
        *,
        collision_report: Optional[str] = None,
    ) -> Optional[str]:
        """Single review-refine pass: LLM reviews the current code and returns an improved version.

        When collision_report is provided, it's injected at {collision_report} in
        the prompt so the refine pass can target specific overlapping pairs rather
        than relying on the LLM to read pixi source and intuit overlap.
        """
        topic = guideline.topic_title or guideline.topic
        grade = f"Grade {guideline.grade}" if guideline.grade else "Grade 3"

        prompt = (_REVIEW_REFINE_PROMPT
            .replace("{grade_level}", grade)
            .replace("{topic_title}", topic)
            .replace("{card_content}", card.get("content", ""))
            .replace("{visual_spec}", decision.visual_spec or "")
            .replace("{output_type}", decision.decision)
            .replace("{current_code}", current_code)
            .replace("{collision_report}", collision_report or "(none)")
        )

        try:
            result = self.code_llm.call(
                prompt=prompt,
                reasoning_effort="none",
                json_mode=False,
            )
            code = result["output_text"]
            return self._strip_markdown_fences(code)
        except Exception as e:
            logger.error(f"Visual review-refine failed for card {decision.card_idx}: {e}")
            return None

    def _overlap_gate(
        self,
        pixi_code: str,
        decision: "VisualDecision",
        card: dict,
        guideline: TeachingGuideline,
        *,
        explanation: "TopicExplanation",
        stage_collector: Optional[list],
    ) -> tuple[str, bool]:
        """Render → detect overlap → if overlap, one extra targeted refine round → re-check.

        Returns (final_code, layout_warning). layout_warning=True means overlap
        persists after the extra round; we store the code anyway so the
        student-facing chip can render.

        A harness failure (playwright not installed, localhost unreachable, etc.)
        does NOT set the warning flag — we don't false-flag cards when the check
        itself failed.
        """
        from book_ingestion_v2.services.visual_overlap_detector import (
            detect_overlaps, format_collision_report,
        )
        from book_ingestion_v2.services.visual_render_harness import VisualRenderHarness

        harness = VisualRenderHarness()
        result = harness.render(pixi_code, output_type=decision.decision)
        if not result.ok:
            logger.warning(
                f"Overlap gate: render failed for card {decision.card_idx} "
                f"({result.error}) — skipping overlap check, not flagging"
            )
            self._collect_snapshot(
                stage_collector, guideline, explanation, decision, pixi_code,
                stage="overlap_gate_skipped",
            )
            return pixi_code, False

        overlaps = detect_overlaps(result.bounds)
        if not overlaps:
            self._collect_snapshot(
                stage_collector, guideline, explanation, decision, pixi_code,
                stage="overlap_gate_clean",
            )
            return pixi_code, False

        collision_report = format_collision_report(overlaps)
        logger.info(
            f"Overlap detected on card {decision.card_idx}: {len(overlaps)} pairs — "
            f"running targeted refine round"
        )

        refined = self._review_and_refine_code(
            decision, card, guideline, pixi_code, collision_report=collision_report,
        )
        if not refined or not self._validate_code(refined):
            logger.info(
                f"Targeted refine returned no valid code for card {decision.card_idx} "
                f"— storing original with layout_warning=True"
            )
            self._collect_snapshot(
                stage_collector, guideline, explanation, decision, pixi_code,
                stage="overlap_gate_refine_failed",
            )
            return pixi_code, True

        # Re-render, re-check
        result2 = harness.render(refined, output_type=decision.decision)
        if not result2.ok:
            logger.warning(
                f"Re-render failed after targeted refine for card {decision.card_idx} "
                f"({result2.error}) — storing refined code with layout_warning=True"
            )
            self._collect_snapshot(
                stage_collector, guideline, explanation, decision, refined,
                stage="overlap_gate_rerender_failed",
            )
            return refined, True

        overlaps2 = detect_overlaps(result2.bounds)
        if overlaps2:
            logger.info(
                f"Overlap persists on card {decision.card_idx} after targeted refine "
                f"({len(overlaps2)} pairs) — storing with layout_warning=True"
            )
            self._collect_snapshot(
                stage_collector, guideline, explanation, decision, refined,
                stage="overlap_gate_persists",
            )
            return refined, True

        logger.info(f"Targeted refine fixed overlaps on card {decision.card_idx}")
        self._collect_snapshot(
            stage_collector, guideline, explanation, decision, refined,
            stage="overlap_gate_fixed",
        )
        return refined, False

    def _decide_and_spec(
        self,
        cards: list[dict],
        guideline: TeachingGuideline,
        variant_label: str,
    ) -> list[VisualDecision]:
        """LLM call: decide which cards get visuals and write specs."""
        topic = guideline.topic_title or guideline.topic
        subject = guideline.subject or "Mathematics"
        grade = f"Grade {guideline.grade}" if guideline.grade else "Grade 3"

        # Build cards summary for prompt (strip audio_text to save tokens)
        cards_for_prompt = [
            {k: v for k, v in c.items() if k in ("card_idx", "card_type", "title", "content", "visual")}
            for c in cards
        ]

        # Use system file for claude_code: static instructions loaded from file
        system_file = _DECISION_SYSTEM_FILE if self.llm.provider == "claude_code" else None

        if system_file:
            # Dynamic data only — static instructions + schema in system file
            prompt = (
                f"## Context\n\n"
                f"You are reviewing explanation cards for a {grade} student learning about: {topic}\n"
                f"Subject: {subject}\n"
                f"Teaching approach for this variant: {variant_label}\n\n"
                f"## Cards to Review\n\n"
                f"{json.dumps(cards_for_prompt, indent=2)}"
            )
        else:
            # Legacy: full prompt with everything inlined
            prompt = (_DECISION_PROMPT
                .replace("{grade_level}", grade)
                .replace("{topic_title}", topic)
                .replace("{subject}", subject)
                .replace("{variant_approach}", variant_label)
                .replace("{cards_json}", json.dumps(cards_for_prompt, indent=2))
            )

        try:
            result = self.llm.call(
                prompt=prompt,
                reasoning_effort="medium",
                json_mode=True,
                system_prompt_file=system_file,
            )
            raw = json.loads(result["output_text"])

            # Handle both array and wrapped object responses
            if isinstance(raw, list):
                decisions_list = raw
            elif isinstance(raw, dict) and "decisions" in raw:
                decisions_list = raw["decisions"]
            else:
                logger.warning(f"Unexpected decision output format: {type(raw)}")
                return []

            return [VisualDecision(**d) for d in decisions_list]

        except Exception as e:
            logger.error(f"Visual decision failed for {topic}: {e}")
            return []

    def _generate_and_validate_code(
        self,
        decision: VisualDecision,
        card: dict,
        guideline: TeachingGuideline,
    ) -> Optional[str]:
        """Generate PixiJS code from spec, validate, retry once on failure."""
        code = self._generate_code(decision, card, guideline)

        if code and self._validate_code(code):
            return code

        # Retry once with error feedback
        error_msg = self._get_validation_error(code) if code else "Empty code generated"
        logger.info(f"Retrying code generation for card {decision.card_idx} (error: {error_msg})")

        code = self._generate_code(decision, card, guideline, error_feedback=error_msg)

        if code and self._validate_code(code):
            return code

        return None

    def _generate_code(
        self,
        decision: VisualDecision,
        card: dict,
        guideline: TeachingGuideline,
        error_feedback: Optional[str] = None,
    ) -> Optional[str]:
        """Single LLM call to generate PixiJS code from a visual spec."""
        topic = guideline.topic_title or guideline.topic
        grade = f"Grade {guideline.grade}" if guideline.grade else "Grade 3"

        # Use replace instead of .format() — prompt contains PixiJS code examples with curly braces
        prompt = (_CODE_GEN_PROMPT
            .replace("{grade_level}", grade)
            .replace("{topic_title}", topic)
            .replace("{card_content}", card.get("content", ""))
            .replace("{visual_spec}", decision.visual_spec or "")
            .replace("{output_type}", decision.decision)
        )

        if error_feedback:
            prompt += (
                f"\n\n## PREVIOUS ATTEMPT FAILED\nError: {error_feedback}\n"
                "Fix the issue and generate correct code."
            )

        try:
            result = self.code_llm.call(
                prompt=prompt,
                reasoning_effort="none",
                json_mode=False,
            )
            code = result["output_text"]
            return self._strip_markdown_fences(code)
        except Exception as e:
            logger.error(f"Code generation failed for card {decision.card_idx}: {e}")
            return None

    def _validate_code(self, code: str) -> bool:
        """Basic validation: not empty, not too long, has addChild."""
        if not code or not code.strip():
            return False
        if len(code) > MAX_CODE_LENGTH:
            return False
        if "app.stage.addChild" not in code and "stage.addChild" not in code:
            return False
        return True

    def _get_validation_error(self, code: Optional[str]) -> str:
        """Describe why validation failed, for retry feedback."""
        if not code or not code.strip():
            return "Generated code was empty"
        if len(code) > MAX_CODE_LENGTH:
            return f"Code too long ({len(code)} chars, max {MAX_CODE_LENGTH}). Simplify."
        if "app.stage.addChild" not in code and "stage.addChild" not in code:
            return "Code never adds display objects to app.stage. Must call app.stage.addChild()."
        return "Unknown validation error"

    @staticmethod
    def _strip_markdown_fences(code: str) -> str:
        """Extract JS code from an LLM response.

        Handles: pure code; fenced block (optionally wrapped in prose);
        prose followed by raw code without a fence.
        """
        text = (code or "").strip()
        fenced = re.search(r"```[a-zA-Z]*\s*\n(.*?)\n```", text, re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        if text.startswith("```"):
            newline_idx = text.find("\n")
            if newline_idx == -1:
                return ""
            text = text[newline_idx + 1:]
            if text.endswith("```"):
                text = text[:-3]
            return text.strip()
        js_starts = ("const ", "let ", "var ", "function ", "//", "app.", "new ")
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.lstrip().startswith(js_starts):
                return "\n".join(lines[i:]).strip()
        return text
