# Session Handover — 2026-04-28 (Phase 3 shipped)

This is the handover from the implementation session that shipped Phase 3.
Pairs with `session-handover-2026-04-28-phase-1-shipped.md` and
`session-handover-2026-04-28-phase-2-shipped.md`.

## TL;DR

Phase 3 of the Topic Pipeline DAG is implemented, two-reviewer feedback
is addressed, and **PR #129** is squash-merged to main as commit
`e223e41`. Memory tracker updated. Phase 4 (`baatcheet_visuals` V2
refactor) is ready to start; **four post-merge codex findings on the
follow-up commit need attention before Phase 4 work begins** — see
"Open codex findings" below.

## What shipped this session

**PR:** https://github.com/manishjain-py/learnlikemagic/pull/129
**Squash commit:** `e223e41` on main
**Branch:** `feat/topic-pipeline-dag-phase-3` (deleted on merge)
**Diff:** 7 files, +1979 / −1 across two commits (`c573179` initial,
`7b16417` review fixes).

### New code

- `book_ingestion_v2/dag/cascade.py` — `CascadeOrchestrator` with
  `start_cascade` / `on_stage_complete` / `cancel`. In-memory state
  per `guideline_id`. Halt-on-failure; soft-cancel; lock-collision
  aware. `build_launcher_kwargs` mirrors the synchronous orchestrator's
  per-stage kwargs.
- `book_ingestion_v2/api/dag_routes.py` — five endpoints:
  - `GET /admin/v2/dag/definition` → DAG topology
  - `GET /admin/v2/topics/{guideline_id}/dag` → per-stage state +
    cascade summary
  - `POST /admin/v2/topics/{guideline_id}/stages/{stage_id}/rerun`
    → cascade from stage
  - `POST /admin/v2/topics/{guideline_id}/dag/run-all` → cascade over
    not-done + stale stages
  - `POST /admin/v2/topics/{guideline_id}/dag/cancel` → soft-cancel
- `tests/unit/test_cascade_orchestrator.py` — 37 unit tests across
  `build_launcher_kwargs`, `_compute_pending`, `_ready_in_pending`,
  `start_cascade`, full event-chain (topo invariant), halt-on-failure,
  soft-cancel, read-order overlay, terminal-hook integration,
  reconciliation-hook integration, and 6 API endpoint tests.

### Hooks + service edits

- `processing_routes.py` — `_write_topic_stage_run_terminal` fires
  `cascade_orchestrator.on_stage_complete` AFTER the row is written,
  in its own try/except so a cascade bug can't break observability.
- `topic_pipeline_status_service.py`:
  - `_overlay_topic_stage_run_signals` surfaces `is_stale` from rows
    onto the existing reconstruction-shaped `StageStatus` response.
  - `_reconcile_stuck_running_rows` now fires the cascade hook after
    flipping a stuck row to terminal — covers the orphan-recovery
    path that `run_in_background_v2` doesn't see.
- `models/schemas.py` — `TopicStageRunState` Literal alias for the
  4-state row vocabulary; new `DAGDefinitionResponse`,
  `TopicDAGResponse`, `CascadeInfo`, `StartCascadeRequest`,
  `RunAllCascadeRequest`, `CascadeKickoffResponse`,
  `CascadeCancelResponse`.
- `main.py` — registers `v2_dag_routes.router`.

## Reviewer fixes folded in (commit `7b16417`)

Two cloud reviewers ran on the initial Phase 3 commit (`c573179`).
Six functional fixes baked into the merged PR:

1. **Stuck cascade on unmet upstream deps (R1#1).**
   `start_cascade(from_stage_id=X)` validates that every dep of X is
   `done AND not stale`. Unmet → `CascadeNotReadyError` → API returns
   409 with `code: upstream_not_done`. Without this, a downstream
   rerun while upstream wasn't done registered the cascade with
   `running=null` and blocked future kickoffs.

2. **Stale flags committed before launch (R1#2).**
   `start_cascade` reordered: launch first, then mark descendants
   stale. A `ChapterJobLockError` no longer leaves orphan stale
   writes on a cascade that never ran.

3. **Run-all skipped stale rows (R1#3).**
   `_compute_pending` now takes a `stale_set` and includes
   `done AND is_stale=True` rows in the run-all pending set.
   Matches plan §2 decision 16. Warning-state coverage stays
   reconstruction-only (row vocab is intentionally 4-state).

4. **Reconciliation didn't notify cascade (R1#4).**
   `_reconcile_stuck_running_rows` fires `on_stage_complete` after
   flipping a stuck row. Dead-worker reaping no longer leaves an
   active cascade stuck on `running=<stage>`.

5. **`cancel_cascade` didn't 404 on bogus id (R2#3).**
   Added `_resolve_topic_keys` guard. Surface stays uniform.

6. **Stale flags stuck after halt-on-failure (R2#4).**
   `on_stage_complete` failed branch clears `is_stale=False` on
   pending descendants. The failed rerun didn't actually change
   upstream artifacts, so downstream isn't truly stale.

Plus P3 cleanup: `TopicDAGStageRow.state` tightened from `str` to
`Literal["pending","running","done","failed"]`; 5 new API endpoint
tests using a thread-safe in-memory engine.

## Open codex findings on `7b16417` — address before Phase 4

Codex re-reviewed the follow-up commit and surfaced 4 issues that
weren't fixed before merge. **Two are P1 — Phase 4 work should start
with a small Phase-3.5 PR clearing these.**

### P1 — Force=True on cascade-launched rebuilds

**File:** `book_ingestion_v2/dag/cascade.py:398` (`_launch_next`)

**Issue.** Cascade descendants launch with `force=False` for every
stage after the first. Some downstream services short-circuit when
artifacts already exist (e.g., visual enrichment skips
fully-enriched cards). Result: cascade-launched stages can
"complete" without actually recomputing on the new upstream content,
then `upsert_terminal "done"` clears `is_stale`, leaving stale
artifacts that the system reports as fresh.

**This was actually mis-evaluated as a P3 in the first review pass
(I argued force=False was correct because byte-identical output
would naturally skip).** The reviewer is right: byte-identical is
the rare case; the common case is upstream changed → downstream
needs rebuild → force=False might skip.

**Fix.** In `_launch_next`, decide `force` per-stage based on the
pre-cascade row state:

```python
is_first = not cascade.stage_results
if is_first:
    force = cascade.force_first
else:
    # Cascade contract: descendants whose previous run is `done` or
    # `failed` must rebuild — services short-circuit on artifact
    # presence in non-force mode. First-time stages (no row) can
    # stay force=False.
    prior_state = state_map.get(next_stage_id)
    force = prior_state in ("done", "failed")
```

### P1 — Defense cleanup in `_launch_next`

**File:** `book_ingestion_v2/dag/cascade.py:384`

**Issue.** Even after the upfront `CascadeNotReadyError` check in
`start_cascade`, if `_launch_next` ever finds no ready stages with
non-empty pending, `_maybe_cleanup` keeps the cascade alive
(pending non-empty, not halted, not cancelled) — orphaning it with
`running=None`.

**Fix.** Make `_launch_next`'s no-ready branch fail loudly:

```python
if not ready:
    if cascade.pending and cascade.running is None:
        cascade.halted_at = "no_ready_stages"
        logger.warning(
            f"Cascade {cascade.cascade_id} has pending {cascade.pending} "
            f"but no ready stages; halting"
        )
    self._maybe_cleanup(cascade)
    return
```

This is defense-in-depth — the upfront check should prevent it, but
a future regression shouldn't strand cascades.

### P2 — Legacy guideline lookup in `get_topic_dag`

**File:** `book_ingestion_v2/api/dag_routes.py:98`

**Issue.** `_resolve_topic_keys` falls back to `guideline.topic`
when `topic_key` is NULL. The dag endpoint then passes that fallback
into `TopicPipelineStatusService.get_pipeline_status`, whose
`_load_guideline` filters on `topic_key` — which won't match a NULL
row. Legacy guidelines with NULL topic_key 404 even though the id
was already resolved.

**Fix options.**
- (a) Add `TopicPipelineStatusService.run_backfill_for_guideline(guideline_id, chapter_id)` that skips topic_key resolution and goes straight to backfill + overlay.
- (b) Have `_load_guideline` also accept lookup by id when topic_key
  resolution fails.

Option (a) is cleaner and matches the dag endpoint's natural shape
(it already has the guideline_id).

### P2 — Pre-existing stale flags wiped on halt

**File:** `book_ingestion_v2/dag/cascade.py:457`
(`_clear_stale_on_pending_descendants`)

**Issue.** On halt-on-failure, the helper unconditionally writes
`is_stale=False` on every pending stage — but some rows may have
been stale before THIS cascade started (e.g., legitimate stale flag
from a prior cancelled cascade). A failed rerun erases those
legitimate signals; subsequent run-all skips stages that still need
regeneration.

**Fix.** Track a `stale_marked: set[str]` on `CascadeState`. In
`start_cascade`, only mark stale on rows that aren't already stale,
and add to `cascade.stale_marked`. In
`_clear_stale_on_pending_descendants`, only clear those.

```python
@dataclass
class CascadeState:
    ...
    stale_marked: set[str] = field(default_factory=set)

# In start_cascade after launch succeeds:
for sid in pending:
    if sid == from_stage_id:
        continue
    row = repo.get(guideline_id, sid)
    if row and row.state == "done" and not row.is_stale:
        repo.mark_stale(guideline_id, sid, is_stale=True)
        cascade.stale_marked.add(sid)

# In _clear_stale_on_pending_descendants:
to_clear = cascade.stale_marked & cascade.pending
```

## Plan deviations worth remembering (Phase 3)

- **`LAUNCHER_BY_STAGE` lookup at call time, not import time.**
  Cascade resolves via `LAUNCHER_BY_STAGE[stage_id]` per call so
  test monkeypatches take effect. Same dict object as
  `topic_pipeline_orchestrator`.
- **`build_launcher_kwargs` duplicates orchestrator logic.** Mirrors
  `TopicPipelineOrchestrator._launcher_kwargs`. Phase 1 follow-up
  (move kwargs onto `Stage`) still open and would unify both.
- **Warning state stays reconstruction-only.** Row vocab remains
  `pending|running|done|failed`. Per-stage rerun is the documented
  recovery path for `warning` artifacts.
- **In-memory cascade state.** Server restart drops active cascades.
  Documented limitation. Multi-worker uvicorn = `cancel` from worker
  B can't reach a cascade from worker A.
- **Read-order flip is overlay-only.** The reconstruction is still
  authoritative for state; rows only contribute `is_stale` to the
  `StageStatus` response. Reconstruction handles ready/blocked/
  warning/failed/done semantics.

## Phase 3 follow-ups inherited by later phases

| What | Where | When |
|---|---|---|
| **Force=True on cascade-launched rebuilds** (P1 codex) | `dag/cascade.py:398` | **Phase 3.5** (before Phase 4) |
| **Defense cleanup in `_launch_next`** (P1 codex) | `dag/cascade.py:384` | **Phase 3.5** (before Phase 4) |
| **Legacy guideline lookup in `get_topic_dag`** (P2 codex) | `api/dag_routes.py:98` + `services/topic_pipeline_status_service.py` | Phase 3.5 or Phase 5 |
| **Preserve pre-cascade stale flags on halt** (P2 codex) | `dag/cascade.py` (CascadeState + `_clear_stale_*`) | Phase 3.5 |
| **`pipeline_run_id` / `cascade_id` tagging on launches** | `dag/cascade.py:341` | Phase 5 (observability) |
| **Move per-stage kwargs onto `Stage`** | `dag/types.py` + 8 stage modules | Phase 1 follow-up; not gating |
| **Frontend `STAGE_ORDER` / `TopicPipelineDashboard` cleanup** | `llm-frontend/src/features/admin/...` | Phase 5 |

## Status of memory + tracker

Updated this session:
- `~/.claude/projects/-Users-manishjain-repos-learnlikemagic/memory/project_topic_pipeline_dag.md` — Phase 3 → shipped, codex follow-ups embedded.
- `~/.claude/projects/-Users-manishjain-repos-learnlikemagic/memory/MEMORY.md` — pointer rewritten to "Phases 1+2+3 shipped 2026-04-28; Phase 4 next".
- `docs/feature-development/topic-pipeline-dag/plan.md` §0 — phase list now shows ✅ tags on phases 1+2+3.

A fresh session will auto-load both memory files via the memory subsystem.

## Phase 4 — starter checklist (next session)

Per plan §7 Phase 4. **Recommendation: bundle the four codex
findings into a small Phase 3.5 PR FIRST**, then start Phase 4
clean.

### Phase 3.5 (suggested, before Phase 4)

1. Force=True on cascade descendants whose prior state is
   `done`/`failed` (cascade.py:398).
2. Defense cleanup: `_launch_next` halts loudly on no-ready +
   non-empty pending (cascade.py:384).
3. `run_backfill_for_guideline(guideline_id, chapter_id)` on
   `TopicPipelineStatusService`; switch `get_topic_dag` to use it.
4. `CascadeState.stale_marked` set + scoped clear in
   `_clear_stale_on_pending_descendants`.
5. Tests: cascade-launched stage on previously-done row passes
   force=True; halt with pre-existing stale flag preserves it;
   legacy NULL-topic-key guideline returns 200 from
   `/topics/{id}/dag`.

**Bound:** ~60-90 minutes.

### Phase 4 (`baatcheet_visuals` V2 refactor)

Per plan §7 Phase 4 + V2 working doc:

1. Refactor `BaatcheetVisualEnrichmentService.enrich_for_guideline`:
   - **Selection step:** call existing visual-pass prompts
     (`baatcheet_visual_pass_system.txt` + `baatcheet_visual_pass.txt`)
     to pick cards based on `visual_required` flags + default-generate
     logic. Drop the SVG generation from the prompt — production path
     uses PixiJS.
   - **Generation step:** for each selected card, call
     `tutor.services.pixi_code_generator.PixiCodeGenerator.generate(visual_intent)`.
     Persist `card.visual_explanation = {output_type, title, visual_summary, visual_spec, pixi_code}`
     on `topic_dialogues.cards_json` via `flag_modified`.
2. Status check: `{cards_with_visuals: N, total_cards: M}`. `done`
   when every `visual_required: true` card has `visual_explanation`.
3. Stage's `staleness_check`: stale if the dialogue's
   `source_content_hash` changed since the visual pass ran.
4. Tests: round-trip a V2 plan + dialogue through the refactored
   stage; assert PixiJS code is present on every
   `visual_required: true` card and on most concrete-content cards.

**Acceptance:** rerun `baatcheet_visuals` on math G4 ch1 topic 1
(existing in prod DB) → ~12-18 visuals appear in `cards_json`.

**Bound:** ~1-2 days.

**Key references for Phase 4:**
- Service: `book_ingestion_v2/services/baatcheet_visual_enrichment_service.py`
- Prompts: `book_ingestion_v2/prompts/baatcheet_visual_pass_system.txt` + `.txt`
- Production generator: `tutor/services/pixi_code_generator.py`
- Experiment harness: `scripts/baatcheet_v2_visualize.py`
- V2 working doc: `docs/feature-development/baatcheet/dialogue-quality-v2-designed-lesson.md` §7

## Open questions for the next session

- Phase 3.5 vs roll codex findings into Phase 4 PR? Recommendation:
  3.5 separately — Phase 4 is a substantive runtime change and
  shouldn't be entangled with cascade fixes.
- Phase 5 timing: UI is the most visible piece but blocked on no
  one — could start in parallel with Phase 4 if a second contributor
  picks it up.
