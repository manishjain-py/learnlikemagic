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
- Triggered post-sync via existing sync routes
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
  (inject {explanation_context} summary into system prompt)
```

### New modules

| Module | Purpose |
|--------|---------|
| `book_ingestion_v2/services/explanation_generator_service.py` | Multi-pass LLM generation of explanation variants |
| `book_ingestion_v2/repositories/explanation_repository.py` | CRUD for `topic_explanations` table |
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
| `tutor/prompts/master_tutor_prompts.py` | `{explanation_context}` section |
| `tutor/api/sessions.py` | Updated response shapes, card navigation endpoint |
| `tutor/models/messages.py` | New DTOs for explanation cards |
| `study_plans/services/generator_service.py` | Annotate explain steps with `explanation_source` |
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
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_topic_explanations_guideline_variant
    ON topic_explanations (guideline_id, variant_key);
```

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

New function in `db.py`: `_apply_topic_explanations_table()`. Follows existing pattern — uses `Base.metadata.create_all()` for initial table creation, then checks for unique index and adds if missing.

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
    inspector = inspect(db_manager.engine)
    existing_tables = inspector.get_table_names()
    if "topic_explanations" not in existing_tables:
        # Base.metadata.create_all() in migrate() handles creation.
        # Just ensure unique index exists.
        pass
    if "topic_explanations" in inspector.get_table_names():
        constraints = inspector.get_unique_constraints("topic_explanations")
        constraint_names = {c["name"] for c in constraints}
        if "uq_explanation_guideline_variant" not in constraint_names:
            with db_manager.engine.connect() as conn:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_explanations_guideline_variant "
                    "ON topic_explanations (guideline_id, variant_key)"
                ))
                conn.commit()
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

### 4.3 Explanation Repository

**New file:** `llm-backend/book_ingestion_v2/repositories/explanation_repository.py`

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
```

**Decision: Repository lives in `book_ingestion_v2/repositories/`.** It's written by the ingestion pipeline and read by the tutor session service. The tutor module imports the repository directly (same pattern as how tutor imports `TeachingGuidelineRepository` from `shared/repositories/`). If this coupling feels wrong later, we can move it to `shared/repositories/`.

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

    def _build_summary(self, cards: list[dict], variant_label: str) -> dict:
        """Extract summary_json from cards (card titles, key analogies, key examples)."""

    def generate_for_chapter(self, book_id: str, chapter_id: str) -> dict:
        """Generate explanations for all synced guidelines in a chapter."""
```

**Multi-pass pipeline per variant:**
```
1. _generate_cards()     → raw cards list
2. _critique_cards()     → critique feedback (issues, suggestions)
3. _refine_cards()       → improved cards list
4. _build_summary()      → summary_json for tutor context
5. repo.upsert()         → persist to DB
```

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
  ]
}
```

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

### 4.6 Modified: Topic Sync Service

**File:** `llm-backend/book_ingestion_v2/services/topic_sync_service.py`

Add explanation generation after sync completes:

```python
def sync_chapter(self, book_id: str, chapter_id: str) -> SyncResponse:
    # ... existing sync logic (unchanged) ...

    # NEW: trigger explanation generation for synced guidelines
    explanation_results = self._generate_explanations_for_synced(synced_guideline_ids)

    return SyncResponse(
        synced_chapters=1,
        synced_topics=len(synced_guideline_ids),
        explanations_generated=explanation_results["generated"],
        explanation_errors=explanation_results["errors"],
        errors=errors
    )

def _generate_explanations_for_synced(self, guideline_ids: list[str]) -> dict:
    """Generate explanations for each synced guideline."""
    # Create ExplanationGeneratorService with LLM config
    # For each guideline_id: generate_for_guideline()
    # Catch and log errors per guideline (don't fail sync)
    # Return {"generated": count, "errors": [error_msgs]}
```

**Decision: Explanation generation is part of sync, not a separate step.** Simplifies the admin workflow — one button does everything. Errors in explanation generation don't fail the sync (topics are still usable with dynamic tutoring). This matches the PRD: "triggered as part of the same admin pipeline action."

**Decision: Sync is already slow (LLM calls for each topic's curriculum context). Adding explanation generation makes it slower.** Acceptable because sync is an admin-triggered, infrequent operation. We log progress per topic.

### 4.7 Modified: Sync Routes

**File:** `llm-backend/book_ingestion_v2/api/sync_routes.py`

Update `SyncResponse` model to include explanation generation results:

```python
class SyncResponse(BaseModel):
    synced_chapters: int
    synced_topics: int
    errors: list[str]
    explanations_generated: int = 0       # NEW
    explanation_errors: list[str] = []    # NEW
```

### 4.8 Session State Changes

**File:** `llm-backend/tutor/models/session_state.py`

New model:

```python
class CardPhaseState(BaseModel):
    """Tracks card-based explanation phase for pre-computed explanations."""
    active: bool = True
    current_variant_key: str = "A"
    current_card_idx: int = 0
    total_cards: int = 0
    variants_shown: list[str] = []        # ["A"] or ["A", "B"]
    available_variant_keys: list[str] = [] # ["A", "B", "C"]
    completed: bool = False               # True when student says "clear" or exhausts variants
```

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

Changes to `create_new_session()`:

```python
def create_new_session(self, request, user_id=None):
    # ... existing: validate guideline, build StudentContext, load study plan ...
    # ... existing: convert_guideline_to_topic(), create_session() ...

    # NEW: check for pre-computed explanations
    explanation_repo = ExplanationRepository(self.db)
    explanations = explanation_repo.get_by_guideline_id(guideline.id)

    if explanations and session_state.mode == "teach_me":
        # Card phase: skip welcome LLM call, return cards
        variant_a = next((e for e in explanations if e.variant_key == "A"), explanations[0])

        session_state.card_phase = CardPhaseState(
            active=True,
            current_variant_key=variant_a.variant_key,
            current_card_idx=0,
            total_cards=len(variant_a.cards_json),
            variants_shown=[variant_a.variant_key],
            available_variant_keys=[e.variant_key for e in explanations],
        )

        welcome_text = f"Let's learn about {topic.topic_name}! I'll walk you through it, and then we can talk about any questions."
        first_turn = Turn(
            message=welcome_text,
            audio_text=welcome_text,
            hints=[],
            step_idx=0,
            mastery_score=0.0,
            # NEW fields:
            explanation_cards=variant_a.cards_json,
            session_phase="card_phase",
            card_phase_state={
                "current_variant_key": variant_a.variant_key,
                "current_card_idx": 0,
                "total_cards": len(variant_a.cards_json),
                "available_variants": len(explanations),
            },
        )
    else:
        # Existing path: dynamic welcome
        # ... generate_welcome_message() ...

    # ... persist session, return response ...
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
        state.topic.topic_id, variant_key
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
        # Initialize explanation tracking for the post-card interactive phase
        # (skips ExplanationPhase, moves to next step type)
        self._advance_past_explanation_steps(state)
        self._persist_session_state(session, state)

        # Build explanation context summary for tutor
        explanation_context = self._build_explanation_context(state)

        return {
            "action": "transition_to_interactive",
            "message": "Great! Now let's make sure you've got it. Feel free to ask any questions!",
            "explanation_context": explanation_context,
        }

    elif action == "explain_differently":
        # Find next unseen variant
        unseen = [k for k in state.card_phase.available_variant_keys
                  if k not in state.card_phase.variants_shown]

        if unseen:
            return self.switch_explanation_variant(session_id, unseen[0])
        else:
            # All variants exhausted → fall back to dynamic tutor
            state.complete_card_phase()
            self._persist_session_state(session, state)
            return {
                "action": "fallback_dynamic",
                "message": "Let me try explaining this in a completely different way...",
            }
```

Helper for tutor context:

```python
def _build_explanation_context(self, state: SessionState) -> str:
    """Build summary of shown explanations for tutor system prompt injection."""
    if not state.card_phase:
        return ""

    repo = ExplanationRepository(self.db)
    summaries = []
    for variant_key in state.card_phase.variants_shown:
        explanation = repo.get_variant(state.topic.topic_id, variant_key)
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

Add `{explanation_context_section}` to `MASTER_TUTOR_SYSTEM_PROMPT`:

```python
# After {prior_topics_context_section}, add:

EXPLANATION_CONTEXT_BLOCK = """

## Pre-Explained Content

The student has already seen the following explanation(s) before this interactive session began. DO NOT repeat these analogies, examples, or explanations. If the student is confused, try a fundamentally different approach.

{explanation_context}
"""
```

In the prompt construction function, conditionally include this block:

```python
explanation_context_section = ""
if explanation_context:  # passed from session service
    explanation_context_section = EXPLANATION_CONTEXT_BLOCK.format(
        explanation_context=explanation_context
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
    """Handle card phase actions: switch variant or complete."""
    service = SessionService(db)

    if request.action == "switch_variant":
        result = service.switch_explanation_variant(session_id, request.variant_key)
    elif request.action in ("clear", "explain_differently"):
        result = service.complete_card_phase(session_id, request.action)
    else:
        raise HTTPException(400, f"Unknown action: {request.action}")

    return result
```

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
    action: Literal["switch_variant", "clear", "explain_differently"]
    variant_key: Optional[str] = None  # required for switch_variant

class CardPhaseDTO(BaseModel):
    current_variant_key: str
    current_card_idx: int
    total_cards: int
    available_variants: int
```

Update `Turn` model:

```python
class Turn(BaseModel):
    # ... existing fields ...
    explanation_cards: Optional[list[dict]] = None    # NEW
    session_phase: Optional[str] = None               # NEW: "card_phase" or "interactive"
    card_phase_state: Optional[CardPhaseDTO] = None   # NEW
```

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
    onNext={() => setCurrentCardIdx(i => Math.min(i + 1, explanationCards.length - 1))}
    onPrevious={() => setCurrentCardIdx(i => Math.max(i - 1, 0))}
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
  action: 'switch_variant' | 'clear' | 'explain_differently',
  variantKey?: string
): Promise<any> {
  return apiFetch(`/sessions/${sessionId}/card-action`, {
    method: 'POST',
    body: JSON.stringify({ action, variant_key: variantKey }),
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
| 2 | `ExplanationRepository` | `book_ingestion_v2/repositories/explanation_repository.py` | Step 1 | Unit test: CRUD operations on `topic_explanations` |
| 3 | Generation + critique prompts | `book_ingestion_v2/prompts/explanation_generation.txt`, `explanation_critique.txt` | — | Manual review of prompt quality |
| 4 | `ExplanationGeneratorService` | `book_ingestion_v2/services/explanation_generator_service.py` | Steps 2, 3 | Generate explanations for a test guideline, inspect cards in DB |
| 5 | Integrate into `TopicSyncService` | `topic_sync_service.py`, `sync_routes.py` | Step 4 | Run sync on a book, verify explanations generated |
| 6 | `CardPhaseState` model | `session_state.py` | — | Unit test: serialization/deserialization |
| 7 | `ExplanationCard`, `CardActionRequest`, updated `Turn` DTOs | `messages.py` | — | Unit test: model validation |
| 8 | Session service changes: card detection, variant switching, phase completion, explanation context | `session_service.py` | Steps 2, 6, 7 | Create session for topic with explanations → verify cards in response, no LLM welcome call |
| 9 | Card action API endpoint | `sessions.py` | Step 8 | POST card-action with clear/explain_differently, verify state transitions |
| 10 | Master tutor prompt: `{explanation_context}` section | `master_tutor_prompts.py` | Step 8 | Start session with explanations, complete card phase, verify context in tutor prompt |
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
| `test_explanation_context_summary` | Summary built from shown variants | Mock repo with summary_json |
| `test_card_phase_state_serialization` | CardPhaseState round-trips through JSON | Pure model test |

### Manual verification

1. **Offline pipeline:** Run sync on a test book chapter → verify `topic_explanations` rows created with sensible cards
2. **Session creation:** Start teach_me session for a synced topic → verify instant cards, no loading spinner
3. **Card navigation:** Tap through cards → verify all card types render, progress indicator works
4. **Variant switch:** Click "Explain differently" → verify new cards load instantly
5. **Transition to interactive:** Click "I understand" → verify chat starts, tutor has context
6. **Fallback:** Start session for topic without explanations → verify existing dynamic flow unchanged
7. **Session resume:** Refresh page during card phase → verify card position restored

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
| Sync becomes too slow with explanation generation | Medium | Low | Explanation generation errors don't fail sync. Can be made async/background job later. |
| LLM generates poor-quality cards | Low | Medium | Multi-pass pipeline (critique + refine). Manual review of first few chapters. Principles doc guides prompt. |
| Card phase UX feels rigid (no mid-card questions) | Low | Medium | V1 trade-off accepted. Cards are short (15-30s). Escape hatch planned for v2. |
| Large token usage for explanation generation | Low | Low | Offline batch processing, cost amortizes. ~30-50K tokens per topic is acceptable. |
| Session state JSON grows with CardPhaseState | Low | Low | CardPhaseState is small (~200 bytes). Negligible vs existing state_json. |
| Frontend complexity in ChatSession.tsx | Medium | Medium | ExplanationViewer is a separate component. ChatSession only adds phase routing. |

---

## 12. Open Questions

- **Variant count:** Should we always generate 3 variants, or make it configurable per grade/subject? For v1, hardcoded 3 is simplest.
- **Card count target:** Should the prompt specify a target card count (e.g., 5-8 cards)? Or let the LLM decide based on topic complexity? Recommend: soft guidance ("typically 5-10 cards") in the prompt.
- **TTS for cards:** Should cards be read aloud (TTS) in virtual teacher mode? Not in v1 scope, but worth considering. The content field is suitable for TTS.
- **Analytics:** Track which variant students choose and whether they understand after each variant? Useful for optimizing variant ordering. Deferred to post-v1.
