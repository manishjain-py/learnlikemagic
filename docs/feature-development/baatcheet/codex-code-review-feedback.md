# Baatcheet - Codex Code Review Feedback

**Date:** 2026-04-25  
**PR:** https://github.com/manishjain-py/learnlikemagic/pull/121  
**Reviewed against:** `docs/feature-development/baatcheet/impl-plan.md` and current PR head `332d3428c31d3056d8a9ab5adbf719d21d79ca83`

**Verdict:** Do not merge yet. The implementation lands a large amount of the planned shape, but there are still functional blockers around `teach_me_mode` persistence/resume, dialogue audio pipeline status, and the Baatcheet student playback/completion experience.

## Blockers

### 1. `sessions.teach_me_mode` is migrated but missing from the SQLAlchemy model and persistence writes

**Files:** `llm-backend/shared/models/entities.py:45`, `llm-backend/tutor/api/sessions.py:208`, `llm-backend/tutor/services/session_service.py:472`, `llm-backend/tutor/services/session_service.py:778`

`db.py` adds the `sessions.teach_me_mode` column and rebuilds the paused-session unique index around it, but `shared.models.entities.Session` does not define `teach_me_mode`. I confirmed this with:

```text
./venv/bin/python -c "from shared.models.entities import Session; print(hasattr(Session, 'teach_me_mode'))"
False
```

Consequences:

- `GET /sessions/teach-me-options` references `SessionModel.teach_me_mode` in the SQLAlchemy filter and will raise at runtime before the chooser can load.
- New Baatcheet sessions are inserted without the DB column set, so Postgres will use the column default (`explain`). Even after adding the ORM column later, existing PR-created Baatcheet rows would be misclassified in the DB unless backfilled from `state_json`.
- The paused-session unique index still cannot deliver PRD FR-4 in practice, because Baatcheet rows are not persisted as `teach_me_mode='baatcheet'`.
- `_persist_session_state()` updates `mode`, `is_paused`, and `updated_at`, but never updates `teach_me_mode`, so later updates would not repair the DB column either.

**Fix:** Add `teach_me_mode = Column(String, default='explain')` to the `Session` ORM model. Persist it in `_persist_session()`, `_update_session_db()`, and `_persist_session_state()`. Add a migration/backfill that derives `sessions.teach_me_mode` from `state_json->teach_me_mode` for rows already created by this PR. Add a test that creates paused Explain and paused Baatcheet sessions for the same user/topic and verifies both coexist and are returned separately by `/teach-me-options`.

### 2. Stage 10 status ignores dialogue audio, so the one-click pipeline can skip Baatcheet MP3 generation

**Files:** `llm-backend/book_ingestion_v2/services/topic_pipeline_status_service.py:558`, `llm-backend/book_ingestion_v2/services/audio_generation_service.py:391`, `llm-backend/book_ingestion_v2/api/sync_routes.py:1002`

`_run_audio_generation()` now synthesizes both explanations and `TopicDialogue` rows, and `AudioGenerationService.count_dialogue_audio_items()` exists. But `_stage_audio_synthesis()` only counts `topic_explanations` cards. I confirmed the status method does not reference `count_dialogue_audio_items`.

This breaks the default pipeline path for existing topics:

1. Variant A already has complete audio, so `audio_synthesis` is `done`.
2. Baatcheet dialogue is missing or stale, so the super-run schedules Stage 5b/5c.
3. Stage 10 is skipped because the status snapshot says audio is already done.
4. The newly generated dialogue has no pre-rendered MP3s.

That violates the impl plan's Stage 10 extension and PRD FR-29/FR-30 for all non-personalized dialogue cards.

**Fix:** Update `_stage_audio_synthesis()` to include dialogue clip totals when a dialogue exists. If dialogue audio is missing, the stage should be `ready` or `warning`, not `done`. Also consider downstream invalidation: when `baatcheet_dialogue` is stale and selected for rerun, the pipeline should rerun `baatcheet_visuals` and `audio_synthesis` even if their pre-run status was `done`, because regenerating dialogue changes card IDs/content.

### 3. Baatcheet auto-play is broken for the initial card and racy for personalized cards

**Files:** `llm-frontend/src/components/teach/BaatcheetViewer.tsx:63`, `llm-frontend/src/components/teach/BaatcheetViewer.tsx:92`, `llm-frontend/src/components/teach/BaatcheetViewer.tsx:110`, `llm-frontend/src/hooks/usePersonalizedAudio.ts:52`

`visited` is initialized with `initialCardIdx`, and the playback effect exits when `visited.has(cardIdx)`. That means a fresh Baatcheet session starts with card 0 already marked visited, so the welcome card never auto-plays.

There is also a runtime TTS race: `usePersonalizedAudio()` starts async synthesis, but `BaatcheetViewer` immediately checks `getClientAudioBlob(...)`. If the blob is not ready yet, it skips the line and never retries because `cardIdx` does not change. The welcome card is always `includes_student_name=true`, so this path matters on every dialogue.

**Fix:** Do not mark the initial card visited until after its first playback attempt completes. For personalized cards, either synthesize on demand inside the playback path, or expose loading/completion state from `usePersonalizedAudio()` and trigger playback when the blob becomes available. At minimum, the welcome card should play after runtime TTS resolves.

### 4. Baatcheet completion has no usable "Let's Practice" CTA

**Files:** `llm-frontend/src/components/teach/BaatcheetViewer.tsx:187`, `llm-frontend/src/components/teach/BaatcheetViewer.tsx:276`, `llm-frontend/src/pages/ChatSession.tsx:1307`, `llm-frontend/src/pages/ChatSession.tsx:1439`

When the summary card becomes visible, Baatcheet posts `mark_complete=true`, but the standalone viewer only renders Back and Next/Done buttons. On the final card, the primary button is disabled (`cardIdx >= totalCards - 1`), so the student has no "Let's Practice" CTA and no "done for now" escape comparable to the existing Explain completion UI.

The `ChatSession` early return for `dialogue_phase` bypasses the existing Teach Me completion summary and CTA entirely.

**Fix:** Give `BaatcheetViewer` enough context/callbacks to render the same post-summary actions as Explain, or have it call back into `ChatSession` after completion so the existing completion panel can render. This is required by PRD FR-35.

## Functional Concerns

### 5. Stage 5b validators do not enforce banned TTS patterns in check-in fields

**File:** `llm-backend/book_ingestion_v2/services/baatcheet_dialogue_generator_service.py:172`

The validator checks `_BANNED_AUDIO_PATTERNS` only for `lines[].audio`. It checks check-in fields only for `{student_name}` placeholders. Since default dialogue audio review is intentionally skipped in V1, markdown, naked equals signs, or emoji can still land in `check_in.audio_text`, `hint`, `success_message`, `reveal_text`, or `statement`, then get synthesized by `generate_for_topic_dialogue()`.

**Fix:** Walk all TTS-spoken check-in fields and apply the same banned-pattern rules. Also validate `activity_type` against the 11 supported values so an unsupported check-in shape does not reach `CheckInDispatcher`.

### 6. Opt-in Baatcheet audio review cannot apply `check_in_text` revisions

**Files:** `llm-backend/book_ingestion_v2/services/baatcheet_audio_review_service.py:87`, `llm-backend/book_ingestion_v2/services/audio_text_review_service.py:343`

`BaatcheetAudioReviewService` reuses `AudioTextReviewService._apply_revisions()`. For `kind == "check_in_text"`, that method drift-checks against top-level `card["audio_text"]` before mirroring into `card["check_in"]["audio_text"]`. Dialogue cards store the instruction audio only under `check_in.audio_text`, so `check_in_text` revisions will be dropped as drift mismatches.

**Fix:** Add a dialogue-specific apply path for `check_in_text`, or normalize dialogue check-in cards with a temporary top-level `audio_text` before review/apply. This matters because the opt-in review button is the advertised safety valve for subtle dialogue TTS defects.

### 7. Stale dialogue regeneration does not automatically rerun dependent visuals/audio

**Files:** `llm-backend/book_ingestion_v2/services/topic_pipeline_orchestrator.py:408`, `llm-backend/book_ingestion_v2/services/topic_pipeline_status_service.py:495`

`stages_to_run_from_status()` skips stages whose pre-run state is `done`. If `baatcheet_dialogue` is stale but `baatcheet_visuals` was done for the old dialogue, a super-run will regenerate dialogue but skip visuals. The same applies to audio, compounded by blocker #2.

**Fix:** Either mark dependent stages stale when `baatcheet_dialogue` is stale, or make `stages_to_run_from_status()` include downstream stages whenever an upstream dependency is selected. Regenerating dialogue changes card IDs and invalidates visual/audio artifacts attached to the previous cards.

### 8. `source_explanation_id` is documented as an FK but implemented as a plain string

**File:** `llm-backend/shared/models/entities.py:359`

The impl plan says `source_explanation_id` is a nullable FK to `topic_explanations.id`. The ORM model stores it as `Column(String, nullable=True)` without `ForeignKey`. This is debug-only, so it is not a launch blocker, but the schema does not match the plan.

**Fix:** Either add the FK explicitly, or update the plan/progress docs to say this is a non-constrained debug pointer.

## Test Gaps

No committed tests cover the new Baatcheet paths. `rg` found no backend or frontend tests mentioning `baatcheet`, `dialogue_phase`, `teach_me_mode`, `card-progress`, or `topic_dialogues`.

Minimum tests I would add before merge:

- ORM/persistence test proving `sessions.teach_me_mode` is stored and queryable.
- `/sessions/teach-me-options` test returning separate Explain and Baatcheet in-progress sessions.
- Pipeline status test where explanations have full audio but dialogue does not; `audio_synthesis` must not be `done`.
- Baatcheet viewer test for initial-card auto-play behavior, or at least a hook/component test proving personalized audio retries after runtime TTS resolves.
- Completion UI test proving the Baatcheet summary card exposes the practice CTA.
- Validator tests for banned patterns inside check-in TTS fields.

## What Looks Solid

- `topic_dialogues` as one row per guideline is aligned with PRD V1.
- Hash-based staleness is the right design and avoids enrichment timestamp noise.
- `voice_role` allowlisting on runtime TTS is the right security boundary.
- `BaatcheetUnavailableError -> 409` gives the frontend a clean fallback point.
- Server-side welcome-card insertion avoids LLM drift on the literal welcome copy.
- `VisualExplanationComponent` is now wired for dialogue PixiJS cards, fixing the first review's rendering gap.

## Verification Performed

- `npm run build` in `llm-frontend` completed successfully.
- `./venv/bin/python -m py_compile ...` completed for the touched backend modules listed in the review pass.
- Confirmed `Session` ORM lacks `teach_me_mode`.
- Confirmed `AudioGenerationService.count_dialogue_audio_items()` exists but `_stage_audio_synthesis()` does not use it.

Not run: DB migration against a real database, Stage 5b/5c/10 against a real guideline/LLM/TTS/S3, browser smoke test.
