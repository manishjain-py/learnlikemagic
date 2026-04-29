# Audio Pipeline — Force Re-Run + Symmetric Baatcheet Audio Stages

## Problems

Two related issues, fixed together.

### 1. Re-running audio stages was a no-op

Re-triggering `audio_synthesis` from the admin DAG dashboard for an already-synthesized topic was effectively a no-op: the stage iterated every line, saw `audio_url` populated, marked the line "skipped", and finished without writing any new MP3s. The same predicate was preventing audio_review from being meaningful on re-run — only lines the LLM happened to revise got their `audio_url` cleared, so a re-run of audio_review followed by audio_synthesis left most clips frozen.

Triggering needs:
- **TTS voice swap** (e.g. moving Mr. Verma + Meera off `hi-IN-Chirp3-HD-*` onto `en-IN-Chirp3-HD-Orus`/`Leda`, commit `9682363`).
- **Pre-synthesis text rewrite changes** (e.g. dropping the bad `us`→`uhs` hack).
- **Audio_text edits** that bypassed the audio-review path.
- Any future TTS-config change that should propagate to existing topics.

### 2. The audio stages were asymmetric across explanations vs Baatcheet

Per-entity coverage before this change:

|                  | explanation (variant A) | dialogue (Baatcheet) |
|------------------|------------------------:|---------------------:|
| `audio_review`   | ✅                      | ❌                   |
| `audio_synthesis`| ✅                      | ✅ (soft join)       |

Baatcheet had a separate `BaatcheetAudioReviewService` (and `launch_baatcheet_audio_review_job`, `_run_baatcheet_audio_review`), but it lived outside the DAG behind a manual admin button. Synthesis covered both entities in one runner. The asymmetry made re-run behavior confusing and made it impossible to surface dialogue audio status as a first-class DAG tile.

## What changed

### Architectural split

The DAG now has **four audio stages** instead of two phase-paired stages with a soft join:

```
Explanations
├── Visuals
├── Check-ins
├── Practice Bank
├── Audio Review                (variant A only)
│   └── Audio Synthesis         (variant A only)
└── Baatcheet Dialogue
    ├── Baatcheet Visuals
    └── Baatcheet Audio Review  (NEW)
        └── Baatcheet Audio Synth (NEW)
```

Coverage is now fully symmetric:

|                            | explanation | dialogue |
|----------------------------|------------:|---------:|
| `audio_review`             | ✅          | —        |
| `audio_synthesis`          | ✅          | —        |
| `baatcheet_audio_review`   | —           | ✅       |
| `baatcheet_audio_synthesis`| —           | ✅       |

The orphan manual admin button (`POST /review-baatcheet-audio`) is gone — `baatcheet_audio_review` is now a first-class DAG stage.

### Force end-to-end for all four audio stages

The frontend (`TopicDAGView.tsx:645`) already passed `force: true` on every Run click, and the cascade endpoint already accepted it. The break was that `cascade.py:build_launcher_kwargs` and `topic_pipeline_orchestrator.py:_launcher_kwargs` did not add `force` for the audio stages. Now both kwargs builders include all four audio stages with `force` threading.

Service-layer behavior on `force=True`:

- **`audio_synthesis` / `baatcheet_audio_synthesis`** — bypass the per-line `audio_url` skip predicate and the per-check-in-field URL skip; bypass the "all items already have audio" early return. S3 keys are deterministic, so writes overwrite cleanly at the same URL.
- **`audio_review` / `baatcheet_audio_review`** — clear every `audio_url` on the variant up front (via `AudioTextReviewService._clear_audio_urls_in_place`) so the cascaded synthesis stage regenerates the full clip set, not just the lines this review pass happens to revise.

### Files touched

Backend services:
- `services/audio_generation_service.py` — `force` on `generate_for_cards`, `generate_for_topic_explanation`, `generate_for_topic_dialogue`.
- `services/audio_text_review_service.py` — `force` on `review_guideline`, `review_chapter`, `_review_variant`; new `_clear_audio_urls_in_place` helper.
- `services/baatcheet_audio_review_service.py` — `force` on `review_guideline`, reuses `_clear_audio_urls_in_place` from the parent service.

Backend runners (`api/sync_routes.py`):
- `_run_audio_generation` — accepts `force_str`, drops the dialogue path (now its own stage).
- `_run_audio_text_review` — accepts `force_str`.
- `_run_baatcheet_audio_review` — accepts `force_str`.
- `_run_baatcheet_audio_generation` (NEW) — mirrors the dialogue branch that used to live in `_run_audio_generation`.
- Removed `POST /review-baatcheet-audio` route.

Backend launchers (`services/stage_launchers.py`):
- `launch_audio_synthesis_job` — accepts `force`.
- `launch_audio_review_job` — accepts `force`.
- `launch_baatcheet_audio_review_job` — accepts `force` (was previously DAG-orphaned).
- `launch_baatcheet_audio_synthesis_job` (NEW).

Backend DAG wiring:
- `dag/cascade.py:build_launcher_kwargs` — added all four audio-stage branches with force.
- `services/topic_pipeline_orchestrator.py:_launcher_kwargs` — same.
- `stages/audio_synthesis.py` — status check no longer counts dialogue clips.
- `stages/baatcheet_audio_review.py` (NEW).
- `stages/baatcheet_audio_synthesis.py` (NEW).
- `dag/topic_pipeline_dag.py` — STAGES list extended.
- `dag/launcher_map.py` — `JOB_TYPE_TO_STAGE_ID` extended for the two new stages.
- `constants.py` — new `BAATCHEET_AUDIO_GENERATION` job type.
- `services/chapter_job_service.py` — added new job type to `POST_SYNC_JOB_TYPES`.
- `models/schemas.py` — extended `StageId` literal with the two new stage IDs.

Frontend:
- `adminApiV2.ts` — removed orphan `reviewBaatcheetAudio` API client.
- `TopicDAGView.tsx` — no change. Layout is fully metadata-driven and auto-renders the new tiles.

Tests:
- Updated assertions that hardcoded "8 stages" to "10 stages".
- Replaced `BAATCHEET_AUDIO_REVIEW`-as-unknown test with `REFRESHER_GENERATION`-as-unknown.
- Updated cascade fixture's `job_type_by_stage` to include the two new stages.
- Updated `_LEGACY_PIPELINE_ORDER` to reflect the new topo order.
- Updated `test_audio_synthesis_minimal` → `test_audio_synthesis_passes_force`.

## Acceptance criteria

- "Run" on `audio_synthesis` regenerates every variant A line/check-in MP3 (force=True propagated end-to-end).
- "Run" on `baatcheet_audio_synthesis` regenerates every dialogue line/check-in MP3.
- "Run" on `audio_review` clears all variant A `audio_url`s up front so the cascaded `audio_synthesis` regenerates the full set.
- "Run" on `baatcheet_audio_review` does the same for dialogue.
- Each entity's audio subtree is independent: regenerating dialogue audio does not invalidate explanation audio, and vice versa.
- DAG dashboard renders all 10 stages in correct topological order with the right depends_on edges.

## Out of scope

- Per-line force (only re-synth lines whose `audio_text` changed) — would require text-hash bookkeeping; defer.
- A separate "Force re-synth" affordance distinct from "Run" — the existing button now does what users expect.
- Backfill across the entire book / library — scripted separately if needed.
- Renaming `audio_review`/`audio_synthesis` to `explanation_audio_review`/`explanation_audio_synthesis` — names are persisted in DB job records and JOB_TYPE_TO_STAGE_ID mappings; backwards-compat hold preserved.
