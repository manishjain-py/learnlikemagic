# Session Handover — 2026-04-28 (Phases 3.5 + 4 shipped)

This is the handover from the implementation session that shipped Phases 3.5 and 4 together in PR #130. Pairs with the prior handover docs:
- `session-handover-2026-04-28-phase-1-shipped.md`
- `session-handover-2026-04-28-phase-2-shipped.md`
- `session-handover-2026-04-28-phase-3-shipped.md` (the source of the Phase 3.5 codex findings)

## TL;DR

Phases 3.5 and 4 of the Topic Pipeline DAG are shipped, **squash-merged to main as commit `ab99907`** (PR #130). Phases 1+2+3+3.5+4 of the DAG plan are now done. Next is Phase 5 — the React Flow UI that replaces the existing stage-ladder dashboard.

## What shipped this session

**PR:** https://github.com/manishjain-py/learnlikemagic/pull/130
**Squash commit:** `ab99907` on main
**Branch:** `feat/topic-pipeline-dag-phase-3-5` (deleted on merge)
**Diff:** 9 files, +1198 / −91 across two commits (`3da6007` Phase 3.5, `835e7ac` Phase 4).

### Phase 3.5 (commit `3da6007`) — cascade codex follow-ups

Four findings from the Phase 3 follow-up commit (`7b16417`) that landed unfixed before merge:

1. **P1 — descendants launch with `force` based on prior row state.** `cascade.py:_launch_next` previously launched every non-first stage with `force=False`. Several downstream services (visual enrichment, audio synthesis) short-circuit on artifact presence in non-force mode. Result: cascade-launched descendants "completed" without rebuilding, then `upsert_terminal "done"` cleared `is_stale`, marking stale artifacts as fresh. Fix: descendants whose prior row state was `done` or `failed` launch with `force=True`. First-time descendants (no prior row) keep `force=False`. The first stage still honours the caller's `force` arg.

2. **P1 — `_launch_next` halts loudly on no-ready + non-empty pending.** Defense-in-depth: the upfront check in `start_cascade` rejects unsatisfiable kickoffs, but a future regression in pending computation shouldn't strand cascades with `running=None`. Now sets `cascade.halted_at = "no_ready_stages"` and logs a warning so `_maybe_cleanup` drops the entry.

3. **P2 — `get_topic_dag` returns 200 for legacy NULL-`topic_key` guidelines.** `TopicPipelineStatusService._load_guideline` filters by `topic_key`, which excluded guidelines whose `topic_key` is NULL (the `_resolve_topic_keys` fallback to `guideline.topic` doesn't match). Added `TopicPipelineStatusService.run_backfill_for_guideline(guideline_id, chapter_id)` that bypasses topic_key resolution; the DAG endpoint switched to use it.

4. **P2 — pre-existing stale flags survive halt-on-failure.** `_clear_stale_on_pending_descendants` previously wrote `is_stale=False` on every pending stage, erasing legitimate signals from prior cancelled cascades or operator action. Added `CascadeState.stale_marked: set[str]` — populated only when this cascade flips a row from `is_stale=False → True` at kickoff. Halt-cleanup now scopes the clear to `cascade.stale_marked & cascade.pending`.

8 new tests in `tests/unit/test_cascade_orchestrator.py`:
- `TestForceOnCascadeDescendants` (4 tests) — descendant with done/failed/no-row, first-stage honours arg
- `TestLaunchNextDefenseCleanup` (1 test) — no-ready halt
- `TestPreserveExistingStaleOnHalt` (2 tests) — stale_marked excludes pre-existing, halt preserves them
- `TestGetTopicDAGEndpoint::test_legacy_null_topic_key_guideline_returns_200`

### Phase 4 (commit `835e7ac`) — `baatcheet_visuals` V2 refactor

V2 dialogues (with `plan_json`) didn't get prod visuals because the V1 service only enriched `card_type=="visual"` cards — V2 plans don't generate those. This refactor wires the validated visual-pass selector into production.

**Service refactor (`BaatcheetVisualEnrichmentService.enrich_guideline`):**
- V2 path: LLM selector reads `plan_json` + slim dialogue cards via the existing `baatcheet_visual_pass_system.txt` + `.txt` prompts. Returns `{visualizations: [{card_idx, visual_intent, why}]}` for every `visual_required: true` slot plus default-generate picks (12-18 visuals on a 30-40-card dialogue).
- For each selection, `PixiCodeGenerator.generate(visual_prompt, output_type="image")` produces static-visual PixiJS code. Persisted as `card.visual_explanation = {output_type: "static_visual", title, visual_summary, visual_spec, pixi_code}` on `topic_dialogues.cards_json`. `visual_intent` also surfaced on the card itself for debug/read-side.
- V1 fallback: no `plan_json` → cards with `card_type=="visual"` and `visual_intent` enrich without the selector LLM call. Preserves back-compat for legacy dialogues.
- Persistence: `repo.upsert(...)` reused; delete-then-insert preserves the schema contract.
- Idempotent: cards with existing `pixi_code` skip unless `force=True`.

**Prompt edits — dropped SVG generation:**
- `baatcheet_visual_pass_system.txt`: removed the SVG section + the SVG element in the output schema. Schema is now `{visualizations: [{card_idx, visual_intent, why}]}` only. Production routes intent through PixiJS, so SVG was paying generation cost on output we discard (~1000+ chars per card × 12-18 cards = significant).
- `baatcheet_visual_pass.txt`: minor reword + explicit "do NOT generate SVG, PNG, or PixiJS" reminder.
- ⚠️ **Side effect:** `scripts/baatcheet_v2_visualize.py` (research harness) renders SVG inline in HTML reviews. After this change the harness will produce empty SVGs. Update the harness in a follow-up if the rendered HTML is still wanted for prompt iteration. Suggestion: have the harness call `PixiCodeGenerator` and render PixiJS in a sandbox iframe, OR keep an SVG-flavoured system prompt as a separate file for the harness.

**Stage `_status` (`book_ingestion_v2/stages/baatcheet_visuals.py`):**
- V2: `done` when every plan slot with `visual_required: true` has a card with `visual_explanation.pixi_code`. Default-generate picks count as "extras" and don't gate `done`. Summary: `"{required_present}/{required} required visuals · {extras} extras"`.
- V1: unchanged — `"{n}/{m} visual cards have PixiJS"`.
- No explicit `staleness_check` added; cascade-based staleness (Phase 3) handles the rerun-from-upstream case. Read-time content-hash invalidation deferred until admins find the cascade signal insufficient.

17 new tests in `tests/unit/test_baatcheet_visual_enrichment.py`:
- `TestEnrichV2` (4 tests) — required cards get pixi, selector failure short-circuits, pixi failure on one card lets others proceed, idempotent without force
- `TestEnrichV1Fallback` (1 test) — no plan → no selector LLM call
- `TestStageStatusV2` (6 tests) — done/warning/ready transitions, extras don't gate, no required slots is trivially done, blocked when no dialogue
- `TestStageStatusV1Fallback` (2 tests) — V1 done/warning
- `TestSelectorParsing` (4 tests) — `_extract_json` parses fenced + bare JSON + garbage; `_slim_cards_for_prompt` strips noise

## Test results

- **45/45 cascade tests pass** (`tests/unit/test_cascade_orchestrator.py`) — 37 from Phase 3 + 8 new from Phase 3.5.
- **17/17 Phase 4 tests pass** (`tests/unit/test_baatcheet_visual_enrichment.py`).
- **222/222 pipeline-related tests pass** (cascade + DAG + topic pipeline + topic_stage_runs + chapter job lock + baatcheet + ingestion quality fixes).
- **67 unrelated unit failures unchanged** — pre-existing on main, all in tutor/ + topic_adapter + precomputed_explanations + safety_agent + shared_models. Not in scope.

## Plan deviations worth remembering

- **Phase 3.5 + Phase 4 bundled into one PR.** Originally the previous handover suggested Phase 3.5 as a separate PR before Phase 4. Bundled in practice because the code changes are independent (cascade vs visual enrichment) and reviewers can see them as separate commits. If you want them split for cleaner attribution, the squash-merged PR can be re-extracted by cherry-picking the two commits onto fresh branches before merge.
- **No explicit `Stage.staleness_check` added in Phase 4.** Plan §7 Phase 4 mentions "stale if the dialogue's `source_content_hash` changed since the visual pass ran" but the cascade-based staleness from Phase 3 already covers the rerun-from-upstream case (which is the operationally important one). Read-time staleness display would require persisting per-card hash + a comparison helper; deferred until there's evidence admins need it.
- **Visual-pass prompts edited in place.** The harness (`scripts/baatcheet_v2_visualize.py`) breaks slightly (empty SVGs) until updated. Tradeoff: clean single source of truth + production cost saving > research-tool continuity. The harness fix is a small, separate task.

## Status of memory + tracker

Updated this session:
- `~/.claude/projects/-Users-manishjain-repos-learnlikemagic/memory/project_topic_pipeline_dag.md` — Phases 3.5 + 4 → shipped, recommended next = Phase 5.
- `~/.claude/projects/-Users-manishjain-repos-learnlikemagic/memory/MEMORY.md` — pointer rewritten to "Phases 1+2+3+3.5+4 shipped; Phase 5 (React Flow UI) next".
- `docs/feature-development/topic-pipeline-dag/plan.md` §0 — phase list now shows ✅ tags on phases 1+2+3+3.5+4.

A fresh session will auto-load both memory files via the memory subsystem.

## Phase 5 — starter checklist (next session)

Per plan §7 Phase 5. The most visible piece — replaces `TopicPipelineDashboard` with a React Flow-based per-topic DAG view.

**Reference orchestrator** (the user built this for a different domain, mentioned in plan §6): `/Users/manishjain/Downloads/workflow-dag-reference.zip` — extract to `/tmp/workflow-dag-reference/` if missing. Vite + React + `@xyflow/react`; ~50-line BFS-depth `autoLayoutSteps`. Contains the patterns to lift wholesale.

### Build steps

1. **Confirm `@xyflow/react` is installed.** Check `llm-frontend/package.json`. If not, `npm install @xyflow/react` in `llm-frontend/`.

2. **New component `llm-frontend/src/features/admin/components/TopicDAGView.tsx`:**
   - Fetch `GET /admin/v2/dag/definition` once on mount (DAG topology — static).
   - Poll `GET /admin/v2/topics/{guideline_id}/dag` periodically — every 2s while any stage is `running`, every 30s otherwise.
   - Render with `@xyflow/react`. Auto-layout: port `autoLayoutSteps` from `/tmp/workflow-dag-reference/.../mockData.js` — BFS depth → row-grouped layout.
   - Node component: id, label, state badge (colours: `pending=grey`, `running=blue+animated`, `done=green`, `failed=red`, plus yellow stale-overlay), duration, last-run timestamp ("4m 12s · 2 hrs ago"). Click → side panel.
   - Side panel: state, started_at, completed_at, duration_ms, last_job_id link (deep-link to existing admin page), error message if failed, **Rerun** button (disabled when stage is `running`), summary fields.
   - Top bar: "Run all" button (`POST /admin/v2/topics/{guideline_id}/dag/run-all`), "Cancel cascade" button (`POST /admin/v2/topics/{guideline_id}/dag/cancel`) when a cascade is running, banner area for cross-DAG warnings (Phase 6 populates).

3. **Replace `TopicPipelineDashboard`** with `TopicDAGView` at the same URL. Delete the old stage-ladder code (full delete — no parallel routes). Keep the file path or rename per convention.

4. **Plumbing:**
   - Existing v2 admin endpoints to use:
     - `GET /admin/v2/dag/definition` → topology
     - `GET /admin/v2/topics/{guideline_id}/dag` → state + cascade summary
     - `POST /admin/v2/topics/{guideline_id}/stages/{stage_id}/rerun` → cascade from stage (202)
     - `POST /admin/v2/topics/{guideline_id}/dag/run-all` → cascade over not-done (202)
     - `POST /admin/v2/topics/{guideline_id}/dag/cancel` → soft-cancel (200)
   - 409 codes the UI must handle: `cascade_active` (a cascade is already running), `upstream_not_done` (downstream rerun while upstream not done), `stage_running` (per-topic chapter-job lock collision).

5. **Polish:**
   - Edge labels showing dependency relationships (light grey, low contrast).
   - Cascade halo: when a cascade is active, draw a thin banner at the top with `running` stage + `pending` queue size.
   - `is_stale` overlay: render the stale flag as a yellow corner badge on otherwise-`done` nodes — admin can choose to leave them or rerun.

**Acceptance per plan §7 Phase 5:** open a topic → see DAG with all 8 nodes + current state. Click Rerun on a node → cascade fires, UI shows progression. Cancel mid-cascade works. Reload page → state survives (read from `topic_stage_runs`).

**Bound:** ~2-3 days.

### Useful pointers

- Existing admin frontend: `llm-frontend/src/features/admin/` — find `TopicPipelineDashboard` and trace its routes/imports.
- Stage colour palette + sizing already exists; lift the visual language so nothing looks out of place.
- The `cascade` field on `GET /topics/{guideline_id}/dag` returns `{cascade_id, running, halted_at, cancelled, pending: string[], started_at, stage_results: {[stage_id]: state}}` — render `running` + `pending.length` for the halo banner.

## Open follow-ups inherited (not gating Phase 5)

| What | Where | When |
|---|---|---|
| Update `scripts/baatcheet_v2_visualize.py` to call `PixiCodeGenerator` (or keep a separate SVG-flavoured prompt) | `llm-backend/scripts/baatcheet_v2_visualize.py` | Phase 5 polish or later |
| `pipeline_run_id` / `cascade_id` tagging on stage launches (observability) | `dag/cascade.py:_launch_next` | Phase 5 (observability) |
| Move per-stage kwargs onto `Stage` (kill duplication between cascade + sync orchestrator) | `dag/types.py` + 8 stage modules | Phase 1 follow-up; not gating |
| Read-time content-hash staleness for `baatcheet_visuals` (per-card hash compare) | `stages/baatcheet_visuals.py` | If admins need it; deferred until then |
| Eval rubric hardening for Baatcheet (V2 working doc Phase 5) | `llm-backend/services/baatcheet_eval_service.py` (new) | Separate workstream |

## Open questions for the next session

- Phase 5 scope: ship the basic DAG view first (matches plan §7) and iterate, OR build the polished version (animations, halos, transitions) up front? Recommendation: ship basic first — feedback comes faster, and the polish steps are independently shippable.
- Cross-DAG warning (Phase 6) timing: parallel with Phase 5 or after? Phase 5 has the banner area ready to receive it; the detection + capture work in Phase 6 plugs in cleanly later.

## Quick commands for the next session

```bash
# Sync + branch
cd /Users/manishjain/repos/learnlikemagic
git checkout main && git pull
git checkout feat/topic-pipeline-dag-phase-5  # already created from main this session

# Run the cascade tests (sanity)
cd llm-backend && ./venv/bin/python -m pytest \
  tests/unit/test_cascade_orchestrator.py \
  tests/unit/test_baatcheet_visual_enrichment.py \
  tests/unit/test_topic_pipeline_dag.py \
  -q

# Start backend + frontend for Phase 5 dev
cd llm-backend && source venv/bin/activate && make run     # :8000
cd llm-frontend && npm run dev                              # :3000
```
