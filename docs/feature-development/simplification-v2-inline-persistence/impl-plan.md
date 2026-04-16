# Tech Implementation Plan: "I Didn't Understand" v2

**Date:** 2026-04-10 | **Status:** Draft | **PRD:** `docs/feature-development/simplification-v2-inline-persistence/prd.md`

---

## 1. Overview

Two changes to the per-card simplification feature:
1. **Inline expansion** — simplified content appends within the same card (no carousel insertion). Fixes the v1 navigation bug and keeps original + simplified content visible together.
2. **Per-student persistence** — new `student_topic_cards` table stores simplification overlays. Returning students see their personalized cards immediately.

---

## 2. Architecture

```
CURRENT SESSION:
  Student taps "I didn't understand" on card 3
    -> POST /sessions/{id}/simplify-card { card_idx: 3 }
    -> SessionService.simplify_card()
       -> Orchestrator.generate_simplified_card() (returns lines[] + visual)
       -> In ONE transaction:
          -> Store in session.card_phase.remedial_cards[3]
          -> Upsert to student_topic_cards (user_id, guideline_id, variant_key)  <-- NEW
    -> Response: { action: "append_to_card", simplification: {...} }             <-- CHANGED
    -> Frontend: append to card.simplifications[], auto-scroll, typewriter

NEXT VISIT:
  create_new_session(user_id, guideline_id)
    -> Find student's last-used variant from student_topic_cards                 <-- NEW
    -> Load base cards from TopicExplanation (saved variant or default)
    -> Lookup student_topic_cards(user_id, guideline_id, variant_key)            <-- NEW
    -> If found AND explanation_id matches: attach saved simplifications
    -> If explanation_id differs: delete stale record, start fresh
    -> Frontend: render inline sections from start (no typewriter for pre-loaded)
```

### New modules

| Module | Purpose |
|--------|---------|
| `shared/models/entities.py` | `StudentTopicCards` ORM model |
| `shared/repositories/student_topic_cards_repository.py` | CRUD for per-student simplifications |

### Modified modules

| Module | Change |
|--------|--------|
| `tutor/agents/master_tutor.py` | `SimplifiedCardOutput` gains `lines` field |
| `tutor/prompts/master_tutor_prompts.py` | Prompt updated to return structured `lines[]` |
| `tutor/orchestration/orchestrator.py` | Minor — pass `lines` through |
| `tutor/services/session_service.py` | `simplify_card()` upserts to `student_topic_cards`; `create_new_session()` pre-loads saved simplifications |
| `tutor/api/sessions.py` | Response format change; replay merges inline instead of inserting |
| `db.py` | Migration function for new table |
| `llm-frontend/src/api.ts` | `ExplanationCard.simplifications` field; update `simplifyCard()` response handling |
| `llm-frontend/src/pages/ChatSession.tsx` | Inline rendering, remove splice logic, auto-scroll, loading skeleton |
| `llm-frontend/src/components/TypewriterMarkdown.tsx` | Support animating appended sections |
| `llm-frontend/src/App.css` | Separator styles, skeleton animation, cleanup stale `.simplify-options` CSS |

---

## 3. Database

### Card Index Contract

`card_idx` has ONE canonical meaning everywhere:
- **0-based index into `variant.cards_json`** (which includes welcome card at index 0)
- Frontend `explanationCards[i]` = `cards_json[i]` = `carouselSlides[i]` during card_phase
- Frontend sends `currentSlideIdx` directly as `card_idx` — **no offset math**
- Persistence keys use the same `card_idx` (as string keys in the JSONB)
- The v1 `cardArrayIdx = currentSlideIdx - 1` offset is removed entirely

### New table: `student_topic_cards`

```sql
CREATE TABLE student_topic_cards (
    id              VARCHAR PRIMARY KEY,
    user_id         VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    guideline_id    VARCHAR NOT NULL REFERENCES teaching_guidelines(id) ON DELETE CASCADE,
    variant_key     VARCHAR NOT NULL,
    explanation_id  VARCHAR NOT NULL,
    simplifications JSONB NOT NULL DEFAULT '{}',
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_student_topic_cards_user_guideline_variant
    ON student_topic_cards(user_id, guideline_id, variant_key);
```

Key differences from v1 draft:
- **`UNIQUE (user_id, guideline_id, variant_key)`** — one row per variant. Switching variants doesn't destroy other variants' data.
- **`explanation_id`** replaces `base_card_count` — stores the `TopicExplanation.id` UUID. On read, if the current explanation has a different ID, saved simplifications are stale (explanations were regenerated). Catches same-count regenerations, reordered cards, and content changes.
- No `base_card_count` — `explanation_id` is a strictly stronger guard.

`simplifications` JSONB structure (keys are `card_idx` per the contract above):
```json
{
  "3": [
    {
      "content": "...",
      "lines": [{"display": "...", "audio": "..."}],
      "audio_text": "...",
      "visual_explanation": {"output_type": "image", "title": "...", "pixi_code": "..."}
    }
  ],
  "7": [
    {"content": "...", "lines": [...], "audio_text": "...", "visual_explanation": null}
  ]
}
```

### Migration

Add to `db.py` as `_apply_student_topic_cards()`, called from `migrate()`. Pattern matches existing migrations (e.g., `_apply_study_plans_user_id`):

```python
def _apply_student_topic_cards(db_manager):
    """Ensure student_topic_cards table exists."""
    inspector = inspect(db_manager.engine)
    if "student_topic_cards" not in inspector.get_table_names():
        # Table will be created by Base.metadata.create_all() from the ORM model
        pass
    # No column migrations needed — new table
```

The ORM model in `entities.py` + `Base.metadata.create_all()` handles table creation.

---

## 4. Backend

### Step 1: ORM Model

**File:** `shared/models/entities.py`

Add after `TopicExplanation` class (~line 338):

```python
class StudentTopicCards(Base):
    """Per-student, per-variant simplification overlays for explanation cards.

    Stores the simplifications a student generated via "I didn't understand"
    so they persist across sessions. One row per (user, guideline, variant).
    The overlay is merged with base cards from TopicExplanation on session creation.
    """
    __tablename__ = "student_topic_cards"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    guideline_id = Column(String, ForeignKey("teaching_guidelines.id", ondelete="CASCADE"), nullable=False)
    variant_key = Column(String, nullable=False)
    explanation_id = Column(String, nullable=False)  # TopicExplanation.id — stale guard
    simplifications = Column(JSONB, nullable=False, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "guideline_id", "variant_key",
                         name="uq_student_topic_cards_user_guideline_variant"),
    )
```

### Step 2: Repository

**File:** `shared/repositories/student_topic_cards_repository.py` (NEW)

```python
class StudentTopicCardsRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, user_id: str, guideline_id: str, variant_key: str) -> Optional[StudentTopicCards]:
        """Fetch saved simplifications for a student+topic+variant."""
        return self.db.query(StudentTopicCards).filter(
            StudentTopicCards.user_id == user_id,
            StudentTopicCards.guideline_id == guideline_id,
            StudentTopicCards.variant_key == variant_key,
        ).first()

    def get_most_recent(self, user_id: str, guideline_id: str) -> Optional[StudentTopicCards]:
        """Fetch the most recently used variant's record for a student+topic."""
        return self.db.query(StudentTopicCards).filter(
            StudentTopicCards.user_id == user_id,
            StudentTopicCards.guideline_id == guideline_id,
        ).order_by(StudentTopicCards.updated_at.desc()).first()

    def upsert(self, user_id: str, guideline_id: str, variant_key: str,
               explanation_id: str, card_idx: int, simplification: dict):
        """Add a simplification to the student's saved overlay.

        Does NOT commit — caller is responsible for committing the transaction
        (allows atomic write with session state persistence).
        """
        record = self.get(user_id, guideline_id, variant_key)
        if record:
            # Stale guard: if explanation was regenerated, reset simplifications
            if record.explanation_id != explanation_id:
                record.simplifications = {}
                record.explanation_id = explanation_id
            existing = record.simplifications or {}
            key = str(card_idx)
            if key not in existing:
                existing[key] = []
            existing[key].append(simplification)
            record.simplifications = existing
            record.updated_at = datetime.utcnow()
            flag_modified(record, "simplifications")
        else:
            record = StudentTopicCards(
                user_id=user_id,
                guideline_id=guideline_id,
                variant_key=variant_key,
                explanation_id=explanation_id,
                simplifications={str(card_idx): [simplification]},
            )
            self.db.add(record)
        # No commit here — caller commits both session state + this in one transaction

    def delete_stale(self, user_id: str, guideline_id: str, variant_key: str):
        """Delete a stale record (explanation was regenerated)."""
        self.db.query(StudentTopicCards).filter(
            StudentTopicCards.user_id == user_id,
            StudentTopicCards.guideline_id == guideline_id,
            StudentTopicCards.variant_key == variant_key,
        ).delete()
```

**Transaction boundary:** `upsert()` does NOT commit independently. The caller (`session_service.simplify_card()`) commits both the session state persistence and the student_topic_cards upsert in one `db.commit()`. This prevents partial-failure states where one write succeeds and the other fails.

### Step 3: Prompt — Add `lines[]` to Output

**File:** `tutor/prompts/master_tutor_prompts.py` (~line 282)

Change the output requirements section of `SIMPLIFY_CARD_PROMPT`:

```
### Output requirements
Return a single simplified explanation card as JSON:
- card_type: "simplification"
- title: A fresh, short title for this concept (3-6 words). Do NOT reuse the original title. Do NOT prefix with "Let's simplify:" or any meta-text.
- lines: An array of line objects. Each line has:
  - "display": one sentence of the simplified explanation (markdown OK)
  - "audio": TTS-friendly spoken version of that sentence (pure words, no symbols/markdown, Roman script only)
  One idea per line. Keep each line under 15 words. This is how the student will see the content revealed one line at a time.
- visual_prompt: A description of a helpful visual diagram or animation for this card. Be specific about objects, layout, colors, labels, and any animation steps. Set to null ONLY if the card truly doesn't benefit from any visual.
```

Remove the flat `content` and `audio_text` fields from the prompt — they'll be derived from `lines`.

### Step 4: Agent — Update `SimplifiedCardOutput` Schema

**File:** `tutor/agents/master_tutor.py` (~line 195)

```python
class SimplifiedCardLine(BaseModel):
    display: str = Field(description="One sentence of the explanation (markdown OK)")
    audio: str = Field(description="TTS-friendly spoken version (pure words, Roman script)")

class SimplifiedCardOutput(BaseModel):
    card_type: str = Field(default="simplification")
    title: str = Field(description="Simplified title")
    lines: list[SimplifiedCardLine] = Field(description="Per-line display+audio pairs")
    visual_prompt: Optional[str] = Field(default=None, description="Visual description or null")
```

In `generate_simplified_card()` (~line 286-320), after parsing the LLM output, derive `content` and `audio_text` from `lines`:

```python
result = validate_agent_output(output=parsed, model=output_model, ...)
result_dict = result.model_dump()

# Derive flat content and audio_text from lines
result_dict["content"] = "\n\n".join(line["display"] for line in result_dict["lines"])
result_dict["audio_text"] = " ".join(line["audio"] for line in result_dict["lines"])

return result_dict
```

### Step 5: Service — Upsert to `student_topic_cards`

**File:** `tutor/services/session_service.py`

In `simplify_card()` (~line 1200-1238), after building the remedial card but BEFORE the existing `_persist_session_state()` call:

```python
# Persist to student_topic_cards for cross-session persistence
# (same DB session — committed together with session state)
db_session = self._get_session_from_db(session_id)
if db_session and db_session.user_id:
    from shared.repositories.student_topic_cards_repository import StudentTopicCardsRepository
    stc_repo = StudentTopicCardsRepository(self.db)
    stc_repo.upsert(
        user_id=db_session.user_id,
        guideline_id=session.card_phase.guideline_id,
        variant_key=variant_key,
        explanation_id=variant.id,  # TopicExplanation.id — stale guard
        card_idx=card_idx,
        simplification=card_dict,
    )
# _persist_session_state() commits the transaction (both writes)
```

Change the response format (~line 1233):

```python
return {
    "action": "append_to_card",
    "source_card_idx": card_idx,
    "simplification": card_dict,
    "depth": depth,
    "card_id": card_id,
}
```

### Step 6: Service — Pre-load on Session Creation

**File:** `tutor/services/session_service.py`

In `create_new_session()`, BEFORE selecting the variant (~line 151), check for the student's last-used variant:

```python
# Check for student's last-used variant (for returning students)
preferred_variant_key = None
if user_id and explanations and mode == "teach_me":
    from shared.repositories.student_topic_cards_repository import StudentTopicCardsRepository
    stc_repo = StudentTopicCardsRepository(self.db)
    most_recent = stc_repo.get_most_recent(user_id, request.goal.guideline_id)
    if most_recent:
        preferred_variant_key = most_recent.variant_key

# Select variant: prefer saved, fall back to first available
if preferred_variant_key:
    first_variant = next(
        (e for e in explanations if e.variant_key == preferred_variant_key),
        explanations[0],  # fall back if saved variant no longer exists
    )
else:
    first_variant = explanations[0]
```

After initializing `CardPhaseState` (~line 164), pre-load saved simplifications:

```python
# Pre-load saved simplifications for returning students
if user_id and mode == "teach_me":
    saved = stc_repo.get(user_id, request.goal.guideline_id, first_variant.variant_key)
    if saved:
        if saved.explanation_id == first_variant.id:
            # Explanation unchanged — restore simplifications
            session.card_phase.remedial_cards = {
                int(k): [RemedialCard(
                    card_id=f"remedial_{first_variant.variant_key}_{k}_{i+1}",
                    source_card_idx=int(k),
                    depth=i + 1,
                    card=s,
                ) for i, s in enumerate(v)]
                for k, v in (saved.simplifications or {}).items()
            }
        else:
            # Explanation was regenerated — discard stale simplifications
            stc_repo.delete_stale(user_id, request.goal.guideline_id, first_variant.variant_key)
            self.db.commit()
```

This populates `remedial_cards` from saved data — same structure as if the student had just generated them. The rest of the pipeline (replay, frontend) works unchanged.

### Step 7: API — Replay Merge Change

**File:** `tutor/api/sessions.py` (~line 272-288)

Change the replay merge to attach simplifications inline instead of inserting separate cards:

```python
# Merge remedial cards as inline simplifications (not separate cards)
remedial_map = card_phase.get("remedial_cards", {})
variant_key = card_phase.get("current_variant_key", "A")
base_cards = state["_replay_explanation_cards"]

for i, card in enumerate(base_cards):
    card["card_id"] = f"{variant_key}_{i}"
    card["source_card_idx"] = i
    # Attach simplifications inline
    remedials = remedial_map.get(str(i), remedial_map.get(i, []))
    if remedials:
        card["simplifications"] = [
            r.get("card", {}) if isinstance(r, dict) else {}
            for r in remedials
        ]

state["_replay_explanation_cards"] = base_cards
```

No more inserting remedial cards as separate entries in the merged list.

### Step 8: API — Initial Session Response

The initial session response (returned from `create_new_session`) includes explanation cards via `firstTurn.explanation_cards`. If `remedial_cards` were pre-loaded (step 6), attach simplifications to the card dicts before returning:

**File:** `tutor/services/session_service.py` (~line 170, after building explanation cards for response)

```python
# Attach pre-loaded simplifications to card dicts for frontend
# card_idx = cards_json index = explanationCards index (per card index contract, no offset)
if session.card_phase.remedial_cards:
    for card_idx_str, remedials in session.card_phase.remedial_cards.items():
        idx = int(card_idx_str)
        if 0 <= idx < len(explanation_cards):
            explanation_cards[idx]["simplifications"] = [
                r.card for r in remedials
            ]
```

### Step 8b: Service — Variant Switch Wiring

**File:** `tutor/services/session_service.py` — `_switch_variant_internal()` (~line 1362)

When the student clicks "Explain differently", the existing code swaps the variant and clears `remedial_cards`. Add persistence awareness:

```python
def _switch_variant_internal(self, session, session_id, new_variant_key, ...):
    # ... existing variant switch logic ...

    # Load any saved simplifications for the new variant
    db_session = self._get_session_from_db(session_id)
    if db_session and db_session.user_id:
        stc_repo = StudentTopicCardsRepository(self.db)
        saved = stc_repo.get(db_session.user_id, session.card_phase.guideline_id, new_variant_key)
        new_variant = self.explanation_repo.get_variant(
            session.card_phase.guideline_id, new_variant_key)

        if saved and new_variant and saved.explanation_id == new_variant.id:
            # Restore saved simplifications for this variant
            session.card_phase.remedial_cards = {
                int(k): [RemedialCard(...) for i, s in enumerate(v)]
                for k, v in (saved.simplifications or {}).items()
            }
        else:
            session.card_phase.remedial_cards = {}
            # Clean up stale record if exists
            if saved:
                stc_repo.delete_stale(db_session.user_id,
                    session.card_phase.guideline_id, new_variant_key)
```

---

## 5. Frontend

### Step 9: API Types

**File:** `llm-frontend/src/api.ts` (~line 125)

Add `simplifications` to `ExplanationCard`:

```typescript
export interface ExplanationCard {
  // ... existing fields
  simplifications?: {
    content: string;
    lines?: ExplanationLine[];
    audio_text?: string;
    visual_explanation?: VisualExplanation | null;
    title?: string;
  }[];
}
```

Update `simplifyCard()` response handling (~line 664) to expect `append_to_card`:

```typescript
export async function simplifyCard(sessionId: string, cardIdx: number) {
  const res = await fetch(`${API}/sessions/${sessionId}/simplify-card`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ card_idx: cardIdx }),
  });
  return res.json();
  // Response: { action: "append_to_card", source_card_idx, simplification, depth, card_id }
}
```

### Step 10: handleSimplifyCard — Append Instead of Splice

**File:** `llm-frontend/src/pages/ChatSession.tsx` (~line 1246-1279)

Replace the entire `handleSimplifyCard` function:

```typescript
const handleSimplifyCard = async () => {
  if (!sessionId || simplifyLoading) return;

  // Per card index contract: currentSlideIdx = cards_json index = explanationCards index
  // No offset math. Welcome card (idx 0) never shows simplify button.
  const cardIdx = currentSlideIdx;
  if (cardIdx < 0 || cardIdx >= explanationCards.length) return;

  const currentCard = explanationCards[cardIdx];
  const baseCardIdx = currentCard.source_card_idx ?? cardIdx;

  setSimplifyLoading(true);
  setSimplifyJustAdded(false);
  try {
    const result = await simplifyCard(sessionId, baseCardIdx);

    if (result.action === 'append_to_card' && result.simplification) {
      // Append to the card's inline simplifications — no new card, no index change
      setExplanationCards(prev => {
        const updated = [...prev];
        if (cardIdx >= 0 && cardIdx < updated.length) {
          const card = { ...updated[cardIdx] };
          card.simplifications = [...(card.simplifications || []), result.simplification];
          updated[cardIdx] = card;
        }
        return updated;
      });
      setSimplifyJustAdded(true);
      // No setCurrentSlideIdx — we stay on the same card
      // Auto-scroll to new section (step 12)
    }
  } catch (err: any) {
    console.error('Simplify card failed:', err);
  } finally {
    setSimplifyLoading(false);
  }
};
```

Key differences from v1:
- **No `-1` offset** — `currentSlideIdx` sent directly as `card_idx` (per card index contract)
- No `splice` — no card insertion
- No `setCurrentSlideIdx` — user stays on same card
- Appends to `card.simplifications[]` instead

### Step 11: Card Rendering — Inline Simplification Sections

**File:** `llm-frontend/src/pages/ChatSession.tsx` (~line 1776-1810)

After the existing card content rendering (TypewriterMarkdown + visuals), add inline simplification sections:

```tsx
{/* Existing card content */}
<div className="focus-tutor-msg">
  <TypewriterMarkdown content={slide.content} title={slide.title} ... />
</div>
{revealedSlides.has(i) && slide.visual && (
  <pre className="explanation-card-visual">{slide.visual}</pre>
)}
{revealedSlides.has(i) && slide.visualExplanation && (
  <VisualExplanationComponent visual={slide.visualExplanation} />
)}

{/* Inline simplification sections */}
{slide.simplifications?.map((simplification, sIdx) => {
  const isNew = sIdx === slide.simplifications!.length - 1 && simplifyJustAdded;
  const separatorTexts = [
    "Let me break this down",
    "Even simpler",
    "One more way to think about it",
    "Let's try another angle",
  ];
  return (
    <div key={`simplification-${sIdx}`} className="inline-simplification">
      <div className="simplification-separator">
        <span>{separatorTexts[Math.min(sIdx, separatorTexts.length - 1)]}</span>
      </div>
      <div className="focus-tutor-msg">
        <TypewriterMarkdown
          content={simplification.content}
          title={simplification.title}
          isActive={i === currentSlideIdx && isNew}
          skipAnimation={!isNew}
          audioLines={simplification.lines}
          onRevealComplete={() => setSimplifyJustAdded(false)}
          onBlockTyped={async (audioText) => {
            if (audioText.trim()) await playLineAudio(audioText);
          }}
        />
      </div>
      {simplification.visual_explanation && (
        <VisualExplanationComponent visual={simplification.visual_explanation} />
      )}
    </div>
  );
})}

{/* Loading skeleton while generating */}
{simplifyLoading && i === currentSlideIdx && (
  <div className="inline-simplification">
    <div className="simplification-separator">
      <span>Let me break this down</span>
    </div>
    <div className="simplification-skeleton">
      <div className="skeleton-line" />
      <div className="skeleton-line short" />
      <div className="skeleton-line" />
    </div>
  </div>
)}
```

Add a `simplifyJustAdded` state variable to control typewriter animation for new simplifications only:
```typescript
const [simplifyJustAdded, setSimplifyJustAdded] = useState(false);
```
Set to `true` in `handleSimplifyCard` when a simplification is successfully appended.

### Step 12: Auto-Scroll to New Section

After the simplification is appended and the card re-renders, scroll the `.focus-slide` container to the bottom where the new section appears.

In `handleSimplifyCard`, after the state update:

```typescript
// Auto-scroll to the new simplification section
setTimeout(() => {
  const slide = document.querySelector(`.focus-slide:nth-child(${currentSlideIdx + 1})`);
  if (slide) {
    slide.scrollTo({ top: slide.scrollHeight, behavior: 'smooth' });
  }
}, 100);
```

### Step 13: Carousel Slide Derivation

**File:** `llm-frontend/src/pages/ChatSession.tsx` (~line 220-250)

Add `simplifications` to the slide object:

```typescript
slides.push({
  id: card.card_id || `card-${i}`,
  type: 'explanation',
  content: card.content,
  title: card.title,
  // ... existing fields
  simplifications: card.simplifications || [],  // <-- NEW
});
```

### Step 14: CSS — Separator, Skeleton, Cleanup

**File:** `llm-frontend/src/App.css`

Add new styles:

```css
/* Inline simplification sections */
.inline-simplification {
  margin-top: 24px;
}

.simplification-separator {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 20px 0 16px;
  color: #999;
  font-size: 0.85rem;
}
.simplification-separator::before,
.simplification-separator::after {
  content: '';
  flex: 1;
  height: 1px;
  background: #ddd;
}

/* Loading skeleton */
.simplification-skeleton {
  padding: 16px 0;
}
.skeleton-line {
  height: 14px;
  background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-radius: 4px;
  margin-bottom: 12px;
  width: 100%;
}
.skeleton-line.short {
  width: 60%;
}
@keyframes skeleton-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
```

Remove stale CSS for the old sub-options modal (~lines 2851-2902):
- `.simplify-options`
- `.simplify-options-header`
- `.simplify-options-label`
- `.simplify-options-close`
- `.simplify-options-row`
- `.simplify-option`
- `.simplify-option:hover`
- `.simplify-option:active`

---

## 6. Implementation Order

Dependency-ordered steps. Each step is independently testable.

| Order | Step | Description | Files |
|-------|------|-------------|-------|
| 1 | ORM model + migration | `StudentTopicCards` entity + `db.py` migration | `entities.py`, `db.py` |
| 2 | Repository | CRUD for `student_topic_cards` (per-variant, no independent commit) | `student_topic_cards_repository.py` (NEW) |
| 3 | Prompt + agent | `lines[]` in `SimplifiedCardOutput` + updated prompt | `master_tutor_prompts.py`, `master_tutor.py` |
| 4 | Service — write path | Upsert to `student_topic_cards` (same transaction as session state) | `session_service.py` |
| 5 | Service — read path | Variant selection + pre-load saved simplifications | `session_service.py` |
| 6 | Service — variant switch | Restore/clear simplifications on `_switch_variant_internal()` | `session_service.py` |
| 7 | API — response format | `append_to_card` response + replay merge change | `sessions.py` |
| 8 | Frontend — card index fix | Remove `-1` offset in `handleSimplifyCard`, align with contract | `ChatSession.tsx` |
| 9 | Frontend — API types | `simplifications` on `ExplanationCard` | `api.ts` |
| 10 | Frontend — handler | Replace splice with append-to-card logic | `ChatSession.tsx` |
| 11 | Frontend — rendering | Inline sections, separator, skeleton, auto-scroll | `ChatSession.tsx`, `App.css` |
| 12 | CSS cleanup | Remove stale `.simplify-options` styles | `App.css` |

---

## 7. Testing

| Test | Validates |
|------|-----------|
| `test_simplify_returns_append_to_card` | Response format is `append_to_card` with `simplification` dict containing `lines[]` |
| `test_simplification_has_lines` | LLM output includes `lines` array with `display` + `audio` pairs |
| `test_student_topic_cards_upsert` | Upsert creates record on first simplification, appends on subsequent |
| `test_student_topic_cards_per_variant` | Separate rows for variant A and B; switching doesn't destroy other variant's data |
| `test_student_topic_cards_preload` | New session pre-loads saved simplifications into `remedial_cards` |
| `test_preload_uses_saved_variant` | Returning student starts on their last-used variant, not always "A" |
| `test_preload_skips_stale_explanation` | Saved simplifications discarded when `explanation_id` differs (explanations regenerated) |
| `test_preload_deletes_stale_record` | Stale record is deleted, not silently ignored |
| `test_preload_skips_anonymous` | No pre-loading when `user_id` is None |
| `test_replay_inline_merge` | Replay attaches simplifications as `card.simplifications[]`, not separate cards |
| `test_variant_switch_restores_saved` | Switching to variant B restores B's previously saved simplifications |
| `test_variant_switch_clears_on_stale` | Switching to variant B clears simplifications if explanation_id doesn't match |
| `test_write_atomicity` | Session state + student_topic_cards written in same transaction; partial failure rolls back both |
| `test_guideline_cascade_delete` | Deleting guideline cascades to `student_topic_cards` |
| `test_card_idx_no_offset` | Frontend sends `currentSlideIdx` directly; backend receives correct card_idx |
| Frontend: inline render | Simplification sections appear below original content with separator |
| Frontend: auto-scroll | Card scrolls to new section after generation |
| Frontend: typewriter | New simplification gets typewriter animation; pre-loaded ones don't |
| Frontend: skeleton | Shimmer appears during generation, replaced by content on completion |
| Frontend: no index change | `currentSlideIdx` unchanged after simplification — no carousel navigation |

---

## 8. Key Files

| File | Status | Purpose |
|------|--------|---------|
| `shared/models/entities.py` | MODIFY | Add `StudentTopicCards` ORM model |
| `shared/repositories/student_topic_cards_repository.py` | NEW | CRUD for per-student simplifications |
| `db.py` | MODIFY | Migration for new table |
| `tutor/prompts/master_tutor_prompts.py` | MODIFY | Prompt returns `lines[]` instead of flat `content` |
| `tutor/agents/master_tutor.py` | MODIFY | `SimplifiedCardOutput` gains `lines` field |
| `tutor/orchestration/orchestrator.py` | MODIFY | Pass `lines` through (minor) |
| `tutor/services/session_service.py` | MODIFY | Write + read paths for `student_topic_cards`; response format change |
| `tutor/api/sessions.py` | MODIFY | `append_to_card` response; replay inline merge |
| `llm-frontend/src/api.ts` | MODIFY | `simplifications` field on `ExplanationCard` |
| `llm-frontend/src/pages/ChatSession.tsx` | MODIFY | Inline rendering, remove splice, auto-scroll, skeleton |
| `llm-frontend/src/App.css` | MODIFY | Separator, skeleton styles; remove stale `.simplify-options` |
