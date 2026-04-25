# Baatcheet — Code Review (PR #121)

**Date:** 2026-04-25
**PR:** https://github.com/manishjain-py/learnlikemagic/pull/121 (`feat/baatcheet-conversational-teach-me`)
**Verdict:** 3 blockers, 3 functional bugs, 8 concerns, several nits. Migration shape, hash-based staleness, and per-speaker voice routing land well. Don't merge until blockers are fixed.

---

## Blockers (must fix before merge)

### 1. Migration leaves the wrong paused-session unique index
**File:** `llm-backend/db.py:144-151`

`_apply_sessions_teach_me_mode_column()` (line 798) drops `idx_sessions_one_paused_per_user_guideline` and recreates it on `(user_id, guideline_id, mode, teach_me_mode)`. Then `_apply_practice_mode_support()` runs a few lines later (called at line 151, defined at line 314) and **re-drops** the same index name and recreates it on `(user_id, guideline_id, mode)` — without `teach_me_mode`.

End state on every fresh OR existing DB:
```
idx_sessions_one_paused_per_user_guideline ON (user_id, guideline_id, mode) WHERE is_paused = TRUE
```

**Consequences:**
- A paused Baatcheet and a paused Explain on the same `(user_id, guideline_id)` cannot coexist (both `mode='teach_me'`). Violates PRD §FR-4.
- The second `pause_session()` for the alternate submode will raise a unique-constraint violation in PG.

**Fix:** move `_apply_sessions_teach_me_mode_column(db_manager)` (db.py:145) to run *after* `_apply_practice_mode_support(db_manager)` (db.py:151), OR update `_apply_practice_mode_support` to include `teach_me_mode`.

### 2. Stage 5c PixiJS code is never rendered
**File:** `llm-frontend/src/components/teach/BaatcheetViewer.tsx:226-263`

```tsx
const visualPixiCode = currentCard.visual_explanation?.pixi_code || null;
...
{visualPixiCode ? (
  <div className="baatcheet-visual-stage" data-pixi-pending={visualPixiCode ? 'true' : 'false'}>
    {currentCard.visual_intent && (
      <p className="baatcheet-viewer__visual-fallback">{currentCard.visual_intent}</p>
    )}
  </div>
) : ...}
```

Comment claims "PixiJS stage is wired by the existing visual harness," but this component imports nothing PixiJS-related — no `<canvas>`, no Pixi runner, no integration with `tutor/services/pixi_code_generator.py`'s output. Visual cards display only the `visual_intent` text fallback. Stage 5c is generating PixiJS code that the viewer throws away.

Not CSS-pending — missing logic. Either render via the same `VisualExplanationComponent` Explain mode uses (already imported in `ChatSession.tsx:31`), or remove Stage 5c from V1.

### 3. Explain replay "off-by-one fix" silently breaks Explain resume
**File:** `llm-frontend/src/pages/ChatSession.tsx:533-539`

The change rewrites:
```js
slideIdx = state.card_phase.current_card_idx + 1; // +1 for welcome slide
```
to:
```js
slideIdx = state.card_phase.current_card_idx;
```

But there is no code path on the frontend that *writes* `card_phase.current_card_idx` for Explain mode:
- `record_card_progress` is only called from `BaatcheetViewer` with `phase: 'dialogue_phase'` (`BaatcheetViewer.tsx:175`).
- The WS `card_navigate` handler exists (`tutor/api/sessions.py:903-910`) but no caller in the frontend ever sends it.
- Forward/back nav writes only to `localStorage.setItem('slide-pos-${sessionId}', ...)` (`ChatSession.tsx:1710, 1721`).

`SessionState.card_phase.current_card_idx` has Pydantic default `0`, so it serializes as `0` — never `null`. The `localStorage` fallback (`ChatSession.tsx:537-539`) is dead code: `state.card_phase.current_card_idx != null` is always true (`0 != null` is `true` in JS).

**Net effect:** every Explain resume now lands at card 0, not where the user left off. The pre-PR `+1` was wrong too, but landed at card 1 (closer to actual). The PR claim "Explain replay off-by-one bug fixed" is inverted — for users who had been hitting the localStorage fallback, this regresses resume.

**Fix options:** (a) wire the inline Explain navigation handlers to call `postCardProgress({phase: 'card_phase', card_idx: ...})` on `setCurrentSlideIdx`, OR (b) keep reading `localStorage` first and treat `current_card_idx === 0` as "unknown."

---

## Functional bugs (likely-broken, not blockers)

### 4. Baatcheet check-in struggle events are never sent to the server
`BaatcheetViewer.tsx:208-211` — `onCheckInComplete = (_result: CheckInActivityResult) => { goNext(); }`. The `_result` underscore signals intentional drop. The progress posting at `:175` never sets `check_in_events`. `DialoguePhaseState.check_in_struggles` exists in the schema (`session_state.py:95`) and the server accepts it (`session_service.py:554-560`), but the channel is empty.

PRD §10 doesn't require this for V1 explicitly, but the server-side schema and the scaffolding suggest it was intended.

### 5. `usePersonalizedAudio` only covers `lines[].audio`, not check-in fields
`usePersonalizedAudio.ts:62` iterates `card.lines` only. Check-in cards may have `{student_name}` in `instruction` / `audio_text` / `hint` / `success_message`. The validator (`baatcheet_dialogue_generator_service.py:180-191`) only inspects `lines[].audio` for placeholder/flag consistency, so a generator that puts `{student_name}` into `check_in.instruction` will:

- Fail validator's flag-check → audio-gen line 364 still skips because text contains `{student_name}` → no pre-rendered MP3 → no runtime synthesis either → field plays silently.

**Fix one of:** (a) extend validator to walk check-in fields, (b) extend `usePersonalizedAudio` to handle check-in fields, or (c) tighten the prompt to forbid `{student_name}` outside `lines[].audio`. Cheapest is (c).

### 6. Schema-less prompt path for non-Claude providers
`baatcheet_dialogue_generator_service.py:380-388` uses `_GENERATION_SYSTEM_FILE` only when `provider == "claude_code"`. If the admin UI ever switches `baatcheet_dialogue_generator` to OpenAI, the user-prompt is just topic+guideline+variant_a — no card-type rules, no banned-pattern guidance, no shape spec.

Compare to `explanation_generator_service.py:332-352` which has a full inline fallback for non-claude_code. Fragile — seeded config is `claude_code`, so this only bites if someone changes it.

**Fix:** mirror the dual-path fallback now, or add a startup assertion that the bound provider supports `system_prompt_file`.

---

## Concerns worth addressing

### 7. `process_step` does not reject `dialogue_phase` sessions
`session_service.py:368-369` rejects `is_in_card_phase()` only. A Baatcheet session calling `POST /sessions/{id}/step` falls through to `orchestrator.process_turn` with surprising results. Add: `if session.is_in_dialogue_phase(): raise CardPhaseError("Session is in dialogue phase. Use /card-progress endpoint.")`.

### 8. Banned-pattern emoji range is incomplete
`baatcheet_dialogue_generator_service.py:67`: `[☀-➿\U0001F300-\U0001FAFF]`. Misses the Misc Symbols & Pictographs precursor block (U+2300–U+25FF, e.g. `⏰`, `▶`, `□`) and Dingbat-adjacent ranges. Audio-text-review's regex has the same gaps so it's not new, but if Stage 5b's stricter validator is the V1 safety net, plug them.

### 9. `_build_welcome_card_pydantic` ignores its `guideline` parameter
`baatcheet_dialogue_generator_service.py:494` accepts `guideline: TeachingGuideline` but never reads it; the literal `WELCOME_CARD_TEMPLATE` is hard-coded with both `{student_name}` and `{topic_name}` placeholders. Per PRD §FR-14 runtime materializes them, but the unused param is misleading.

The welcome card relies on the frontend handling **two** placeholders even though only one (`{student_name}`) is part of the documented contract. Either drop the param, or use it to bake `{topic_name}` server-side and remove the runtime substitution path for that placeholder.

### 10. `/teach-me-options` filters paused sessions in Python
`tutor/api/sessions.py:203-214` loads all teach_me sessions for `(user_id, guideline_id)`, then filters by `teach_me_mode` in Python. For a heavy user the row count grows without bound. Push the filter into SQL: `db.query(...).filter(SessionModel.teach_me_mode == submode)`. The required index already exists (`idx_sessions_user_guideline_teach_mode`).

### 11. `_finalize_baatcheet_session` coverage source differs from Explain
- Explain (`session_service.py:1287-1296`) uses `card.get("concept") or card.get("title")` from variant A card dicts.
- Baatcheet (`session_service.py:609-623`) uses `variant_a.summary_json.get("card_titles")`.

In practice these may produce the same set (Explain's `card.concept` is unset and `summary_json.card_titles` is `[c.title for c in cards]` per `explanation_generator_service.py:452`). The comment claim ("uses variant A concepts") is sloppy — these are *titles*, not *concepts*, and neither matches `study_plan.get_concepts()` which seeds `mastery_estimates`.

Coverage for both modes likely yields ~0% against canonical concepts. Pre-existing in Explain, not made worse here, but the impl plan's "identical coverage contribution" claim is technically true only because both are equally broken. Make both modes use the same field explicitly so they cannot drift.

### 12. `_stage_baatcheet_dialogue` blocked-by check uses any variant
`topic_pipeline_status_service.py:470` says `explanations_done = any(bool(e.cards_json) for e in explanations)`. Baatcheet specifically depends on variant A. If only B/C are present (unusual), the tile shows "ready" but Stage 5b raises `ValueError`. Filter to `variant_key == "A"` for parity with the runtime check.

### 13. Stage 5c's `asyncio.run` inside a thread
`baatcheet_visual_enrichment_service.py:99-101`:
```py
pixi_code = asyncio.run(self.pixi_gen.generate(visual_prompt, output_type="image"))
```
Fine when called from `_run_baatcheet_visual_enrichment` in a daemon thread. If the orchestrator ever puts this stage into an async dispatch path, it'll explode with `RuntimeError: cannot be called from a running event loop`. Comment that this assumes a sync context, or use `asyncio.new_event_loop()` defensively.

### 14. `TeachMeOptionState.card_count` doesn't reflect stale-vs-current variant A
For Explain: `card_count` is `len(variant_a.cards_json)`. For Baatcheet: `len(dialogue.cards_json)`. If variant A changed after dialogue generation, the UI's "X / N" continues showing dialogue's count — semantically correct (it's the dialogue's deck), and the stale badge is the only signal that the dialogue may be out-of-date.

OK if the stale badge is loud enough.

---

## Nits

- **`audio_generation_service.py:310`** skips the **entire** card when `includes_student_name` is true. If a check-in card is flagged, both `lines[]` and `check_in.*` audio fields get skipped together. Coupled with #5 — runtime only handles lines.
- **Prompt vs validator card-count mismatch** — `baatcheet_dialogue_generation_system.txt:31` asks for 24-34 LLM cards (final 25-35), but validator accepts 13-35. Tighten validator (`MIN_TOTAL_CARDS = 25`) or update prompt to allow 12-34.
- **`BaatcheetViewer.tsx`** does `setVisited(new Set([initialCardIdx]))` then later marks-visited via effect — initial set means resume to a non-zero card *won't* autoplay audio. PRD-compliant but UX-debatable on first resume.
- **`tutor/api/sessions.py:230-235`** accesses `state.dialogue_phase` / `state.card_phase` assuming they exist when submode matches — if a Baatcheet session crashed before `dialogue_phase` initialization, this would silently produce `current_idx=None`. Defensive only.
- **`Personalization.topic_name`** is required (no default), and `_build_personalization` falls back to empty string when guideline is missing. Renders `{topic_name}` as empty. Consider falling back to "this topic".

---

## What works well

- **Hash-based staleness** via `compute_explanation_content_hash` is the right call — clean, semantic-only, well-scoped.
- **`voice_role: Literal["tutor", "peer"]` allowlist** on `/text-to-speech` is exactly the security boundary you'd want.
- **`BaatcheetUnavailableError → 409`** with structured detail code is clean — frontend can react to it specifically.
- **`_finalize_baatcheet_session` idempotency** via `dialogue_phase.completed` is correct.
- **Server-prepended welcome card** avoids LLM drift on a literal-text PRD requirement.
- **`usePersonalizedAudio`'s concurrency cap (4) and cancellation flag** look correct.
- **Opt-in `BaatcheetAudioReviewService`** reusing `_review_card`/`_apply_revisions` is a good wrap — avoids duplicating the LLM contract.

---

## Recommended path

Block on **#1 (migration ordering)** — straight schema correctness bug. Also fix **#3 (Explain resume regression)** before merge or revert that single-line change so resume works as it did pre-PR until the Explain side gets `card-progress` wiring.

**#2 (Pixi rendering)** is a feature gap — call out explicitly that Stage 5c output is not yet visible to students, or wire it through to the existing visual harness.

The rest can land in a follow-up (the same one that does the ChatSession refactor).

---

## Review scope / what was not verified

- Code-reading review on `pr121-review` branch. No DB migration run, no `tsc`, no browser smoke test.
- Stage 5b → 5c → audio-synthesis end-to-end against a real guideline not exercised.
- Coverage-percentage claims for Baatcheet vs Explain not verified against actual variant A data.
