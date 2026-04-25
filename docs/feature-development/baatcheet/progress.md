# Baatcheet — Implementation Progress

**Date:** 2026-04-25
**Status:** Backend complete; frontend rendering wired; code-review fixes F1–F9 landed; CSS + PEER_VOICE + minimum unit tests landed; end-to-end ingestion + browser smoke + ChatSession refactor pending
**PRD:** `docs/feature-development/baatcheet/PRD.md` (PR #119)
**Impl plan:** `docs/feature-development/baatcheet/impl-plan.md` (PR #120)
**Code review:** `docs/feature-development/baatcheet/code-review.md`
**Fix plan (consolidated):** `docs/feature-development/baatcheet/pr121-fix-plan.md`

---

## Summary

All 28 build-sequence steps from the impl plan were executed except **Step 21 (ChatSession.tsx refactor)**, which was intentionally deferred to a follow-up cleanup PR. Baatcheet is shipped as a **standalone** `BaatcheetViewer` so Explain mode keeps using the existing inline ChatSession render path unchanged.

Total: **12 new files + 23 modified files** (close to the plan's 14 + 21 budget — `BaatcheetAudioReviewService` is ~150 lines; the deferred refactor accounts for the missing 2 new files).

---

## What's Done

### DB foundations (Steps 1–4)
- `topic_dialogues` ORM model (`shared/models/entities.py`) — one row per guideline, cascade-deleted with guideline, semantic `source_content_hash` column.
- Migration helpers in `db.py` — `_apply_topic_dialogues_table`, `_apply_sessions_teach_me_mode_column` (rebuilds paused-session unique index to include `teach_me_mode`).
- `_LLM_CONFIG_SEEDS` extended with `baatcheet_dialogue_generator` (provider `claude_code`, model `claude-opus-4-7`).
- `dialogue_hash.py` — semantic-fields-only SHA-256 over `card_type`, `title`, `content`, `audio_text`, `lines[].display`, `lines[].audio`, plus `summary_json` keys. Excludes `audio_url`, `pixi_code`, `visual_explanation` so enrichment refreshes don't trigger false staleness.
- `DialogueRepository` mirrors `ExplanationRepository`. `is_stale()` compares current variant A hash to stored hash.

### Stage 5b — Dialogue generator (Steps 5–6)
- `baatcheet_dialogue_generator_service.py` + 4 prompts (`baatcheet_dialogue_generation*.txt`, `baatcheet_dialogue_review_refine*.txt`).
- **Welcome card 1 is prepended server-side** using the literal PRD §FR-14 template. LLM produces cards 2..N only.
- `_BANNED_AUDIO_PATTERNS` regex (markdown bold, naked equals, emoji ranges) enforced at generation time; matches `audio_text_review_service.py` patterns.
- **No silent truncation.** Validator failure raises `DialogueValidationError`, which the route surfaces as a failed job.
- Review-refine feeds the validator's issue list into the next refine prompt as repair instructions.
- Stores `source_explanation_id` (debug FK) + `source_content_hash` on upsert.

### Stage 5c — Visual enrichment (Step 7)
- `baatcheet_visual_enrichment_service.py` + `baatcheet_visual_intent.txt`.
- Reuses `tutor/services/pixi_code_generator.py` unchanged. No review-refine pass (matches simpler check-in pattern; if quality drifts post-launch, copy review-refine from `AnimationEnrichmentService`).

### Pipeline plumbing (Steps 8–10)
- 3 new `V2JobType` values: `BAATCHEET_DIALOGUE_GENERATION`, `BAATCHEET_VISUAL_ENRICHMENT`, `BAATCHEET_AUDIO_REVIEW`.
- 3 new launchers + `LAUNCHER_BY_STAGE` extended.
- `PIPELINE_LAYERS` reordered: `explanations → baatcheet_dialogue → baatcheet_visuals → visuals → check_ins → practice_bank → audio_review → audio_synthesis`. **Sequential layers**, not parallel — per-topic lock would force serialization anyway; parallel branch needs a `lock_channel` schema change deferred to V2.
- `QUALITY_ROUNDS` extended with `baatcheet_dialogue` (0/1/2 for fast/balanced/thorough).
- `topic_pipeline_status_service.py` gets two new stage computations + content-hash staleness for Baatcheet (mismatch → warning state with "Variant A has changed since dialogue was generated" warning).

### Audio synthesis (Step 11)
- Per-call voice routing in `audio_generation_service.py`: `_voice_for_speaker(speaker, language)`, `TUTOR_VOICE`/`PEER_VOICE` constants. Variant A behavior unchanged when `speaker` is absent.
- `generate_for_topic_dialogue(dialogue)`: skips `includes_student_name` cards, routes voice per `card.speaker`, S3 keys live in parallel namespace `audio/{guideline_id}/dialogue/{card_id}/{line_idx}.mp3`. Mandatory `card_id` per dialogue card.
- `_run_audio_generation` in `sync_routes.py` extended to also process dialogues per guideline.

### Opt-in audio review (Step 12)
- `baatcheet_audio_review_service.py` wraps existing `AudioTextReviewService`. Reuses per-card LLM call + `_apply_revisions` machinery.
- Admin route `POST /review-baatcheet-audio` + launcher.
- **Frontend button NOT wired** — backend is ready, UI affordance deferred to a polish pass.

### Admin frontend (Step 13)
- `adminApiV2.ts` extended with `generateBaatcheetDialogue`, `generateBaatcheetVisuals`, `reviewBaatcheetAudio`, plus the two new `StageId` values.
- `TopicPipelineDashboard` STAGE_ORDER updated; `handleStageAction` routes to the new generators.
- `StageLadderRow` STAGE_LABELS gets entries for `baatcheet_dialogue` and `baatcheet_visuals`. Stale warnings render automatically through the existing `state="warning"` + `warnings[]` path.

### Tutor runtime (Steps 14–19)
- `DialoguePhaseState` + `teach_me_mode` field added to `SessionState`. `is_complete` honors Baatcheet completion.
- `SessionService.create_new_session` resolves `teach_me_mode`, branches into a Baatcheet path that loads from `DialogueRepository`, raises `BaatcheetUnavailableError` (→ 409 with detail code `baatcheet_unavailable`), forces refresher topics to `"explain"`.
- `record_card_progress` — single endpoint for fwd/back nav + summary-card completion + check-in struggle events. Idempotent on `mark_complete`.
- `_finalize_baatcheet_session` pulls covered concepts from variant A's `summary_json.card_titles` (fallback: dialogue card titles excluding chrome). Without this, Baatcheet completions would zero-out scorecard.
- `_finalize_explain_session` extracted with the same idempotent contract.
- New routes: `POST /sessions/{id}/card-progress`, `GET /sessions/teach-me-options` (aggregator drives the chooser).
- `/resumable` and `/guideline/{id}` surface `teach_me_mode` in their responses.
- `/text-to-speech` accepts `voice_role: Literal["tutor", "peer"]` (security boundary — never accept arbitrary voice IDs from frontend).
- **Explain replay off-by-one bug fixed.** ChatSession was using `current_card_idx + 1`; the welcome card is `cards_json[0]` and the carousel maps 1:1 onto `cards_json`, so the +1 was double-counting.

### Frontend types + client (Step 20)
- `api.ts` types: `TeachMeMode`, `DialogueSpeaker`, `DialogueCardType`, `DialogueLine`, `DialogueCard`, `DialoguePhaseDTO`, `Personalization`, `CardProgressRequest`, `TeachMeOptionState`, `TeachMeOptionsResponse`. `Turn` extended with dialogue fields. `ResumableSession` and `GuidelineSessionEntry` carry `teach_me_mode`.
- New client functions: `getTeachMeOptions`, `postCardProgress`. `synthesizeSpeech` accepts `{ voiceRole }`.

### Frontend rendering (Steps 22–24)
- `TeachMeSubChooser.tsx` — new sub-step page at `/learn/:subject/:chapter/:topic/teach`. Two cards (Baatcheet recommended, Explain secondary). Surfaces availability, in-progress / completed CTAs, stale badge.
- `ModeSelectPage` redirects Teach Me click to the chooser instead of creating the session directly.
- `BaatcheetViewer.tsx` — standalone deck viewer. Owns carousel state, audio playback rules (auto-play on first visit, no replay on revisit), `SpeakerAvatar` cross-fade, debounced `/card-progress` posting, summary-card completion mark.
- `SpeakerAvatar.tsx` + V1 placeholder SVGs (`public/avatars/tutor.svg`, `public/avatars/peer.svg`).
- `usePersonalizedAudio` hook — runtime TTS for `includes_student_name` cards with concurrency cap of 4. Stores blobs under synthetic keys via `attachClientAudioBlob`.
- `audioController.ts` extended with `attachClientAudioBlob` / `getClientAudioBlob` / `clearClientAudioBlobs`.
- `ChatSession.tsx` early-returns to `BaatcheetViewer` when `session_phase === 'dialogue_phase'`. Replay path rehydrates from new `_replay_dialogue_cards` and `_replay_dialogue_personalization` fields the backend surfaces in `GET /sessions/{id}/replay`.

### Resume + stale (Steps 25–28)
- Resume Baatcheet: server is the source of truth. `getTeachMeOptions` returns the latest session per submode (does not require `is_paused = true`); `BaatcheetViewer` accepts `initialCardIdx`.
- Resume Explain off-by-one fix landed in Step 16.
- Stale-dialogue admin warning is automatic through the existing `StageStatus` warning rendering.
- Bulk "Regenerate all stale dialogues" button — deferred (plan flagged as optional).

---

## Key architectural decisions made during implementation

These are the same decisions called out in the impl plan §1, applied as written:

1. **Submode (`teach_me_mode`), not top-level `mode`** — preserves existing report card / scorecard / coverage logic that keys off `mode == "teach_me"`.
2. **Staleness via `source_content_hash`**, not timestamp — `topic_explanations` lacks `updated_at` and enrichment mutates `cards_json` in place.
3. **`_BANNED_PATTERNS` regex in Stage 5b validators**; default audio_text_review NOT extended to dialogues in V1. Opt-in admin button is the safety valve.
4. **Welcome card prepended server-side**, not LLM-generated — LLMs drift even with strict prompts; the PRD specifies the literal text.
5. **`source_content_hash` excludes `audio_url`, `pixi_code`, `visual_explanation`** — these mutate during enrichment without changing semantic identity.
6. **Sequential pipeline layers** (5b/5c BEFORE variant A enrichment) — parallel branch needs a `lock_channel` schema change deferred to V2.
7. **Coverage propagation uses variant A concepts** — Baatcheet completion contributes identical coverage regardless of submode.
8. **`card_id` mandatory for dialogue cards** — regen rotates content; positional keys would race.
9. **`voice_role` allowlist on TTS endpoint** — security boundary prevents frontend from passing arbitrary Google voice IDs.
10. **Refresher topics force `teach_me_mode = "explain"` in V1** — PRD doesn't address; safest default.

---

## Code-review feedback addressed (in this PR)

After the first revision was reviewed, the following blockers + concerns were verified against the code and fixed in-PR:

1. **Migration ordering bug** (Blocker #1) — `_apply_practice_mode_support` ran after my migration and clobbered the index back to 3-col, dropping `teach_me_mode`. Violated PRD §FR-4 (paused Baatcheet + paused Explain couldn't coexist). Fix: made `_apply_practice_mode_support` teach_me_mode-aware (column-detect + 4-col when present, 3-col fallback). Both helpers now converge on the same index regardless of order — robust against future migration reordering.
2. **Stage 5c PixiJS never rendered** (Blocker #2) — `BaatcheetViewer` only displayed `visual_intent` text, throwing away the generated `pixi_code`. Fix: imported `VisualExplanationComponent` (the same Pixi runner Explain mode uses, sandboxed in an iframe) and rendered it when `visual_explanation.pixi_code` is present. `autoStart` is wired to first-visit.
3. **Explain resume regression** (Blocker #3) — my "off-by-one fix" assumed the server's `card_phase.current_card_idx` was being written by the frontend; verification showed nothing in the frontend ever sends `card_navigate`, so the server's value is always 0. The previous `+1` masked this by landing at card 1; my change made it land at card 0 always. Fix: inverted priority — read `localStorage` first (the actual truth source for Explain), fall back to server only when `localStorage` is empty. Better than the original `+1` because it now honors actual progress where the user navigated.
4. **`{student_name}` outside `lines[].audio` plays silently** (Bug #5) — my own system prompt explicitly asked the LLM to put `{student_name}` inside check-in instructions, but `audio_generation_service.py` skips the entire flagged card before iterating check-in fields, and `usePersonalizedAudio` doesn't synthesize check-in fields. Fix: tightened the prompt to forbid `{student_name}` in any `check_in.*` field + extended the validator to detect violations across `check_in.{instruction, hint, success_message, audio_text, reveal_text, statement}`. Also added a check that `{student_name}` in `lines[].display` must mirror in `lines[].audio` (otherwise the student would see the name but not hear it).
5. **`process_step` doesn't reject `dialogue_phase`** (Concern #7) — Baatcheet sessions calling `POST /sessions/{id}/step` would fall through to the orchestrator with surprising results. Fix: added the parallel `is_in_dialogue_phase()` guard alongside the existing `is_in_card_phase()` check.
6. **`/teach-me-options` Python-side filter** (Concern #10) — the endpoint was loading all teach_me sessions then filtering `teach_me_mode` in Python. Fix: pushed the filter to SQL via `func.coalesce(SessionModel.teach_me_mode, 'explain') == submode` + `.first()`. Index `idx_sessions_user_guideline_teach_mode` covers the leading filter columns.
7. **Stage 5b blocked-by uses `any` variant** (Concern #12) — Stage 5b raises `ValueError` if specifically variant A is missing, but the status tile said "ready" if any variant existed. Fix: filter to `variant_key == "A"` so the tile reflects the runtime contract.
8. **Validator card-count floor** (Nit) — prompt asks for 24-34 LLM cards (final 25-35), but `MIN_TOTAL_CARDS = 13` was way looser. Tightened to `25` so the floor matches the prompt's lower bound.
9. **Empty topic_name fallback** (Nit) — `_build_personalization` and `_replay_dialogue_personalization` fell back to empty string. Changed to `"this topic"` so a missing guideline title doesn't render `{topic_name}` as nothing.

Verified each fix with structural + behavioral smoke tests (validator catches all 5 new failure modes; structural checks confirm the SQL coalesce, variant-A filter, and migration convergence).

### Deferred from review to follow-up PRs

- **#3 long-term fix** — wire Explain forward/back nav to `postCardProgress({phase: 'card_phase', ...})`. Will land with the ChatSession refactor since both touch the same nav handlers.
- **#4 — Check-in struggle events not sent.** PRD §10 doesn't require for V1; either wire `usePersonalizedAudio` + `BaatcheetViewer.onCheckInComplete` to send `check_in_events`, or remove `DialoguePhaseState.check_in_struggles` until V2.
- **#6 — Schema-less prompt path for non-Claude providers.** Defensive against a future config change; mirror `explanation_generator_service.py:332-352`'s inline fallback.
- **#8 — Banned-pattern emoji range.** Same parity gap exists in `audio_text_review_service.py`; tighten both regexes together.
- **#9 — `_build_welcome_card_pydantic` ignored guideline param.** Could bake `{topic_name}` server-side and remove the second runtime substitution path.
- **#11 — Coverage source mismatch.** Pre-existing in Explain. Both modes use card titles, not concepts; `study_plan.get_concepts()` (which seeds `mastery_estimates`) doesn't align with either. Fix should touch both modes consistently.
- **#13 — `asyncio.run` in Stage 5c thread.** Currently safe (daemon thread); add a defensive comment and switch to `new_event_loop()` if the orchestrator ever async-dispatches.
- **Other nits** — `audio_generation_service.py:310` whole-card skip, `BaatcheetViewer` initial visited set means resume to non-zero card won't autoplay (PRD-compliant but UX-debatable).

---

## Deviations from the impl plan

### 1. ChatSession.tsx refactor deferred (Step 21)

**Plan said:** "Refactor before adding Baatcheet rendering — non-negotiable. Extract `DeckCarousel`, `ExplanationViewer`, `useCardProgressPersistence`, `useDeckAudio`."

**Shipped instead:** `BaatcheetViewer` is standalone with its own carousel state. Explain mode is unchanged.

**Why:** The extraction touches ~1700 lines of fragile logic (audio rules, simplifications, remedial cards, check-ins, blob caching). Doing it in the same PR raises Explain regression risk meaningfully. Keeping Explain on the existing path lets us ship Baatcheet end-to-end and keeps the blast radius small.

**Owed:** A follow-up cleanup PR that extracts the shared deck primitives. Both viewers should converge on `DeckCarousel` + `useDeckAudio` once the refactor lands.

### 2. Opt-in audio review UI button not wired (Step 12)

Backend route + service + launcher are all in place. The "Review Baatcheet audio" button next to the audio_synthesis tile context menu was not added. Editors can hit the route via curl until the polish pass.

### 3. Bulk "Regenerate all stale dialogues" button (Step 28)

Plan flagged optional in V1; not built.

---

## What was NOT verified

- **No frontend type-check.** `tsc` is not installed locally and no `vite build` was run. The new `.tsx` files compile in isolation by inspection but have not been verified end-to-end.
- **No runtime test against real DB / LLM.** Backend modules import cleanly and committed unit tests pass (see `tests/unit/test_baatcheet.py`, 36 tests), but the full Stage 5b → 5c → audio synthesis flow has not been exercised against a real guideline.
- **No browser test.** CSS landed (see "CSS landed" below) but no real browser walk-through has been done.
- **Persistence migration applied.** `python db.py --migrate` ran cleanly: `teach_me_mode` column added, 621 teach_me sessions backfilled to `'explain'`, both indexes (paused-unique + lookup) include `teach_me_mode`. `topic_dialogues` table + unique-on-`guideline_id` index in place.

---

## CSS landed

`llm-frontend/src/App.css` now styles all classes the new components reference:

- BaatcheetViewer chalk-island wrapper (`.baatcheet-active` + `.baatcheet-viewer*`) — chalkboard-themed since ChatSession is OUTSIDE AppShell so `.chalkboard-active` isn't on the parent.
- `.speaker-avatar` + `.speaker-avatar--speaking` + `.speaker-avatar__pulse` — circular avatar with cross-fade keyframe + speaking-indicator pulse ring; respects `prefers-reduced-motion`.
- Sub-chooser cards under `.chalkboard-active` (TeachMeSubChooser is INSIDE AppShell): `.mode-cards`, `.selection-card.baatcheet-card` (gold-bordered, recommended), `.selection-card.explain-card` (quieter secondary), `.selection-card.is-disabled`, `.mode-card-title`, `.mode-card-stale` badge, `.badge` (Recommended pill), `.selection-step__title`.
- Mobile-tightening media query at `max-width: 600px` for both scopes.

`.session-error-banner` was already styled in chalkboard mode (App.css:5083) — re-used, no new rule.

---

## PEER_VOICE selected (heuristic, pre-audition)

`PEER_VOICE` set to `("hi-IN", "hi-IN-Chirp3-HD-Leda")` — Leda is documented as a youthful feminine voice in Google's Chirp 3 HD catalog, contrasts most audibly with Kore (the tutor's smooth/professional voice), and matches Meera's peer-aged persona. Pick is heuristic, NOT the result of a real audition — keep an eye on the first dialogue listen-test and revisit if it sounds too similar to Kore in production audio.

---

## Unit tests landed

`llm-backend/tests/unit/test_baatcheet.py` — 36 tests covering the minimum set called out in the fix plan:

- F1: ORM round-trip — `Session.teach_me_mode` persists `'baatcheet'`, defaults to `'explain'`, paused Baatcheet + paused Explain coexist for same `(user, guideline)`.
- F4: `count_dialogue_audio_items` skips `includes_student_name` cards, skips `{student_name}` placeholder lines, counts check-in fields.
- F5: `{topic_name}` outside welcome card → validator failure; inside welcome card → passes.
- F6: `{student_name}` in `check_in.hint` → fail; markdown bold in `check_in.audio_text` → fail; emoji in `check_in.success_message` → fail; unsupported `activity_type` → fail.
- F7: `BaatcheetAudioReviewService` (delegates to `AudioTextReviewService._apply_revisions`) lands `check_in_text` revisions on dialogue check-in cards (no top-level `audio_text`); drift-mismatch still drops revisions.
- F8: `_finalize_baatcheet_session` populates `concepts_covered_set` AND `card_covered_concepts` with concept tokens (not display titles) → `coverage_percentage = 100%`; idempotent; no-op without dialogue_phase.
- F9: emoji range covers Misc Technical (`▶` U+25B6 in `lines[].audio` → fail).
- Voice routing — peer → `PEER_VOICE`; tutor → `VOICE_MAP[lang]`; absent speaker → tutor (variant A backwards compat); peer ≠ Kore.
- TTS allowlist — `voice_role: "tutor"|"peer"` accepted; arbitrary string + None rejected via Pydantic Literal.
- DialogueCard schema round-trip + invalid speaker / card_type rejected.
- Hash invariants — `audio_url` / `pixi_code` / `visual_explanation` mutations don't change hash; line text edit does.

Pre-existing 68 unit-test failures in the suite are unrelated to Baatcheet (test_topic_adapter, test_session_service::test_create_session_success, test_safety_agent::test_prompt_mentions_safety_checks, etc.) — confirmed by stashing baatcheet changes and re-running.

---

## Next steps before merge

1. **End-to-end ingestion test** — open admin TopicPipelineDashboard for a topic with variant A done, run `Generate Baatcheet Dialogue`, then `Generate Baatcheet Visuals`, then `Generate Audio`. Verify the `topic_dialogues` row appears with content_hash, dialogue MP3s land in `audio/{guideline_id}/dialogue/...`, and the audio_synthesis tile reports both variant A and dialogue clip counts (F4 fix).
2. **Browser smoke test** — pick a topic, tap Teach Me → see chooser → tap Baatcheet → walk through the dialogue → verify avatar swap, audio playback in Leda for peer turns + Kore for tutor turns, check-in dispatch, summary completion + Practice CTA, and resume after exit.
3. **Audition listen-test on Leda** — listen to ~3 dialogue cards Meera-side; if it sounds too similar to Kore, swap to one of Charon/Fenrir/Orus/Puck (male) or Aoede (other female) and re-test.
4. **Update PR #121 description** to reflect the F1–F9 fixes + CSS + PEER_VOICE + tests landed.

## Next steps before pilot

1. **ChatSession.tsx refactor** (Step 21) as a separate cleanup PR.
2. **Wire the "Review Baatcheet audio" admin button** (Step 12 polish).
3. **Bulk "Regenerate all stale dialogues" button** (Step 28).
4. **Feature flag `enable_baatcheet_mode`** — soft-launch lever. Plan §10.2 describes the rollout path.
5. **Curriculum reviewer pass** on the first 10 generated dialogues (PRD §14.3 success criterion).

---

## File inventory

### New files (12)

```
llm-backend/
├── shared/
│   ├── repositories/dialogue_repository.py
│   └── utils/dialogue_hash.py
├── book_ingestion_v2/
│   ├── services/baatcheet_dialogue_generator_service.py
│   ├── services/baatcheet_visual_enrichment_service.py
│   ├── services/baatcheet_audio_review_service.py
│   └── prompts/
│       ├── baatcheet_dialogue_generation.txt
│       ├── baatcheet_dialogue_generation_system.txt
│       ├── baatcheet_dialogue_review_refine.txt
│       ├── baatcheet_dialogue_review_refine_system.txt
│       └── baatcheet_visual_intent.txt

llm-frontend/
├── src/
│   ├── pages/TeachMeSubChooser.tsx
│   ├── components/baatcheet/SpeakerAvatar.tsx
│   ├── components/teach/BaatcheetViewer.tsx
│   └── hooks/usePersonalizedAudio.ts
└── public/avatars/
    ├── tutor.svg
    └── peer.svg
```

### Modified files (23)

```
llm-backend/
├── db.py                                         (+ 2 migration helpers, + LLM seed row)
├── shared/models/entities.py                     (+ TopicDialogue ORM)
├── shared/models/schemas.py                      (+ teach_me_mode, + Personalization, + TeachMe types)
├── shared/repositories/session_repository.py     (list_by_guideline returns teach_me_mode)
├── book_ingestion_v2/
│   ├── constants.py                              (+ 3 V2JobType values)
│   ├── models/schemas.py                         (StageId Literal extended)
│   ├── services/stage_launchers.py               (+ 3 launchers)
│   ├── services/topic_pipeline_orchestrator.py   (PIPELINE_LAYERS, QUALITY_ROUNDS)
│   ├── services/topic_pipeline_status_service.py (+ 2 stage statuses, content_hash staleness)
│   ├── services/audio_generation_service.py      (per-speaker voice, generate_for_topic_dialogue)
│   └── api/sync_routes.py                        (+ 3 routes, + 3 _run_* fns, dialogue branch in _run_audio_generation)
└── tutor/
    ├── models/session_state.py                   (+ DialoguePhaseState, + teach_me_mode)
    ├── services/session_service.py               (+ baatcheet branch, + record_card_progress, + _finalize_baatcheet_session)
    ├── api/sessions.py                           (+ /card-progress, + /teach-me-options, + dialogue replay hydration, + 409 mapping)
    └── api/tts.py                                (+ voice_role allowlist)

llm-frontend/
├── src/
│   ├── api.ts                                    (+ DialogueCard types, + new client fns, + voiceRole)
│   ├── App.tsx                                   (+ /learn/.../teach route)
│   ├── pages/ChatSession.tsx                     (dialogue_phase short-circuit, replay rehydrate, off-by-one fix)
│   ├── pages/ModeSelectPage.tsx                  (Teach Me click → sub-chooser)
│   ├── hooks/audioController.ts                  (+ attachClientAudioBlob)
│   └── features/admin/
│       ├── api/adminApiV2.ts                     (+ StageId values, + 3 generate fns)
│       ├── pages/TopicPipelineDashboard.tsx      (STAGE_ORDER, handleStageAction)
│       └── components/StageLadderRow.tsx         (STAGE_LABELS for new stages)
```
