# Audio Synthesis — Force Re-Synth Flag

## Problem

Re-triggering the `audio_synthesis` stage from the admin DAG dashboard for an already-synthesized topic is a no-op. The stage iterates every line, sees `audio_url` is populated, marks the line "skipped", and finishes in a few seconds without writing any new MP3s.

This bites us whenever upstream conditions change but cards_json still carries the old `audio_url` values:

- **TTS voice swap** (e.g. moving Mr. Verma + Meera off `hi-IN-Chirp3-HD-*` onto `en-IN-Chirp3-HD-Orus`/`Leda`, commit `9682363`).
- **Pre-synthesis text rewrite changes** (e.g. dropping the bad `us`→`uhs` hack).
- **Audio_text edits** that weren't surfaced through the audio-review path (which clears URLs on revised lines).
- Any future TTS-config change that should propagate to existing topics.

Today the only way to force regeneration is a manual SQL `UPDATE` that nulls every `audio_url` / `audio_text_url` / `hint_audio_url` / `success_audio_url` / `reveal_audio_url` field in `topic_explanations.cards_json` and `topic_dialogues.cards_json` for a guideline, then re-run the stage. That's brittle, error-prone, and blocks non-engineers from fixing audio drift.

## Where the no-op happens

```python
# llm-backend/book_ingestion_v2/services/audio_generation_service.py:165-167  (explanations)
for line_idx, line in enumerate(card.get("lines") or []):
    total += 1
    if line.get("audio_url"):
        skipped += 1
        continue
```

```python
# llm-backend/book_ingestion_v2/services/audio_generation_service.py:348-350  (baatcheet dialogue)
total += 1
if line.get("audio_url"):
    skipped += 1
    continue
```

Same skip predicate inside `_check_in_fields_for(...)` for `audio_text_url` / `hint_audio_url` / `success_audio_url` / `reveal_audio_url` (lines ~195 and ~378).

## What needs to change

1. **Service layer** — `AudioGenerationService.generate_for_cards` and `generate_for_topic_dialogue` accept `force: bool = False`. When `force=True`, the skip predicate is bypassed and the existing S3 object is overwritten (S3 keys are deterministic, so writes overwrite cleanly — no orphan cleanup needed).

2. **Job runner** — `_run_audio_generation` in `llm-backend/book_ingestion_v2/api/sync_routes.py` accepts and threads through a `force_str` param (mirrors the `force_str: str = "False"` pattern used by `_run_baatcheet_visual_enrichment`).

3. **Launcher** — `launch_audio_synthesis_job` in `book_ingestion_v2/services/stage_launchers.py` accepts `force: bool = False` and passes `str(force)` into the background runner. Today the signature only takes `total_items`; mirror the launcher signatures of the visual-enrichment / dialogue-generation launchers (which already wire `force` through to the runner).

4. **Stage definition / cascade** — `Stage(launch=launch_audio_synthesis_job, ...)` in `stages/audio_synthesis.py` already passes a `force` kwarg through the cascade orchestrator (see `dag/cascade.py:91-119`), so the launcher just needs to accept it.

5. **Dashboard UI** — the topic-pipeline DAG view renders a single "Run" button per stage. Add a secondary affordance ("Force re-synth", or a dropdown on the existing button) that POSTs the run with `force=true`. Confirm-dialog the destructive nature ("This will overwrite all existing MP3s for this topic — ~30-90s per line, ~5-10 min total"). The frontend lives in `llm-frontend/src/features/admin/components/TopicDAGView.tsx`.

6. **Audit/log surface** — `_run_audio_generation` already logs `{generated, skipped, failed}` per topic. With force=True, every line counts as `generated` (unless empty), so the existing log lines are sufficient — no new instrumentation needed.

## What does NOT need to change

- **S3 layout** — keys are already deterministic per `(guideline_id, variant_key, card_idx, line_idx)` for explanations and `(guideline_id, dialogue, card_id, line_idx)` for baatcheet, so overwrites are clean.
- **Frontend playback** — pre-rendered audio URLs are immutable strings; the new MP3 lives at the same URL, so cache busting is a non-issue beyond the browser blob cache (which is per-session and self-clears).
- **Personalized realtime synth** — `tutor/api/tts.py` already re-synthesizes on every call; this work is irrelevant for that path.

## Acceptance criteria

- A "Force re-synth" run on a previously-synthesized topic produces N generated, 0 skipped (where N = total clips on the topic).
- The same run without force is unchanged (still skips populated `audio_url` lines).
- Pre-existing non-force callers (cascade triggers from upstream regen) keep working without modification.
- Dashboard surfaces a clearly-labelled affordance and the existing tile state derivation is unaffected.

## Out of scope

- Per-line force (only re-synth lines whose `audio_text` has changed) — would require text-hash bookkeeping; defer.
- Cascade-driven force (e.g. an `audio_review` regen automatically forces audio_synthesis for the lines it revised) — `audio_review` already nulls URLs on revised lines today, so the existing non-force path handles that case cleanly. No need to overload force.
- Backfill across the entire book / library — out of scope for this change; scripted separately if needed.

## Suggested test plan

1. Pick a topic with audio already populated (e.g. math grade 4 ch1 topic 1, guideline `23632b15-a6bf-45d5-990e-a04c89bf29ee`).
2. Snapshot `audio_url` count before run; should match clip count.
3. Click "Force re-synth"; wait for completion.
4. Snapshot again — same count, but `updated_at` on `topic_explanations` / `topic_dialogues` should advance.
5. Spot-check 2-3 of the new MP3s by playing them in browser → confirm new voice (en-IN-Orus / en-IN-Leda).
6. Verify a non-force re-run (regular Run button) on the same topic finishes fast with all lines skipped.

## Related context (latest at branch HEAD)

- TTS voice swap to en-IN: commit `9682363`
- Drop of `us`→`uhs` rewrite hack: same commit
- Earlier `us`→`uss` (later `uhs`) rewrites: commits `e305557`, `684a8ab`
- Per-stage status helpers + cascade plumbing: `book_ingestion_v2/dag/`
- Reference launcher pattern for `force_str`: `_run_baatcheet_visual_enrichment` in `sync_routes.py:2594`.
