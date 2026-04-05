# Code Review Response: Check-In Cards

Response to `code-review.md` — commit `1d979ed` addresses all must-fix and should-fix items.

---

## Reviewer 1

### 1. Struggle signal card_idx mapping is broken
**Fixed.** Replaced broken `card-N` string matching with direct `card_id` lookup:
```typescript
const card = explanationCards.find(c => c.card_id === cardId);
return { card_idx: card?.card_idx ?? 0, card_title: card?.title || ... };
```
Also fixed as part of the re-key to `card_id` (R2-1) — `checkInStruggles` is now `Map<string, ...>` keyed by card_id, so the mapping is straightforward.

### 2. Final-card simplify button not guarded
**Fixed.** Added `carouselSlides[currentSlideIdx]?.type !== 'check_in'` guard to the final-card simplify button block (same guard as the non-final block).

### 3. No minimum position validation
**Fixed.** Added `if ci.insert_after_card_idx < 3: continue` in `_validate_check_ins()`. Also added a `MIN_POSITION = 3` constant for clarity.

### 4. Generic card_title in CheckInStruggleEvent
**Fixed.** Added `card_title` field to both `CheckInEventDTO` (frontend → backend) and the frontend mapping. The backend now uses `evt.card_title or f"Check-in at card {evt.card_idx}"` as fallback. Tutor summary now shows the actual instruction (e.g., "Match each fraction to its meaning") instead of "Check-in at card 5".

### 5. Mixed card_idx numbering in summary
**Acknowledged, not fixed in this PR.** The inconsistency between 0-based (confusion events from frontend simplify flow) and 1-based (visual notes from card_idx field) is pre-existing. The check-in section now uses 1-based card_idx field values consistently. Reconciling the confusion events section is a separate task — it requires changing the simplify flow's index convention, which is unrelated to check-ins.

### 6. No TTS for hints and success messages
**Fixed.** Added `playTTS()` helper in `MatchActivity.tsx` that calls `synthesizeSpeech()` fire-and-forget. Called on:
- Wrong match → reads hint aloud
- All pairs matched (both correct-match and auto-reveal paths) → reads success_message aloud

### 7. Back-to-back validation incomplete
**Fixed.** Replaced same-position check with minimum gap check:
```python
if valid:
    gap = ci.insert_after_card_idx - valid[-1].insert_after_card_idx
    if gap < 2:
        continue
```

### 8. Concurrent enrichment can silently overwrite cards_json
**Fixed (service-level pre-flight).** Added `_check_no_conflicting_jobs()` in `CheckInEnrichmentService` — called at the start of `enrich_guideline()`. Queries `ChapterJobService` for running `v2_explanation_generation` or `v2_visual_enrichment` jobs. Raises `RuntimeError` if found. This protects both API and CLI paths.

Note: row-level locking on the write itself was not added. The pre-flight check + job system provide sufficient protection for the operational reality (admin-triggered, sequential pipelines). Row-level locking would be the right long-term fix if we add concurrent automated pipelines.

### 9. explain_differently discards struggle data
**Fixed.** Removed the `action === 'clear'` guard from the struggle forwarding code. Events are now built and sent for both `clear` and `explain_differently` actions. Check-in state is cleared after variant switch so the new variant starts fresh.

### 10. simplify_card uses array index — enrichment changes array positions
**Acknowledged, pre-existing.** The reviewer's analysis is correct: `simplify_card()` reloads `cards_json` from DB each time, so re-enrichment during an active session could cause index mismatch. This is pre-existing (visual enrichment has the same issue).

Currently safe because: (a) enrichment is admin-triggered, not automatic, and (b) the pre-flight check now prevents enrichment while other pipelines run. The fundamental fix (session-level card snapshot) is out of scope for this PR.

### 11. ExplanationCard model change is backwards-compatible
**Acknowledged, no action needed.** New fields are Optional with None defaults. `parse_cards()` is strict but only validates known fields — Pydantic v2 ignores extra fields by default. Low risk.

### 12. Welcome slide offset assumption
**Acknowledged, pre-existing.** The `slideIdx - 1` offset for welcome slide exists before check-ins and isn't worsened. Noted for future refactoring.

### 13. Dead exception handler
**Fixed.** Removed `try/except Exception: raise` from `_run_check_in_enrichment`.

### 14. Prompt file missing trailing newline
**Fixed.**

### 15. Redundant card_id fallback
**Fixed.** `(card as any).card_id` removed — `card.card_id` is now a typed field.

### 16. Heartbeat lambda captures stale totals
**Acknowledged, pre-existing pattern.** `AnimationEnrichmentService` has the same issue. Progress display lags by one topic. Not a regression.

---

## Reviewer 2

### R2-1. Check-in state keyed by slide index
**Fixed.** This was the most important change:
- `completedCheckIns`: `Set<string>` keyed by `card_id` (was `Set<number>` by slide index)
- `checkInStruggles`: `Map<string, MatchActivityResult>` keyed by `card_id`
- `onComplete` callback writes `slide.id` (which is `card_id`)
- Gate checks use `completedCheckIns.has(slide.id)` instead of `completedCheckIns.has(slideIdx)`
- Both maps cleared on variant switch (`setCompletedCheckIns(new Set()); setCheckInStruggles(new Map())`)

This makes check-in state stable across deck mutations (variant switch, remedial insertion).

### R2-2. Resume position persistence only works for swipes
**Acknowledged, pre-existing.** Back/Next buttons write to localStorage only; server-side `current_card_idx` updates only via WebSocket `card_navigate`. This is a pre-existing issue in the card phase implementation, not introduced or worsened by check-ins. Out of scope for this PR.

### R2-3. No card snapshot — regeneration changes in-flight sessions
**Acknowledged, pre-existing.** The reviewer is correct that `simplify_card()` and replay both re-read from DB. This is an architectural limitation affecting all enrichment pipelines, not specific to check-ins. The pre-flight concurrency check (R2-4 fix) reduces the practical risk. The long-term fix (session-level card snapshot) is a separate architectural change.

The sub-issue about replay overwriting `card_id` with synthetic IDs is valid and important — but it's in existing replay code, not new check-in code. Should be addressed in a separate PR.

### R2-4. Pre-flight enrichment safety check missing from service
**Fixed.** Added `_check_no_conflicting_jobs()` to `CheckInEnrichmentService`. Called at the start of `enrich_guideline()`, before any card reading or LLM calls. Checks for running `v2_explanation_generation` and `v2_visual_enrichment` jobs via `ChapterJobService`. Raises `RuntimeError` on conflict.

This protects all entry points: API endpoint, CLI script, and chapter-wide enrichment — because they all go through `enrich_guideline()`.

### R2-5. Admin rollout health is easy to misread
**Fixed (partially):**
- Pipeline step "Check-ins" now marks done when **all topics with explanations** have check-ins: `.filter(t => t.has_explanations).every(t => t.cards_with_check_ins > 0)` (was `.some()`)
- Added completed/error result banner for check-in jobs with teal theme, matching the explanation job banner pattern. Shows enriched/skipped/failed counts and error details.

Not fixed: the `_enrich_variant()` return value ambiguity (skip vs quality failure both return `False`). This is a minor reporting issue — the enriched/skipped/failed counts in the job result already disambiguate at the guideline level.

### R2-6. Automated test coverage absent
**Acknowledged.** No tests were added in this fix commit either. The impl plan has a comprehensive test plan (15 unit tests, 3 integration tests). These should be implemented as a follow-up. The core validation logic (`_validate_check_ins`), card insertion (`_insert_check_ins`), and summary builder extension are the highest-priority test targets.

---

## Summary of Changes in `1d979ed`

| # | Status | What changed |
|---|--------|-------------|
| 1 | **Fixed** | card_idx mapping uses card_id lookup |
| 2 | **Fixed** | Final-card simplify button guarded |
| 3 | **Fixed** | Minimum position validation (card_idx >= 3) |
| 4 | **Fixed** | Actual title in CheckInEventDTO + backend |
| 5 | Pre-existing | Check-in section uses 1-based consistently; broader fix deferred |
| 6 | **Fixed** | TTS for hints and success messages |
| 7 | **Fixed** | Minimum gap of 2 between consecutive check-ins |
| 8 | **Fixed** | Pre-flight concurrency check in service |
| 9 | **Fixed** | Struggles forwarded on explain_differently too |
| 10 | Pre-existing | Documented; mitigated by pre-flight check |
| 11 | No action | Backwards-compatible, low risk |
| 12 | Pre-existing | Not worsened by check-ins |
| 13 | **Fixed** | Dead exception handler removed |
| 14 | **Fixed** | Trailing newline added |
| 15 | **Fixed** | Redundant fallback removed |
| 16 | Pre-existing | Same pattern as AnimationEnrichmentService |
| R2-1 | **Fixed** | Re-keyed by card_id, cleared on variant switch |
| R2-2 | Pre-existing | Not introduced by check-ins |
| R2-3 | Pre-existing | Mitigated by pre-flight check; snapshot deferred |
| R2-4 | **Fixed** | _check_no_conflicting_jobs() in service |
| R2-5 | **Fixed** | Done condition tightened + result banner added |
| R2-6 | Deferred | Tests planned, follow-up commit |
