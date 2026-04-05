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
- Struggle signals (per-pair retry counts, confused pairs) forwarded to interactive tutor via new `CheckInStruggleEvent` model and `_build_precomputed_summary()`
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
       ↓ Pre-flight: verify no other enrichment job running for this chapter
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
       ↓ gate: Next + swipe disabled until all pairs matched
  On phase transition → check-in struggle signals sent via CardActionRequest
       ↓
  _build_precomputed_summary() includes per-pair confusion detail for tutor
```

### card_idx renumbering safety

The enrichment pipeline runs **offline before any session consumes the cards**. Renumbering `card_idx` after inserting check-in cards is safe because:
- Active sessions use their own snapshot of `cards_json` loaded at session creation — they are unaffected
- All in-session references (`CardPhaseState.current_card_idx`, `ConfusionEvent.base_card_idx`, `remedial_cards` dict keys) are created from the enriched card set and stay internally consistent
- No cross-session references to `card_idx` exist

`card_idx` in card data is **1-based** (matching `ExplanationCardOutput.card_idx` from the generator). Frontend navigation uses **0-based array position**, which is separate from the card's `card_idx` field. The enrichment maintains the 1-based convention: `card["card_idx"] = i + 1`.

Long-term, references should migrate from `card_idx` to `card_id` for stability. For v1, `card_id` is assigned but not yet used as the primary identifier in session state.

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
| `llm-backend/tutor/models/session_state.py` | Add `CheckInStruggleEvent` model; add `check_in_struggles` to `CardPhaseState` |
| `llm-backend/tutor/models/messages.py` | Extend `CardActionRequest` with optional `check_in_events` |
| `llm-backend/tutor/services/session_service.py` | Handle `check_in_events` in `complete_card_phase()`; extend `_build_precomputed_summary()` |
| `llm-backend/book_ingestion_v2/constants.py` | Add `V2JobType.CHECK_IN_ENRICHMENT` |
| `llm-backend/book_ingestion_v2/api/processing_routes.py` | Add check-in enrichment endpoint |
| `llm-frontend/src/api.ts` | Add `MatchPair`, `CheckInActivity` types; extend `ExplanationCard` |
| `llm-frontend/src/pages/ChatSession.tsx` | Add `check_in` slide type, gate logic (button + swipe), struggle tracking |
| `llm-frontend/src/App.css` | Match activity styles |
| `llm-frontend/src/features/admin/pages/ExplanationAdmin.tsx` | Add `check_in` badge color |

---

## 3. Database Changes

### No new tables

Check-in cards live inside the existing `topic_explanations.cards_json` JSONB column as additional entries in the card array.

### No schema migrations

`card_id` and `check_in` are added to the Pydantic model only. The JSONB column already stores arbitrary dicts — new fields appear naturally. Existing cards without `card_id` work fine (`Optional[str]`).

**Decision:** No migration needed. The `card_id` field is Optional in the Pydantic model. The enrichment pipeline assigns `card_id` to all cards (existing + new) when it runs. Cards loaded before enrichment simply have `card_id = None`, which is harmless — the frontend already uses array position for navigation and falls back gracefully.

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
    insert_after_card_idx: int          # Insert after this card (1-based, matching card data)
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

1. **Pre-flight check** — verify no `v2_explanation_generation` or `v2_visual_enrichment` job is `running`/`pending` for this chapter (via `ChapterJobService`). Fail fast if conflict detected.
2. **Skip check** — if cards already contain `card_type="check_in"` and `force=False`, skip
3. **Strip existing check-ins** — if `force=True`, remove any existing check-in cards first
4. **LLM call** — send all explanation cards (without existing check-ins), receive `CheckInGenerationOutput`
5. **Validate each check-in:**
   - 2-4 pairs
   - `insert_after_card_idx` references a valid non-summary card
   - No duplicate left or right items within a check-in
   - hint and success_message non-empty
   - Fail-open: drop invalid check-ins, keep valid ones
6. **Assign card_ids** — UUID for every card (existing cards get `card_id` if missing)
7. **Insert and re-index** — insert check-in cards at correct positions, re-number `card_idx` sequentially (1-based, matching existing generator convention)
8. **Write back** — update `cards_json` via ORM update + commit

**Decision:** Single LLM call (not two-phase like visuals) because check-in generation is simpler — no code generation step, just structured JSON output. The decision of WHERE to place check-ins and WHAT pairs to generate are tightly coupled and best done together.

**Decision:** Pre-flight concurrent-write check rather than row-level locking. The job system already tracks running jobs per chapter — a simple query before starting is sufficient. This matches the operational reality: enrichments are admin-triggered and sequential.

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

    # 6. Re-number card_idx (1-based, matching ExplanationCardOutput convention)
    for i, card in enumerate(merged):
        card["card_idx"] = i + 1

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

- Loads LLM config via `LLMConfigService.get_config("check_in_enrichment")` with try/except fallback to `get_config("explanation_generator")` — matching the `run_visual_enrichment.py` pattern exactly
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

New endpoint for admin-triggered check-in enrichment. This is a **new endpoint pattern** — no visual enrichment API endpoint exists to mirror. The endpoint follows the `run_in_background_v2()` + job lock pattern from other processing endpoints (e.g., explanation generation trigger in the same file).

```python
@router.post("/{chapter_id}/enrich-check-ins")
def enrich_check_ins(chapter_id: str, book_id: str, force: bool = False, db = Depends(get_db)):
    # Acquire job lock (V2JobType.CHECK_IN_ENRICHMENT)
    # Launch background task via run_in_background_v2()
    # Returns job status for polling
```

### 4.7 Struggle Signal Model (`tutor/models/session_state.py`)

New model — **not reusing `ConfusionEvent`**. The ConfusionEvent model tracks simplification depth ("student needed 3 simplifications") which is semantically different from check-in struggle ("student got 3 wrong matches"). Reusing it would cause `_build_precomputed_summary()` to produce misleading tutor context like "Card 7: 3 simplification(s)" when the student actually had 3 wrong match attempts.

```python
class CheckInStruggleEvent(BaseModel):
    """Tracks a student's struggles on a check-in activity."""
    card_idx: int = Field(description="Check-in card index (1-based)")
    card_title: str = Field(description="Check-in title for readability")
    wrong_count: int = Field(default=0, description="Total wrong match attempts")
    hints_shown: int = Field(default=0, description="Times hint was displayed")
    confused_pairs: list[dict] = Field(
        default_factory=list,
        description="Pairs the student struggled with: [{left, right, wrong_count}]"
    )
    auto_revealed: int = Field(default=0, description="Pairs auto-revealed by safety valve")
```

Add to `CardPhaseState`:

```python
class CardPhaseState(BaseModel):
    # ... existing fields ...
    check_in_struggles: list[CheckInStruggleEvent] = Field(
        default_factory=list,
        description="Per-check-in struggle tracking"
    )
```

### 4.8 CardActionRequest Extension (`tutor/models/messages.py`)

```python
class CheckInEventDTO(BaseModel):
    """Check-in struggle data sent from frontend at phase transition."""
    card_idx: int
    wrong_count: int = 0
    hints_shown: int = 0
    confused_pairs: list[dict] = Field(default_factory=list)  # [{left, right, wrong_count}]
    auto_revealed: int = 0

class CardActionRequest(BaseModel):
    """Request body for card phase actions."""
    action: Literal["clear", "explain_differently"]
    check_in_events: Optional[list[CheckInEventDTO]] = None  # NEW
```

### 4.9 Summary Builder Extension (`tutor/services/session_service.py`)

In `complete_card_phase()`: before building the summary, convert incoming `check_in_events` to `CheckInStruggleEvent` entries and store in `session.card_phase.check_in_struggles`.

In `_build_precomputed_summary()`: add a **separate section** for check-in struggles (not mixed with simplification confusion events):

```python
# After existing confusion_events section:
if session.card_phase and session.card_phase.check_in_struggles:
    struggle_lines = []
    for evt in session.card_phase.check_in_struggles:
        pair_details = ", ".join(
            f'confused "{p["left"]}" with "{p["right"]}" ({p["wrong_count"]}x)'
            for p in evt.confused_pairs if p.get("wrong_count", 0) > 0
        )
        auto = f", {evt.auto_revealed} pair(s) auto-revealed" if evt.auto_revealed else ""
        struggle_lines.append(
            f"- \"{evt.card_title}\": {evt.wrong_count} wrong attempts"
            f"{', ' + pair_details if pair_details else ''}{auto}"
        )
    summaries.append(
        "Check-in struggles:\n" + "\n".join(struggle_lines)
    )
```

This gives the tutor actionable context like: `Check-in struggles: "Match fractions": 4 wrong attempts, confused "1/2" with "one of four equal parts" (3x)`.

**Decision:** Struggle data is captured client-side during the card phase and sent at phase transition via `CardActionRequest.check_in_events`. If the session is abandoned before phase transition, struggle data is lost. Acceptable for v1 — the primary value is during the active learning flow, and abandoned sessions are a minority case.

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
// Per-check-in struggle data for tutor context
const [checkInStruggles, setCheckInStruggles] = useState<Map<number, {
  wrongCount: number;
  hintsShown: number;
  autoRevealed: number;
  confusedPairs: Array<{left: string; right: string; wrongCount: number}>;
}>>(new Map());
```

Gate computed value:

```typescript
const isGated = carouselSlides[currentSlideIdx]?.type === 'check_in'
  && !completedCheckIns.has(currentSlideIdx);
```

Apply gate to **both** Next button and swipe handler:

```typescript
// Next button — add isGated to disabled prop
<button disabled={simplifyLoading || isGated}>Next</button>

// Swipe handler (~line 1059) — add gate check to forward swipe
} else if (dx < -80 && currentSlideIdx < carouselSlides.length - 1 && !isGated) {
  newIdx = currentSlideIdx + 1;
}
```

Hide "I didn't understand" button when current slide is `check_in`.

### 5.5 TTS Auto-Play

The existing TTS hook (`ChatSession.tsx` ~line 297) skips `'explanation'` slides:
```typescript
if (slide && slide.type !== 'explanation') {
```

This accidentally auto-plays for `'check_in'` slides since `'check_in' !== 'explanation'`. Make this intentional:

```typescript
// Auto-play audio for message slides and check-in slides (instruction)
if (slide && (slide.type === 'message' || slide.type === 'check_in')) {
```

### 5.6 Struggle Signal Forwarding

When sending `card-action` with `action: "clear"`, include accumulated check-in struggle data:

```typescript
const checkInEvents = Array.from(checkInStruggles.entries()).map(([slideIdx, data]) => ({
  card_idx: carouselSlides[slideIdx]?.cardIdx ?? slideIdx,
  wrong_count: data.wrongCount,
  hints_shown: data.hintsShown,
  confused_pairs: data.confusedPairs,
  auto_revealed: data.autoRevealed,
}));

cardAction(sessionId, { action: 'clear', check_in_events: checkInEvents });
```

### 5.7 MatchActivity Component (`components/MatchActivity.tsx`)

```typescript
interface MatchActivityProps {
  checkIn: CheckInActivity;
  onComplete: (struggles: {
    wrongCount: number;
    hintsShown: number;
    autoRevealed: number;
    confusedPairs: Array<{left: string; right: string; wrongCount: number}>;
  }) => void;
}
```

**State machine:**

```
State: {
  shuffledRightIndices: number[],      // Shuffled on mount (Fisher-Yates)
  selectedLeft: number | null,         // Currently selected left index
  matchedPairs: Set<number>,           // Left indices that are matched
  wrongAttempts: Map<number, number>,  // Per left-index wrong count
  showHint: boolean,
  showSuccess: boolean,
}
```

**Flow:**
1. On mount: shuffle right column indices (Fisher-Yates)
2. Tap left box -> highlight, set `selectedLeft`
3. Tap right box -> evaluate:
   - If `shuffledRightIndices[rightIdx]` matches `selectedLeft` -> correct
     - Add to `matchedPairs`, play checkmark animation
   - Else -> wrong
     - Increment `wrongAttempts[selectedLeft]`, shake animation, show hint
     - If `wrongAttempts[selectedLeft] >= 5` -> auto-reveal: lock pair, show explanation
4. All pairs matched -> show `success_message`, call `onComplete` with per-pair struggle data

**onComplete data assembly:**

```typescript
const confusedPairs = checkIn.pairs
  .map((pair, i) => ({ left: pair.left, right: pair.right, wrongCount: wrongAttempts.get(i) || 0 }))
  .filter(p => p.wrongCount > 0);

onComplete({
  wrongCount: totalWrongAttempts,
  hintsShown: hintCount,
  autoRevealed: autoRevealedCount,
  confusedPairs,
});
```

**Animations:**
- Select: border highlight + subtle scale
- Correct: green background, checkmark icon, fade-in connection line
- Wrong: shake (CSS `@keyframes shake`), red flash
- Auto-reveal: amber background, lock icon
- Complete: success message slides in, "Continue" button appears

**TTS integration:**
- On mount: play `audio_text` (instruction) — auto-played by carousel's TTS hook (section 5.5)
- On wrong: play hint via `synthesizeSpeech()`
- On complete: play `success_message` via `synthesizeSpeech()`

### 5.8 Simplification Interaction on Check-Ins

The "I didn't understand" / simplify button does not appear on check-in cards — hints serve that role. If a student is stuck because they didn't understand the preceding explanation cards, they navigate back manually to re-read/simplify those cards, then return to the check-in.

This flow is functional but clunky. **v2 consideration:** a "Go back and review" button on the check-in card that auto-navigates to the first relevant explanation card.

### 5.9 Admin Badge (`features/admin/pages/ExplanationAdmin.tsx`)

Add `check_in` to the badge color mapping (teal — positive comprehension check, not red which signals errors):

```typescript
card.card_type === 'check_in' ? '#CCFBF1' : // background (teal)
card.card_type === 'check_in' ? '#115E59' : // text color (dark teal)
```

### 5.10 CSS Styles (`App.css`)

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

- ~3K tokens per variant x 1-3 variants per topic
- Comparable to a single visual enrichment decision call
- No retry loop (unlike visual code generation) — just validate and drop bad ones

---

## 7. Configuration & Environment

### New LLM config entry

| Component Key | Provider | Model | Purpose |
|---------------|----------|-------|---------|
| `check_in_enrichment` | openai | gpt-5.2 | Check-in generation for explanation cards |

Loaded via `LLMConfigService.get_config("check_in_enrichment")` with try/except fallback to `get_config("explanation_generator")` — matching the `run_visual_enrichment.py` pattern.

### No new environment variables

Uses existing LLM API keys and database connection.

---

## 8. Implementation Order

| Step | What to Build | Files | Depends On | Verification |
|------|---------------|-------|------------|--------------|
| 1 | Backend models | `explanation_repository.py` | — | `ExplanationCard` parses existing cards + new fields without breaking |
| 2 | Struggle event model | `session_state.py`, `messages.py` | — | `CheckInStruggleEvent` + extended `CardActionRequest` parse correctly |
| 3 | CheckInEnrichmentService | `check_in_enrichment_service.py` | Step 1 | Unit test: generates valid check-ins from sample cards |
| 4 | LLM prompt | `check_in_generation.txt` | Step 3 | Manual: run against a real guideline, inspect output quality |
| 5 | CLI script | `run_check_in_enrichment.py` | Step 3-4 | Run against test topic, verify cards_json updated with check-ins |
| 6 | Job type constant | `constants.py` | — | Import check |
| 7 | API endpoint | `processing_routes.py` | Step 3, 6 | Trigger via admin UI, verify job completes |
| 8 | Summary builder | `session_service.py` | Step 2 | Unit test: check-in struggles render as separate section in summary |
| 9 | Frontend types | `api.ts` | — | TypeScript compiles |
| 10 | MatchActivity component | `MatchActivity.tsx`, `App.css` | Step 9 | Manual: renders pairs, tap-tap works, per-pair struggle data correct |
| 11 | Carousel integration | `ChatSession.tsx` | Step 9-10 | Manual: check-in slides appear, gate on button + swipe, TTS intentional |
| 12 | Struggle signal forwarding | `ChatSession.tsx` | Step 11 | Manual: complete check-in with retries, verify per-pair data in tutor summary |
| 13 | Admin badge | `ExplanationAdmin.tsx` | Step 9 | Visual: check-in cards show teal badge |

**Order rationale:** Backend models first (non-breaking — Optional fields). Struggle event model next (needed by both service and frontend). Service + prompt next (can test with CLI). Summary builder (uses struggle model). Frontend types, then component, then integration. Admin badge last (cosmetic).

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
| `test_insert_check_ins_correct_order` | Check-ins inserted at correct positions, card_idx re-numbered 1-based | — |
| `test_card_ids_assigned` | All cards get card_id after enrichment | — |
| `test_strip_existing_check_ins` | Re-enrichment removes old check-ins before re-generating | — |
| `test_enrich_variant_skips_when_exists` | Skips if check-ins present and force=False | — |
| `test_enrich_variant_force_regenerates` | Regenerates when force=True | — |
| `test_preflight_blocks_concurrent` | Enrichment fails fast if another enrichment job is running | Mock job service |
| `test_check_in_struggle_summary` | `_build_precomputed_summary()` renders check-in struggles as separate section with per-pair detail | — |
| `test_check_in_struggle_not_mixed_with_confusion` | Check-in struggles don't appear in "Cards that needed simplification" section | — |

### Integration tests

| Test | What it Verifies |
|------|------------------|
| `test_enrich_guideline_end_to_end` | Full pipeline: LLM call -> validate -> insert -> persist (with mock LLM) |
| `test_session_serves_check_in_cards` | Session creation returns cards including check-in type |
| `test_card_action_with_check_in_events` | `complete_card_phase()` correctly stores CheckInStruggleEvents from request |

### Manual verification

1. Run `python scripts/run_check_in_enrichment.py --guideline-id <id>` on a test topic
2. Check admin panel — check-in cards visible with teal badge
3. Start a "Teach Me" session on enriched topic
4. Verify: check-in card renders with match pairs
5. Verify: wrong match -> shake + hint + TTS
6. Verify: correct match -> green + lock
7. Verify: Next button disabled until all matched
8. Verify: **swiping forward** also blocked until all matched
9. Verify: safety valve triggers after 5 wrong on same pair
10. Verify: success message + TTS on completion
11. Verify: "I didn't understand" button hidden on check-in cards
12. Complete card phase -> verify interactive tutor mentions specific confused pairs (not "simplifications")

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
| Concurrent enrichment overwrites | Low | High (data loss) | Pre-flight job check before starting. Pipeline ordering enforced by admin UI. |
| Existing cards lose card_id on re-generation | Low | Medium | Explanation generation replaces entire cards_json — check-ins and card_ids must be re-run after. Pipeline ordering enforced. |
| Mobile layout cramped with 4 pairs | Low | Medium (UX) | Enforce max 4 pairs in validation. CSS uses min-height 48px. Test on small screens. |
| Abandoned session loses struggle data | Medium | Low | Struggle data sent at phase transition only. Acceptable for v1 — primary value is during active flow. |

---

## 12. Open Questions

- **card_id migration scope for v1:** The plan adds `card_id` to all cards but in-session references (`CardPhaseState.current_card_idx`, `remedial_cards` dict keys, `ConfusionEvent.base_card_idx`) still use `card_idx`. Migrating all references to `card_id` is the right long-term move but adds scope. For v1, `card_id` is assigned but not yet used as primary session identifier. Should we plan the full migration now or defer to a follow-up?
