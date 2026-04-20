# Pre-Computed Audio — Check-In Cards Extension

Extends the explanation-card pre-computed audio pipeline (see `PRD.md`) to check-in activities.

## Problem

Check-in cards play TTS at up to four moments. Each fires `POST /text-to-speech` live (Google Cloud TTS + network ≈ 500ms–1s per call), producing a perceptible gap between user action and audio.

| String | When it plays | Current playback path |
|--------|---------------|-----------------------|
| `check_in.audio_text` | Check-in slide arrives | `playTeacherAudio` in `ChatSession.tsx:715` |
| `check_in.hint` | First wrong tap | `useCheckInAudio.play()` from each activity |
| `check_in.success_message` | Correct tap | Same |
| `check_in.reveal_text` (predict_then_reveal only) | Wrong pick → reveal | Inline `playTTS` in `PredictRevealActivity.tsx:5` |

Explanation lines already solved this via offline synth → S3 → live-TTS fallback (stage 10 / `AudioGenerationService`). Check-ins were not wired in — omission, not policy.

## Design

### 1. Storage shape — URLs on `card.check_in`

Four optional string fields, colocated with the text they describe:

```
card.check_in = {
  ...,
  audio_text_url:    Optional[str],
  hint_audio_url:    Optional[str],
  success_audio_url: Optional[str],
  reveal_audio_url:  Optional[str],  # only for predict_then_reveal
}
```

Not on the card top level — frontend reads `card.check_in.audio_text` (not the duplicated `card.audio_text`) for playback, so the URL belongs next to its text. Not on `CheckInDecision` — that is LLM output; URLs are populated post-LLM by `AudioGenerationService`, mutating the stored dict. Persists via `topic_explanations.cards_json` (JSONB) — no migration.

### 2. S3 key uses `card_id` (UUID), not `card_idx`

```
audio/{guideline_id}/{variant_key}/{card_id}/check_in/{field}.mp3
  # field ∈ {audio_text, hint, success, reveal}
```

Rationale: check-in `card_idx` is renumbered on every `_insert_check_ins` pass (`check_in_enrichment_service.py:386`). A positional key could serve audio from a previous occupant after a re-insert. `card_id` is a UUID assigned in `_build_check_in_card` — stable for the life of that check-in.

Explanation lines keep their existing `{card_idx}/{line_idx}.mp3` keys — lines don't get re-inserted, and migrating live URLs isn't worth the churn.

### 3. Synthesis rule

Per check-in, `AudioGenerationService.generate_for_cards` synthesizes whichever of (`audio_text`, `hint`, `success_message`, `reveal_text` if `activity_type == "predict_then_reveal"`) is non-empty and has no corresponding `*_audio_url`. Skip empties, skip already-URL-stamped. Same idempotency rule as line audio. Fail per-field, not per-card — a single TTS error leaves that field null and the frontend falls back to live TTS.

### 4. Stale-audio invalidation — extend stage 6

`audio_text_review_service.py` reviews `line.audio` (clears `line.audio_url`) and card-level `audio_text` on check-in cards (no URL to clear). It does **not** touch `check_in.hint` / `success_message` / `reveal_text` — their text can be rewritten without invalidating the stale audio. The prior draft handwaved this. Concrete changes:

- `AudioLineRevision.kind` Literal gains three values: `check_in_hint`, `check_in_success`, `check_in_reveal`.
- `_apply_revisions`: on each new kind, verify `card_type == "check_in"` + drift-check `original_audio`, write `revised_audio` into the correct nested field, clear the corresponding URL.
- `_strip_audio_urls`: also strip the four new URL fields before sending the card to the reviewer.
- `prompts/audio_text_review.txt`: surface hint / success / reveal alongside the existing fields; document the new kinds.
- Banned-pattern validation (`_validate_revision`) applies unchanged.

### 5. Frontend — three playback surfaces, two hook extensions

**a. `useCheckInAudio.play(text, audioUrl?)`**
When `audioUrl` is present, `fetch(url)` → blob → play. On non-OK response or fetch failure, fall back to `synthesizeSpeech(text)`. Mirrors `prefetchAudio` in `ChatSession.tsx:775-823`. This one hook covers `hint` / `success` / `reveal` for every activity that uses it.

**b. `playTeacherAudio(text, slideId?, audioUrl?)`**
Same extension for the instruction audio. Call sites in `ChatSession.tsx` (`:291`, `:327`, `:1254`) pass `slide.audioUrl`; slide construction (`:216`) reads `card.check_in.audio_text_url` into `slide.audioUrl`.

**c. Migrate the two outliers to the hook**
`SpotTheErrorActivity.tsx:5-14` and `PredictRevealActivity.tsx:5-14` have inline copies of the pre-hook `playTTS`. Delete both; use `useCheckInAudio` like the other 9. This is required for consistent URL plumbing.

**d. Per-activity call-site updates**
Every `*Activity.tsx` calls `playTTS(checkIn.hint)` and/or `playTTS(checkIn.success_message)` (and `reveal_text` in PredictReveal). Each call gains the matching URL arg. Count: ~22 call sites across 11 files, all one-line edits.

**e. `CheckInActivity` TS interface** (`api.ts:94`)
Add four optional `_audio_url` fields.

### 6. Pipeline-status coverage

`topic_pipeline_status_service.py:467-492` computes the `audio_synthesis` stage from `lines_with_audio / total_lines`. Without update it would report "done" while check-in audio is missing. Extension: for each check-in card, add its non-empty audio strings to `total_lines` and its populated `*_audio_url`s to `lines_with_audio`. Unified count, summary wording stays similar ("X/Y audio clips have pre-computed MP3").

## What does NOT change

- **`CheckInDecision` Pydantic model** — LLM output; URLs arrive post-synth, not from the LLM.
- **`_build_check_in_card`** — builds fresh check-ins with no URLs; first synth pass populates them.
- **Admin bulk-gen endpoint** (`_run_audio_generation`, `sync_routes.py:904`) — delegates to `generate_for_topic_explanation` → `generate_for_cards`. Once the service walks check-ins, backfill "just works".
- **Explanation-line pipeline and S3 keys** — untouched.

## Migration

Existing books have no check-in URLs. The three live-TTS fallbacks (hook, `playTeacherAudio`, plus the two migrated inline sites) keep them working. Backfill = existing admin bulk-gen trigger, once `generate_for_cards` is extended. Idempotent; re-runs skip anything already URL-stamped. No DB migration needed (JSONB).

## Out of Scope

- Content-hash dedup across books — positional+UUID keys are fine for now.
- Migrating explanation-line S3 keys to UUID — existing URLs work; not worth the rewrite.
- Streaming TTS — MP3s are 5–15 KB, full download is fine.
- Interactive-phase teacher-response TTS — different path (tutor session, not offline-pre-computable), low volume, live TTS acceptable.

## Files Touched

| Layer | File | Change |
|-------|------|--------|
| Ingestion synth | `book_ingestion_v2/services/audio_generation_service.py` | `generate_for_cards`: walk `card.check_in`; synth up to 4 fields conditional on activity_type; UUID-based S3 key for check-ins |
| Ingestion review | `book_ingestion_v2/services/audio_text_review_service.py` | `AudioLineRevision.kind`: add `check_in_hint` / `check_in_success` / `check_in_reveal`; apply + URL-clear; extend `_strip_audio_urls` |
| Prompt | `book_ingestion_v2/prompts/audio_text_review.txt` | Surface hint/success/reveal; document new kinds |
| Pipeline status | `book_ingestion_v2/services/topic_pipeline_status_service.py` | Count check-in audio clips in `audio_synthesis` stage |
| Frontend hook | `llm-frontend/src/hooks/useCheckInAudio.ts` | `play(text, audioUrl?)` with S3-then-live fallback |
| Frontend types | `llm-frontend/src/api.ts` | Add 4 optional `_audio_url` fields to `CheckInActivity` |
| Frontend playback | `llm-frontend/src/pages/ChatSession.tsx` | Extend `playTeacherAudio(text, slideId?, audioUrl?)`; plumb `audio_text_url` at slide construction + call sites |
| Frontend outliers | `SpotTheErrorActivity.tsx`, `PredictRevealActivity.tsx` | Replace inline `playTTS` with `useCheckInAudio` hook |
| Frontend activities | `PickOneActivity`, `TrueFalseActivity`, `FillBlankActivity`, `MatchActivity`, `SortBucketsActivity`, `SequenceActivity`, `OddOneOutActivity`, `SwipeClassifyActivity`, `TapToEliminateActivity` (9 files) | Pass matching URL to each `play(...)` call |

## Implementation Order

1. **Backend synth** — extend `AudioGenerationService.generate_for_cards` (+unit tests). Deploy.
2. **Backfill one test chapter** via existing admin bulk-gen trigger. Verify URLs present in `cards_json` for all four fields across all activity types (predict_then_reveal → 4 fields; others → 3).
3. **Stage 6 extension** — `audio_text_review_service` + prompt update. Unit-test the four kinds (including drift + URL-clear).
4. **Pipeline status** — update `topic_pipeline_status_service` so stage state reflects check-in coverage.
5. **Frontend types** (`CheckInActivity` interface) → hook extension → `playTeacherAudio` extension → migrate the two outliers → per-activity call-site updates.
6. **Manual QA** — one variant with pre-computed URLs, one variant without (validates fallback). Cover all 11 activity types. Verify no audible gap on pre-computed path; verify identical behavior to today on fallback path.
7. **Full backfill** across approved chapters.

## Success Criteria

- Time-to-first-audio on check-in interactions drops from ~500ms–1s to sub-200ms on pre-computed content.
- `audio_synthesis` stage reports accurate coverage including check-ins.
- Old books (no URLs) keep working via fallback — no regression.
- Stage 6 text rewrite of hint/success/reveal invalidates corresponding audio on the same run; subsequent synth re-generates it.
