# Tech Implementation Plan: Baatcheet — Conversational Teach Me Mode

**Date:** 2026-04-25
**Status:** Draft
**PRD:** `docs/feature-development/baatcheet/PRD.md` (PR #119)
**Author:** Tech Impl Plan Generator + Manish Jain

---

## 1. Overview

Baatcheet adds a conversational variant of the existing pre-computed Teach Me ("Explain") flow. The student watches a pre-scripted dialogue between the tutor (Mr. Verma) and a peer (Meera), card-by-card, with the same carousel + check-in dispatch already used by Explain. Two new ingestion stages produce the dialogue text (5b) and Baatcheet-specific PixiJS visuals (5c). Stage 10 (audio synthesis) is extended to select voice per `card.speaker`. A new `topic_dialogues` table mirrors the `topic_explanations` storage pattern (single row per guideline; cascade-deleted with the guideline). The frontend gains a third `sessionPhase` (`dialogue_phase`), a Teach-Me sub-chooser, server-side resume-from-last-card (also added to Explain), and a runtime TTS pre-fetch for cards flagged `includes_student_name`. The implementation follows the existing variant-A pipeline patterns one-to-one — new services slot into the same `ChapterJobService` lock model, the same launcher map, the same Pydantic-driven LLM call shape, the same admin trigger-button surface.

**Guiding principle:** every new piece of code mirrors an existing one. We are duplicating-and-tweaking, not inventing.

---

## 2. Architecture Changes

### 2.1 Pipeline DAG (orchestrator)

```
BEFORE                                  AFTER
───────                                 ─────
Layer 1: explanations                   Layer 1: explanations
Layer 2: visuals                        Layer 2: visuals
Layer 3: check_ins                      Layer 3: check_ins
Layer 4: practice_bank                  Layer 4: baatcheet_dialogue   ← NEW
Layer 5: audio_review                   Layer 5: baatcheet_visuals    ← NEW
Layer 6: audio_synthesis                Layer 6: practice_bank
                                        Layer 7: audio_review         (extended for dialogues)
                                        Layer 8: audio_synthesis      (extended for dialogues)
```

**Decision: sequential layers, not parallel branch.** PRD §6 frames 5b/5c as a "parallel branch alongside variant A enrichment." In the existing orchestrator, that requires either a per-target lock channel (`ChapterJobService.acquire_lock` is currently keyed `(chapter_id, guideline_id)` and serializes the whole topic) or breaking the single-row contract. Both are scope-creep beyond V1. Sequential adds ~30–60s wall-clock per topic for cold ingestion — acceptable since ingestion is offline, parallelism across topics already exists in `run_chapter_pipeline_all`, and the PRD's <30s success criterion is achievable in V2 by adding a `lock_channel` column. Documented as a follow-up below (§11).

### 2.2 New backend modules

| Path | Purpose | Mirrors |
|---|---|---|
| `llm-backend/shared/repositories/dialogue_repository.py` | CRUD + Pydantic validation for `topic_dialogues` | `shared/repositories/explanation_repository.py` |
| `llm-backend/book_ingestion_v2/services/baatcheet_dialogue_generator_service.py` | Stage 5b: dialogue generation + review-refine | `services/explanation_generator_service.py` |
| `llm-backend/book_ingestion_v2/services/baatcheet_visual_enrichment_service.py` | Stage 5c: PixiJS for dialogue visual cards | `services/animation_enrichment_service.py` |
| `llm-backend/book_ingestion_v2/prompts/baatcheet_dialogue_generation*.txt` | LLM prompts for stage 5b | `prompts/explanation_generation*.txt` |
| `llm-backend/book_ingestion_v2/prompts/baatcheet_dialogue_review_refine*.txt` | LLM prompts for review-refine pass | `prompts/explanation_review_refine*.txt` |
| `llm-backend/book_ingestion_v2/prompts/baatcheet_visual_intent.txt` | Prompt for converting dialogue visual slot → PixiJS code | `prompts/visual_code_generation.txt` |

### 2.3 New frontend modules

| Path | Purpose | Mirrors |
|---|---|---|
| `llm-frontend/src/pages/TeachMeSubChooser.tsx` | New sub-step page between ModeSelectPage and ChatSession when mode is teach_me | inline within ModeSelection.tsx pattern |
| `llm-frontend/src/components/baatcheet/SpeakerAvatar.tsx` | Single-speaker avatar with cross-fade + speaking-indicator pulse | `Virtual Teacher` legacy avatar |
| `llm-frontend/public/avatars/tutor.svg` | V1 stylized placeholder for tutor (Mr. Verma) | new |
| `llm-frontend/public/avatars/peer.svg` | V1 stylized placeholder for peer (Meera) | new |
| `llm-frontend/src/hooks/usePersonalizedAudio.ts` | Pre-fetch runtime TTS for `includes_student_name` cards | uses existing `synthesizeSpeech` + `audioController` |

### 2.4 Modified modules

| Path | Change |
|---|---|
| `llm-backend/shared/models/entities.py` | Add `TopicDialogue` ORM class |
| `llm-backend/db.py` | Register new table seed; new `_apply_topic_dialogues_table` helper (same pattern as `_apply_topic_explanations_table`); seed LLM config row for `baatcheet_dialogue_generator` |
| `llm-backend/book_ingestion_v2/constants.py` | Add `V2JobType.BAATCHEET_DIALOGUE_GENERATION`, `V2JobType.BAATCHEET_VISUAL_ENRICHMENT` |
| `llm-backend/book_ingestion_v2/models/schemas.py` | Extend `StageId` Literal; add per-stage status response shapes; add `TopicDialogueDetailResponse` |
| `llm-backend/book_ingestion_v2/services/stage_launchers.py` | Add `launch_baatcheet_dialogue_job`, `launch_baatcheet_visual_job`, extend `LAUNCHER_BY_STAGE` |
| `llm-backend/book_ingestion_v2/services/topic_pipeline_orchestrator.py` | Extend `PIPELINE_LAYERS` and `QUALITY_ROUNDS` |
| `llm-backend/book_ingestion_v2/services/topic_pipeline_status_service.py` | Add status computation for the two new stages |
| `llm-backend/book_ingestion_v2/services/audio_generation_service.py` | Per-card `speaker` voice routing; new `generate_for_topic_dialogue`; respect `includes_student_name` |
| `llm-backend/book_ingestion_v2/services/audio_text_review_service.py` | Extend to also review dialogue audio text |
| `llm-backend/book_ingestion_v2/api/sync_routes.py` | Add 2 new POST routes; add `_run_baatcheet_dialogue_generation`, `_run_baatcheet_visual_enrichment`; extend `_run_audio_generation` and `_run_audio_text_review` to also process dialogues |
| `llm-backend/tutor/services/session_service.py` | Branch on `mode == "baatcheet"`; load from `DialogueRepository`; populate new `dialogue_phase` state; implement server-side `last_card_idx` for both teach_me and baatcheet |
| `llm-backend/tutor/api/sessions.py` | Accept `mode == "baatcheet"`; new `POST /sessions/{id}/card-progress` endpoint to persist last viewed card; extend `GET /sessions/resumable` to surface baatcheet sessions |
| `llm-backend/tutor/models/session_state.py` | Add `DialoguePhaseState` next to `CardPhaseState`; add `last_card_idx` field |
| `llm-frontend/src/api.ts` | Types for `DialogueCard`, `DialoguePhaseDTO`, `mode: 'baatcheet'`; new `postCardProgress` client function |
| `llm-frontend/src/pages/ModeSelectPage.tsx` | Route teach_me click to TeachMeSubChooser instead of `createSession` directly |
| `llm-frontend/src/pages/ChatSession.tsx` | Add `'dialogue_phase'` sessionPhase; render `SpeakerAvatar`; integrate `usePersonalizedAudio`; replace localStorage `slide-pos-${sessionId}` with server-side `postCardProgress` (keep localStorage as fallback) |
| `llm-frontend/src/features/admin/api/adminApiV2.ts` | Add `generateBaatcheetDialogue`, `generateBaatcheetVisuals`, extend `StageId` Literal |
| `llm-frontend/src/features/admin/pages/TopicPipelineDashboard.tsx` | Extend `STAGE_ORDER`; wire new stage actions in `handleStageAction` |
| `llm-frontend/src/components/ModeSelection.tsx` | (no change — sub-choice happens after mode selection) |

---

## 3. Database Changes

### 3.1 New table

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `topic_dialogues` | Single dialogue per guideline (Baatcheet content) | `id` (UUID PK), `guideline_id` (FK→teaching_guidelines, CASCADE), `cards_json` (JSONB), `generator_model` (VARCHAR), `source_variant_key` (VARCHAR, default 'A'), `created_at`, `updated_at` |

**Decision: one row per guideline, no `variant_key`.** PRD §5 explicitly excludes multiple dialogue variants per topic. The unique constraint is therefore on `guideline_id` alone — simpler than the explanation pattern. We keep `source_variant_key` as a column (not a unique key) so future expansion to "dialogue derived from variant B" is possible without a schema migration.

### 3.2 Modified tables

| Table | Change | Details |
|-------|--------|---------|
| `topic_explanations` | None | Schema unchanged. Stage 10 voice routing uses card-level `speaker` flag in JSONB (no schema change). |
| `sessions` | None | `mode` column already exists; values just get a new string `"baatcheet"`. Server-side `last_card_idx` lives inside `state_json` (same pattern as `card_phase`). |
| `chapter_processing_jobs` | None | New `V2JobType` values are stored in the existing `job_type` VARCHAR column. The `idx_chapter_active_topic_job` partial unique index already enforces per-topic serialization. |

### 3.3 Relationships

```
teaching_guidelines ──1:N──► topic_explanations  (existing)
teaching_guidelines ──1:1──► topic_dialogues     (NEW; single row per guideline)
```

Cascade behavior: deleting a `TeachingGuideline` deletes its `TopicDialogue` (PRD §FR-54). Implemented via `ondelete="CASCADE"` on the FK, matching `topic_explanations`.

### 3.4 Migration plan

Add a new helper in `db.py` following the established pattern.

```python
def _apply_topic_dialogues_table(db_manager):
    """Verify topic_dialogues table exists (created by Base.metadata.create_all)
    and seed any required indexes. Idempotent."""
    inspector = inspect(db_manager.engine)
    if "topic_dialogues" not in inspector.get_table_names():
        # create_all should have already made it; defensive log otherwise
        logger.warning("topic_dialogues table missing after create_all")
        return
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("topic_dialogues")}
    with db_manager.engine.connect() as conn:
        if "idx_topic_dialogues_guideline" not in existing_indexes:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_dialogues_guideline "
                "ON topic_dialogues(guideline_id)"
            ))
        conn.commit()
```

Hook it into `migrate()` immediately after `_apply_topic_explanations_table`. Also seed an LLM config row for the new component (`baatcheet_dialogue_generator`, provider `claude_code`, model `claude-opus-4-7`) inside `_seed_llm_config()` — same shape as the existing `check_in_enrichment` and `practice_bank_generator` rows in the seed. No data backfill is required (new table, no historical rows).

---

## 4. Backend Changes

### 4.1 Models layer

#### `llm-backend/shared/models/entities.py`

Add the ORM model immediately after `TopicExplanation`:

```python
class TopicDialogue(Base):
    """Pre-computed Baatcheet dialogue for a teaching guideline.

    One row per guideline (no variant key). Cascade-deleted when the parent
    guideline is deleted (e.g., during re-sync).
    """
    __tablename__ = "topic_dialogues"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    guideline_id = Column(
        String,
        ForeignKey("teaching_guidelines.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    cards_json = Column(JSONB, nullable=False)
    generator_model = Column(String, nullable=True)
    source_variant_key = Column(String, nullable=False, default="A")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

#### Pydantic card schema

Add to `llm-backend/shared/repositories/dialogue_repository.py` (mirrors `explanation_repository.py`). Reuses `ExplanationLine`, `CardVisualExplanation`, `CheckInActivity` from `explanation_repository.py` to avoid duplication.

```python
from typing import Literal, Optional
from pydantic import BaseModel
from shared.repositories.explanation_repository import (
    ExplanationLine, CardVisualExplanation, CheckInActivity,
)

DialogueCardType = Literal[
    "welcome", "tutor_turn", "peer_turn", "visual", "check_in", "summary",
]
SpeakerKey = Literal["tutor", "peer"]

class DialogueCard(BaseModel):
    """Validated schema for cards stored in topic_dialogues.cards_json."""
    card_id: Optional[str] = None              # Stable UUID, assigned at generation
    card_idx: int                               # 1-based
    card_type: DialogueCardType
    speaker: Optional[SpeakerKey] = None        # None for welcome/summary/visual
    title: Optional[str] = None
    lines: list[ExplanationLine] = []           # display + audio pairs (reused)
    audio_url: Optional[str] = None             # Card-level audio (composed from lines)
    includes_student_name: bool = False         # Skip pre-render; runtime TTS
    visual: Optional[str] = None                # ASCII fallback (reused)
    visual_explanation: Optional[CardVisualExplanation] = None  # Stage 5c output
    check_in: Optional[CheckInActivity] = None  # For card_type="check_in"
```

**Decision: reuse `ExplanationLine` and `CheckInActivity` directly.** They already model what a dialogue turn needs (display+audio split, 11 check-in types). Inventing parallel `DialogueLine` / `DialogueCheckInActivity` types would diverge over time. The only Baatcheet-specific fields are `speaker` and `includes_student_name` — both live on the card, not the line.

### 4.2 Repository layer

#### `llm-backend/shared/repositories/dialogue_repository.py`

```python
class DialogueRepository:
    """CRUD for topic_dialogues. Mirrors ExplanationRepository.

    Lives in shared/ so both ingestion (book_ingestion_v2) and tutor runtime
    can read it without cross-module imports.
    """

    def __init__(self, db: DBSession):
        self.db = db

    def get_by_guideline_id(self, guideline_id: str) -> Optional[TopicDialogue]:
        return (
            self.db.query(TopicDialogue)
            .filter(TopicDialogue.guideline_id == guideline_id)
            .first()
        )

    def upsert(
        self,
        guideline_id: str,
        cards_json: list[dict],
        generator_model: str,
        source_variant_key: str = "A",
    ) -> TopicDialogue:
        """Delete-then-insert. Same pattern as ExplanationRepository.upsert."""
        self.db.query(TopicDialogue).filter(
            TopicDialogue.guideline_id == guideline_id
        ).delete()
        d = TopicDialogue(
            id=str(uuid4()),
            guideline_id=guideline_id,
            cards_json=cards_json,
            generator_model=generator_model,
            source_variant_key=source_variant_key,
        )
        self.db.add(d)
        self.db.commit()
        self.db.refresh(d)
        return d

    def delete_by_guideline_id(self, guideline_id: str) -> int:
        count = (
            self.db.query(TopicDialogue)
            .filter(TopicDialogue.guideline_id == guideline_id)
            .delete()
        )
        self.db.commit()
        return count

    def has_dialogue(self, guideline_id: str) -> bool:
        return (
            self.db.query(TopicDialogue.id)
            .filter(TopicDialogue.guideline_id == guideline_id)
            .first()
        ) is not None

    def is_stale_vs_variant_a(self, guideline_id: str) -> bool:
        """True iff variant A explanation was updated more recently than this dialogue.
        Used for the admin "stale dialogue" warning (PRD §FR-46).
        """
        dialogue = self.get_by_guideline_id(guideline_id)
        if not dialogue:
            return False
        from shared.models.entities import TopicExplanation
        variant_a = (
            self.db.query(TopicExplanation)
            .filter(
                TopicExplanation.guideline_id == guideline_id,
                TopicExplanation.variant_key == "A",
            )
            .first()
        )
        if not variant_a:
            return False
        # variant A's updated_at is implicit via created_at since upsert is delete+insert
        return variant_a.created_at > dialogue.updated_at

    @staticmethod
    def parse_cards(cards_json: list[dict]) -> list[DialogueCard]:
        return [DialogueCard(**c) for c in cards_json]
```

### 4.3 Stage 5b: Dialogue Generation Service

#### `llm-backend/book_ingestion_v2/services/baatcheet_dialogue_generator_service.py`

Mirrors `ExplanationGeneratorService` line-for-line. Key shape:

```python
class BaatcheetDialogueGeneratorService:
    """Generate the Baatcheet dialogue for a teaching guideline.

    Pipeline: read variant A + guideline → generate → review-refine (N rounds)
    → validate → store in topic_dialogues. Mirrors ExplanationGeneratorService.
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

    def generate_for_guideline(
        self,
        guideline: TeachingGuideline,
        review_rounds: int = 1,
        stage_collector: list | None = None,
        force: bool = False,
    ) -> Optional[TopicDialogue]:
        # Skip if dialogue exists and not force (retry semantics — same as Explain)
        if not force and self.repo.has_dialogue(guideline.id):
            return None

        # Gather inputs
        variant_a = self.exp_repo.get_variant(guideline.id, "A")
        if not variant_a:
            raise ValueError(f"Variant A not found for {guideline.id}; run stage 5 first")

        guideline_meta = self.guideline_repo._parse_metadata(guideline.metadata_json)
        misconceptions = guideline_meta.common_misconceptions if guideline_meta else []

        # Generate → refine
        cards = self._generate_cards(guideline, variant_a.cards_json, misconceptions)
        for round_num in range(review_rounds):
            cards = self._review_and_refine(cards, guideline, variant_a.cards_json)

        # Validate
        if not self._validate_cards(cards):
            return None

        cards_dicts = [c.model_dump() for c in cards]
        # Assign card_ids for stable audio S3 keys (mirrors check-in enrichment)
        for c in cards_dicts:
            c.setdefault("card_id", str(uuid4()))

        return self.repo.upsert(
            guideline_id=guideline.id,
            cards_json=cards_dicts,
            generator_model=self.llm.model_id,
        )
```

#### Pydantic LLM-output schema

```python
class DialogueLineOutput(BaseModel):
    display: str
    audio: str  # TTS-friendly, may contain `{student_name}` placeholder

class DialogueCardOutput(BaseModel):
    card_idx: int
    card_type: DialogueCardType
    speaker: Optional[SpeakerKey] = None
    title: Optional[str] = None
    lines: list[DialogueLineOutput] = []
    includes_student_name: bool = False
    visual_intent: Optional[str] = None  # NL description for stage 5c (only on card_type="visual")
    check_in: Optional[CheckInActivity] = None  # For card_type="check_in"

class DialogueGenerationOutput(BaseModel):
    cards: list[DialogueCardOutput]
```

#### Validators (PRD §6 + §FR-11)

```python
def _validate_cards(cards: list[DialogueCardOutput]) -> bool:
    if not (13 <= len(cards) <= 35):
        return False
    if cards[0].card_type != "welcome":
        return False
    if cards[-1].card_type != "summary":
        return False
    # No back-to-back check-ins (≥4 cards apart)
    last_check_in = -10
    for i, c in enumerate(cards):
        if c.card_type == "check_in":
            if i - last_check_in < 4:
                return False
            last_check_in = i
    # tutor_turn / peer_turn must have ≥1 line
    for c in cards:
        if c.card_type in ("tutor_turn", "peer_turn") and not c.lines:
            return False
    # visual cards must have non-empty visual_intent
    for c in cards:
        if c.card_type == "visual" and not (c.visual_intent or "").strip():
            return False
    return True
```

If validation fails → trigger another review-refine round (same retry pattern as `_generate_variant` in `ExplanationGeneratorService`).

#### Prompt structure

`prompts/baatcheet_dialogue_generation_system.txt` — static instructions + JSON schema (same `--append-system-prompt-file` pattern as Explain). Contents:

- Persona: Mr. Verma (tutor) and Meera (peer) — describe both, age cue per student grade.
- Role mix for Meera: ask / answer correctly / answer incorrectly / react (FR-7).
- Easy-English rules (stricter for Meera per FR-8).
- Card structure: welcome first, summary last, ~25–30 cards (cap 35), check-ins every 6–8 cards.
- Welcome card template (FR-14).
- `{student_name}` placeholder usage rules (FR-17–20): only on tutor turns that address the student directly; flag with `includes_student_name: true`.
- Misconception coverage as soft material (FR-49–50).
- Output JSON schema.

`prompts/baatcheet_dialogue_generation.txt` — dynamic input template:

```
TOPIC: {topic_name}
SUBJECT: {subject}, Grade {grade}
TEACHING GUIDELINE:
{guideline_text}

VARIANT A EXPLANATION (covers the same content; use its ideas, not its prose):
{variant_a_cards_json}

COMMON MISCONCEPTIONS (soft — Meera MAY voice some via "answer incorrectly" turns):
{misconceptions_list}

PRIOR TOPICS CONTEXT:
{prior_topics_section}
```

`prompts/baatcheet_dialogue_review_refine_system.txt` and `_review_refine.txt` — mirror the Explain review-refine prompt structure.

**Decision: Claude Code provider for stage 5b.** The seeds in `db.py:70-78` already use `claude_code` for `check_in_enrichment` and `practice_bank_generator`. Dialogue generation is similar in shape (long-form structured pedagogy, benefits from Opus-level reasoning) — same provider keeps the LLM stack consistent. Configurable via the `llm_configs` table at runtime.

### 4.4 Stage 5c: Baatcheet Visual Enrichment Service

#### `llm-backend/book_ingestion_v2/services/baatcheet_visual_enrichment_service.py`

Far simpler than `AnimationEnrichmentService` because the dialogue generator already decided which cards are visuals (`card_type == "visual"`) and supplied a `visual_intent` description. Stage 5c just converts intent → PixiJS code.

```python
class BaatcheetVisualEnrichmentService:
    """Stage 5c: fill visual_explanation slots in topic_dialogues using PixiCodeGenerator."""

    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.repo = DialogueRepository(db)
        self.pixi_gen = PixiCodeGenerator(llm_service)

    async def enrich_guideline(
        self, guideline_id: str, force: bool = False,
    ) -> Optional[TopicDialogue]:
        dialogue = self.repo.get_by_guideline_id(guideline_id)
        if not dialogue:
            return None

        cards = list(dialogue.cards_json)  # mutable copy
        modified = False

        for card in cards:
            if card.get("card_type") != "visual":
                continue
            if card.get("visual_explanation") and not force:
                continue
            intent = card.get("visual_intent") or card.get("title") or ""
            if not intent.strip():
                continue
            pixi_code = await self.pixi_gen.generate(intent, output_type="image")
            if not pixi_code:
                continue
            card["visual_explanation"] = {
                "output_type": "static_visual",
                "title": card.get("title"),
                "visual_summary": intent,
                "pixi_code": pixi_code,
            }
            modified = True

        if modified:
            return self.repo.upsert(
                guideline_id=guideline_id,
                cards_json=cards,
                generator_model=dialogue.generator_model,
                source_variant_key=dialogue.source_variant_key,
            )
        return dialogue
```

**Decision: no separate review-refine pass for visuals.** `AnimationEnrichmentService` has visual code review for variant A because variant A visuals are core to the explanation. Baatcheet visuals are accents (PRD §15 punts illustrated avatars to V2; visual cards are the only non-text canvas). Match the simpler check-in-style "generate once, regenerate if needed" pattern. If quality is insufficient post-launch, copy the review-refine round structure from `AnimationEnrichmentService`.

### 4.5 Stage 10: Audio Synthesis (refactored)

#### `llm-backend/book_ingestion_v2/services/audio_generation_service.py`

Three changes — all backwards-compatible (existing variant A audio behavior is unchanged when no `speaker` flag is present).

**(a) Voice routing helper.**

```python
# Module-level constants — Meera's voice TBD during impl after audition (PRD §13).
TUTOR_VOICE = ("hi-IN", "hi-IN-Chirp3-HD-Kore")        # existing
PEER_VOICE  = ("hi-IN", "hi-IN-Chirp3-HD-Aoede")        # placeholder; pick during impl

def _voice_for_speaker(speaker: Optional[str], language: str) -> tuple[str, str]:
    """Return (language_code, voice_name) for a given speaker. Defaults to the
    language-mapped tutor voice when speaker is missing — this preserves variant A
    behavior for cards that don't carry a speaker field."""
    if speaker == "peer":
        return PEER_VOICE
    return VOICE_MAP.get(language, VOICE_MAP["en"])
```

**(b) Synthesize per-call rather than per-instance.**

Refactor `_synthesize` to accept a voice parameter so the existing `self.voice` instance attribute can fall through for variant A but be overridden for dialogue cards.

```python
def _synthesize(self, text: str, voice: Optional[texttospeech.VoiceSelectionParams] = None) -> bytes:
    response = self.tts_client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=voice or self.voice,
        audio_config=self.audio_config,
    )
    return response.audio_content

def _synth_and_upload(
    self, text: str, s3_key: str,
    voice: Optional[texttospeech.VoiceSelectionParams] = None,
) -> str:
    mp3_bytes = self._synthesize(text, voice=voice)
    self.s3.upload_bytes(mp3_bytes, s3_key, content_type="audio/mpeg")
    return self._s3_url(s3_key)
```

**(c) New `generate_for_topic_dialogue(dialogue)` method.**

```python
def generate_for_topic_dialogue(
    self, dialogue: TopicDialogue, *, dry_run: bool = False,
) -> Optional[list[dict]]:
    """Generate audio for a TopicDialogue record.

    - Skips lines on cards with includes_student_name=True (frontend handles runtime TTS).
    - Routes voice via card.speaker.
    - S3 keys: audio/{guideline_id}/dialogue/{card_id}/{line_idx}.mp3
              audio/{guideline_id}/dialogue/{card_id}/check_in/{field}.mp3
    """
    cards = dialogue.cards_json
    if not cards:
        return None

    guideline_id = dialogue.guideline_id
    for card in cards:
        if card.get("includes_student_name"):
            continue  # Runtime TTS — never pre-render.

        speaker = card.get("speaker")
        lang_code, voice_name = _voice_for_speaker(speaker, self.language)
        voice = texttospeech.VoiceSelectionParams(language_code=lang_code, name=voice_name)
        card_id = card.get("card_id")
        if not card_id:
            logger.warning(f"Dialogue card at idx {card.get('card_idx')} missing card_id; skipping audio")
            continue

        # Explanation-shaped lines (works for tutor_turn, peer_turn, welcome, summary, visual)
        for line_idx, line in enumerate(card.get("lines") or []):
            if line.get("audio_url"):
                continue
            text = (line.get("audio") or "").strip()
            if not text or "{student_name}" in text:
                # safety belt: text-level placeholder also defers to runtime
                continue
            s3_key = f"audio/{guideline_id}/dialogue/{card_id}/{line_idx}.mp3"
            try:
                line["audio_url"] = self._synth_and_upload(text, s3_key, voice=voice)
            except Exception as e:
                logger.error(f"Dialogue TTS failed for {guideline_id}/{card_id}/line{line_idx}: {e}")

        # Check-in fields (reuses _check_in_fields_for; tutor voice always)
        check_in = card.get("check_in")
        if check_in and card.get("card_type") == "check_in":
            tutor_voice = texttospeech.VoiceSelectionParams(
                language_code=TUTOR_VOICE[0], name=TUTOR_VOICE[1],
            )
            for text_field, key_suffix, url_field in _check_in_fields_for(check_in):
                if check_in.get(url_field):
                    continue
                text = (check_in.get(text_field) or "").strip()
                if not text:
                    continue
                s3_key = f"audio/{guideline_id}/dialogue/{card_id}/check_in/{key_suffix}.mp3"
                try:
                    check_in[url_field] = self._synth_and_upload(text, s3_key, voice=tutor_voice)
                except Exception as e:
                    logger.error(f"Dialogue check-in TTS failed for {guideline_id}/{card_id}/{key_suffix}: {e}")

    return cards
```

**Decision: do NOT change variant A's S3 key convention.** Existing keys (`audio/{guideline_id}/{variant_key}/...`) keep working. Dialogue uses a parallel namespace `audio/{guideline_id}/dialogue/{card_id}/...`. This is what makes the change backwards-compatible — any pre-existing audio file URL still resolves.

**Decision: `card_id` is mandatory for dialogue cards.** Stage 5b assigns one per card during `upsert`. Variant A explanations only enforce `card_id` on check-in cards (because re-insertion at a new `card_idx` would otherwise serve stale audio). Dialogue cards use `card_id` everywhere because the dialogue may be regenerated; positional keys like `card_idx` would race during regeneration.

#### `_run_audio_generation` extension in `sync_routes.py`

After the existing `for explanation in explanations:` loop, add a parallel loop for dialogues:

```python
# Existing variant A loop unchanged...

# NEW: Dialogues for the same guideline(s)
from shared.models.entities import TopicDialogue
for guideline in guidelines:
    dialogue = db.query(TopicDialogue).filter(
        TopicDialogue.guideline_id == guideline.id
    ).first()
    if not dialogue:
        continue
    try:
        updated_cards = audio_svc.generate_for_topic_dialogue(dialogue)
        if updated_cards is not None:
            dialogue.cards_json = updated_cards
            attributes.flag_modified(dialogue, "cards_json")
            db.commit()
    except Exception as e:
        logger.error(f"Dialogue audio failed for guideline={guideline.id}: {e}")
        db.rollback()
        topic_had_failure = True
```

`_run_audio_text_review` is extended in the same shape — review pass also walks `topic_dialogues`.

### 4.6 Stage launchers

#### `llm-backend/book_ingestion_v2/services/stage_launchers.py`

```python
def launch_baatcheet_dialogue_job(
    db: Session, *, book_id: str, chapter_id: str, guideline_id: str,
    force: bool = False, review_rounds: int = 1, total_items: int = 1,
) -> str:
    from book_ingestion_v2.api.sync_routes import _run_baatcheet_dialogue_generation
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id, chapter_id=chapter_id, guideline_id=guideline_id,
        job_type=V2JobType.BAATCHEET_DIALOGUE_GENERATION.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_baatcheet_dialogue_generation, job_id, book_id,
        chapter_id, guideline_id, str(force), str(review_rounds),
    )
    return job_id


def launch_baatcheet_visual_job(
    db: Session, *, book_id: str, chapter_id: str, guideline_id: str,
    force: bool = False, total_items: int = 1,
) -> str:
    from book_ingestion_v2.api.sync_routes import _run_baatcheet_visual_enrichment
    from book_ingestion_v2.api.processing_routes import run_in_background_v2

    job_id = ChapterJobService(db).acquire_lock(
        book_id=book_id, chapter_id=chapter_id, guideline_id=guideline_id,
        job_type=V2JobType.BAATCHEET_VISUAL_ENRICHMENT.value,
        total_items=total_items,
    )
    run_in_background_v2(
        _run_baatcheet_visual_enrichment, job_id, book_id,
        chapter_id, guideline_id, str(force),
    )
    return job_id


LAUNCHER_BY_STAGE = {
    "explanations": launch_explanation_job,
    "visuals": launch_visual_job,
    "check_ins": launch_check_in_job,
    "baatcheet_dialogue": launch_baatcheet_dialogue_job,    # NEW
    "baatcheet_visuals": launch_baatcheet_visual_job,        # NEW
    "practice_bank": launch_practice_bank_job,
    "audio_review": launch_audio_review_job,
    "audio_synthesis": launch_audio_synthesis_job,
}
```

### 4.7 Orchestrator extension

#### `llm-backend/book_ingestion_v2/services/topic_pipeline_orchestrator.py`

```python
PIPELINE_LAYERS: list[list[StageId]] = [
    ["explanations"],
    ["visuals"],
    ["check_ins"],
    ["baatcheet_dialogue"],  # NEW
    ["baatcheet_visuals"],   # NEW
    ["practice_bank"],
    ["audio_review"],
    ["audio_synthesis"],
]

QUALITY_ROUNDS: dict[QualityLevel, dict[StageId, int]] = {
    "fast":      {"explanations": 0, "visuals": 0, "check_ins": 0, "practice_bank": 0,
                  "baatcheet_dialogue": 0},
    "balanced":  {"explanations": 2, "visuals": 1, "check_ins": 1, "practice_bank": 2,
                  "baatcheet_dialogue": 1},
    "thorough":  {"explanations": 3, "visuals": 2, "check_ins": 2, "practice_bank": 3,
                  "baatcheet_dialogue": 2},
}
```

Update `_launcher_kwargs` to include the new stages:

```python
if stage in ("explanations", "visuals", "check_ins", "practice_bank", "baatcheet_dialogue"):
    kwargs["review_rounds"] = self.rounds.get(stage, 1)
    kwargs["force"] = self.force
elif stage == "baatcheet_visuals":
    kwargs["force"] = self.force
elif stage == "audio_review":
    kwargs["language"] = None
```

### 4.8 API layer

#### `llm-backend/book_ingestion_v2/api/sync_routes.py`

**New routes** (mirror the existing visuals/check_ins/practice_bank route shape exactly):

```python
@router.post("/generate-baatcheet-dialogue", response_model=ProcessingJobResponse, status_code=202)
def generate_baatcheet_dialogue_route(
    book_id: str,
    guideline_id: str = Query(...),
    force: bool = Query(False),
    review_rounds: int = Query(1),
    db: Session = Depends(get_db),
):
    _resolve_single_guideline(db, book_id=book_id, guideline_id=guideline_id)
    chapter_id = _get_chapter_id_for_guideline(db, guideline_id)
    job_id = launch_baatcheet_dialogue_job(
        db, book_id=book_id, chapter_id=chapter_id, guideline_id=guideline_id,
        force=force, review_rounds=review_rounds,
    )
    return ProcessingJobResponse(job_id=job_id, status="started")


@router.post("/generate-baatcheet-visuals", response_model=ProcessingJobResponse, status_code=202)
def generate_baatcheet_visuals_route(
    book_id: str,
    guideline_id: str = Query(...),
    force: bool = Query(False),
    db: Session = Depends(get_db),
):
    _resolve_single_guideline(db, book_id=book_id, guideline_id=guideline_id)
    chapter_id = _get_chapter_id_for_guideline(db, guideline_id)
    job_id = launch_baatcheet_visual_job(
        db, book_id=book_id, chapter_id=chapter_id, guideline_id=guideline_id,
        force=force,
    )
    return ProcessingJobResponse(job_id=job_id, status="started")
```

**New background tasks** (mirror `_run_explanation_generation` / `_run_visual_enrichment`):

```python
def _run_baatcheet_dialogue_generation(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str, force_str: str = "False", review_rounds_str: str = "1",
):
    job_service = ChapterJobService(db)
    try:
        force = force_str == "True"
        review_rounds = int(review_rounds_str)

        guideline = db.query(TeachingGuideline).filter(
            TeachingGuideline.id == guideline_id
        ).first()
        if not guideline:
            job_service.release_lock(job_id, status="failed",
                                     error=f"Guideline {guideline_id} not found")
            return

        llm_config = LLMConfigService(db).get_config("baatcheet_dialogue_generator")
        llm_service = LLMService(
            api_key=get_settings().openai_api_key,
            provider=llm_config["provider"],
            model_id=llm_config["model_id"],
        )
        svc = BaatcheetDialogueGeneratorService(db, llm_service)

        if force:
            DialogueRepository(db).delete_by_guideline_id(guideline_id)

        result = svc.generate_for_guideline(
            guideline, review_rounds=review_rounds, force=force,
        )
        status = "completed" if result else "completed_with_errors"
        job_service.release_lock(job_id, status=status)
    except Exception as e:
        logger.exception("Baatcheet dialogue generation failed")
        job_service.release_lock(job_id, status="failed", error=str(e))


def _run_baatcheet_visual_enrichment(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str, force_str: str = "False",
):
    job_service = ChapterJobService(db)
    try:
        force = force_str == "True"
        llm_config = LLMConfigService(db).get_config("animation_enrichment")
        llm_service = LLMService(
            api_key=get_settings().openai_api_key,
            provider=llm_config["provider"],
            model_id=llm_config["model_id"],
        )
        svc = BaatcheetVisualEnrichmentService(db, llm_service)
        import asyncio
        asyncio.run(svc.enrich_guideline(guideline_id, force=force))
        job_service.release_lock(job_id, status="completed")
    except Exception as e:
        logger.exception("Baatcheet visual enrichment failed")
        job_service.release_lock(job_id, status="failed", error=str(e))
```

#### `llm-backend/book_ingestion_v2/services/topic_pipeline_status_service.py`

Extend `get_pipeline_status` to compute states for the two new stages. State rules:
- **baatcheet_dialogue**: `done` if `topic_dialogues` row exists; `warning` if exists but `is_stale_vs_variant_a()`; `blocked` if variant A is missing; `ready` otherwise.
- **baatcheet_visuals**: `done` if every `card_type == "visual"` card in the dialogue has `visual_explanation`; `blocked` if dialogue is missing; `ready` otherwise.
- Use last-job lookup against `V2JobType.BAATCHEET_DIALOGUE_GENERATION` / `BAATCHEET_VISUAL_ENRICHMENT` exactly as the other stages do.

### 4.9 Tutor runtime

#### `llm-backend/tutor/services/session_service.py`

In `create_new_session`, branch on `mode == "baatcheet"` immediately after the `mode == "teach_me"` block. Pattern is identical to the variant-A path but loads from `DialogueRepository` and constructs a `DialoguePhaseState`.

```python
if mode == "baatcheet":
    dialogue_repo = DialogueRepository(self.db)
    dialogue = dialogue_repo.get_by_guideline_id(request.goal.guideline_id)
    if not dialogue:
        raise VariantNotFoundError(
            f"No Baatcheet dialogue found for guideline {request.goal.guideline_id}",
        )

    cards = dialogue.cards_json
    session.dialogue_phase = DialoguePhaseState(
        guideline_id=request.goal.guideline_id,
        active=True,
        current_card_idx=0,
        total_cards=len(cards),
    )

    first_card = cards[0] if cards else {}
    first_turn = {
        "message": first_card.get("content") or _join_lines(first_card.get("lines")),
        "audio_text": first_card.get("audio_text") or "",
        "hints": [],
        "step_idx": 0,
        "total_steps": 0,
        "dialogue_cards": cards,
        "session_phase": "dialogue_phase",
        "dialogue_phase_state": {
            "current_card_idx": 0,
            "total_cards": len(cards),
        },
    }
```

**Resume-from-last-card (PRD §FR-33).** `DialoguePhaseState` and `CardPhaseState` both carry `current_card_idx` already (variant A populates it during gameplay). Currently the **frontend** stores `slide-pos-${sessionId}` in localStorage but the server's `card_phase.current_card_idx` is only updated when student-server interactions cause a phase event. We close that gap by:

1. New API: `POST /sessions/{session_id}/card-progress` with body `{"card_idx": int}`. Frontend calls it on every advance. Backend updates `state.card_phase.current_card_idx` (for teach_me) or `state.dialogue_phase.current_card_idx` (for baatcheet) and persists.
2. On resume — `GET /sessions/resumable` already returns paused sessions; `SessionService.resume_session` reads `state.card_phase.current_card_idx` (or dialogue) and the frontend jumps `currentSlideIdx` to it.
3. `SessionService.create_new_session` for `mode=baatcheet` should also handle the resume path: if a paused session exists for this `(user_id, guideline_id, "baatcheet")`, return it with the saved `current_card_idx`. The unique index `idx_sessions_one_paused_per_user_guideline` already keys on `(user_id, guideline_id, mode)` so baatcheet sessions don't collide with teach_me sessions for the same topic.

#### `llm-backend/tutor/models/session_state.py`

Add `DialoguePhaseState` next to `CardPhaseState`:

```python
class DialoguePhaseState(BaseModel):
    guideline_id: str
    active: bool = False
    current_card_idx: int = 0
    total_cards: int = 0
    last_visited_at: Optional[datetime] = None
```

Add to `SessionState`: `dialogue_phase: Optional[DialoguePhaseState] = None`.

**Decision: separate `DialoguePhaseState` rather than reusing `CardPhaseState`.** They share three fields (`guideline_id`, `current_card_idx`, `total_cards`) but `CardPhaseState` has variant-specific fields (`current_variant_key`, `variants_shown`, `available_variant_keys`, `remedial_cards`) that don't apply to Baatcheet. Forcing a single struct would either bloat both modes or require nullable variant fields that are easy to misuse. Cost of duplication: ~20 lines.

#### `llm-backend/tutor/api/sessions.py`

- Extend the `mode` validation in `POST /sessions` to accept `"baatcheet"`.
- Add new route:

```python
@router.post("/sessions/{session_id}/card-progress", status_code=204)
def update_card_progress(
    session_id: str,
    payload: CardProgressRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    SessionService(db).record_card_progress(
        session_id, payload.card_idx, user_id=current_user["id"],
    )
```

- Extend `GET /sessions/resumable?guideline_id=...` to optionally accept `mode`. Default behavior (no mode filter) returns the paused session for the guideline regardless of mode — frontend will use this on the sub-chooser to surface the correct resume CTA.

### 4.10 Configuration / LLM config seed

Add to `db.py` `_seed_llm_config()` (only seeded when llm_configs table is empty):

```python
{
    "component": "baatcheet_dialogue_generator",
    "provider": "claude_code",
    "model_id": "claude-opus-4-7",
    "fallback_provider": "openai",
    "fallback_model_id": "gpt-5.2",
}
```

No new env vars. Google Cloud TTS API key already exists for the existing Chirp 3 HD Kore voice; the Meera voice uses the same key.

---

## 5. Frontend Changes

### 5.1 New pages and components

#### `llm-frontend/src/pages/TeachMeSubChooser.tsx`

New page that intercepts the teach_me click from `ModeSelectPage` and shows two cards (PRD §FR-1, §FR-2):

```tsx
function TeachMeSubChooser() {
  const navigate = useNavigate();
  const { subject, chapter, topic } = useParams();
  const guidelineId = useGuidelineId();
  const { hasDialogue } = useBaatcheetAvailability(guidelineId);
  const { hasDialogueResume, hasExplainResume } = useResumableTeachMe(guidelineId);

  const startSession = async (mode: 'teach_me' | 'baatcheet') => {
    // Either resume paused session or createSession() — same shape as ModeSelectPage
    ...
  };

  return (
    <div className="selection-step">
      {/* Recommended: Baatcheet (or "Continue" if resume available) */}
      <button
        className="selection-card baatcheet-card"
        onClick={() => startSession('baatcheet')}
        disabled={!hasDialogue}
      >
        <span className="badge">Recommended</span>
        <strong>Baatcheet</strong>
        <span className="mode-card-sub">
          {hasDialogue ? 'Listen in on a friendly chat about this topic'
                       : 'Coming soon'}
        </span>
      </button>
      {/* Quieter secondary: Explain */}
      <button
        className="selection-card explain-card"
        onClick={() => startSession('teach_me')}
      >
        <strong>Explain</strong>
        <span className="mode-card-sub">Step-by-step explanation cards</span>
      </button>
    </div>
  );
}
```

Routing: add a new route `/learn/:subject/:chapter/:topic/teach` (the URL segment for teach_me already exists per `MODE_URL_SEGMENT` in `ModeSelectPage.tsx:14-17`). The sub-chooser becomes the page rendered at this URL **before** session creation.

**Decision: separate page, not inline in ModeSelection.tsx.** The PRD makes the sub-choice deliberate ("Both modes always presented. No memory of last choice. Student picks every entry"). A separate page better supports the resume CTA (which mode to resume) and the disabled-state for topics without dialogue. ModeSelection.tsx still renders the top-level (Teach Me / Practice / Clarify) — only the click on Teach Me changes destination.

#### `llm-frontend/src/components/baatcheet/SpeakerAvatar.tsx`

```tsx
interface SpeakerAvatarProps {
  speaker: 'tutor' | 'peer' | null;
  speaking: boolean;
}

export function SpeakerAvatar({ speaker, speaking }: SpeakerAvatarProps) {
  if (!speaker) return null;
  const src = speaker === 'tutor'
    ? '/avatars/tutor.svg'
    : '/avatars/peer.svg';
  return (
    <div className={`speaker-avatar ${speaking ? 'speaking' : ''}`} key={speaker}>
      <img src={src} alt={speaker === 'tutor' ? 'Mr. Verma' : 'Meera'} />
    </div>
  );
}
```

CSS: cross-fade on `key` change (300ms opacity transition), `.speaking` adds a pulsing glow ring.

#### Avatar assets

`llm-frontend/public/avatars/tutor.svg` and `peer.svg` — V1 stylized placeholders (PRD §FR-38). Two distinct silhouettes with subtle color difference. Aim: visually cue who's speaking without aspiring to character art (V2 deferral).

### 5.2 Modified components

#### `llm-frontend/src/pages/ChatSession.tsx`

**(a) Add `'dialogue_phase'` to `sessionPhase`** (line 138):

```tsx
const [sessionPhase, setSessionPhase] = useState<
  'card_phase' | 'interactive' | 'dialogue_phase'
>('interactive');
```

**(b) New state for dialogue cards** (alongside `explanationCards`):

```tsx
const [dialogueCards, setDialogueCards] = useState<DialogueCard[]>([]);
```

**(c) Carousel slide derivation.** Extend `carouselSlides` `useMemo` (line 204): when `sessionPhase === 'dialogue_phase'`, build slides from `dialogueCards` instead of `explanationCards`. Each slide carries `speaker` so `SpeakerAvatar` can render.

**(d) First-turn handler.** After `firstTurn.session_phase === 'dialogue_phase'` is detected (line 410), set `sessionPhase`, `dialogueCards`, and pre-fetch personalized audio (next subsection).

**(e) Replace localStorage with server progress.** In the navigation handlers (lines 1646-1669), call `postCardProgress(sessionId, currentSlideIdx)` on each advance. Keep the localStorage write as a fallback for offline tolerance, but make the server the source of truth on resume.

**(f) Render `SpeakerAvatar`.** When `sessionPhase === 'dialogue_phase'`, render the avatar above the card content. `speaking` is true while `playingSlideId === slide.id`.

**(g) Personalized audio pre-fetch.** Use the new hook (next subsection).

#### `llm-frontend/src/hooks/usePersonalizedAudio.ts`

```tsx
export function usePersonalizedAudio(
  cards: DialogueCard[] | null,
  studentName: string | null,
  language: string,
) {
  useEffect(() => {
    if (!cards) return;
    const personalized = cards.filter(c => c.includes_student_name);
    if (personalized.length === 0) return;

    Promise.all(personalized.map(async (card) => {
      for (const line of card.lines) {
        const text = line.audio.replace('{student_name}', studentName || '');
        if (!text.trim()) continue;
        try {
          const blob = await synthesizeSpeech(text, language);
          // Cache under a stable, per-card-line URL so the carousel can pull from it
          const cacheKey = `personalized:${card.card_id}:${line.audio.slice(0, 32)}`;
          // audioController exposes blob cache; extend with a setBlob helper or
          // attach a synthetic ObjectURL to line.audio_url client-side.
          attachClientAudioBlob(cacheKey, blob);
        } catch (e) {
          console.warn('Runtime TTS failed for', card.card_id, e);
        }
      }
    }));
  }, [cards, studentName, language]);
}
```

`attachClientAudioBlob` is a small extension to `audioController.ts` that stores a `Blob` under a synthetic key and surfaces a `blob:` URL the playback path can resolve. Falls back to plain text-only display per PRD §12 ("Runtime TTS fetch fails for personalized card → Show display text only, skip audio for that card").

#### `llm-frontend/src/components/ModeSelection.tsx`

No structural change — it still renders three top-level CTAs. The teach_me click handler now navigates to `/learn/:subject/:chapter/:topic/teach` (the sub-chooser route) instead of calling `createSession` directly. Mechanically: change `onSelectMode('teach_me')` upstream in `ModeSelectPage.tsx` to navigate to the sub-chooser.

### 5.3 API client

#### `llm-frontend/src/api.ts`

Add types:

```ts
export type DialogueSpeaker = 'tutor' | 'peer';
export type DialogueCardType = 'welcome' | 'tutor_turn' | 'peer_turn'
  | 'visual' | 'check_in' | 'summary';

export interface DialogueLine {
  display: string;
  audio: string;            // may contain "{student_name}"
  audio_url?: string | null;
}

export interface DialogueCard {
  card_id: string;
  card_idx: number;
  card_type: DialogueCardType;
  speaker: DialogueSpeaker | null;
  title: string | null;
  lines: DialogueLine[];
  audio_url: string | null;
  includes_student_name: boolean;
  visual: string | null;
  visual_explanation: CardVisualExplanation | null;
  check_in: CheckInActivity | null;
}

export interface DialoguePhaseDTO {
  current_card_idx: number;
  total_cards: number;
}

export type SessionMode = 'teach_me' | 'baatcheet' | 'clarify_doubts' | 'practice';
```

New client function:

```ts
export async function postCardProgress(
  sessionId: string, cardIdx: number,
): Promise<void> {
  const r = await fetch(`${API_BASE_URL}/sessions/${sessionId}/card-progress`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ card_idx: cardIdx }),
  });
  if (!r.ok && r.status !== 204) throw new Error(`Card progress failed: ${r.status}`);
}
```

Update `createSession` request type to include `mode: 'baatcheet'`. The existing `Turn` type (server response) gains `dialogue_cards` and `dialogue_phase_state` (optional fields).

### 5.4 Admin frontend

#### `llm-frontend/src/features/admin/api/adminApiV2.ts`

```ts
export type StageId =
  | 'explanations' | 'visuals' | 'check_ins'
  | 'baatcheet_dialogue' | 'baatcheet_visuals'  // NEW
  | 'practice_bank' | 'audio_review' | 'audio_synthesis';

export async function generateBaatcheetDialogue(
  bookId: string,
  { guidelineId, force }: { guidelineId: string; force?: boolean },
): Promise<ProcessingJobResponse> {
  return postAdmin(
    `/admin/v2/books/${bookId}/generate-baatcheet-dialogue`,
    { guideline_id: guidelineId, force: !!force },
  );
}

export async function generateBaatcheetVisuals(
  bookId: string,
  { guidelineId, force }: { guidelineId: string; force?: boolean },
): Promise<ProcessingJobResponse> {
  return postAdmin(
    `/admin/v2/books/${bookId}/generate-baatcheet-visuals`,
    { guideline_id: guidelineId, force: !!force },
  );
}
```

#### `llm-frontend/src/features/admin/pages/TopicPipelineDashboard.tsx`

```ts
const STAGE_ORDER: StageId[] = [
  'explanations',
  'visuals',
  'check_ins',
  'baatcheet_dialogue',  // NEW
  'baatcheet_visuals',   // NEW
  'practice_bank',
  'audio_review',
  'audio_synthesis',
];
```

Extend `handleStageAction` with two new branches:

```ts
} else if (stageId === 'baatcheet_dialogue') {
  await generateBaatcheetDialogue(bookId, { guidelineId, force: shouldForce });
} else if (stageId === 'baatcheet_visuals') {
  await generateBaatcheetVisuals(bookId, { guidelineId, force: shouldForce });
}
```

Bulk "Regenerate all stale dialogues" button (PRD §FR-47): defer to a later iteration; the per-topic regenerate button covers the V1 use case.

### 5.5 State management

No new global context. The sub-chooser is a leaf page; ChatSession's existing local state machine is extended (one new sessionPhase value, one new card array, one new state struct).

---

## 6. LLM Integration

### 6.1 New agent: Baatcheet dialogue generator (Stage 5b)

- **Provider:** `claude_code` (subprocess wrapper, mirrors `check_in_enrichment` and `practice_bank_generator` per `db.py:70-78`).
- **Model:** `claude-opus-4-7` initially. Configurable via `llm_configs` table.
- **Reasoning effort:** `high` (matches Stage 5).
- **Structured output:** `DialogueGenerationOutput` Pydantic schema, validated post-call.
- **Prompt strategy:** split system prompt (static rules + JSON schema, loaded via `--append-system-prompt-file`) and dynamic user prompt (topic + variant A cards + misconceptions). Same split optimization as Stage 5 (~30–40% stdin reduction).
- **Review-refine:** 1 round at `balanced`, 2 rounds at `thorough` (default 0 at `fast`). Same shape as Stage 5.

### 6.2 Reused: PixiJS code generator (Stage 5c)

- Reuses `tutor/services/pixi_code_generator.py:46-108` unchanged.
- New prompt template `prompts/baatcheet_visual_intent.txt` is just an input format — `PixiCodeGenerator.generate(prompt, output_type)` takes a plain string. The Baatcheet enrichment service constructs that string from `card.title + " — " + card.visual_intent`.

### 6.3 Cost and latency considerations

- **Stage 5b token usage estimate:** ~3000 input tokens (variant A cards + guideline + misconceptions + system prompt) → ~6000 output tokens (25–30 dialogue cards × ~200 tokens). ~30s per round at Opus high effort. At 2 rounds: ~60s wall-clock per topic.
- **Stage 5c token usage:** ~5 visual cards per dialogue × ~500 input + ~2000 output = small. ~30s total per topic.
- **Stage 10 audio (extension):** ~50 lines per dialogue × ~1KB MP3 = ~50KB upload per topic. TTS API rate is fast (<200ms per line). Adds ~10–15s per topic.
- **Caching:** structured prompt-cache via Claude Code adapter is automatic for the static system prompt. The dynamic prompt (topic-specific) won't cache cross-topic but will cache within review-refine rounds (same topic, same variant A).

---

## 7. Configuration & Environment

### 7.1 New environment variables

None.

### 7.2 Config changes

#### `llm-backend/db.py:_seed_llm_config()`

Add row for `baatcheet_dialogue_generator` (see §4.10).

#### `llm-backend/book_ingestion_v2/services/audio_generation_service.py`

Add module-level constant `PEER_VOICE = ("hi-IN", "hi-IN-Chirp3-HD-Aoede")`. Specific voice is a placeholder — confirm during impl after audition (PRD §13.1).

---

## 8. Implementation Order

The build sequence below is end-to-end testable per step. Each step adds a vertical slice, not a horizontal layer — so a developer can validate one piece in isolation before moving on.

| Step | What to Build | Files | Depends On | Testable? |
|------|---------------|-------|------------|-----------|
| 1 | `TopicDialogue` ORM model + migration helper | `shared/models/entities.py`, `db.py` | — | Run `python -m llm-backend.db migrate`; verify table exists in Postgres + cascade delete works |
| 2 | `DialogueRepository` + Pydantic `DialogueCard` model | `shared/repositories/dialogue_repository.py` | Step 1 | Unit test: upsert → get → parse_cards → delete |
| 3 | `BaatcheetDialogueGeneratorService` (no review-refine yet) + prompts | `book_ingestion_v2/services/baatcheet_dialogue_generator_service.py`, `prompts/baatcheet_dialogue_generation*.txt` | Step 2 | Integration test: pick a guideline with variant A; call `generate_for_guideline`; assert `topic_dialogues` row appears with valid card structure |
| 4 | Add review-refine round loop + validators | same as Step 3 | Step 3 | Test: validators reject malformed cards; review-refine improves output |
| 5 | `BaatcheetVisualEnrichmentService` + prompt | `book_ingestion_v2/services/baatcheet_visual_enrichment_service.py`, `prompts/baatcheet_visual_intent.txt` | Step 3 | Integration test: dialogue with `visual` card → `pixi_code` populated |
| 6 | Stage launchers + `V2JobType` + `LAUNCHER_BY_STAGE` | `book_ingestion_v2/services/stage_launchers.py`, `book_ingestion_v2/constants.py` | Steps 3–5 | Manual: call launcher from a python REPL, watch a `chapter_processing_jobs` row appear |
| 7 | Background tasks `_run_baatcheet_*` + admin POST routes | `book_ingestion_v2/api/sync_routes.py` | Step 6 | curl `POST /admin/v2/books/{id}/generate-baatcheet-dialogue?guideline_id=...` → 202 + job completes |
| 8 | Extend `StageId` Literal + `PIPELINE_LAYERS` + `QUALITY_ROUNDS` + status service | `book_ingestion_v2/models/schemas.py`, `services/topic_pipeline_orchestrator.py`, `services/topic_pipeline_status_service.py` | Step 7 | Hit `GET /admin/v2/books/.../topic-pipeline-status` and confirm new stages appear |
| 9 | Audio generation: per-speaker voice routing + `generate_for_topic_dialogue` + extend `_run_audio_generation` | `book_ingestion_v2/services/audio_generation_service.py`, `book_ingestion_v2/api/sync_routes.py` | Step 7 | Trigger audio_synthesis on a guideline that has both variant A and a dialogue; verify both sets of MP3s in S3 with correct voices |
| 10 | Extend `_run_audio_text_review` to cover dialogues | `book_ingestion_v2/services/audio_text_review_service.py`, `book_ingestion_v2/api/sync_routes.py` | Step 9 | Trigger audio_review; check that audio text on dialogue lines is reviewed |
| 11 | Admin frontend stage list + buttons | `llm-frontend/src/features/admin/api/adminApiV2.ts`, `pages/TopicPipelineDashboard.tsx` | Step 8 | Admin UI shows all 8 stages, buttons trigger correct endpoints |
| 12 | `DialoguePhaseState` + `SessionService` baatcheet branch | `tutor/models/session_state.py`, `tutor/services/session_service.py` | Step 9 | curl `POST /sessions {mode: "baatcheet"}` → returns `first_turn.session_phase = "dialogue_phase"` with cards |
| 13 | Server-side card progress endpoint | `tutor/api/sessions.py`, `tutor/services/session_service.py` | Step 12 | curl `POST /sessions/{id}/card-progress {card_idx: 5}` → 204; resume returns idx=5 |
| 14 | Frontend types + `postCardProgress` client | `llm-frontend/src/api.ts` | Step 13 | TypeScript compiles cleanly |
| 15 | `TeachMeSubChooser` page + routing | `llm-frontend/src/pages/TeachMeSubChooser.tsx`, App.tsx routes, `pages/ModeSelectPage.tsx` | Step 14 | Click Teach Me → see sub-chooser; both buttons start sessions in correct modes |
| 16 | `SpeakerAvatar` component + assets | `llm-frontend/src/components/baatcheet/SpeakerAvatar.tsx`, `public/avatars/*.svg` | — | Storybook-style visual check |
| 17 | `ChatSession` `dialogue_phase` integration: render dialogue cards, avatar, navigation | `llm-frontend/src/pages/ChatSession.tsx` | Steps 14, 16 | Local browser: complete a dialogue end-to-end |
| 18 | `usePersonalizedAudio` hook + `attachClientAudioBlob` extension | `llm-frontend/src/hooks/usePersonalizedAudio.ts`, `hooks/audioController.ts` | Step 17 | Local: card with `includes_student_name=true` plays correct name |
| 19 | Resume-from-last-card on Explain (scope expansion) | `llm-frontend/src/pages/ChatSession.tsx`, `tutor/services/session_service.py` | Step 13 | Pause Explain mid-card → re-enter → resume at correct idx |
| 20 | Resume-from-last-card on Baatcheet | same | Step 17, 19 | Same test as 19 in baatcheet mode |
| 21 | Stale-dialogue admin warning + bulk regenerate (deferred to follow-up if time-pressured) | `book_ingestion_v2/services/topic_pipeline_status_service.py`, `pages/TopicPipelineDashboard.tsx` | Step 8 | Regenerate variant A → admin shows warning on dialogue tile |

**Order rationale:** database first (step 1) so subsequent code has something to read/write. Then repository (2) and the two service classes (3–5) which are the hardest LLM-shaped logic. Then plumbing (6–8) so the new stages are admin-triggerable. Audio (9–10) before frontend so the runtime path has data. Frontend (11–18) builds bottom-up — types → page → component → integration. Resume (19–20) at the end because it touches both modes and shouldn't gate the happy path. Step 21 is intentionally last and optional for V1.

---

## 9. Testing Plan

### 9.1 Unit tests

| Test | What it Verifies | Key Mocks |
|------|------------------|-----------|
| `test_dialogue_repository_upsert_replaces_existing` | upsert deletes old row and inserts new one | none |
| `test_dialogue_repository_cascade_delete_on_guideline` | deleting a guideline removes its dialogue | none |
| `test_dialogue_repository_is_stale_vs_variant_a` | true when variant A.created_at > dialogue.updated_at | none |
| `test_baatcheet_dialogue_validators_reject_too_few_cards` | <13 cards fails validation | none |
| `test_baatcheet_dialogue_validators_reject_back_to_back_check_ins` | <4 cards apart fails | none |
| `test_baatcheet_dialogue_validators_require_welcome_first_summary_last` | both card types enforced | none |
| `test_audio_voice_routing_tutor_uses_existing_voice` | speaker=tutor → Chirp 3 HD Kore | mock TextToSpeechClient |
| `test_audio_voice_routing_peer_uses_peer_voice` | speaker=peer → PEER_VOICE | mock TextToSpeechClient |
| `test_audio_skips_includes_student_name_lines` | flagged cards have audio_url unset post-synthesis | mock TextToSpeechClient |
| `test_audio_backwards_compat_no_speaker_uses_tutor` | absent speaker field → tutor voice (variant A path) | mock TextToSpeechClient |
| `test_session_service_baatcheet_mode_loads_from_dialogue_repo` | mode=baatcheet → DialogueRepository is queried | mock DialogueRepository |
| `test_session_service_baatcheet_raises_when_no_dialogue` | guideline without dialogue → VariantNotFoundError | none |
| `test_card_progress_persists_to_state_json` | POST /card-progress updates state.dialogue_phase.current_card_idx | none |
| `test_orchestrator_includes_new_stages_in_dag` | PIPELINE_LAYERS contains baatcheet_dialogue and baatcheet_visuals | none |

### 9.2 Integration tests

| Test | What it Verifies |
|------|------------------|
| `test_run_baatcheet_dialogue_generation_end_to_end` | Real LLM call → topic_dialogues row exists with valid card_count, validators pass |
| `test_run_baatcheet_visual_enrichment_end_to_end` | Stage 5b output → Stage 5c → all visual cards have pixi_code |
| `test_audio_synthesis_extends_to_dialogues` | Trigger audio_synthesis on a guideline with both → both sets of MP3s appear in S3, dialogue MP3s use peer voice |
| `test_pipeline_orchestrator_runs_all_8_stages_for_topic` | Cold ingestion of a topic produces variant A AND a dialogue |
| `test_session_create_baatcheet_returns_dialogue_phase` | POST /sessions {mode: "baatcheet"} → first_turn.session_phase == "dialogue_phase" with N cards |
| `test_resume_baatcheet_returns_correct_card_idx` | POST card-progress → pause → resume → returns same idx |

### 9.3 Manual verification

1. **Ingestion path:** open admin TopicPipelineDashboard for a topic with variant A done. Click Generate Baatcheet Dialogue → wait for completion (~60s). Click Generate Baatcheet Visuals → wait. Click Generate Audio → wait. Inspect topic_dialogues row in Postgres; verify cards_json structure.
2. **Student path (Baatcheet):** open the app on `localhost:3000`. Pick a topic. Tap Teach Me → see sub-chooser. Tap Baatcheet → see welcome card with avatar. Advance through dialogue. Verify (a) avatar swaps tutor↔peer; (b) audio plays in correct voice on each card; (c) check-in cards work via existing CheckInDispatcher; (d) personalized cards say the student's actual name.
3. **Resume:** mid-dialogue, navigate away. Re-enter via Teach Me → sub-chooser shows "Continue Baatcheet" CTA → tap → land on same card. Repeat for Explain mode.
4. **Stale warning:** edit a topic's variant A explanation cards (re-run Stage 5 with force). In the admin TopicPipelineDashboard, the baatcheet_dialogue tile should show "stale" badge. Click Regenerate → warning clears.
5. **Audio fallback:** disconnect from network. Open a Baatcheet session with personalized cards. Verify display text appears even without audio (PRD §12 fallback row).
6. **Mode chooser disabled state:** open a topic that has variant A done but no dialogue. Tap Teach Me → sub-chooser shows Baatcheet card disabled with "coming soon" hint.

---

## 10. Deployment Considerations

### 10.1 Migration

- New `topic_dialogues` table is created via `Base.metadata.create_all()` on backend startup (no separate Alembic step — codebase doesn't use Alembic).
- Idempotent: re-running migration is safe (CREATE INDEX IF NOT EXISTS, DELETE-then-INSERT in upsert).
- No data backfill: existing topics simply have no dialogue row until their first Stage 5b run.

### 10.2 Order of operations (deploy)

1. **Deploy backend first** (with new table + new endpoints + extended audio service). Existing variant A path is fully backwards-compatible: cards without `speaker` field route to the tutor voice; cards without `includes_student_name` are pre-rendered; absent `topic_dialogues` rows simply mean Baatcheet is unavailable for that topic.
2. **Deploy frontend** with new UI. Until backend is live, the `mode: 'baatcheet'` request would 404 — frontend should defensively check `availability` before showing the Baatcheet card (a `GET /topics/{id}/baatcheet-availability` endpoint, or simply checking `dialogue_cards.length > 0` from the createSession response).
3. **Run ingestion for at least one topic** (admin manual) to seed dialogue data.
4. **Soft launch** with the Baatcheet card disabled by default for topics without dialogues (PRD §12 already specifies this).

### 10.3 Feature flag

Add a `feature_flags` row `enable_baatcheet_mode` (default false). Controls whether the sub-chooser appears at all. When disabled, `ModeSelectPage` skips the sub-chooser and goes straight to teach_me / explain — preserves the pre-Baatcheet UX exactly. Hide via the admin feature-flags surface; flip on once content is seeded.

### 10.4 Rollback plan

- Frontend: flip `enable_baatcheet_mode` flag to false. Sub-chooser disappears. All existing topics still work via Explain.
- Backend: the new endpoints are additive. Reverting just the frontend flag is sufficient.
- Data: `topic_dialogues` rows can be left in place — they're orphan but harmless. Drop the table if doing a full revert.
- Audio: dialogue MP3s are under a distinct S3 prefix (`audio/{guideline_id}/dialogue/...`); cleanup is `aws s3 rm` on that prefix only.

### 10.5 Infrastructure

- No new AWS resources. Existing S3 bucket, RDS, Cognito are all reused.
- Google Cloud TTS quota: 50 lines × N topics × 2 (initial + occasional regen) per ingestion run. Far below the per-day quota at current scale; monitor via existing CloudWatch metrics.

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Stage 5b dialogue quality drift on edge-case topics | Medium | Medium | Curriculum reviewer rates first 10 generations (PRD §14.3). Tune prompt + add review-refine rounds at `thorough` quality. |
| Per-topic lock prevents 5b/5c from running parallel with stages 6a/6b → ingestion latency >30s target | Medium | Low | Sequential layers in V1 (this plan). Plan a follow-up `lock_channel` schema change to enable parallel branches. PRD §14.4 success criterion may slip in V1; revisit post-launch. |
| Meera voice audition picks a voice too similar to Mr. Verma's | Medium | Medium | Audition during step 9 (audio voice routing). Listen test on ≥3 sample dialogue cards. Pick a Chirp 3 HD voice with distinctly different pitch/tone (e.g., `hi-IN-Chirp3-HD-Aoede` or `-Charon`). |
| Variant A regen unexpectedly cascades to Baatcheet (PRD §FR-45 forbids this) | Low | Low | No code path triggers 5b automatically. Stale warning is the user-facing signal. Test: regen variant A → confirm `topic_dialogues` row unchanged. |
| `includes_student_name` flag misused — runtime TTS fails for cards that should have been pre-rendered | Low | Medium | Stage 5b validator: `includes_student_name=true` cards must contain the literal `{student_name}` substring; cards without the substring must not have the flag. Reject otherwise. |
| Frontend localStorage `slide-pos-${sessionId}` and server `current_card_idx` get out of sync (e.g., user opens two tabs) | Medium | Low | Server is the source of truth on resume. Local state is best-effort during a single tab session. Minor UX wobble, not a correctness issue. |
| Admin runs the orchestrator on a topic mid-edit and creates inconsistent state (variant A + dialogue refer to different content) | Low | Medium | Stale warning + per-topic lock. The lock prevents concurrent runs. The warning prevents silent drift after a manual variant A edit. |
| Stage 5c reuses `PixiCodeGenerator` but `visual_intent` strings from dialogue context are too sparse for good visuals | Medium | Low | Provide example-rich prompt template. If output quality is poor, copy review-refine rounds from `AnimationEnrichmentService` (deferred from V1 simple-pass design). |
| `DialogueCard` schema drift (e.g., new field added) breaks old cards on read | Low | Medium | All new fields default to None or empty list. `DialogueRepository.parse_cards` raises ValidationError if data is malformed → caller logs and falls back gracefully (same defensive shape as `ExplanationRepository.parse_cards`). |
| Two voices on the same Stage 10 run double the synthesis time and breach heartbeat threshold | Low | Medium | Heartbeat is 30 min (`HEARTBEAT_STALE_THRESHOLD = 1800` in `book_ingestion_v2/constants.py`). Each TTS call is <200ms. Even 200 lines per topic = ~40s. Comfortable headroom. |

---

## 12. Open Questions

1. **Specific Meera voice selection.** PRD §13.1 defers this. To resolve in step 9 of impl. Suggest auditioning `hi-IN-Chirp3-HD-Aoede`, `-Charon`, `-Fenrir`, `-Leda`, `-Orus`, `-Puck` — pick the one most distinct from Kore that still sounds peer-aged. Document the chosen voice in `audio_generation_service.py` with a one-line comment.
2. **Avatar placeholder design.** PRD §13.2 defers this. Need stylized SVGs that read as "tutor" and "peer" but don't ship as character art. Suggest two distinct silhouettes with subject-color tinting (matches existing `--board-*` chalkboard palette in `App.css:30-36`).
3. **Review-refine round count for Stage 5b.** Default 1 in `balanced`; tune after 10–20 sample generations. Adding a third round at `thorough` is cheap and recommended if quality is inconsistent.
4. **Validator threshold details.** PRD §13.4 punts max card count tuning. Plan starts with 13–35 (lower bound from PRD §6 validator, upper from §FR-11). If real outputs cluster around 25–30, tighten to 20–32 to catch outliers.
5. **Bulk regenerate UI surface.** PRD §FR-47 calls for a "Regenerate all stale dialogues" button. Step 21 in the build order, optional for V1. Decide during impl whether it slots into the chapter dashboard or the topic dashboard.
6. **Should the existing `slide-pos-${sessionId}` localStorage mechanism be deleted entirely, or kept as a fallback?** Plan keeps it as fallback for offline tolerance. Revisit after step 19 — if server-side resume is reliable enough, drop the localStorage path to avoid two-source-of-truth complexity.
7. **Personalization edge case: students whose name contains characters that break Chirp 3 HD (e.g., emoji).** Frontend should sanitize the name before sending to `synthesizeSpeech`. Current `synthesizeSpeech` clips at 5000 chars but doesn't sanitize. Add a small helper.

---

## Appendix A: Decision log

| Decision | Why |
|---|---|
| One row per guideline in `topic_dialogues` (no `variant_key`) | PRD §5 explicitly excludes multiple dialogue variants. Schema simplification — single FK index, no composite uniqueness. |
| Sequential pipeline layers (not parallel branch) | Existing per-topic lock would force serialization anyway. Parallel branch requires a `lock_channel` schema change beyond V1 scope. |
| Reuse `ExplanationLine` and `CheckInActivity` Pydantic models | They already encode display+audio split and the 11-type check-in shape. Inventing parallel models guarantees future drift. |
| `DialoguePhaseState` separate from `CardPhaseState` | They share 3 fields but `CardPhaseState` is variant-aware. Forcing one struct creates nullable-fields-easy-to-misuse. |
| Server-side `last_card_idx` via `state.card_phase.current_card_idx` extension (not new column) | `state_json` already exists and is mode-flexible. Adding a column ties resume to teach_me/baatcheet only — but other modes might want it later. |
| Voice routing as a per-call parameter, not a per-instance config | Variant A cards lack `speaker`; falling back to `self.voice` keeps existing behavior identical. Per-instance refactor would force every call site to pass it explicitly. |
| Dialogue audio S3 keys in a separate prefix `dialogue/` | Variant A keys (`audio/{guideline_id}/{variant_key}/...`) are unchanged. Dialogue keys (`audio/{guideline_id}/dialogue/...`) are isolated → backwards compat is mechanical, not contractual. |
| `card_id` mandatory for dialogue cards (not just check-ins) | Dialogue regen rotates content; positional keys (`card_idx`) would race. UUID per card decouples audio identity from order. |
| Sub-chooser as separate page, not inline UI in `ModeSelection` | Cleaner for the resume CTA, the disabled-state, and future per-mode preferences. PRD's "no memory of last choice" rules out implicit sub-mode persistence anyway. |
| Stage 5b → Claude Code provider | Matches existing high-pedagogical-quality stages (`check_in_enrichment`, `practice_bank_generator`). Configurable via `llm_configs` if quality demands a switch. |
| No review-refine round in Stage 5c (visual enrichment) | Matches the simpler check-in enrichment pattern. PRD doesn't require it; V2 can add if quality slips. |

---

## Appendix B: File-by-file change matrix

```
NEW FILES
├── llm-backend/
│   ├── shared/repositories/dialogue_repository.py
│   ├── book_ingestion_v2/
│   │   ├── services/baatcheet_dialogue_generator_service.py
│   │   ├── services/baatcheet_visual_enrichment_service.py
│   │   └── prompts/
│   │       ├── baatcheet_dialogue_generation.txt
│   │       ├── baatcheet_dialogue_generation_system.txt
│   │       ├── baatcheet_dialogue_review_refine.txt
│   │       ├── baatcheet_dialogue_review_refine_system.txt
│   │       └── baatcheet_visual_intent.txt
└── llm-frontend/
    ├── src/
    │   ├── pages/TeachMeSubChooser.tsx
    │   ├── components/baatcheet/SpeakerAvatar.tsx
    │   └── hooks/usePersonalizedAudio.ts
    └── public/avatars/
        ├── tutor.svg
        └── peer.svg

MODIFIED FILES
├── llm-backend/
│   ├── db.py                                     (+ migration helper, + LLM config seed)
│   ├── shared/models/entities.py                 (+ TopicDialogue ORM)
│   ├── book_ingestion_v2/
│   │   ├── constants.py                          (+ 2 V2JobType values)
│   │   ├── models/schemas.py                     (+ StageId, + status response shapes)
│   │   ├── services/stage_launchers.py           (+ 2 launchers, + LAUNCHER_BY_STAGE entries)
│   │   ├── services/topic_pipeline_orchestrator.py (PIPELINE_LAYERS, QUALITY_ROUNDS, _launcher_kwargs)
│   │   ├── services/topic_pipeline_status_service.py (+ 2 stage statuses)
│   │   ├── services/audio_generation_service.py  (per-speaker voice, generate_for_topic_dialogue, includes_student_name)
│   │   ├── services/audio_text_review_service.py (extend to dialogues)
│   │   └── api/sync_routes.py                    (+ 2 routes, + 2 _run_* fns, + dialogue branch in _run_audio_*)
│   └── tutor/
│       ├── models/session_state.py               (+ DialoguePhaseState)
│       ├── services/session_service.py           (+ baatcheet branch, + record_card_progress)
│       └── api/sessions.py                       (+ /card-progress route, mode validation)
└── llm-frontend/
    ├── src/
    │   ├── api.ts                                (+ DialogueCard types, + postCardProgress, + 'baatcheet' mode)
    │   ├── App.tsx                               (+ /learn/.../teach route → TeachMeSubChooser)
    │   ├── pages/ChatSession.tsx                 ('dialogue_phase' state, dialogue card rendering, SpeakerAvatar, postCardProgress)
    │   ├── pages/ModeSelectPage.tsx              (route teach_me click → sub-chooser)
    │   ├── hooks/audioController.ts              (attachClientAudioBlob extension)
    │   └── features/admin/
    │       ├── api/adminApiV2.ts                 (+ StageId, + 2 generate functions)
    │       └── pages/TopicPipelineDashboard.tsx  (STAGE_ORDER, handleStageAction)
```

Total: 9 new files + 21 modified files.
