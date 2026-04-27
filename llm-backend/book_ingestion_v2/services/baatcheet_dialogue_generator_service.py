"""Stage 5b — generate the Baatcheet dialogue for a teaching guideline.

Pipeline: load variant A + guideline → LLM-generate cards 2..N → review-refine
(N rounds with validator-issue feedback) → prepend the literal welcome card →
re-index → validate (raise on failure, no silent truncation) → store with
content hash.

Mirrors `ExplanationGeneratorService` line-for-line, plus four Baatcheet-
specific concerns:
  1. Welcome card (card_idx=1) is prepended SERVER-SIDE, not LLM-generated.
  2. Strict validators: card-count bounds, banned audio patterns, check-in
     spacing, includes_student_name flag/placeholder consistency. No silent
     truncation — failure raises DialogueValidationError.
  3. Content-hash from variant A is stored on the dialogue row for staleness
     detection.
  4. Refresher topics are not generated (caller checks; service is unaware).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from shared.models.entities import TeachingGuideline, TopicDialogue
from shared.repositories.dialogue_repository import DialogueRepository
from shared.repositories.explanation_repository import ExplanationRepository
from shared.repositories.guideline_repository import TeachingGuidelineRepository
from shared.services import LLMService
from shared.utils.dialogue_hash import compute_explanation_content_hash

logger = logging.getLogger(__name__)


# ─── Prompt files (same split-prompt pattern as Explain) ────────────────────

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_LESSON_PLAN_PROMPT = (_PROMPTS_DIR / "baatcheet_lesson_plan_generation.txt").read_text()
_LESSON_PLAN_SYSTEM_FILE = str(_PROMPTS_DIR / "baatcheet_lesson_plan_generation_system.txt")
_GENERATION_PROMPT = (_PROMPTS_DIR / "baatcheet_dialogue_generation.txt").read_text()
_GENERATION_SYSTEM_FILE = str(_PROMPTS_DIR / "baatcheet_dialogue_generation_system.txt")
_REVIEW_REFINE_PROMPT = (_PROMPTS_DIR / "baatcheet_dialogue_review_refine.txt").read_text()
_REVIEW_REFINE_SYSTEM_FILE = str(_PROMPTS_DIR / "baatcheet_dialogue_review_refine_system.txt")


# ─── Constants ──────────────────────────────────────────────────────────────

# Welcome card 1 is prepended server-side; LLM produces cards 2..N.
# After the welcome is added, total = LLM_count + 1.
MIN_TOTAL_CARDS = 25       # V2 plan card_plan floor (25 lenient) + welcome
MAX_TOTAL_CARDS = 42       # V2 plan card_plan max (40) + welcome (1) + 1 slack
MIN_CHECK_IN_SPACING = 4   # cards between two check-in cards (PRD §FR-12)

DEFAULT_REVIEW_ROUNDS = 1

# Mirrors the activity types CheckInDispatcher renders. An unsupported value
# would silently fall through on the frontend (blank check-in card).
_SUPPORTED_ACTIVITY_TYPES = {
    "pick_one", "true_false", "fill_blank", "match_pairs", "sort_buckets",
    "sequence", "spot_the_error", "odd_one_out", "predict_then_reveal",
    "swipe_classify", "tap_to_eliminate",
}


# Same defect classes the audio_text_review_service.py regex catches.
# Centralising them here means Stage 5b's validator rejects deterministic
# defects at generation time instead of relying on a separate review pass.
_BANNED_AUDIO_PATTERNS = [
    re.compile(r"\*\*"),                              # markdown bold
    re.compile(r"(?<![a-zA-Z])=(?![a-zA-Z])"),         # naked equals
    re.compile(r"[⌀-➿\U0001F300-\U0001FAFF]"),  # emoji + misc technical
]


WELCOME_CARD_TEMPLATE = (
    "Hi {student_name}! I'm Mr. Verma. Today, Meera is joining us — "
    "she wants to learn about {topic_name} too. Let's start!"
)


# ─── Pydantic LLM-output schema ─────────────────────────────────────────────


class DialogueLineOutput(BaseModel):
    display: str = Field(description="Text shown on screen (may use **bold**)")
    audio: str = Field(description="TTS-friendly spoken version — no markdown, no naked =, no emoji")


class CheckInActivityOutput(BaseModel):
    activity_type: str
    instruction: str
    hint: str
    success_message: str
    audio_text: str
    options: Optional[list[str]] = None
    correct_index: Optional[int] = None
    statement: Optional[str] = None
    correct_answer: Optional[bool] = None
    pairs: Optional[list[dict]] = None
    bucket_names: Optional[list[str]] = None
    bucket_items: Optional[list[dict]] = None
    sequence_items: Optional[list[str]] = None
    error_steps: Optional[list[str]] = None
    error_index: Optional[int] = None
    odd_items: Optional[list[str]] = None
    odd_index: Optional[int] = None
    reveal_text: Optional[str] = None


class DialogueCardOutput(BaseModel):
    card_idx: int
    card_type: str  # tutor_turn | peer_turn | visual | check_in | summary | welcome
    speaker: Optional[str] = None        # tutor | peer | None
    speaker_name: Optional[str] = None
    title: Optional[str] = None
    lines: list[DialogueLineOutput] = []
    includes_student_name: bool = False
    visual_intent: Optional[str] = None
    check_in: Optional[CheckInActivityOutput] = None


class DialogueGenerationOutput(BaseModel):
    cards: list[DialogueCardOutput]


# ─── Validation ────────────────────────────────────────────────────────────


class DialogueValidationError(Exception):
    """Raised when generated cards fail validation. Caller (the route) decides
    whether to retry via review-refine or fail the job. Final pass after the
    last refine round runs with raise_on_fail=True so persistent failure
    propagates to the background task and marks the job failed."""


class LessonPlanValidationError(Exception):
    """Raised when the V2 lesson-plan stage produces output that's missing a
    top-level key or has the wrong shape. The dialogue stage depends on plan
    structure (card_plan slots, misconceptions list, spine particulars) so a
    malformed plan would silently corrupt the dialogue downstream."""


def _parse_json_with_preamble_tolerance(text: str) -> dict:
    """Extract a JSON object from LLM output that may include preamble or
    postamble (the model occasionally narrates before/after the JSON despite
    explicit "JSON only" instructions, especially on dense prompts).

    The naive "first { to last }" approach breaks when the preamble itself
    contains curly braces (e.g. literal `{student_name}` in an analysis
    bullet). Instead we walk through every `{` position and try
    JSONDecoder.raw_decode — the first one that produces a valid object is
    the answer. This is O(n) in practice because we early-exit on the first
    success.

    Order: strict json.loads → ```json fenced block → raw_decode at each
    `{` position. Raises LLMServiceError if no parseable object is found.
    """
    from shared.services.llm_service import LLMServiceError

    text = (text or "").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    for start in (i for i, c in enumerate(text) if c == "{"):
        try:
            obj, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj

    raise LLMServiceError(
        f"No JSON object found in LLM response (preview: {text[:200]!r})"
    )


def _validate_plan(plan: dict) -> None:
    """Lightweight schema check on lesson-plan output. Raises if a required
    top-level key is missing or has the wrong cardinality. Detailed schema is
    enforced by the prompt — this is a backstop against LLM drift, not a
    duplicate validator."""
    required = {"misconceptions", "spine", "concrete_materials", "macro_structure", "card_plan"}
    missing = required - set(plan or {})
    if missing:
        raise LessonPlanValidationError(f"lesson plan missing keys: {sorted(missing)}")
    miscs = plan.get("misconceptions")
    if not isinstance(miscs, list) or not (2 <= len(miscs) <= 3):
        raise LessonPlanValidationError(
            f"lesson plan misconceptions must be 2-3 entries (got {len(miscs) if isinstance(miscs, list) else type(miscs).__name__})"
        )
    card_plan = plan.get("card_plan")
    if not isinstance(card_plan, list) or not (25 <= len(card_plan) <= 40):
        raise LessonPlanValidationError(
            f"lesson plan card_plan must be 25-40 entries (got {len(card_plan) if isinstance(card_plan, list) else type(card_plan).__name__})"
        )
    spine = plan.get("spine")
    if not isinstance(spine, dict) or "situation" not in spine:
        raise LessonPlanValidationError("lesson plan spine must have 'situation'")


def _validate_cards(cards: list[DialogueCardOutput], *, raise_on_fail: bool) -> list[str]:
    """Return list of issue strings (empty when clean). Raises if requested.

    Validates (mirrors PRD §6 + impl plan §4.3):
    - 13 ≤ total cards ≤ 35
    - first card_type == 'welcome', last == 'summary'
    - check-in cards ≥ MIN_CHECK_IN_SPACING apart
    - tutor_turn / peer_turn / summary have ≥1 line
    - visual cards have non-empty visual_intent
    - lines[].audio matches no _BANNED_AUDIO_PATTERNS
    - includes_student_name flag ⇔ {student_name} placeholder in lines
    """
    issues: list[str] = []

    if not (MIN_TOTAL_CARDS <= len(cards) <= MAX_TOTAL_CARDS):
        issues.append(
            f"card count {len(cards)} outside [{MIN_TOTAL_CARDS},{MAX_TOTAL_CARDS}]"
        )
    if cards and cards[0].card_type != "welcome":
        issues.append(f"first card_type must be 'welcome' (got '{cards[0].card_type}')")
    if cards and cards[-1].card_type != "summary":
        issues.append(f"last card_type must be 'summary' (got '{cards[-1].card_type}')")

    last_check_in_pos = -1000
    for i, c in enumerate(cards):
        if c.card_type == "check_in":
            if i - last_check_in_pos < MIN_CHECK_IN_SPACING:
                issues.append(
                    f"card {c.card_idx}: check-in too close to previous "
                    f"(need ≥{MIN_CHECK_IN_SPACING} cards apart)"
                )
            last_check_in_pos = i
            if not c.check_in:
                issues.append(f"card {c.card_idx}: check_in card missing check_in object")

        if c.card_type in ("tutor_turn", "peer_turn", "summary", "welcome") and not c.lines:
            issues.append(f"card {c.card_idx}: {c.card_type} has no lines")
        if c.card_type == "visual" and not (c.visual_intent or "").strip():
            issues.append(f"card {c.card_idx}: visual card missing visual_intent")

        for li, line in enumerate(c.lines):
            for pat in _BANNED_AUDIO_PATTERNS:
                if pat.search(line.audio):
                    issues.append(
                        f"card {c.card_idx} line {li}: banned pattern in audio "
                        f"(/{pat.pattern}/)"
                    )
            # `{topic_name}` is only valid on the server-prepended welcome
            # card. Anywhere else it would TTS as the literal string.
            if c.card_type != "welcome":
                if "{topic_name}" in line.audio or "{topic_name}" in line.display:
                    issues.append(
                        f"card {c.card_idx} line {li}: '{{topic_name}}' is "
                        f"reserved for the welcome card — write the topic name "
                        f"in plain words instead"
                    )

        text_blob = " ".join(line.audio for line in c.lines)
        has_placeholder = "{student_name}" in text_blob
        if c.includes_student_name and not has_placeholder:
            issues.append(
                f"card {c.card_idx}: flagged includes_student_name but "
                f"contains no '{{student_name}}' placeholder"
            )
        if has_placeholder and not c.includes_student_name:
            issues.append(
                f"card {c.card_idx}: contains '{{student_name}}' but "
                f"includes_student_name flag is False"
            )

        # `{student_name}` is allowed ONLY in lines[].audio / lines[].display.
        # Check-in fields are pre-rendered as static audio in V1, so a
        # placeholder there would never get substituted and play silently.
        # Banned audio patterns (markdown / equals / emoji) must also be
        # caught here — otherwise they leak into the pre-rendered MP3s.
        if c.check_in:
            ci = c.check_in
            check_in_audio_fields = {
                "instruction": ci.instruction,
                "hint": ci.hint,
                "success_message": ci.success_message,
                "audio_text": ci.audio_text,
                "reveal_text": ci.reveal_text or "",
                "statement": ci.statement or "",
            }
            for field_name, field_text in check_in_audio_fields.items():
                if not field_text:
                    continue
                if "{student_name}" in field_text:
                    issues.append(
                        f"card {c.card_idx}: '{{student_name}}' found inside "
                        f"check_in.{field_name} — not allowed (V1 pre-renders "
                        f"check-in audio statically)"
                    )
                if "{topic_name}" in field_text:
                    issues.append(
                        f"card {c.card_idx}: '{{topic_name}}' found inside "
                        f"check_in.{field_name} — write the topic name in "
                        f"plain words instead"
                    )
                for pat in _BANNED_AUDIO_PATTERNS:
                    if pat.search(field_text):
                        issues.append(
                            f"card {c.card_idx}: banned pattern in "
                            f"check_in.{field_name} (/{pat.pattern}/)"
                        )
            if ci.activity_type and ci.activity_type not in _SUPPORTED_ACTIVITY_TYPES:
                issues.append(
                    f"card {c.card_idx}: activity_type '{ci.activity_type}' "
                    f"is not one of the supported CheckInDispatcher types"
                )
        for li, line in enumerate(c.lines):
            if "{student_name}" in line.display and "{student_name}" not in line.audio:
                issues.append(
                    f"card {c.card_idx} line {li}: '{{student_name}}' in display "
                    f"but not in audio — student would see name but not hear it"
                )

    if issues and raise_on_fail:
        raise DialogueValidationError("; ".join(issues[:8]))
    return issues


# ─── Card serialization helpers ────────────────────────────────────────────


def _card_output_to_dict(card: DialogueCardOutput) -> dict:
    """Convert LLM output card to storage dict; preserves all dialogue-only
    fields (speaker, includes_student_name, visual_intent)."""
    d = card.model_dump()
    # Tutor turns + welcome + summary always speak with the tutor voice.
    # Peer turns always speak with the peer voice. Visual narration is tutor.
    if d.get("speaker") is None:
        if d["card_type"] in ("tutor_turn", "welcome", "summary", "visual"):
            d["speaker"] = "tutor"
        elif d["card_type"] == "peer_turn":
            d["speaker"] = "peer"
    if d.get("speaker_name") is None:
        d["speaker_name"] = "Mr. Verma" if d.get("speaker") == "tutor" else (
            "Meera" if d.get("speaker") == "peer" else None
        )
    d.setdefault("card_id", str(uuid4()))
    return d


# ─── Service ────────────────────────────────────────────────────────────────


class BaatcheetDialogueGeneratorService:
    """Generate the Baatcheet dialogue for a teaching guideline.

    Pipeline (V2 designed-lesson architecture):
      1. Load variant A (raises if missing — caller must run Stage 5 first).
      2. LLM generates a structured lesson plan (misconceptions, spine,
         macro_structure, card_plan).
      3. LLM generates cards 2..N realizing the plan.
      4. Review-refine N rounds against the plan. The refine prompt receives
         the validator's issue list and the plan so the LLM targets both
         mechanical fixes and plan-adherence in one pass.
      5. Prepend the literal welcome card 1 server-side.
      6. Re-index card_idx 1..N.
      7. Final validation with raise_on_fail=True. No silent truncation.
      8. Persist with source_content_hash + source_explanation_id + plan_json.
    """

    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.llm = llm_service
        self.repo = DialogueRepository(db)
        self.exp_repo = ExplanationRepository(db)
        self.guideline_repo = TeachingGuidelineRepository(db)
        self._generation_schema = LLMService.make_schema_strict(
            DialogueGenerationOutput.model_json_schema()
        )

    def _refresh_db_session(self) -> None:
        """Get a fresh DB session after long-running LLM calls."""
        from database import get_db_manager
        try:
            self.db.close()
        except Exception:
            pass
        self.db = get_db_manager().get_session()
        self.repo = DialogueRepository(self.db)
        self.exp_repo = ExplanationRepository(self.db)
        self.guideline_repo = TeachingGuidelineRepository(self.db)

    def generate_for_guideline(
        self,
        guideline: TeachingGuideline,
        review_rounds: int = DEFAULT_REVIEW_ROUNDS,
        stage_collector: list | None = None,
        force: bool = False,
    ) -> Optional[TopicDialogue]:
        """Generate the dialogue for a single guideline. Returns the stored
        TopicDialogue, or None if the dialogue already exists and force=False."""
        if not force and self.repo.has_dialogue(guideline.id):
            logger.info(
                f"Baatcheet dialogue already exists for {guideline.id}, skipping"
            )
            return self.repo.get_by_guideline_id(guideline.id)

        variant_a = self.exp_repo.get_variant(guideline.id, "A")
        if not variant_a or not variant_a.cards_json:
            raise ValueError(
                f"Variant A explanation not found for guideline {guideline.id}; "
                f"run Stage 5 (explanations) first."
            )

        topic = guideline.topic_title or guideline.topic
        logger.info(json.dumps({
            "step": "BAATCHEET_DIALOGUE_GENERATION",
            "status": "starting",
            "guideline_id": guideline.id,
            "topic": topic,
            "model": self.llm.model_id,
        }))

        guideline_meta = self.guideline_repo._parse_metadata(guideline.metadata_json)
        misconceptions = guideline_meta.common_misconceptions if guideline_meta else []

        # Step 1: Generate the lesson plan (misconceptions + spine + card_plan).
        # Plan is the primary spec for both dialogue + refine; the upstream
        # guideline misconceptions become starting points the planner refines.
        plan = self._generate_lesson_plan(guideline, variant_a, misconceptions)
        self._refresh_db_session()

        if stage_collector is not None:
            stage_collector.append({
                "guideline_id": guideline.id,
                "topic_title": topic,
                "stage": "lesson_plan",
                "plan": plan,
                "timestamp": datetime.utcnow().isoformat(),
            })

        # Step 2: Generate cards 2..N realizing the plan (no welcome)
        gen_output = self._generate_dialogue(plan, guideline, variant_a)
        self._refresh_db_session()
        cards = gen_output.cards

        if stage_collector is not None:
            stage_collector.append({
                "guideline_id": guideline.id,
                "topic_title": topic,
                "stage": "initial",
                "cards": [c.model_dump() for c in cards],
                "timestamp": datetime.utcnow().isoformat(),
            })

        # Step 3: Review-refine N rounds against the plan, feeding validator issues
        last_issues: list[str] = []
        for round_num in range(1, review_rounds + 1):
            refined_output = self._review_and_refine(
                cards, plan, guideline, variant_a, validator_issues=last_issues,
            )
            self._refresh_db_session()
            cards = refined_output.cards

            if stage_collector is not None:
                stage_collector.append({
                    "guideline_id": guideline.id,
                    "topic_title": topic,
                    "stage": f"refine_{round_num}",
                    "cards": [c.model_dump() for c in cards],
                    "timestamp": datetime.utcnow().isoformat(),
                })

            # Pre-prepend validation: pass the welcome+summary checks against
            # the LLM output by simulating the prepend so issue list reflects
            # what the *final* deck will look like.
            sim_cards = [self._build_welcome_card_pydantic(guideline)] + list(cards)
            for i, c in enumerate(sim_cards, start=1):
                c.card_idx = i
            last_issues = _validate_cards(sim_cards, raise_on_fail=False)
            if not last_issues:
                logger.info(
                    f"Refine round {round_num}: validators clean, stopping early"
                )
                break

        # Step 4: Prepend welcome card 1, re-index, final validation
        final_cards: list[DialogueCardOutput] = (
            [self._build_welcome_card_pydantic(guideline)] + list(cards)
        )
        for i, c in enumerate(final_cards, start=1):
            c.card_idx = i

        _validate_cards(final_cards, raise_on_fail=True)  # No silent truncation

        # Step 5: Persist with content hash + plan
        cards_dicts = [_card_output_to_dict(c) for c in final_cards]
        content_hash = compute_explanation_content_hash(
            variant_a.cards_json, variant_a.summary_json,
        )

        dialogue = self.repo.upsert(
            guideline_id=guideline.id,
            cards_json=cards_dicts,
            generator_model=self.llm.model_id,
            source_variant_key="A",
            source_explanation_id=variant_a.id,
            source_content_hash=content_hash,
            plan_json=plan,
        )

        logger.info(json.dumps({
            "step": "BAATCHEET_DIALOGUE_GENERATION",
            "status": "complete",
            "guideline_id": guideline.id,
            "card_count": len(final_cards),
            "content_hash": content_hash[:16],
        }))
        return dialogue

    # ─── LLM calls ────────────────────────────────────────────────────────

    def _generate_lesson_plan(
        self,
        guideline: TeachingGuideline,
        variant_a,
        misconceptions: list[str],
    ) -> dict:
        """V2 Stage 5b.0: produce a structured lesson plan that the dialogue
        stage realizes. Returns the parsed JSON dict (validated for required
        top-level keys; detailed schema enforced by the prompt)."""
        prompt = self._build_lesson_plan_prompt(guideline, variant_a, misconceptions)
        system_file = (
            _LESSON_PLAN_SYSTEM_FILE if self.llm.provider == "claude_code" else None
        )
        response = self.llm.call(
            prompt=prompt,
            json_schema=None,  # plan schema is large + nested; enforced by prompt
            schema_name="LessonPlanOutput",
            system_prompt_file=system_file,
        )
        parsed = _parse_json_with_preamble_tolerance(response["output_text"])
        if not isinstance(parsed, dict):
            raise LessonPlanValidationError(
                f"lesson plan output was not a JSON object (got {type(parsed).__name__})"
            )
        _validate_plan(parsed)
        return parsed

    def _generate_dialogue(
        self,
        plan: dict,
        guideline: TeachingGuideline,
        variant_a,
    ) -> DialogueGenerationOutput:
        prompt = self._build_generation_prompt(plan, guideline, variant_a)
        system_file = (
            _GENERATION_SYSTEM_FILE if self.llm.provider == "claude_code" else None
        )
        # reasoning_effort intentionally omitted — LLMService uses the
        # per-component default from llm_config (admin-tunable).
        response = self.llm.call(
            prompt=prompt,
            json_schema=None if system_file else self._generation_schema,
            schema_name="DialogueGenerationOutput",
            system_prompt_file=system_file,
        )
        parsed = _parse_json_with_preamble_tolerance(response["output_text"])
        return DialogueGenerationOutput.model_validate(parsed)

    def _review_and_refine(
        self,
        cards: list[DialogueCardOutput],
        plan: dict,
        guideline: TeachingGuideline,
        variant_a,
        validator_issues: list[str],
    ) -> DialogueGenerationOutput:
        prompt = self._build_refine_prompt(
            cards, plan, guideline, variant_a, validator_issues,
        )
        system_file = (
            _REVIEW_REFINE_SYSTEM_FILE if self.llm.provider == "claude_code" else None
        )
        response = self.llm.call(
            prompt=prompt,
            json_schema=None if system_file else self._generation_schema,
            schema_name="DialogueGenerationOutput",
            system_prompt_file=system_file,
        )
        parsed = _parse_json_with_preamble_tolerance(response["output_text"])
        return DialogueGenerationOutput.model_validate(parsed)

    # ─── Prompt builders ───────────────────────────────────────────────────

    def _build_lesson_plan_prompt(
        self,
        guideline: TeachingGuideline,
        variant_a,
        misconceptions: list[str],
    ) -> str:
        """V2 Stage 5b.0 — feed the planner the topic, guideline, key concepts
        from variant A, and upstream misconceptions as starting points."""
        return (_LESSON_PLAN_PROMPT
            .replace("{topic_name}", guideline.topic_title or guideline.topic)
            .replace("{subject}", guideline.subject or "")
            .replace("{grade}", str(guideline.grade or ""))
            .replace("{guideline_text}", guideline.guideline or guideline.description or "")
            .replace("{key_concepts_list}", self._extract_key_concepts(variant_a))
            .replace("{variant_a_cards_json}", json.dumps(variant_a.cards_json, indent=2))
            .replace("{misconceptions_list}", self._format_misconceptions(misconceptions))
            .replace("{prior_topics_section}", self._prior_topics_section(guideline))
        )

    def _build_generation_prompt(
        self,
        plan: dict,
        guideline: TeachingGuideline,
        variant_a,
    ) -> str:
        """V2 Stage 5b.1 — feed the dialogue stage the lesson plan as primary
        spec. Variant A is kept for content fidelity check only."""
        return (_GENERATION_PROMPT
            .replace("{topic_name}", guideline.topic_title or guideline.topic)
            .replace("{subject}", guideline.subject or "")
            .replace("{grade}", str(guideline.grade or ""))
            .replace("{lesson_plan_json}", json.dumps(plan, indent=2))
            .replace("{variant_a_cards_json}", json.dumps(variant_a.cards_json, indent=2))
            .replace("{prior_topics_section}", self._prior_topics_section(guideline))
        )

    def _build_refine_prompt(
        self,
        cards: list[DialogueCardOutput],
        plan: dict,
        guideline: TeachingGuideline,
        variant_a,
        validator_issues: list[str],
    ) -> str:
        """V2 Stage 5b.2 — feed the refine stage the plan + the current cards.
        Refine validates plan-followed AND fixes any validator-flagged defects
        in one pass."""
        cards_for_review = [c.model_dump() for c in cards]
        cards_json_str = json.dumps(cards_for_review, indent=2)

        if validator_issues:
            issues_section = (
                "VALIDATOR ISSUES from the previous round (FIX EACH):\n- "
                + "\n- ".join(validator_issues)
            )
        else:
            issues_section = ""

        return (_REVIEW_REFINE_PROMPT
            .replace("{topic_name}", guideline.topic_title or guideline.topic)
            .replace("{subject}", guideline.subject or "")
            .replace("{grade}", str(guideline.grade or ""))
            .replace("{lesson_plan_json}", json.dumps(plan, indent=2))
            .replace("{variant_a_cards_json}", json.dumps(variant_a.cards_json, indent=2))
            .replace("{cards_json}", cards_json_str)
            .replace("{validator_issues_section}", issues_section)
            .replace("{prior_topics_section}", self._prior_topics_section(guideline))
        )

    @staticmethod
    def _format_misconceptions(items: list[str]) -> str:
        if not items:
            return "(none on file for this topic)"
        return "\n".join(f"- {m}" for m in items)

    @staticmethod
    def _extract_key_concepts(variant_a) -> str:
        """Flat bulleted list of concept titles from variant A.

        Variant A emits the card_types: concept | example | visual | analogy |
        summary | welcome (see `explanation_generator_service.py:44`). We pull
        titles from the four teaching types and skip the structural ones
        (welcome, summary). Analogy cards often carry the load-bearing
        intuition for a topic — omitting them would let the refine round's
        coverage check pass with a real concept missing.

        The dialogue must teach every concept here, but is free to choose
        order, examples, and pacing — variant A's structure is not the
        dialogue's spine. See `dialogue-quality-impl-plan.md` §3.
        """
        cards = variant_a.cards_json or []
        teaching_types = {"concept", "visual", "example", "analogy"}
        titles: list[str] = []
        seen = set()
        for c in cards:
            ct = c.get("card_type")
            title = (c.get("title") or "").strip()
            if ct in teaching_types and title and title not in seen:
                seen.add(title)
                titles.append(title)
        if not titles:
            return "(none extracted — fall back to the variant A reference below)"
        return "\n".join(f"- {t}" for t in titles)

    @staticmethod
    def _prior_topics_section(guideline: TeachingGuideline) -> str:
        ctx = (guideline.prior_topics_context or "").strip()
        if not ctx:
            return ""
        return (
            "PRIOR TOPICS CONTEXT (what the student has seen earlier in this chapter):\n"
            f"{ctx}\n"
            "Weave natural callbacks where helpful (Mr. Verma can reference these)."
        )

    # ─── Welcome card builder (server-side, never LLM) ─────────────────────

    @staticmethod
    def _build_welcome_card_pydantic(guideline: TeachingGuideline) -> DialogueCardOutput:
        return DialogueCardOutput(
            card_idx=1,
            card_type="welcome",
            speaker="tutor",
            speaker_name="Mr. Verma",
            title=None,
            lines=[
                DialogueLineOutput(
                    display=WELCOME_CARD_TEMPLATE,
                    audio=WELCOME_CARD_TEMPLATE,
                ),
            ],
            includes_student_name=True,  # forces runtime TTS at session start
            visual_intent=None,
            check_in=None,
        )
