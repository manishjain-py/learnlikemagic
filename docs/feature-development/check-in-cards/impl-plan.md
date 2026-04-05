# Tech Implementation Plan: Check-In Cards

**Date:** 2026-04-05
**Status:** Draft
**PRD:** `docs/feature-development/check-in-cards/PRD.md`

---

## 1. Overview

Interactive check-in cards are match-the-pairs activities inserted between explanation cards at concept boundaries. They are generated offline by a new enrichment pipeline (mirroring `AnimationEnrichmentService`), stored as new card entries in the existing `cards_json` JSONB column, and rendered by a new frontend component with tap-to-match interaction and forward-navigation gating.

**High-level approach:**
- Extend `ExplanationCard` Pydantic model with `card_id` (UUID) and `check_in` (new struct)
- New `CheckInEnrichmentService` — reads explanation cards, calls LLM to generate match pairs at concept boundaries, inserts new `card_type="check_in"` cards into `cards_json`
- New `MatchActivity.tsx` frontend component — two-column tap-to-match UI with gate logic
- Struggle signals (retry counts, hints shown) forwarded to interactive tutor via `_build_precomputed_summary()`
- No new DB tables. No new API endpoints for student interaction. No server-side check-in state.

---

## 2. Architecture Changes

### Data flow

```
OFFLINE (enrichment pipeline)
═══════════════════════════════════════════════

  topic_explanations.cards_json (existing)
       ↓
  CheckInEnrichmentService.enrich_guideline()
       ↓ LLM: analyze cards → generate check-ins → validate
       ↓ Insert check_in cards, assign card_ids, re-number card_idx
  topic_explanations.cards_json (updated with check-in cards)

═══════════════════════════════════════════════
ONLINE (session time — no changes to flow)
═══════════════════════════════════════════════

  SessionService.create_new_session()
       ↓ loads cards_json (now includes check-in cards)
  Frontend receives all cards including check-ins
       ↓
  ChatSession.tsx renders check-in cards as MatchActivity
       ↓ gate: Next disabled until all pairs matched
  On phase transition → struggle signals added to summary
```

### New files

| File | Purpose |
|------|---------|
| `llm-backend/book_ingestion_v2/services/check_in_enrichment_service.py` | Pipeline service |
| `llm-backend/book_ingestion_v2/prompts/check_in_generation.txt` | LLM prompt |
| `llm-backend/scripts/run_check_in_enrichment.py` | CLI script |
| `llm-frontend/src/components/MatchActivity.tsx` | Match-the-pairs UI |

### Modified files

| File | Change |
|------|--------|
| `llm-backend/shared/repositories/explanation_repository.py` | Add `MatchPair`, `CheckInActivity` models; add `card_id` to `ExplanationCard` |
| `llm-backend/book_ingestion_v2/constants.py` | Add `V2JobType.CHECK_IN_ENRICHMENT` |
| `llm-backend/book_ingestion_v2/api/processing_routes.py` | Add check-in enrichment endpoint |
| `llm-frontend/src/api.ts` | Add `MatchPair`, `CheckInActivity` types; extend `ExplanationCard` |
| `llm-frontend/src/pages/ChatSession.tsx` | Add `check_in` slide type, gate logic, struggle tracking |
| `llm-frontend/src/App.css` | Match activity styles |
| `llm-frontend/src/features/admin/pages/ExplanationAdmin.tsx` | Add `check_in` badge color |

---

## 3. Database Changes

### No new tables

Check-in cards live inside the existing `topic_explanations.cards_json` JSONB column as additional entries in the card array.

### No schema migrations

`card_id` and `check_in` are added to the Pydantic model only. The JSONB column already stores arbitrary dicts — new fields appear naturally. Existing cards without `card_id` work fine (`Optional[str]`).

**Decision:** No migration needed. The `card_id` field is Optional in the Pydantic model. The enrichment pipeline assigns `card_id` to all cards (existing + new) when it runs. Cards loaded before enrichment simply have `card_id = None`, which is harmless — the frontend already uses `card_idx` for navigation and falls back gracefully.

---

## 4. Backend Changes

### 4.1 Shared Models (`shared/repositories/explanation_repository.py`)

Extend existing Pydantic models:

```python
class MatchPair(BaseModel):
    """A single left-right pair in a match activity."""
    left: str
    right: str

class CheckInActivity(BaseModel):
    """Match-the-pairs activity embedded in a check-in card."""
    activity_type: str = "match_pairs"  # extensible later
    instruction: str                     # "Match each fraction to its meaning"
    pairs: list[MatchPair]              # 3-4 pairs, stored in correct order
    hint: str                           # shown on wrong match
    success_message: str                # shown when all matched
    audio_text: str                     # TTS for instruction

class ExplanationCard(BaseModel):
    """Validated schema for cards stored in cards_json."""
    card_id: Optional[str] = None       # NEW — stable UUID, assigned by enrichment
    card_idx: int
    card_type: str                      # concept, example, visual, analogy, summary, check_in
    title: str
    content: str
    visual: Optional[str] = None
    audio_text: Optional[str] = None
    visual_explanation: Optional[CardVisualExplanation] = None
    check_in: Optional[CheckInActivity] = None  # NEW — populated for card_type="check_in"
```

**Decision:** Models live in `explanation_repository.py` alongside `ExplanationCard` rather than a new file — keeps the card schema in one place, matching existing pattern.

### 4.2 Check-In Enrichment Service (`book_ingestion_v2/services/check_in_enrichment_service.py`)

Mirrors `AnimationEnrichmentService` structure. Single LLM call per variant (not two-phase like visuals).

```python
class CheckInDecision(BaseModel):
    """LLM output: one check-in to insert."""
    insert_after_card_idx: int          # Insert after this card
    title: str                          # "Let's check!"
    instruction: str
    pairs: list[MatchPairOutput]
    hint: str
    success_message: str
    audio_text: str

class CheckInGenerationOutput(BaseModel):
    """Full structured output from the generation prompt."""
    check_ins: list[CheckInDecision]

class CheckInEnrichmentService:
    def __init__(self, db: DBSession, llm_service: LLMService)
    def enrich_guideline(self, guideline: TeachingGuideline, force: bool = False,
                         variant_keys: Optional[list[str]] = None,
                         heartbeat_fn: Optional[callable] = None) -> dict
    def enrich_chapter(self, book_id: str, chapter_id: Optional[str] = None,
                       force: bool = False, job_service=None, job_id: Optional[str] = None) -> dict
```

**Internal pipeline per variant:**

1. **Skip check** — if cards already contain `card_type="check_in"` and `force=False`, skip
2. **Strip existing check-ins** — if `force=True`, remove any existing check-in cards first
3. **LLM call** — send all explanation cards (without existing check-ins), receive `CheckInGenerationOutput`
4. **Validate each check-in:**
   - 2-4 pairs
   - `insert_after_card_idx` references a valid non-summary card
   - No duplicate left or right items within a check-in
   - hint and success_message non-empty
   - Fail-open: drop invalid check-ins, keep valid ones
5. **Assign card_ids** — UUID for every card (existing cards get `card_id` if missing)
6. **Insert and re-index** — insert check-in cards at correct positions, re-number `card_idx` sequentially
7. **Write back** — update `cards_json` via ORM update + commit

**Decision:** Single LLM call (not two-phase like visuals) because check-in generation is simpler — no code generation step, just structured JSON output. The decision of WHERE to place check-ins and WHAT pairs to generate are tightly coupled and best done together.

**Key method — `_enrich_variant`:**

```python
def _enrich_variant(self, explanation: TopicExplanation, guideline: TeachingGuideline) -> bool:
    # 1. Build cards for prompt (strip existing check-ins)
    explanation_cards = [c for c in explanation.cards_json if c.get("card_type") != "check_in"]

    # 2. LLM call
    output = self._generate_check_ins(explanation_cards, guideline)

    # 3. Validate
    valid_check_ins = self._validate_check_ins(output.check_ins, explanation_cards)
    if not valid_check_ins:
        return False

    # 4. Assign card_ids to existing cards (if missing)
    for card in explanation_cards:
        if not card.get("card_id"):
            card["card_id"] = str(uuid4())

    # 5. Build merged deck: explanation cards + check-in cards at correct positions
    merged = self._insert_check_ins(explanation_cards, valid_check_ins)

    # 6. Re-number card_idx
    for i, card in enumerate(merged):
        card["card_idx"] = i + 1  # 1-based

    # 7. Write back
    self.db.query(TopicExplanation).filter(TopicExplanation.id == explanation.id)\
        .update({"cards_json": merged})
    self.db.commit()
    return True
```

### 4.3 LLM Prompt (`book_ingestion_v2/prompts/check_in_generation.txt`)

```
You are designing quick comprehension check-ins for a Grade {grade} student
learning about {topic_title} ({subject}).

These check-ins are match-the-pairs activities inserted between explanation cards.
They test whether the student absorbed the key ideas from the preceding 2-3 cards.
They are NOT quizzes — they are warm readiness signals. Tone: "Let's check!" not "Test time."

EXPLANATION CARDS:
{cards_json}

RULES:
1. Insert 2-3 check-ins across the card sequence — at natural concept boundaries
2. Never before card 2 (student needs content first)
3. Never immediately after another check-in
4. Never after the last card (summary)
5. Each check-in tests ONLY concepts from the preceding 2-3 cards
6. Each check-in has 3-4 match pairs
7. Each pair must have EXACTLY ONE unambiguous correct match — no synonym collisions
8. Pairs must work from TEXT ALONE — no visual-dependent matching
9. Left column: terms, numbers, or short phrases
10. Right column: definitions, descriptions, or results
11. Hint: one sentence nudge that helps without giving the answer
12. Success message: warm confirmation + one-sentence reinforcement of the concept
13. Use SAME language and examples from the cards — don't introduce new terms
14. audio_text: spoken version of instruction — pure words, no symbols

OUTPUT FORMAT — respond with valid JSON only:
{output_schema}
```

**LLM call settings:** `reasoning_effort="medium"`, structured output via `json_schema`.

### 4.4 CLI Script (`scripts/run_check_in_enrichment.py`)

Mirrors `run_visual_enrichment.py`:

```bash
python scripts/run_check_in_enrichment.py --guideline-id <id> [--force]
python scripts/run_check_in_enrichment.py --chapter-id <id> [--force]
```

- Loads LLM config key `"check_in_enrichment"`, fallback to `"explanation_generator"`
- Instantiates `CheckInEnrichmentService`
- Calls `enrich_guideline()` or `enrich_chapter()`

### 4.5 Constants (`book_ingestion_v2/constants.py`)

Add job type:

```python
class V2JobType(str, Enum):
    # ... existing ...
    CHECK_IN_ENRICHMENT = "v2_check_in_enrichment"
```

### 4.6 API Route (`book_ingestion_v2/api/processing_routes.py`)

Add endpoint for admin-triggered check-in enrichment (same pattern as explanation generation trigger):

```python
@router.post("/{chapter_id}/enrich-check-ins")
def enrich_check_ins(chapter_id: str, book_id: str, force: bool = False, db = Depends(get_db)):
    # Acquire job lock, launch background task
    # Returns job status for polling
```

### 4.7 Struggle Signal in Summary (`tutor/services/session_service.py`)

Extend `_build_precomputed_summary()` to include check-in struggle data. The summary already includes confusion events from simplification — check-in struggles are appended in the same format.

**No backend changes needed for this.** The struggle data is captured client-side during the card phase and sent as part of the `card-action` request when transitioning to interactive. The session service already builds the summary from `confusion_events` — we add check-in struggle data to the same list.

**Decision:** Reuse the existing `ConfusionEvent` model for check-in struggles rather than creating a new model. A check-in struggle maps naturally: `base_card_idx` = the check-in card's index, `base_card_title` = check-in title, `depth_reached` = total wrong attempts, `escalated` = whether safety valve triggered. This keeps the summary builder unchanged.

---

## 5. Frontend Changes

### 5.1 API Types (`api.ts`)

```typescript
export interface MatchPair {
  left: string;
  right: string;
}

export interface CheckInActivity {
  activity_type: 'match_pairs';
  instruction: string;
  pairs: MatchPair[];
  hint: string;
  success_message: string;
  audio_text: string;
}

export interface ExplanationCard {
  card_id?: string;                 // NEW — stable UUID
  card_idx: number;
  card_type: 'concept' | 'example' | 'visual' | 'analogy' | 'summary' | 'simplification' | 'check_in';
  title: string;
  content: string;
  visual?: string | null;
  audio_text?: string | null;
  visual_explanation?: VisualExplanation | null;
  check_in?: CheckInActivity | null;  // NEW
  source_card_idx?: number;
}
```

### 5.2 Slide Interface (`ChatSession.tsx`)

Extend `Slide` type:

```typescript
interface Slide {
  id: string;
  type: 'explanation' | 'message' | 'check_in';  // add check_in
  content: string;
  title?: string;
  cardType?: string;
  visual?: string | null;
  visualExplanation?: VisualExplanationType | null;
  questionFormat?: QuestionFormat | null;
  studentResponse?: string | null;
  audioText?: string | null;
  checkIn?: CheckInActivity | null;  // NEW
}
```

### 5.3 Carousel Slide Mapping (`ChatSession.tsx`)

In the `carouselSlides` useMemo, when mapping explanation cards to slides:

```typescript
explanationCards.forEach((card, i) => {
  if (card.card_type === 'check_in' && card.check_in) {
    slides.push({
      id: card.card_id || `card-${i}`,
      type: 'check_in',
      content: card.check_in.instruction,
      title: card.title,
      cardType: 'check_in',
      checkIn: card.check_in,
      audioText: card.check_in.audio_text,
    });
  } else {
    slides.push({
      id: card.card_id || `card-${i}`,
      type: 'explanation',
      // ... existing mapping
    });
  }
});
```

### 5.4 Gate Logic (`ChatSession.tsx`)

New state:

```typescript
const [completedCheckIns, setCompletedCheckIns] = useState<Set<number>>(new Set());
// Struggle tracking for tutor context
const [checkInStruggles, setCheckInStruggles] = useState<Map<number, {wrongCount: number, hintsShown: number, autoRevealed: number}>>(new Map());
```

In the "Next" button's `disabled` prop and swipe handler:

```typescript
const isGated = carouselSlides[currentSlideIdx]?.type === 'check_in'
  && !completedCheckIns.has(currentSlideIdx);
// Next button disabled when isGated is true
```

Hide "I didn't understand" button when current slide is `check_in`.

### 5.5 Struggle Signal Forwarding

When `card-action` with `action: "clear"` is sent, include check-in struggle data. The existing `ConfusionEvent` pathway already flows through `_build_precomputed_summary()`.

**Implementation:** Before sending `card-action`, convert `checkInStruggles` map into `ConfusionEvent`-compatible entries and append to the session's confusion tracking. Since card actions go through the REST endpoint and the backend reads from persisted state, the simplest approach is:

- On check-in completion (or safety valve trigger), call a lightweight endpoint or piggyback on the existing card-action payload to record the struggle event.

**Decision:** Extend the `CardActionRequest` to accept optional `check_in_events` — a list of `{card_idx, wrong_count, hints_shown, auto_revealed}`. The session service converts these to `ConfusionEvent` entries before building the summary. This is a minor extension to an existing endpoint, not a new one.

### 5.6 MatchActivity Component (`components/MatchActivity.tsx`)

```typescript
interface MatchActivityProps {
  checkIn: CheckInActivity;
  onComplete: (struggles: {wrongCount: number, hintsShown: number, autoRevealed: number}) => void;
}
```

**State machine:**

```
State: {
  shuffledRightIndices: number[],      // Shuffled on mount
  selectedLeft: number | null,         // Currently selected left index
  matchedPairs: Set<number>,           // Left indices that are matched
  wrongAttempts: Map<number, number>,  // Per left-index wrong count
  showHint: boolean,
  showSuccess: boolean,
}
```

**Flow:**
1. On mount: shuffle right column indices (Fisher-Yates)
2. Tap left box → highlight, set `selectedLeft`
3. Tap right box → evaluate:
   - If `shuffledRightIndices[rightIdx]` matches `selectedLeft` → correct
     - Add to `matchedPairs`, play checkmark animation
   - Else → wrong
     - Increment `wrongAttempts[selectedLeft]`, shake animation, show hint
     - If `wrongAttempts[selectedLeft] >= 5` → auto-reveal: lock pair, show explanation
4. All pairs matched → show `success_message`, call `onComplete`

**Animations:**
- Select: border highlight + subtle scale
- Correct: green background, checkmark icon, fade-in connection line
- Wrong: shake (CSS `@keyframes shake`), red flash
- Auto-reveal: amber background, lock icon
- Complete: success message slides in, "Continue" button appears

**TTS integration:**
- On mount: play `audio_text` (instruction)
- On wrong: play hint via `synthesizeSpeech()`
- On complete: play `success_message`

### 5.7 Admin Badge (`features/admin/pages/ExplanationAdmin.tsx`)

Add `check_in` to the badge color mapping:

```typescript
card.card_type === 'check_in' ? '#FEE2E2' : // background
card.card_type === 'check_in' ? '#991B1B' : // text color
```

### 5.8 CSS Styles (`App.css`)

New class names:
- `.match-activity` — container
- `.match-columns` — flex row for left/right
- `.match-item` — individual box (48px+ min-height, touch-friendly)
- `.match-item.selected` — highlighted state
- `.match-item.matched` — green, locked
- `.match-item.wrong` — shake animation
- `.match-item.auto-revealed` — amber, locked
- `.match-success` — success message overlay
- `.match-hint` — hint text below columns

---

## 6. LLM Integration

### Prompt design

Single prompt: `check_in_generation.txt` (see section 4.3).

Input: all explanation cards for a variant (check-in cards stripped if re-running).
Output: structured JSON with `check_ins` array.

### Structured output schema

```python
class MatchPairOutput(BaseModel):
    left: str
    right: str

class CheckInDecision(BaseModel):
    insert_after_card_idx: int
    title: str
    instruction: str
    pairs: list[MatchPairOutput]
    hint: str
    success_message: str
    audio_text: str

class CheckInGenerationOutput(BaseModel):
    check_ins: list[CheckInDecision]
```

### Model and reasoning

- LLM config key: `check_in_enrichment` (new), fallback to `explanation_generator`
- Reasoning effort: `medium` (needs to analyze card content and identify boundaries, but no code generation)
- Estimated tokens: ~2K input (cards) + ~1K output (2-3 check-ins) per variant

### Cost

- ~3K tokens per variant × 1-3 variants per topic
- Comparable to a single visual enrichment decision call
- No retry loop (unlike visual code generation) — just validate and drop bad ones

---

## 7. Configuration & Environment

### New LLM config entry

| Component Key | Provider | Model | Purpose |
|---------------|----------|-------|---------|
| `check_in_enrichment` | openai | gpt-5.2 | Check-in generation for explanation cards |

Seeded via `_ensure_llm_config()` in the enrichment script (same pattern as `animation_enrichment`). Falls back to `explanation_generator` config if not present.

### No new environment variables

Uses existing LLM API keys and database connection.

---

## 8. Implementation Order

| Step | What to Build | Files | Depends On | Verification |
|------|---------------|-------|------------|--------------|
| 1 | Backend models | `explanation_repository.py` | — | `ExplanationCard` parses existing cards + new fields without breaking |
| 2 | CheckInEnrichmentService | `check_in_enrichment_service.py` | Step 1 | Unit test: generates valid check-ins from sample cards |
| 3 | LLM prompt | `check_in_generation.txt` | Step 2 | Manual: run against a real guideline, inspect output quality |
| 4 | CLI script | `run_check_in_enrichment.py` | Step 2-3 | Run against test topic, verify cards_json updated with check-ins |
| 5 | Job type constant | `constants.py` | — | Import check |
| 6 | API endpoint | `processing_routes.py` | Step 2, 5 | Trigger via admin UI, verify job completes |
| 7 | Frontend types | `api.ts` | — | TypeScript compiles |
| 8 | MatchActivity component | `MatchActivity.tsx`, `App.css` | Step 7 | Storybook / manual: renders pairs, tap-tap works, gate works |
| 9 | Carousel integration | `ChatSession.tsx` | Step 7-8 | Manual: check-in slides appear, gate prevents advance, success unlocks |
| 10 | Struggle signal forwarding | `ChatSession.tsx`, `session_service.py` | Step 9 | Manual: complete check-in with retries, verify struggle data in tutor summary |
| 11 | Admin badge | `ExplanationAdmin.tsx` | Step 7 | Visual: check-in cards show distinct badge color |

**Order rationale:** Backend models first (non-breaking — Optional fields). Service + prompt next (can test with CLI). Frontend types, then component, then integration. Admin badge last (cosmetic).

---

## 9. Testing Plan

### Unit tests

| Test | What it Verifies | Key Mocks |
|------|------------------|-----------|
| `test_explanation_card_parses_with_check_in` | ExplanationCard model accepts `card_id` + `check_in` fields | — |
| `test_explanation_card_parses_without_check_in` | Backwards compat — existing cards without new fields still parse | — |
| `test_validate_check_ins_valid` | Valid check-ins pass validation | — |
| `test_validate_check_ins_too_few_pairs` | Check-in with 1 pair rejected | — |
| `test_validate_check_ins_too_many_pairs` | Check-in with 5+ pairs rejected | — |
| `test_validate_check_ins_duplicate_items` | Duplicate left/right items rejected | — |
| `test_validate_check_ins_bad_insert_idx` | Invalid insert_after_card_idx rejected | — |
| `test_insert_check_ins_correct_order` | Check-ins inserted at correct positions, card_idx re-numbered | — |
| `test_card_ids_assigned` | All cards get card_id after enrichment | — |
| `test_strip_existing_check_ins` | Re-enrichment removes old check-ins before re-generating | — |
| `test_enrich_variant_skips_when_exists` | Skips if check-ins present and force=False | — |
| `test_enrich_variant_force_regenerates` | Regenerates when force=True | — |

### Integration tests

| Test | What it Verifies |
|------|------------------|
| `test_enrich_guideline_end_to_end` | Full pipeline: LLM call → validate → insert → persist (with mock LLM) |
| `test_session_serves_check_in_cards` | Session creation returns cards including check-in type |

### Manual verification

1. Run `python scripts/run_check_in_enrichment.py --guideline-id <id>` on a test topic
2. Check admin panel — check-in cards visible with badge
3. Start a "Teach Me" session on enriched topic
4. Verify: check-in card renders with match pairs
5. Verify: wrong match → shake + hint + TTS
6. Verify: correct match → green + lock
7. Verify: Next button disabled until all matched
8. Verify: safety valve triggers after 5 wrong on same pair
9. Verify: success message + TTS on completion
10. Verify: "I didn't understand" button hidden on check-in cards
11. Complete card phase → verify interactive tutor mentions struggle areas

---

## 10. Deployment Considerations

### No infrastructure changes

No new tables, no Terraform changes, no new secrets.

### Migration

None required. `cards_json` is JSONB — new fields appear when enrichment runs. Existing un-enriched topics continue to work (no check-in cards = no change in behavior).

### Rollout

1. Deploy backend (new service, models, endpoint) — zero impact on existing sessions
2. Deploy frontend (new component, types, gate logic) — handles missing `check_in` field gracefully
3. Run enrichment on test topics via CLI script
4. Verify in staging
5. Run enrichment on all topics via admin endpoint

### Rollback

- Frontend: check-in slides only render if `card.card_type === 'check_in'` — removing the component is safe
- Backend: un-enriched topics have no check-in cards, so reverting the frontend is sufficient
- Data: to fully roll back, re-run explanation generation (which replaces `cards_json` entirely)

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LLM generates ambiguous pairs | Medium | High (student trapped) | Strict validation + fail-open (drop bad check-ins) + safety valve (auto-reveal after 5 wrong) |
| Card count exceeds MAX_CARDS (15) | Low | Low | Check-ins are 2-3 cards. Typical topic has 5-10 explanation cards. Total stays under 15. If exceeded, drop the last check-in. |
| Existing cards lose card_id on re-generation | Low | Medium (identity drift) | Explanation generation always replaces entire cards_json — check-ins must be re-run after. Pipeline ordering enforced by admin UI. |
| Mobile layout cramped with 4 pairs | Low | Medium (UX) | Enforce max 4 pairs in validation. CSS uses min-height 48px. Test on small screens during development. |
| TTS latency on hint/success | Low | Low | Hints are short strings. Pre-fetch success audio after first correct match. |

---

## 12. Open Questions

None — all design decisions resolved in PRD review. The implementation is straightforward and mirrors established patterns.
