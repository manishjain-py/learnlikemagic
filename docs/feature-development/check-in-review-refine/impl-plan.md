# Tech Implementation Plan: Check-In Review-Refine

**PRD:** `docs/feature-development/check-in-review-refine/PRD.md`
**Pattern mirrored from:** `ExplanationGeneratorService._review_and_refine` (`llm-backend/book_ingestion_v2/services/explanation_generator_service.py:346–427`)

---

## 1. Overview

Add an LLM-based review-refine loop to check-in generation. Configurable rounds (0–5, default 1). Reviewer is scoped to **accuracy only** — it verifies every factual claim and every marked correct answer, and rewrites cards in place when it finds errors. It does not rewrite for tone, distractor quality, clarity, or cognitive level.

**Data flow unchanged:**

```
_enrich_variant(explanation, guideline)
    ↓ _generate_check_ins(cards, guideline)    ← existing single LLM call
    ↓ FOR round in 1..review_rounds:           ← NEW
    ↓     _review_and_refine_check_ins(...)    ← NEW
    ↓ _validate_check_ins(...)                 ← existing structural validation
    ↓ _insert_check_ins(...)
    ↓ persist cards_json
```

No DB schema changes. No card-shape changes. No new API endpoints.

---

## 2. Files Changed

### Backend

| File | Change |
|------|--------|
| `llm-backend/book_ingestion_v2/prompts/check_in_review_refine.txt` | **NEW** — review-refine prompt (matches `check_in_generation.txt` convention: single file, `{output_schema}` placeholder, no system-file split) |
| `llm-backend/book_ingestion_v2/services/check_in_enrichment_service.py` | Add `DEFAULT_REVIEW_ROUNDS`, `_review_and_refine_check_ins()`, thread `review_rounds` through `_enrich_variant`, `enrich_guideline`, `enrich_chapter` |
| `llm-backend/book_ingestion_v2/api/sync_routes.py` | Add `review_rounds` query param to `generate_check_ins` endpoint; thread into `_run_check_in_enrichment` background task |
| `llm-backend/tests/unit/test_check_in_enrichment.py` | Add tests for new reviewer method and rounds plumbing |

### Frontend

| File | Change |
|------|--------|
| `llm-frontend/src/features/admin/api/adminApiV2.ts` | Add `reviewRounds?: number` option to `generateCheckIns`, serialize as `review_rounds` query param |
| `llm-frontend/src/features/admin/pages/BookV2Detail.tsx` | Add `checkInReviewRounds` state + dropdown UI next to "Check-ins" button; pass value to `generateCheckIns` in `handleGenerateCheckIns` |

---

## 3. Backend Details

### 3.1 New prompt: `check_in_review_refine.txt`

Single-file prompt matching the `check_in_generation.txt` convention (no split system file for now). Mirrors `explanation_review_refine.txt` in structure but narrowly scoped to accuracy.

Key instructions in the prompt:

- Role: "You are reviewing check-in cards for factual accuracy before they reach a student."
- Input the reviewer sees: teaching guideline + preceding explanation cards + generated check-in cards.
- **Review checklist (accuracy only):**
  1. Every factual claim in question / statement / options / hint / success_message / reveal_text / instruction.
  2. The marked correct answer (`correct_index`, `correct_answer`, `error_index`, `odd_index`, `correct_bucket`) is genuinely correct.
  3. Every bucket assignment in `sort_buckets` / `swipe_classify` matches the bucket label.
  4. Every item in `sequence_items` is in the claimed correct order.
  5. Every pair in `match_pairs` is a genuine match.
  6. The flagged step in `spot_the_error` is genuinely the error; other steps are correct.
- **Explicit non-scope**: "Do NOT rewrite for tone, clarity, distractor quality, cognitive level, word choice, or instruction style. Those are handled elsewhere. Only fix accuracy."
- Output: same `CheckInGenerationOutput` JSON schema. If nothing is wrong, return the input unchanged. If something is wrong, rewrite the specific field (not the whole card) and return the full list.
- Include the full JSON schema at the end of the system file (matching `explanation_review_refine_system.txt` convention).

### 3.2 `check_in_enrichment_service.py` changes

**Add prompt loading constant** near the existing `_CHECK_IN_PROMPT` load (around line 31):

```python
_CHECK_IN_REVIEW_PROMPT = (_PROMPTS_DIR / "check_in_review_refine.txt").read_text()
```

**Add constant** near existing constants (line 138 area):

```python
DEFAULT_REVIEW_ROUNDS = 1
```

**Extend `enrich_chapter` signature** (line 211):

```python
def enrich_chapter(
    self,
    book_id: str,
    chapter_id: Optional[str] = None,
    force: bool = False,
    review_rounds: int = DEFAULT_REVIEW_ROUNDS,
    job_service=None,
    job_id: Optional[str] = None,
) -> dict:
```

Pass `review_rounds` into the `enrich_guideline` call at line 249.

**Extend `enrich_guideline` signature** (line 170):

```python
def enrich_guideline(
    self,
    guideline: TeachingGuideline,
    force: bool = False,
    review_rounds: int = DEFAULT_REVIEW_ROUNDS,
    variant_keys: Optional[list[str]] = None,
    heartbeat_fn: Optional[callable] = None,
) -> dict:
```

Pass `review_rounds` into the `_enrich_variant` call at line 198.

**Extend `_enrich_variant` signature** (line 295):

```python
def _enrich_variant(
    self,
    explanation: TopicExplanation,
    guideline: TeachingGuideline,
    force: bool = False,
    review_rounds: int = DEFAULT_REVIEW_ROUNDS,
) -> bool:
```

**Modify the body around line 322** — after `_generate_check_ins`:

```python
output = self._generate_check_ins(explanation_cards, guideline)
if not output or not output.check_ins:
    logger.warning(f"No check-ins generated for {topic} variant {explanation.variant_key}")
    return False

# NEW: review-refine rounds (accuracy only)
for round_num in range(1, review_rounds + 1):
    logger.info(f"Check-in review-refine round {round_num}/{review_rounds} for {topic} variant {explanation.variant_key}")
    refined = self._review_and_refine_check_ins(
        output.check_ins, explanation_cards, guideline,
    )
    self._refresh_db_session()
    if refined and refined.check_ins:
        output = refined
    else:
        logger.warning(f"Review round {round_num} returned no check-ins, keeping prior output")
        break

# Existing structural validation runs on post-refine output
valid_check_ins = self._validate_check_ins(output.check_ins, explanation_cards)
```

**Add new method** `_review_and_refine_check_ins` (place after `_generate_check_ins` at line 399):

```python
def _review_and_refine_check_ins(
    self,
    check_ins: list[CheckInDecision],
    explanation_cards: list[dict],
    guideline: TeachingGuideline,
) -> Optional[CheckInGenerationOutput]:
    """LLM review pass: verify accuracy of every check-in, rewrite in place.

    Narrow scope: factual correctness only — marked correct answers, bucket
    assignments, sequence order, pair matches, flagged errors. Does NOT rewrite
    for tone, clarity, distractor quality, or cognitive level.
    """
    topic = guideline.topic_title or guideline.topic
    subject = guideline.subject or "Mathematics"
    grade = str(guideline.grade) if guideline.grade else "3"

    cards_for_prompt = [
        {k: v for k, v in c.items() if k in ("card_idx", "card_type", "title", "content")}
        for c in explanation_cards
    ]
    check_ins_json = json.dumps([ci.model_dump() for ci in check_ins], indent=2)
    cards_json = json.dumps(cards_for_prompt, indent=2)

    prompt = _CHECK_IN_REVIEW_PROMPT.replace(
        "{grade}", grade,
    ).replace("{topic_title}", topic).replace(
        "{subject}", subject,
    ).replace(
        "{guideline_text}", guideline.guideline or "",
    ).replace(
        "{explanation_cards_json}", cards_json,
    ).replace(
        "{check_ins_json}", check_ins_json,
    ).replace(
        "{output_schema}", json.dumps(
            CheckInGenerationOutput.model_json_schema(), indent=2,
        ),
    )

    try:
        response = self.llm.call(
            prompt=prompt,
            reasoning_effort="medium",
            json_schema=self._generation_schema,
            schema_name="CheckInGenerationOutput",
        )
        parsed = self.llm.parse_json_response(response["output_text"])
        return CheckInGenerationOutput.model_validate(parsed)
    except (LLMServiceError, json.JSONDecodeError, Exception) as e:
        logger.error(f"Check-in review-refine failed for {topic}: {e}")
        return None
```

**Fail-open behavior:** if the reviewer errors, `_review_and_refine_check_ins` returns `None`, the loop preserves the prior output (via the `if refined and refined.check_ins` guard), and the pipeline continues to structural validation. A failing reviewer cannot corrupt generated output.

### 3.4 `sync_routes.py` changes

**Add query param** to `generate_check_ins` (line 1083):

```python
@router.post("/generate-check-ins", response_model=ProcessingJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_check_ins(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope enrichment"),
    guideline_id: Optional[str] = Query(None, description="Optional guideline_id for single-topic enrichment"),
    force: bool = Query(False, description="Re-generate check-ins even if they already exist"),
    review_rounds: int = Query(1, ge=0, le=5, description="Number of review-refine rounds (0 disables)"),
    db: Session = Depends(get_db),
):
```

**Update `run_in_background_v2` call** (line 1139):

```python
run_in_background_v2(
    _run_check_in_enrichment, job_id, book_id,
    chapter_id or "", guideline_id or "", str(force), str(review_rounds),
)
```

**Update `_run_check_in_enrichment` signature** (line 1238):

```python
def _run_check_in_enrichment(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", force_str: str = "False", review_rounds_str: str = "1",
):
    force = force_str.lower() == "true"
    review_rounds = int(review_rounds_str)
    ...
```

**Pass into service calls:**

```python
result = service.enrich_guideline(guideline, force=force, review_rounds=review_rounds, heartbeat_fn=heartbeat_fn)
# and
result = service.enrich_chapter(
    book_id, chapter_id=chapter_id or None, force=force,
    review_rounds=review_rounds, job_service=job_service, job_id=job_id,
)
```

---

## 4. Frontend Details

### 4.1 `adminApiV2.ts` — `generateCheckIns`

Extend options type and serialize (line 724):

```typescript
export async function generateCheckIns(
  bookId: string,
  opts?: { chapterId?: string; guidelineId?: string; force?: boolean; reviewRounds?: number },
): Promise<ProcessingJobResponseV2> {
  const params = new URLSearchParams();
  if (opts?.chapterId) params.set('chapter_id', opts.chapterId);
  if (opts?.guidelineId) params.set('guideline_id', opts.guidelineId);
  if (opts?.force) params.set('force', 'true');
  if (opts?.reviewRounds !== undefined) params.set('review_rounds', opts.reviewRounds.toString());
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiFetch<ProcessingJobResponseV2>(
    `/admin/v2/books/${bookId}/generate-check-ins${qs}`,
    { method: 'POST' }
  );
}
```

### 4.2 `BookV2Detail.tsx` — chapter-level control

**Add state** (near existing checkIn state around line 62):

```tsx
const [checkInReviewRounds, setCheckInReviewRounds] = useState<Record<string, number>>({});
```

Map is keyed by `chapter.id` so each expanded chapter remembers its own setting.

**Update handler** (line 388):

```tsx
const handleGenerateCheckIns = async (ch: ChapterResponseV2, force = false) => {
  if (!id) return;
  try {
    const rounds = checkInReviewRounds[ch.id] ?? 1;
    const job = await generateCheckIns(id, { chapterId: ch.id, force, reviewRounds: rounds });
    setCheckInJobs(prev => ({ ...prev, [ch.id]: job }));
    startCheckInPolling(ch.id);
  } catch (err) {
    setError(err instanceof Error ? err.message : 'Check-in enrichment failed');
  }
};
```

**Add dropdown next to "Check-ins" button** (line 942):

```tsx
<button onClick={() => handleGenerateCheckIns(ch)} style={manageLinkStyle}>Check-ins</button>
<label style={{ fontSize: '11px', color: '#6B7280', marginLeft: '4px' }}>rounds:</label>
<select
  value={checkInReviewRounds[ch.id] ?? 1}
  onChange={e => setCheckInReviewRounds(prev => ({ ...prev, [ch.id]: Number(e.target.value) }))}
  style={{ padding: '2px 6px', borderRadius: '4px', border: '1px solid #D1D5DB', fontSize: '11px' }}
>
  {[0, 1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}</option>)}
</select>
```

Styling matches existing inline controls on the chapter row. Per-chapter state lets admins set different rounds when iterating on a specific chapter.

---

## 5. Tests

### New tests in `test_check_in_enrichment.py`

1. **`test_review_refine_preserves_unchanged_output`** — mock LLM returns the same output as input; assert `_review_and_refine_check_ins` returns `CheckInGenerationOutput` with equal contents.
2. **`test_review_refine_fixes_accuracy_bug`** — mock LLM input contains a sort_buckets card with "87" in the "3-DIGIT" bucket; mock LLM output swaps "87" for "387"; assert the returned output reflects the fix.
3. **`test_review_refine_returns_none_on_llm_error`** — mock LLM raises `LLMServiceError`; assert method returns `None`; assert `_enrich_variant` falls back to pre-review output.
4. **`test_enrich_variant_skips_review_when_rounds_zero`** — patch `_generate_check_ins` and `_review_and_refine_check_ins` on the service; call `_enrich_variant` with `review_rounds=0`; assert the refine method was not called.
5. **`test_enrich_variant_calls_review_n_times`** — call `_enrich_variant` with `review_rounds=3`; assert refine was called 3 times.
6. **`test_structural_validation_runs_after_refine`** — mock review returns check-ins that fail structural validation (e.g., wrong bucket count); assert final saved output is empty (validator drops them).

Mock pattern uses `unittest.mock.patch` on `self.llm.call` and `self.llm.parse_json_response`, matching the pattern already in use for other LLM-touching unit tests in this repo.

---

## 6. Rollout

1. Merge PR.
2. Admin re-runs check-in enrichment on representative chapters at `review_rounds=1` (default) and visually inspects check-ins for accuracy bugs.
3. If reviewer is making cards worse, set `review_rounds=0` on subsequent runs as an escape hatch while we tune the prompt.
4. No backfill in this PR. Admin batch-reprocesses at their own pace using the same chapter-level UI.

---

## 7. Out of Scope (explicit)

- Tone / clarity / distractor rewrites in the review prompt.
- Deterministic rule-based content validation.
- Per-topic (guideline-level) review-refine trigger — chapter-level only for now, matching current check-in admin UX.
- Stage-snapshot capture for check-in review rounds (explanation pipeline has this; not needed for v1 here).
- Check-in-specific admin page like `ExplanationAdmin.tsx`. Current chapter-level button UX is sufficient.
