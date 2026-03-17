# Tech Implementation Plan: Pre-Computed Explanations

**Date:** 2026-03-17
**Status:** Draft
**PRD:** `docs/feature-development/pre-computed-explanations/PRD.md`
**Principles:** `docs/principles/how-to-explain.md`

---

## 1. Overview

Pre-computed explanations are structured, multi-card teaching artifacts generated offline (post-sync) for each topic. At session time, they replace the dynamic `ExplanationPhase` with a zero-latency card navigation experience. The tutor remains for Q&A, re-explanation, and practice after cards are consumed.

**High-level approach:**
- New `TopicExplanation` entity + `ExplanationRepository` for storage
- New `ExplanationGeneratorService` with multi-pass LLM pipeline (generate → critique → refine)
- Triggered via standalone endpoint (decoupled from sync to avoid timeout issues)
- `SessionService` detects pre-computed explanations at session creation, returns cards instead of calling `generate_welcome_message()`
- New `CardPhase` in session state replaces `ExplanationPhase` for pre-computed topics
- New `ExplanationViewer` frontend component for card-based navigation
- Dynamic `ExplanationPhase` retained as fallback

---

## 2. Architecture Changes

### Data flow diagram

```
OFFLINE (ingestion pipeline)
═══════════════════════════════════════════════════════════════

  Finalize Chapter
       ↓
  TopicSyncService.sync_chapter()
       ↓ (creates TeachingGuideline rows)
  ExplanationGeneratorService.generate_for_guideline()
       ↓ (per variant: generate → critique → refine)
  topic_explanations table (JSONB cards)

═══════════════════════════════════════════════════════════════
ONLINE (session time)
═══════════════════════════════════════════════════════════════

  POST /sessions (CreateSessionRequest)
       ↓
  SessionService.create_new_session()
       ↓
  ExplanationRepository.get_by_guideline_id()
       ↓
  ┌─── explanations found? ───┐
  │ YES                       │ NO
  │ Set CardPhase             │ Current ExplanationPhase
  │ Return cards in response  │ generate_welcome_message()
  │ Skip welcome LLM call     │ (unchanged behavior)
  └───────────────────────────┘
       ↓ (card navigation — no LLM calls)
  "Clear" / "Explain differently" / all variants exhausted
       ↓
  Transition to interactive tutor
  (inject {precomputed_explanation_summary} into system prompt)
```

### New modules

| Module | Purpose |
|--------|---------|
| `book_ingestion_v2/services/explanation_generator_service.py` | Multi-pass LLM generation of explanation variants |
| `shared/repositories/explanation_repository.py` | CRUD for `topic_explanations` table |
| `book_ingestion_v2/prompts/explanation_generation.txt` | Generation prompt |
| `book_ingestion_v2/prompts/explanation_critique.txt` | Self-review prompt |
| `llm-frontend/src/components/ExplanationViewer.tsx` | Card-based explanation UI |

### Significantly modified modules

| Module | Change |
|--------|--------|
| `shared/models/entities.py` | New `TopicExplanation` entity |
| `db.py` | New migration function |
| `book_ingestion_v2/services/topic_sync_service.py` | Trigger explanation generation post-sync |
| `book_ingestion_v2/api/sync_routes.py` | Response includes explanation generation status |
| `tutor/models/session_state.py` | New `CardPhaseState` model |
| `tutor/services/session_service.py` | Card detection at session creation, skip welcome LLM call |
| `tutor/orchestration/orchestrator.py` | Card navigation handling, transition to interactive |
| `tutor/prompts/master_tutor_prompts.py` | `{precomputed_explanation_summary}` section |
| `tutor/api/sessions.py` | Updated response shapes, card navigation endpoint |
| `tutor/models/messages.py` | New DTOs for explanation cards |
| `book_ingestion_v2/models/schemas.py` | Updated `SyncResponse` model |
| `llm-frontend/src/api.ts` | New types and API functions |
| `llm-frontend/src/pages/ChatSession.tsx` | Card phase rendering, transition to chat |

---

## 3. Database Changes

### New table: `topic_explanations`

```sql
CREATE TABLE topic_explanations (
    id VARCHAR NOT NULL PRIMARY KEY,
    guideline_id VARCHAR NOT NULL REFERENCES teaching_guidelines(id) ON DELETE CASCADE,
    variant_key VARCHAR NOT NULL,        -- 'A', 'B', 'C'
    variant_label VARCHAR NOT NULL,      -- 'Everyday Analogies', 'Visual Walkthrough', etc.
    cards_json JSONB NOT NULL,           -- ordered list of ExplanationCard objects
    summary_json JSONB,                  -- pre-computed summary for tutor context injection
    generator_model VARCHAR,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_explanation_guideline_variant UNIQUE (guideline_id, variant_key)
);
```

**Decision: Single constraint mechanism.** The `UniqueConstraint` in the entity definition and the DDL both use the name `uq_explanation_guideline_variant`. `Base.metadata.create_all()` handles creation. The migration function only verifies it exists as a fallback for pre-existing tables — it does not create a separate index. This avoids the duplicate constraint/index issue that arises from mixing `UniqueConstraint` with `CREATE UNIQUE INDEX`.

**Decision: `summary_json` column.** Pre-compute the tutor context summary (card titles + key analogies) at generation time rather than computing it at session time. This avoids parsing `cards_json` during session creation and keeps the read path simple.

**Decision: Unique constraint on `(guideline_id, variant_key)`.** Enforces one variant A/B/C per guideline. Regeneration does upsert (delete + insert for same key).

### `cards_json` structure

```json
[
  {
    "card_idx": 1,
    "card_type": "concept",
    "title": "What is a Fraction?",
    "content": "When you share a pizza equally with your friend...",
    "visual": "  [####|    |    |    ]\n   ^-- this piece is yours"
  },
  {
    "card_idx": 2,
    "card_type": "example",
    "title": "Fractions in Real Life",
    "content": "...",
    "visual": null
  }
]
```

### `summary_json` structure

```json
{
  "card_titles": ["What is a Fraction?", "Fractions in Real Life", ...],
  "key_analogies": ["pizza slices", "chocolate bar"],
  "key_examples": ["1/2 of a pizza", "3/4 of a glass"],
  "approach_label": "Everyday Analogies"
}
```

### Relationships

```
teaching_guidelines ──1:N──► topic_explanations (cascade delete)
```

### Migration

New function in `db.py`: `_apply_topic_explanations_table()`. The `UniqueConstraint` is defined in the entity and created by `Base.metadata.create_all()`. The migration function only verifies the table and constraint exist — it does not create a separate index.

---

## 4. Backend Changes

### 4.1 Database Entity

**File:** `llm-backend/shared/models/entities.py`

New class:

```python
class TopicExplanation(Base):
    __tablename__ = "topic_explanations"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    guideline_id = Column(String, ForeignKey("teaching_guidelines.id", ondelete="CASCADE"), nullable=False)
    variant_key = Column(String, nullable=False)       # 'A', 'B', 'C'
    variant_label = Column(String, nullable=False)      # Human-readable
    cards_json = Column(JSONB, nullable=False)           # List[ExplanationCard]
    summary_json = Column(JSONB, nullable=True)          # Pre-computed summary
    generator_model = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("guideline_id", "variant_key", name="uq_explanation_guideline_variant"),
    )
```

### 4.2 Migration

**File:** `llm-backend/db.py`

Add `_apply_topic_explanations_table(db_manager)` to `migrate()` — after existing migration calls, before seed calls.

```python
def _apply_topic_explanations_table(db_manager):
    """Verify topic_explanations table exists (created by Base.metadata.create_all()).

    The UniqueConstraint on (guideline_id, variant_key) is defined in the entity
    and created by create_all(). This function only logs verification — no separate
    index creation to avoid duplicate constraint/index issues.
    """
    inspector = inspect(db_manager.engine)
    if "topic_explanations" in inspector.get_table_names():
        print("  ✓ topic_explanations table exists")
    else:
        print("  ⚠ topic_explanations table not found — will be created by create_all()")
```

Add `"explanation_generator"` to `_LLM_CONFIG_SEEDS` list:
```python
{
    "component_key": "explanation_generator",
    "provider": "openai",
    "model_id": "gpt-5.2",
    "description": "Pre-computed explanation generation for topics",
}
```

**Decision: Idempotent upsert for LLM config.** The existing `_seed_llm_config()` only seeds when the table is empty (won't apply to production). Add an `_ensure_llm_config()` function that inserts if the component_key is missing:
```python
def _ensure_llm_config(db_manager, component_key, provider, model_id, description):
    with db_manager.engine.connect() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM llm_config WHERE component_key = :key"
        ), {"key": component_key}).fetchone()
        if not exists:
            conn.execute(text(
                "INSERT INTO llm_config (component_key, provider, model_id, description) "
                "VALUES (:key, :provider, :model, :desc)"
            ), {"key": component_key, "provider": provider, "model": model_id, "desc": description})
            conn.commit()
```

### 4.3 Explanation Repository

**New file:** `llm-backend/shared/repositories/explanation_repository.py`

```python
class ExplanationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_guideline_id(self, guideline_id: str) -> list[TopicExplanation]:
        """Returns all variants for a guideline, ordered by variant_key."""

    def get_variant(self, guideline_id: str, variant_key: str) -> TopicExplanation | None:
        """Returns a specific variant."""

    def upsert(self, guideline_id: str, variant_key: str, variant_label: str,
               cards_json: list[dict], summary_json: dict, generator_model: str) -> TopicExplanation:
        """Insert or replace a variant (delete existing + insert)."""

    def delete_by_guideline_id(self, guideline_id: str) -> int:
        """Delete all variants for a guideline. Returns count deleted."""

    def has_explanations(self, guideline_id: str) -> bool:
        """Quick existence check — used by session service."""

    @staticmethod
    def parse_cards(cards_json: list[dict]) -> list[ExplanationCard]:
        """Validate and parse raw JSONB cards into ExplanationCard models.
        Ensures DB data matches the expected Pydantic schema on read."""
```

**Decision: Repository lives in `shared/repositories/`.** It's written by the ingestion pipeline and read by the tutor session service. This matches the existing pattern — `TeachingGuidelineRepository` is also in `shared/repositories/` and is consumed by both modules. Avoids creating a new cross-module dependency direction (tutor → book_ingestion_v2).

### 4.4 Explanation Generator Service

**New file:** `llm-backend/book_ingestion_v2/services/explanation_generator_service.py`

```python
class ExplanationGeneratorService:
    """Generates multi-variant pre-computed explanations for a teaching guideline."""

    VARIANT_CONFIGS = [
        {"key": "A", "label": "Everyday Analogies", "approach": "analogy-driven with real-world examples"},
        {"key": "B", "label": "Visual Walkthrough", "approach": "diagram-heavy with visual step-by-step"},
        {"key": "C", "label": "Step-by-Step Procedure", "approach": "procedural walkthrough"},
    ]

    def __init__(self, db: Session, llm: LLMService):
        self.repo = ExplanationRepository(db)
        self.llm = llm

    def generate_for_guideline(self, guideline: TeachingGuideline,
                                variant_keys: list[str] = None) -> list[TopicExplanation]:
        """Generate explanation variants for a guideline. Multi-pass per variant."""

    def _generate_variant(self, guideline: TeachingGuideline,
                          variant_config: dict) -> tuple[list[dict], dict]:
        """Single variant: generate → critique → refine. Returns (cards, summary)."""

    def _generate_cards(self, guideline: TeachingGuideline,
                        variant_config: dict) -> list[dict]:
        """LLM call: generate explanation cards for one variant."""

    def _critique_cards(self, cards: list[dict], guideline: TeachingGuideline,
                        variant_config: dict) -> dict:
        """LLM call: critique cards against how-to-explain principles. Returns feedback."""

    def _refine_cards(self, cards: list[dict], critique: dict,
                      guideline: TeachingGuideline, variant_config: dict) -> list[dict]:
        """LLM call: refine cards based on critique feedback."""

    def _build_summary(self, generation_output: dict) -> dict:
        """Build summary_json from LLM-returned structured metadata (not parsed from freeform text)."""

    def generate_for_chapter(self, book_id: str, chapter_id: str) -> dict:
        """Generate explanations for all synced guidelines in a chapter."""
```

**Multi-pass pipeline per variant:**
```
1. _generate_cards()     → raw cards list + structured summary metadata
2. _critique_cards()     → critique feedback (issues, suggestions)
3. _refine_cards()       → improved cards list (if critique says needs_improvement)
4. _validate_cards()     → reject if < 3 cards or critique was "poor" after refine
5. _build_summary()      → summary_json from LLM-returned metadata (not text extraction)
6. repo.upsert()         → persist to DB (skipped if validation fails)
```

**Card validation before storage:**
- Minimum 3 cards per variant (reject if fewer — topic too thin for cards)
- Maximum 15 cards per variant (split or summarize if exceeded)
- Each card must have non-empty `title` and `content`
- If critique returns `overall_quality: "poor"` after refinement, log a warning and skip storing that variant (don't store known-bad content). The topic falls back to dynamic tutoring for that variant slot.

**LLM configuration:** Uses `reasoning_effort="high"`. Model from `LLMConfig` with `component_key="explanation_generator"`.

### 4.5 Generation Prompts

**New file:** `llm-backend/book_ingestion_v2/prompts/explanation_generation.txt`

Inputs: guideline text, grade, subject, topic name, prior_topics_context, variant approach description, card types reference.

Output schema (strict JSON):
```json
{
  "cards": [
    {
      "card_idx": 1,
      "card_type": "concept | example | visual | analogy | summary",
      "title": "short heading",
      "content": "explanation text, simple language",
      "visual": "optional ASCII/formatted visual or null"
    }
  ],
  "summary": {
    "key_analogies": ["pizza slices", "chocolate bar"],
    "key_examples": ["1/2 of a pizza", "3/4 of a glass"]
  }
}
```

**Decision: LLM returns structured summary metadata alongside cards.** Extracting analogies and examples algorithmically from freeform card content is fragile (regex for "like a..." patterns). Having the LLM identify its own key analogies/examples during generation is reliable and adds negligible token overhead. `_build_summary()` combines this with card titles and the variant label — no text parsing needed.

**New file:** `llm-backend/book_ingestion_v2/prompts/explanation_critique.txt`

Inputs: cards JSON, how-to-explain principles (embedded), guideline text.

Output schema:
```json
{
  "issues": [
    {"card_idx": 2, "principle_violated": "One Idea Per Card", "description": "..."}
  ],
  "suggestions": [
    {"card_idx": 3, "suggestion": "Add a concrete example before the rule"}
  ],
  "overall_quality": "good | needs_improvement | poor"
}
```

### 4.6 Explanation Generation — Decoupled from Sync

**Decision: Explanation generation is a separate step from sync, not inline.**

Sync creates/recreates `TeachingGuideline` rows (fast, ~seconds). Explanation generation is 6-9 LLM calls per topic × 5-7 topics per chapter = 30-63 LLM calls at ~5-15s each = **4-17 minutes per chapter**. Running this inline with sync would:
- Hit HTTP request timeouts (most ASGI servers/load balancers timeout at 30-60s)
- Provide no progress feedback to the admin
- Lose partial progress if the request dies mid-chapter

**Architecture: Sync stays fast. Explanation generation runs separately.**

```
Admin clicks "Sync" → fast sync (seconds)
Admin clicks "Generate Explanations" → separate endpoint, per-guideline progress logging
```

**File:** `llm-backend/book_ingestion_v2/services/topic_sync_service.py` — **No changes.** Sync remains unchanged.

**File:** `llm-backend/book_ingestion_v2/api/sync_routes.py` — New endpoint:

```python
@router.post("/{book_id}/generate-explanations")
def generate_explanations(book_id: str, chapter_id: str = None, db=Depends(get_db)):
    """Generate/regenerate explanations for synced guidelines.

    Runs independently from sync. Idempotent — regenerates existing variants.
    Logs WARNING per failed topic so admin monitoring catches silent degradation.
    """
    llm = get_llm_service("explanation_generator")
    service = ExplanationGeneratorService(db, llm)

    if chapter_id:
        result = service.generate_for_chapter(book_id, chapter_id)
    else:
        result = service.generate_for_book(book_id)

    # Log warnings for failures so they surface in admin monitoring
    for error in result.get("errors", []):
        logger.warning(f"Explanation generation failed: {error}")

    return result
```

Response shape:
```python
class ExplanationGenerationResponse(BaseModel):
    generated: int           # topics with explanations successfully generated
    skipped: int             # topics that already had explanations (unless force=True)
    failed: int              # topics where generation errored
    errors: list[str]        # per-topic error messages
```

**Re-sync cascade delete risk:** Sync deletes/recreates guideline rows → `ON DELETE CASCADE` wipes explanations. Admin must re-run "Generate Explanations" after sync. This is acceptable because:
1. The admin workflow is: Sync → Generate Explanations (two separate actions)
2. If they forget step 2, topics gracefully fall back to dynamic tutoring
3. WARNING logs per failed topic surface in admin monitoring
4. Future: add a health-check endpoint listing topics with guidelines but missing explanations

### 4.7 Sync Response — No Changes

**File:** `llm-backend/book_ingestion_v2/models/schemas.py`

`SyncResponse` is unchanged — sync no longer triggers explanation generation. The new `ExplanationGenerationResponse` model (defined in 4.6) is returned by the separate generate-explanations endpoint.

### 4.8 Session State Changes

**File:** `llm-backend/tutor/models/session_state.py`

New model:

```python
class CardPhaseState(BaseModel):
    """Tracks card-based explanation phase for pre-computed explanations."""
    guideline_id: str                     # FK for explanation lookups (NOT topic_id)
    active: bool = True
    current_variant_key: str = "A"
    current_card_idx: int = 0
    total_cards: int = 0
    variants_shown: list[str] = []        # ["A"] or ["A", "B"]
    available_variant_keys: list[str] = [] # ["A", "B", "C"]
    completed: bool = False               # True when student says "clear" or exhausts variants
```

**Decision: Store `guideline_id` in `CardPhaseState`.** All explanation lookups use `guideline_id` (not `topic_id`). While `topic_id` happens to equal `guideline_id` in the current `convert_guideline_to_topic()` implementation, relying on that is fragile. Storing `guideline_id` explicitly ensures correct lookups in `switch_explanation_variant()` and `_build_precomputed_summary()`.

Add to `SessionState`:

```python
class SessionState(BaseModel):
    # ... existing fields ...

    # Card Phase (pre-computed explanations)
    card_phase: Optional[CardPhaseState] = None

    def is_in_card_phase(self) -> bool:
        return self.card_phase is not None and self.card_phase.active

    def complete_card_phase(self):
        if self.card_phase:
            self.card_phase.active = False
            self.card_phase.completed = True
```

### 4.9 Modified: Session Service

**File:** `llm-backend/tutor/services/session_service.py`

**Audit of `generate_welcome_message()` side effects:** The function is pure — it only calls the LLM and returns `(message, audio_text)`. No state mutations, no logging, no event recording. The important side effects (explanation phase init, `add_message()`, `_persist_session()`, `event_repo.log()`) happen in `create_new_session()` before and after the welcome call. For card phase sessions, we must replicate these surrounding side effects with the pre-computed welcome text.

**What `create_new_session()` does today (in order):**
1. Validate guideline, build `StudentContext`, load study plan
2. `convert_guideline_to_topic()`, `create_session()`
3. If teach_me and first step is "explain": `session.start_explanation(concept, step_id)` ← init explanation tracking
4. **`generate_welcome_message()`** ← LLM call (this is what we skip)
5. `session.add_message(create_teacher_message(welcome))` ← add to conversation history
6. `_persist_session(...)` ← write to DB
7. `event_repo.log(action="session_created")` ← audit trail
8. Build `first_turn` dict and return `CreateSessionResponse`

**For card phase, we skip step 3 (no ExplanationPhase init — cards replace it) and step 4 (no LLM call). Steps 5-8 must still happen with the pre-computed welcome text.**

Changes to `create_new_session()`:

```python
def create_new_session(self, request, user_id=None):
    # ... existing steps 1-2: validate, build context, load plan, create session ...

    # NEW: check for pre-computed explanations
    explanation_repo = ExplanationRepository(self.db)
    explanations = explanation_repo.get_by_guideline_id(guideline.id)

    if explanations and mode == "teach_me":
        # Card phase: skip welcome LLM call AND explanation phase init
        # (cards replace ExplanationPhase — no start_explanation() call)
        # Use first available variant (don't assume "A" exists — it may have
        # failed validation). available_variant_keys comes from actual DB results.
        first_variant = explanations[0]

        session.card_phase = CardPhaseState(
            guideline_id=guideline.id,
            active=True,
            current_variant_key=first_variant.variant_key,
            current_card_idx=0,
            total_cards=len(first_variant.cards_json),
            variants_shown=[first_variant.variant_key],
            available_variant_keys=[e.variant_key for e in explanations],
        )

        welcome_text = f"Let's learn about {topic.topic_name}! I'll walk you through it, and then we can talk about any questions."
        audio_text = welcome_text

        # first_turn is a plain dict (matching existing codebase pattern)
        first_turn = {
            "message": welcome_text,
            "audio_text": audio_text,
            "hints": [],
            "step_idx": session.current_step,
            # NEW fields:
            "explanation_cards": first_variant.cards_json,
            "session_phase": "card_phase",
            "card_phase_state": {
                "current_variant_key": first_variant.variant_key,
                "current_card_idx": 0,
                "total_cards": len(first_variant.cards_json),
                "available_variants": len(explanations),
            },
        }
    else:
        # Existing path: init explanation phase + dynamic welcome
        if mode == "teach_me":
            first_step = session.topic.study_plan.get_step(1) if session.topic else None
            if first_step and first_step.type == "explain":
                session.start_explanation(first_step.concept, first_step.step_id)
        welcome_text, audio_text = asyncio.run(self.orchestrator.generate_welcome_message(session))
        first_turn = {
            "message": welcome_text,
            "audio_text": audio_text,
            "hints": [],
            "step_idx": session.current_step,
        }

    # Steps 5-8 happen for BOTH paths (card phase and dynamic):
    session.add_message(create_teacher_message(welcome_text, audio_text=audio_text))
    self._persist_session(session_id, session, request, user_id=user_id, ...)
    self.event_repo.log(session_id=session_id, node="welcome",
                        step_idx=session.current_step,
                        payload={"action": "session_created", "mode": mode})
    return CreateSessionResponse(session_id=session_id, first_turn=first_turn, mode=mode)
```

New method for variant switching:

```python
def switch_explanation_variant(self, session_id: str, variant_key: str) -> dict:
    """Load a different explanation variant during card phase."""
    session = self._load_session(session_id)
    state = self._deserialize_state(session)

    if not state.is_in_card_phase():
        raise ValueError("Not in card phase")

    explanation = ExplanationRepository(self.db).get_variant(
        state.card_phase.guideline_id, variant_key
    )
    if not explanation:
        raise ValueError(f"Variant {variant_key} not found")

    state.card_phase.current_variant_key = variant_key
    state.card_phase.current_card_idx = 0
    state.card_phase.total_cards = len(explanation.cards_json)
    state.card_phase.variants_shown.append(variant_key)

    self._persist_session_state(session, state)

    return {
        "cards": explanation.cards_json,
        "variant_key": variant_key,
        "variant_label": explanation.variant_label,
    }
```

New method for completing card phase:

```python
def complete_card_phase(self, session_id: str, action: str) -> dict:
    """Handle card phase completion. action: 'clear' or 'explain_differently'."""
    session = self._load_session(session_id)
    state = self._deserialize_state(session)

    if action == "clear":
        state.complete_card_phase()
        # Mark all "explain" steps at the start of the study plan as complete
        # (cards covered the explanation). Advance current_step to the first
        # non-explain step (check/practice).
        self._advance_past_explanation_steps(state)
        self._persist_session_state(session, state)

        # Build explanation context summary for tutor
        precomputed_summary = self._build_precomputed_summary(state)

        return {
            "action": "transition_to_interactive",
            "message": "Great! Now let's make sure you've got it. Feel free to ask any questions!",
            "precomputed_summary": precomputed_summary,
        }

    elif action == "explain_differently":
        # Find next unseen variant
        unseen = [k for k in state.card_phase.available_variant_keys
                  if k not in state.card_phase.variants_shown]

        if unseen:
            # Use internal method to avoid double session load
            return self._switch_variant_internal(state, session, unseen[0])
        else:
            # All variants exhausted → fall back to dynamic ExplanationPhase
            state.complete_card_phase()
            self._init_dynamic_fallback(state)
            self._persist_session_state(session, state)

            # Generate a dynamic welcome for the fallback
            welcome, audio_text = asyncio.run(
                self.orchestrator.generate_welcome_message(state)
            )
            state.add_message(create_teacher_message(welcome, audio_text=audio_text))
            self._persist_session_state(session, state)

            return {
                "action": "fallback_dynamic",
                "message": welcome,
                "audio_text": audio_text,
            }
```

Helper for tutor context:

```python
def _build_precomputed_summary(self, state: SessionState) -> str:
    """Build summary of shown explanations for tutor system prompt injection."""
    if not state.card_phase:
        return ""

    repo = ExplanationRepository(self.db)
    summaries = []
    for variant_key in state.card_phase.variants_shown:
        explanation = repo.get_variant(state.card_phase.guideline_id, variant_key)
        if explanation and explanation.summary_json:
            s = explanation.summary_json
            summaries.append(
                f"Variant '{s['approach_label']}': "
                f"Topics covered: {', '.join(s['card_titles'])}. "
                f"Analogies used: {', '.join(s.get('key_analogies', []))}. "
                f"Examples used: {', '.join(s.get('key_examples', []))}."
            )

    return "\n".join(summaries)
```

**Dynamic fallback initialization** (issue: card phase → ExplanationPhase transition):

```python
def _init_dynamic_fallback(self, state: SessionState):
    """Initialize ExplanationPhase for dynamic fallback after all card variants exhausted.

    This enters the existing ExplanationPhase state machine mid-session.
    The orchestrator's process_turn() will naturally pick up from here.
    """
    # Find the first "explain" step in the study plan
    first_step = state.topic.study_plan.get_step(1) if state.topic else None
    if first_step and first_step.type == "explain":
        # Start at "opening" phase — the tutor will generate its own opening
        # since all pre-computed approaches failed
        state.start_explanation(first_step.concept, first_step.step_id)
        # The ExplanationPhase is now at "opening" (not_started → opening)
        # The orchestrator's _handle_explanation_phase() will advance it
        # through opening → explaining → informal_check → complete as normal
    else:
        # No explain step — just let the tutor proceed normally
        pass
```

**`_advance_past_explanation_steps()`** (for "clear" action):

```python
def _advance_past_explanation_steps(self, state: SessionState):
    """After successful card phase, skip consecutive leading explain steps.

    Cards cover the topic's introductory explanation holistically. This method
    skips consecutive "explain" steps at the start of the study plan, landing
    on the first non-explain step (typically "check" or "practice").

    ASSUMPTION: Pre-computed cards replace the leading explain block only.
    If the study plan has interleaved explain steps later (e.g., explain →
    check → explain → practice), the later explain steps are handled by the
    dynamic tutor. This is intentional — later explain steps often cover
    advanced sub-topics that benefit from interactive, personalized teaching.

    Example: [explain, explain, check, explain, practice]
              ^^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
              skipped by cards  handled by dynamic tutor
    """
    while state.current_step <= state.topic.study_plan.total_steps:
        step = state.topic.study_plan.get_step(state.current_step)
        if step and step.type == "explain":
            state.concepts_covered_set.add(step.concept)
            state.advance_step()
        else:
            break  # Found a non-explain step — stop here
```

**Session resume/refresh during card phase** (issue: complete user journey):

The existing `GET /sessions/{session_id}/replay` endpoint returns full session state including `state_json`. For card-phase sessions:

```python
# In sessions.py — GET /{session_id}/replay
@router.get("/{session_id}/replay")
def get_session_replay(session_id: str, db=Depends(get_db)):
    session = db.query(Session).get(session_id)
    state = json.loads(session.state_json)

    # If session is in card phase, include explanation cards for the active variant
    if state.get("card_phase") and state["card_phase"].get("active"):
        card_phase = state["card_phase"]
        repo = ExplanationRepository(db)
        explanation = repo.get_variant(
            card_phase["guideline_id"],
            card_phase["current_variant_key"]
        )
        if explanation:
            state["_replay_explanation_cards"] = explanation.cards_json

    return state
```

Frontend `ChatSession.tsx` handles this in the deep-link/refresh path:

```typescript
// In the "else → Deep link / page refresh" branch of useEffect:
const replay = await getSessionReplay(sessionId);
if (replay.card_phase?.active && replay._replay_explanation_cards) {
  // Restore card position from localStorage (server only stores variant, not card index)
  const savedPos = localStorage.getItem(`card-pos-${sessionId}`);
  const cardIdx = savedPos ? parseInt(savedPos, 10) : 0;

  setSessionPhase('card_phase');
  setExplanationCards(replay._replay_explanation_cards);
  setCurrentCardIdx(cardIdx);
  setCardPhaseState({
    current_variant_key: replay.card_phase.current_variant_key,
    current_card_idx: cardIdx,
    total_cards: replay.card_phase.total_cards,
    available_variants: replay.card_phase.available_variant_keys.length,
  });
} else {
  // Existing replay path (card phase completed or never started)
}
```

**Decision: Card position stored in localStorage, not server.** Card navigation is rapid (tap/swipe) — persisting every position change to the server would create unnecessary API calls. localStorage is sufficient for refresh recovery. On variant switch, localStorage is reset. On card phase completion, localStorage entry is cleaned up.

The `POST /sessions/{session_id}/resume` endpoint (for paused sessions) is not affected — card-phase sessions cannot be paused (pause only applies to teach_me sessions that have progressed past the explanation phase). If a card-phase session is abandoned (browser closed), the replay endpoint handles restoration.

### 4.10 Modified: Orchestrator

**File:** `llm-backend/tutor/orchestration/orchestrator.py`

No changes to the core `process_turn()` flow. Card navigation is handled by `SessionService` methods (REST endpoints), not by the orchestrator. The orchestrator only needs one change:

When the session transitions from `CardPhase` to interactive, the explanation context must be injected into the tutor's system prompt. This happens via the modified prompt construction (see 4.11).

Add to `_apply_state_updates()`:

```python
def _apply_state_updates(self, session, tutor_output):
    # ... existing logic ...

    # Skip explanation phase tracking if card phase was active
    # (card phase completion is handled by SessionService, not orchestrator)
    if session.state.is_in_card_phase():
        return False  # No state changes during card phase
```

### 4.11 Modified: Master Tutor Prompts

**File:** `llm-backend/tutor/prompts/master_tutor_prompts.py`

Add `{precomputed_explanation_summary_section}` to `MASTER_TUTOR_SYSTEM_PROMPT`:

```python
# After {prior_topics_context_section}, add:

PRECOMPUTED_EXPLANATION_BLOCK = """

## Pre-Explained Content

The student has already seen the following explanation(s) before this interactive session began. DO NOT repeat these analogies, examples, or explanations. If the student is confused, try a fundamentally different approach.

{precomputed_explanation_summary}
"""
```

In the prompt construction function, conditionally include this block:

```python
precomputed_explanation_summary_section = ""
if precomputed_summary:  # passed from session service
    precomputed_explanation_summary_section = PRECOMPUTED_EXPLANATION_BLOCK.format(
        precomputed_summary=precomputed_summary
    )
```

### 4.12 Modified: Study Plan Generator

**File:** `llm-backend/study_plans/services/generator_service.py`

Minor change: when generating a plan for a guideline that has pre-computed explanations, annotate explain steps.

**Decision: Deferred.** The study plan generator doesn't need to know about pre-computed explanations in v1. The session service handles the routing (card phase vs. dynamic) based on explanation availability, not based on study plan annotations. The `explanation_source` annotation from the PRD can be added later if the study plan needs to be aware. This keeps the study plan generator unchanged for now.

### 4.13 Modified: Session API

**File:** `llm-backend/tutor/api/sessions.py`

New endpoints for card phase:

```python
@router.post("/{session_id}/card-action")
def card_action(session_id: str, request: CardActionRequest, db=Depends(get_db)):
    """Handle card phase actions: clear (understood) or explain differently."""
    service = SessionService(db)

    if request.action in ("clear", "explain_differently"):
        result = service.complete_card_phase(session_id, request.action)
    else:
        raise HTTPException(400, f"Unknown action: {request.action}")

    return result
```

**Decision: No public `switch_variant` action.** Variant switching is an internal operation triggered by `explain_differently` → `complete_card_phase()` finds the next unseen variant internally. Exposing `switch_variant` publicly would bypass the "all variants exhausted" fallback logic. The frontend only needs two actions: "I understand" and "Explain differently".

### 4.14 Modified: Messages / DTOs

**File:** `llm-backend/tutor/models/messages.py`

New request/response models:

```python
class ExplanationCard(BaseModel):
    card_idx: int
    card_type: Literal["concept", "example", "visual", "analogy", "summary"]
    title: str
    content: str
    visual: Optional[str] = None

class CardActionRequest(BaseModel):
    action: Literal["clear", "explain_differently"]

class CardPhaseDTO(BaseModel):
    current_variant_key: str
    current_card_idx: int
    total_cards: int
    available_variants: int
```

**Note on `first_turn` construction:** The codebase constructs `first_turn` as a plain Python dict, not a Pydantic model. The new card-phase fields are added as dict keys (see section 4.9). The `Turn` TypeScript interface in `api.ts` is updated to include the new optional fields. No Python `Turn` Pydantic model exists — the response is a dict serialized directly by FastAPI.

---

## 5. Frontend Changes

### New component: `ExplanationViewer`

**File:** `llm-frontend/src/components/ExplanationViewer.tsx`

```typescript
interface ExplanationCard {
  card_idx: number;
  card_type: 'concept' | 'example' | 'visual' | 'analogy' | 'summary';
  title: string;
  content: string;
  visual?: string | null;
}

interface ExplanationViewerProps {
  cards: ExplanationCard[];
  currentIdx: number;
  totalCards: number;
  availableVariants: number;
  variantsShown: number;
  onNext: () => void;
  onPrevious: () => void;
  onClear: () => void;
  onExplainDifferently: () => void;
}
```

**UI structure:**
- Full-screen card view (replaces chat area during card phase)
- Card content area with styled rendering per card_type
- Visual block rendered as `<pre>` for ASCII diagrams
- Progress bar: "Card X of Y"
- Navigation: back/forward buttons or swipe gestures
- After last card: two buttons — "I understand" (→ `onClear`) and "Explain differently" (→ `onExplainDifferently`)
- Card type indicator (icon/label for concept/example/visual/analogy/summary)

### Modified: `ChatSession.tsx`

**New state variables:**

```typescript
// Card phase state
const [sessionPhase, setSessionPhase] = useState<'card_phase' | 'interactive'>('interactive');
const [explanationCards, setExplanationCards] = useState<ExplanationCard[]>([]);
const [currentCardIdx, setCurrentCardIdx] = useState(0);
const [cardPhaseState, setCardPhaseState] = useState<CardPhaseDTO | null>(null);
```

**Session initialization changes:**

```typescript
// In useEffect for session init:
if (locState?.firstTurn?.session_phase === 'card_phase') {
  setSessionPhase('card_phase');
  setExplanationCards(locState.firstTurn.explanation_cards);
  setCardPhaseState(locState.firstTurn.card_phase_state);
  // Add welcome message to messages
  setMessages([{ role: 'teacher', content: locState.firstTurn.message }]);
} else {
  // Existing init path
}
```

**Card phase rendering:**

```tsx
// In render:
{sessionPhase === 'card_phase' ? (
  <ExplanationViewer
    cards={explanationCards}
    currentIdx={currentCardIdx}
    totalCards={explanationCards.length}
    availableVariants={cardPhaseState?.available_variants ?? 0}
    variantsShown={/* track locally */}
    onNext={() => {
      const next = Math.min(currentCardIdx + 1, explanationCards.length - 1);
      setCurrentCardIdx(next);
      localStorage.setItem(`card-pos-${sessionId}`, String(next));
    }}
    onPrevious={() => {
      const prev = Math.max(currentCardIdx - 1, 0);
      setCurrentCardIdx(prev);
      localStorage.setItem(`card-pos-${sessionId}`, String(prev));
    }}
    onClear={() => handleCardAction('clear')}
    onExplainDifferently={() => handleCardAction('explain_differently')}
  />
) : (
  // Existing chat UI (unchanged)
)}
```

**Card action handler:**

```typescript
async function handleCardAction(action: 'clear' | 'explain_differently') {
  const result = await cardAction(sessionId, action);

  if (result.action === 'transition_to_interactive') {
    setSessionPhase('interactive');
    setMessages(prev => [...prev, { role: 'teacher', content: result.message }]);
  } else if (result.cards) {
    // Loaded new variant
    setExplanationCards(result.cards);
    setCurrentCardIdx(0);
  } else if (result.action === 'fallback_dynamic') {
    // All variants exhausted, entering dynamic tutor
    setSessionPhase('interactive');
    setMessages(prev => [...prev, { role: 'teacher', content: result.message }]);
  }
}
```

**Session replay/resume:** When replaying a session that was in card phase, check `session_state.card_phase` and restore card position. If card phase was completed, render in interactive mode with conversation history.

### Modified: `api.ts`

New types:

```typescript
interface ExplanationCard {
  card_idx: number;
  card_type: 'concept' | 'example' | 'visual' | 'analogy' | 'summary';
  title: string;
  content: string;
  visual?: string | null;
}

interface CardPhaseDTO {
  current_variant_key: string;
  current_card_idx: number;
  total_cards: number;
  available_variants: number;
}

// Updated Turn interface
interface Turn {
  // ... existing fields ...
  explanation_cards?: ExplanationCard[];
  session_phase?: 'card_phase' | 'interactive';
  card_phase_state?: CardPhaseDTO;
}
```

New API function:

```typescript
export async function cardAction(
  sessionId: string,
  action: 'clear' | 'explain_differently'
): Promise<any> {
  return apiFetch(`/sessions/${sessionId}/card-action`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  });
}
```

---

## 6. LLM Integration

### Explanation Generator

- **Model:** Configured via `LLMConfig` with `component_key="explanation_generator"`. Default: `gpt-5.2` / openai.
- **Reasoning effort:** `high` for generation and refinement, `medium` for critique.
- **Calls per topic:** 3 variants × 3 passes (generate + critique + refine) = up to 9 LLM calls per topic. Critique may return `overall_quality: "good"` → skip refinement → 3 variants × 2 calls = 6 calls.
- **Structured output:** Strict JSON schema mode (same pattern as study plan generator).
- **Token estimate:** ~2K input (guideline + metadata + prior context) + ~2K output (7-10 cards) per generation call. ~4K per critique (includes cards). Total per topic: ~30-50K tokens across all calls.
- **Cost:** Acceptable for offline, batch processing. Each chapter has 5-7 topics → 150-350K tokens per chapter.

### Prompt design notes

- Generation prompt embeds key principles from `how-to-explain.md` directly (not referenced by path)
- Prompt includes grade level, subject, and guideline text as context
- `prior_topics_context` is included with instruction: "Weave natural references to prior topics into the explanation where relevant"
- Each variant config specifies the pedagogical approach to follow
- Critique prompt lists all 12 principles as a checklist

---

## 7. Configuration & Environment

### New environment variables

None. The explanation generator uses the existing `LLMConfig` infrastructure.

### Config changes

No changes to `config.py`. New `LLMConfig` seed entry (component_key: `explanation_generator`) added in `db.py` migration.

---

## 8. Implementation Order

| Step | What to Build | Files | Depends On | Testable? |
|------|---------------|-------|------------|-----------|
| 1 | `TopicExplanation` entity + migration | `entities.py`, `db.py` | — | Run `migrate()`, verify table created |
| 2 | `ExplanationRepository` | `shared/repositories/explanation_repository.py` | Step 1 | Unit test: CRUD operations on `topic_explanations` |
| 3 | Generation + critique prompts | `book_ingestion_v2/prompts/explanation_generation.txt`, `explanation_critique.txt` | — | Manual review of prompt quality |
| 4 | `ExplanationGeneratorService` | `book_ingestion_v2/services/explanation_generator_service.py` | Steps 2, 3 | Generate explanations for a test guideline, inspect cards in DB |
| 5 | Generate-explanations endpoint + response model | `sync_routes.py`, `schemas.py` | Step 4 | POST generate-explanations for a chapter, verify explanations in DB |
| 6 | `CardPhaseState` model | `session_state.py` | — | Unit test: serialization/deserialization |
| 7 | `ExplanationCard`, `CardActionRequest`, updated `Turn` DTOs | `messages.py` | — | Unit test: model validation |
| 8 | Session service changes: card detection, variant switching, phase completion, explanation context | `session_service.py` | Steps 2, 6, 7 | Create session for topic with explanations → verify cards in response, no LLM welcome call |
| 9 | Card action API endpoint | `sessions.py` | Step 8 | POST card-action with clear/explain_differently, verify state transitions |
| 10 | Master tutor prompt: `{precomputed_explanation_summary}` section | `master_tutor_prompts.py` | Step 8 | Start session with explanations, complete card phase, verify context in tutor prompt |
| 11 | Frontend: `ExplanationViewer` component | `ExplanationViewer.tsx` | — | Render mock cards, test navigation |
| 12 | Frontend: `ChatSession.tsx` card phase integration | `ChatSession.tsx` | Steps 9, 11 | End-to-end: start session → see cards → clear → interactive chat |
| 13 | Frontend: `api.ts` types + `cardAction()` function | `api.ts` | Step 9 | API calls work with backend |

**Rationale:** Database and repository first (foundation). Then generation service (can test offline). Then sync integration (pipeline works end-to-end offline). Then session service (runtime reads). Then API. Then frontend. Each step is independently testable.

---

## 9. Testing Plan

### Unit tests

| Test | What it Verifies | Key Mocks |
|------|------------------|-----------|
| `test_explanation_repository_crud` | Upsert, get, delete, has_explanations | In-memory DB |
| `test_explanation_repository_cascade_delete` | Deleting guideline cascades to explanations | In-memory DB |
| `test_explanation_generator_single_variant` | Generate → critique → refine pipeline | Mock LLM responses |
| `test_explanation_generator_skip_refine` | Critique returns "good" → no refine call | Mock LLM |
| `test_session_creation_with_explanations` | Card phase initialized, welcome not generated via LLM | Mock repo with explanations |
| `test_session_creation_without_explanations` | Falls back to dynamic welcome | Mock repo empty |
| `test_card_action_clear` | Card phase completed, state transitions | Session state assertions |
| `test_card_action_explain_differently` | Variant switched, cards returned | Mock repo |
| `test_card_action_all_variants_exhausted` | Falls back to dynamic tutor | Mock repo |
| `test_precomputed_summary_summary` | Summary built from shown variants | Mock repo with summary_json |
| `test_card_phase_state_serialization` | CardPhaseState round-trips through JSON (including guideline_id) | Pure model test |
| `test_dynamic_fallback_init` | All variants exhausted → ExplanationPhase initialized at "opening" | Session state assertions |
| `test_advance_past_explanation_steps` | "Clear" action skips explain steps, lands on first check/practice | Session state + step index |
| `test_session_replay_card_phase` | Replay endpoint returns explanation cards for active card phase | Mock repo + session state |
| `test_card_validation_min_cards` | Variant with < 3 cards is not stored | Mock LLM returning 2 cards |
| `test_card_validation_poor_quality` | Variant with "poor" critique after refine is not stored | Mock LLM |
| `test_backfill_endpoint` | Generate explanations without re-sync | Mock generator service |

### Manual verification

1. **Offline pipeline:** Run sync on a test book chapter → verify `topic_explanations` rows created with sensible cards
2. **Session creation:** Start teach_me session for a synced topic → verify instant cards, no loading spinner
3. **Card navigation:** Tap through cards → verify all card types render, progress indicator works
4. **Variant switch:** Click "Explain differently" → verify new cards load instantly
5. **Transition to interactive:** Click "I understand" → verify chat starts, tutor has context
6. **Fallback:** Start session for topic without explanations → verify existing dynamic flow unchanged
7. **Session resume:** Refresh page during card phase → verify card position restored, correct variant loaded
8. **Dynamic fallback:** Exhaust all variants → verify dynamic tutor takes over with ExplanationPhase, welcome generated, existing orchestrator flow works
9. **Re-sync recovery:** Sync a chapter (wipes explanations), check explanation_errors in response, then run backfill endpoint to regenerate
10. **Card validation:** Inspect generated cards for minimum count and quality — verify poor-quality variants are skipped

---

## 10. Deployment Considerations

### Migration

- `TopicExplanation` table creation is handled by `Base.metadata.create_all()` (existing pattern)
- The `explanation_generator` LLM config seed is added only if `llm_config` table is empty (won't apply to production where configs already exist). For production, manually insert: `INSERT INTO llm_config (component_key, provider, model_id, description) VALUES ('explanation_generator', 'openai', 'gpt-5.2', 'Pre-computed explanation generation')`
- Migration can be deployed before code changes (table creation is safe)

### Rollout

- **Phase 1:** Deploy backend + migration. No user-facing changes. Sync existing books to generate explanations (admin action).
- **Phase 2:** Deploy frontend. New sessions on topics with explanations will use card phase.
- **No feature flag needed.** Graceful fallback: topics without explanations use the existing dynamic flow. No breaking change.

### Rollback

- If cards cause issues: delete all rows from `topic_explanations` table. Sessions will fall back to dynamic flow automatically.
- Frontend can be rolled back independently — backend still serves the same `Turn` structure (just with `explanation_cards: null`).

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Re-sync cascade-deletes explanations; admin forgets to regenerate | Medium | Medium | Two-step admin workflow (Sync → Generate Explanations). WARNING logs for missing explanations. Graceful fallback to dynamic tutoring. |
| LLM generates poor-quality cards | Low | Medium | Multi-pass pipeline (critique + refine). Manual review of first few chapters. Principles doc guides prompt. |
| Card phase UX feels rigid (no mid-card questions) | Low | Medium | V1 trade-off accepted. Cards are short (15-30s). Escape hatch planned for v2. |
| Large token usage for explanation generation | Low | Low | Offline batch processing, cost amortizes. ~30-50K tokens per topic is acceptable. |
| Session state JSON grows with CardPhaseState | Low | Low | CardPhaseState is small (~200 bytes). Negligible vs existing state_json. |
| Frontend complexity in ChatSession.tsx | Medium | Medium | ExplanationViewer is a separate component. ChatSession only adds phase routing. |

---

## 12. Open Questions

- **Variant count:** Should we always generate 3 variants, or make it configurable per grade/subject? For v1, hardcoded 3 is simplest.
- **Card count target:** Should the prompt specify a target card count (e.g., 5-8 cards)? Or let the LLM decide based on topic complexity? Recommend: soft guidance ("typically 5-10 cards") in the prompt.
- **TTS for cards / virtual teacher mode:** During card phase, the virtual teacher avatar shows the still image for the entire duration (no audio, no speaking state). This is a known UX gap. Future enhancement: auto-play TTS per card with animated GIF synced to playback — the card `content` field is suitable for TTS input.
- **Analytics:** Track which variant students choose and whether they understand after each variant? Useful for optimizing variant ordering. Deferred to post-v1.
