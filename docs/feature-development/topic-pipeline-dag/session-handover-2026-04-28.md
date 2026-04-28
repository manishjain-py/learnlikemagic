# Topic Pipeline DAG — Session Handover (2026-04-28)

**Purpose:** continue the topic-pipeline-DAG redesign from a fresh session. Pure planning session — no code written. Two artefacts in this directory tell the whole story; this handover is just the cold-start map.

## TL;DR

User wants to replace the implicit, multi-place topic-processing pipeline with one explicit workflow DAG + a per-topic React Flow UI showing every stage's state. Reference orchestrator (a fraud-investigation tool the user built before) supplies the UI pattern; the codebase already has most orchestration plumbing in fragments. The session ran a Q&A interview that locked 20 design decisions and produced a canonical implementation plan ready for Phase 1.

**Read first** in a new session: `plan.md` in this directory — every decision baked in.

## Where we are in the work

| Step | Status |
|---|---|
| Map the current pipeline (research) | done — see `initial-plan.md` |
| Characterise user's reference orchestrator | done — extracted to `/tmp/workflow-dag-reference/`; deep-dive in `initial-plan.md` |
| Draft architecture + open decisions | done — original `initial-plan.md` |
| Q&A interview with user to lock decisions | done — 20 decisions locked |
| Revised plan with locked decisions | done — `plan.md` is the canonical v1 plan |
| Phase 1 implementation | **not started — recommended next** |

## What we did this session

1. **Loaded V2 baatcheet context** via working doc §7 (just to be in sync, no work needed there).
2. **Ran two parallel research agents:**
   - Agent A — characterised the user's reference workflow orchestrator at `/Users/manishjain/Downloads/workflow-dag-reference.zip`. Extracted to `/tmp/workflow-dag-reference/`. Output captured in `initial-plan.md` §4.
   - Agent B — exhaustive inventory of every topic-pipeline stage in the codebase (book + chapter + topic scopes). Captured in `initial-plan.md` §6 + dependency graph in §7.
3. **Drafted initial plan** at `docs/feature-development/topic-pipeline-dag/initial-plan.md` with proposed architecture, stage table, dependency graph, 6-phase plan, and 6 open decisions for the user.
4. **Conducted Q&A interview** — 9 questions, locking 20 decisions. User pushed back on two:
   - Asked for **per-stage time logging** to be visible in the UI (added).
   - Pushed back on **optional/conditional stages** — convinced to remove the categories entirely. `baatcheet_audio_review` removed from the DAG; `baatcheet_visuals` to be refactored to do real V2 work (folds Phase 4.6 from the V2 working doc into v1).
5. **Wrote revised plan** at `plan.md` with every decision baked in, 6 phases for v1 (Phase 7 chapter DAG deferred), and a concrete "Adding a new stage (developer experience)" section that demonstrates pain (d) is solved.

No code written this session. No commits. Files added are docs only.

## The 20 locked decisions (from §2 of `plan.md`)

| # | Decision | Choice |
|---|---|---|
| 1 | Auto-cascade on upstream rerun | Yes — cascade marks downstream stale and auto-runs in dep order |
| 2 | Topic + chapter scope | Separate DAGs, independent orchestration |
| 3 | Cross-DAG signal when chapter changes | Banner only on the affected topic DAG; no auto-stale |
| 4 | Failure handling inside cascade | Halt-on-failure |
| 5 | DAG definition format | Python module (`book_ingestion_v2/dag/topic_pipeline_dag.py`) with `to_json()` for UI |
| 6 | Stage code organisation | Stage-as-module — one file per stage exporting a `Stage` object |
| 7 | State enum | 4 states (`pending`, `running`, `done`, `failed`) + `is_stale: bool` flag |
| 8 | State persistence | Latest-only in `topic_stage_runs`; history via existing `chapter_processing_jobs` |
| 9 | UI rollout | Replace `TopicPipelineDashboard` at the same URL |
| 10 | v1 scope | Topic DAG only; chapter DAG = Phase 7 |
| 11 | Cancellable cascade | Yes, soft-cancel — running stage finishes, no further launched |
| 12 | Cost preview before rerun | No — defer |
| 13 | Optional/conditional categories | None — every stage is normal. Remove `baatcheet_audio_review`; refactor `baatcheet_visuals` to V2 pass |
| 14 | Per-stage time logging | Yes — `started_at`, `completed_at`, `duration_ms` visible per node |
| 15 | DAG layout | BFS-depth auto-layout, port `autoLayoutSteps` from reference |
| 16 | "Run all stages" button | Runs every stage that isn't `done` (treats `stale`/`failed` as not-done); cascade does the rest |
| 17 | Lock collision UX | Rerun button disabled when `running`; race → 409 → toast |
| 18 | Migration / backfill | Lazy — first dashboard load reconstructs state from artefacts and INSERTs |
| 19 | Permissions / audit | Any admin can trigger; no new audit log (job rows already record trigger) |
| 20 | Stage timeouts | Keep existing — `HEARTBEAT_STALE_THRESHOLD = 1800s`, `MAX_POLL_WALL_TIME_SEC = 14400s` |

These are immutable for v1. If a fresh session wants to revisit one, that's a real conversation with the user — they're locked from the interview.

## Final stage inventory (v1, topic DAG)

8 stages, all normal, all run in cascade, no toggles:

| Stage ID | Depends on | Notes |
|---|---|---|
| `explanations` | (none) | Stage 5; root of topic DAG |
| `baatcheet_dialogue` | `explanations` | Stage 5b V2 (plan→dialogue→refine); already wired and prod-validated on math G4 ch1 topic 1 |
| `baatcheet_visuals` | `baatcheet_dialogue` | **Refactor in Phase 4** — currently V1 (no-ops on V2 plans); becomes V2 visual pass via `PixiCodeGenerator` |
| `visuals` | `explanations` | Stage 6 (variant A PixiJS) |
| `check_ins` | `explanations` | Stage 7 |
| `practice_bank` | `explanations` | Stage 8 |
| `audio_review` | `explanations` | Stage 9 |
| `audio_synthesis` | `audio_review`, soft `baatcheet_dialogue` | Stage 10; synthesises both variant A + dialogue MP3s |

**Removed from DAG:** `baatcheet_audio_review`. Manual route stays in case a defect surfaces; not in the dashboard.

**Chapter-scope stages** (`toc_save`, `page_ocr`, `chapter_extraction`, `chapter_finalization`, `topic_sync`, `refresher_generation`) — Phase 7 work, not v1. Existing per-chapter admin pages stay as-is.

## Phases (each independently shippable)

| # | Phase | Bound | What it produces |
|---|---|---|---|
| 1 | Declare DAG + stage modules | 1-2 days | DAG file as source of truth; per-stage modules; existing routes/UI unchanged |
| 2 | `topic_stage_runs` table + write-on-complete | 1 day | Durable per-stage state; lazy backfill from artefacts |
| 3 | Cascade orchestrator + rerun/cancel APIs | 2-3 days | Headless cascade + per-stage rerun via curl/HTTP |
| 4 | `baatcheet_visuals` V2 refactor | 1-2 days | The one substantive runtime change in v1 — folds Phase 4.6 from V2 working doc |
| 5 | React Flow UI replaces stage ladder | 2-3 days | The user-facing payoff |
| 6 | Cross-DAG warning + tests + polish | 1-2 days | Production-ready ship |
| 7 | Chapter DAG | (later, not v1) | Same pattern, instantiated for chapter scope |

Total v1: ~8-13 working days, depending on test depth and review cycles.

## Critical files

### Created this session (docs only)
- `docs/feature-development/topic-pipeline-dag/initial-plan.md` — research summary; codebase inventory; reference orchestrator deep-dive; original 6 open decisions.
- `docs/feature-development/topic-pipeline-dag/plan.md` — **canonical v1 plan**, all 20 decisions baked in. Read first.
- `docs/feature-development/topic-pipeline-dag/session-handover-2026-04-28.md` — this file.

### Will be created in Phase 1
- `book_ingestion_v2/dag/types.py` — `Stage` dataclass, `StageScope` enum, `StageStatusOutput`, `TopicPipelineDAG` class.
- `book_ingestion_v2/dag/topic_pipeline_dag.py` — `STAGES` list (8 stages).
- `book_ingestion_v2/stages/{explanations,baatcheet_dialogue,baatcheet_visuals,visuals,check_ins,practice_bank,audio_review,audio_synthesis}.py` — one per stage.
- `tests/unit/test_topic_pipeline_dag.py` — DAG acyclic, every stage has launcher + status check, topo-sort matches old `PIPELINE_LAYERS`.

### Will be modified in Phase 1
- `book_ingestion_v2/services/topic_pipeline_orchestrator.py` — `PIPELINE_LAYERS` deleted; `run_topic_pipeline` iterates `DAG.topo_sort()`.
- `book_ingestion_v2/services/stage_launchers.py` — `LAUNCHER_BY_STAGE` becomes `{s.id: s.launch for s in DAG.stages}`.
- `book_ingestion_v2/services/topic_pipeline_status_service.py` — calls each stage's `status_check()` instead of hard-coded helpers.

### Existing files that drive Phase 4 (`baatcheet_visuals` V2 refactor)
- `book_ingestion_v2/services/baatcheet_visual_enrichment_service.py` — to be refactored.
- `book_ingestion_v2/prompts/baatcheet_visual_pass_system.txt` + `.txt` — already V2-aligned (committed in V2 work session).
- `tutor/services/pixi_code_generator.py` — production PixiJS generator the new path calls.
- `scripts/baatcheet_v2_visualize.py` — experiment harness, the prompt-feeding pattern to mirror.

### Reference orchestrator (extracted)
- `/tmp/workflow-dag-reference/workflow-dag-reference/` — extracted from `~/Downloads/workflow-dag-reference.zip`. **May not persist across sessions / reboots — re-extract if missing.** Most-important files:
  - `ARCHITECTURE.md`
  - `scripts/orchestrate.mjs` — DAG walker (~40 lines).
  - `ui/src/components/StepNode.jsx` + `WorkflowRunner.jsx` — UI to port in Phase 5.
  - `ui/src/data/mockData.js` `autoLayoutSteps` — BFS-depth layout (~50 lines).

## How to resume in a fresh session

1. **Read in this order:**
   - `MEMORY.md` (auto-loads — points at `project_topic_pipeline_dag.md`).
   - `docs/feature-development/topic-pipeline-dag/plan.md` — the canonical plan.
   - This handover doc.
   - `initial-plan.md` only if you need the original research depth.

2. **Confirm reference orchestrator is still extracted:**
   ```bash
   ls /tmp/workflow-dag-reference/workflow-dag-reference/ARCHITECTURE.md && echo OK || \
     unzip -d /tmp/workflow-dag-reference \
       /Users/manishjain/Downloads/workflow-dag-reference.zip
   ```

3. **If the user asks to start Phase 1**, the work order is:
   - Create `book_ingestion_v2/dag/types.py` with the `Stage` dataclass + `TopicPipelineDAG` class + `validate_acyclic()`.
   - Create `book_ingestion_v2/stages/` directory + 8 stage files (one per stage, each importing existing service/repo code unchanged at first).
   - Create `book_ingestion_v2/dag/topic_pipeline_dag.py` with the `STAGES` list.
   - Refactor `LAUNCHER_BY_STAGE`, `PIPELINE_LAYERS`, `TopicPipelineStatusService` per `plan.md` §7 Phase 1.
   - Add unit tests.
   - Acceptance: existing dashboards render identically, super-button works as before, `git grep PIPELINE_LAYERS` returns zero.

4. **If the user asks "do we need to revisit any decision"**, re-read §2 of `plan.md`. Decisions are locked from the interview. Revisiting is a real conversation, not a code change.

5. **If the user asks about `baatcheet_visuals` and Phase 4.6 from the V2 working doc**, explain that Phase 4.6 from `dialogue-quality-v2-designed-lesson.md` §7 is now folded into v1 of this DAG plan as Phase 4. Same work, different home.

6. **If the user asks to defer `baatcheet_visuals` refactor**, note that doing so means shipping a no-op stage in the DAG (the V1 stage doesn't find any `card_type=visual` cards on V2 dialogues). The plan recommended folding it in for that reason.

## Key decisions made this session (the why)

- **Separate DAGs for chapter and topic** — avoids the blast-radius problem of chapter-scope cascade affecting all topics in the chapter. User's call.
- **Cross-DAG = banner only** — keeps cross-scope coupling minimal; admin retains control over when to retrigger affected topics.
- **Halt-on-failure not best-effort** — simpler for v1; matches existing behaviour; can layer retry/sibling-continuation later if friction surfaces.
- **Stage-as-module not status-quo-plus-DAG-file** — the only combination that actually fixes pain (d). Cost is a real but bounded refactor.
- **Remove `baatcheet_audio_review`, refactor `baatcheet_visuals`** — user pushed back on optional/conditional categories. Convinced because the categories existed for unprincipled reasons (defensive duplication; mid-V2 migration). Cleaner to either drop or promote each. After this, the DAG = the pipeline.
- **Per-stage time logging visible** — user explicitly added this. Existing `chapter_processing_jobs` already captures the timing, so it's pure plumbing through `topic_stage_runs`.

## References

- Canonical plan: `docs/feature-development/topic-pipeline-dag/plan.md`
- Research history: `docs/feature-development/topic-pipeline-dag/initial-plan.md`
- This handover: `docs/feature-development/topic-pipeline-dag/session-handover-2026-04-28.md`
- Reference orchestrator (local): `/tmp/workflow-dag-reference/workflow-dag-reference/`
- Reference orchestrator (zip): `/Users/manishjain/Downloads/workflow-dag-reference.zip`
- Project memory: `~/.claude/projects/-Users-manishjain-repos-learnlikemagic/memory/project_topic_pipeline_dag.md`
- Adjacent project (folds in): `docs/feature-development/baatcheet/dialogue-quality-v2-designed-lesson.md` §7 Phase 4.6 (now folded into v1 Phase 4 of this plan).

## Commits this session

**None.** Pure planning. No code, no docs committed. Three new files added under `docs/feature-development/topic-pipeline-dag/` (`initial-plan.md`, `plan.md`, `session-handover-2026-04-28.md`). User can commit these whenever they want; the canonical plan is durable as a working doc until implementation begins.

## Next step

Start Phase 1 from `plan.md` §7. Lowest-risk, fastest-feedback step (~1-2 days). Unblocks every other phase. No user input needed beyond "go" — every design decision is locked.
