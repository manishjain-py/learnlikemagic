# PRD: Topic Pipeline Dashboard

A topic-scoped admin view that makes the post-sync ingestion pipeline legible and one-click runnable for any single topic.

---

## Problem

The book ingestion pipeline has 6 post-sync topic-level stages (Explanations, Visuals, Check-ins, Practice bank, Audio text review, Audio synthesis) that today live behind separate chapter-scoped admin pages (`ExplanationAdmin`, `VisualsAdmin`, `PracticeBankAdmin`, etc.) plus the chapter-level `BookV2Detail` page.

Admin workflow pain:

| Symptom | Cause |
|---|---|
| "What's left to do for *this* topic?" has no single answer | Status is scattered across 4+ pages, each scoped to a chapter |
| Running the pipeline for one topic takes 6 manual clicks across 4 pages | Every stage is triggered from its own admin page; no end-to-end button |
| Admin cannot tell *recommended order* from the UI | Pages are alphabetized/route-ordered, not dependency-ordered |
| Chapter-level status hides per-topic variance | A chapter shows "explanations done" even when only 4 of 10 topics have explanations |
| Parallelism within a chapter is blocked by the job lock | `ChapterJobService` enforces one active job per chapter; running Topic A stalls Topic B |

Operational cost is real: ingesting one chapter (8–15 topics, ~6 stages each) today is dozens of careful clicks with no clear overview.

---

## Solution

A new admin page — the **Topic Pipeline Dashboard** — at `/admin/books/:bookId/chapters/:chapterId/topics/:topicKey/pipeline`. It is a **hub, not a replacement**. Existing per-stage admin pages remain the primary surfaces for detailed work (viewing generated content, per-stage configuration, inspection). The hub adds:

1. A **stage ladder** that shows all 6 post-sync stages in recommended run order with per-stage status badges.
2. A **super-button** ("Run entire pipeline") that runs all remaining stages for the topic in dependency order, respecting parallelism where stages are independent.
3. A **chapter-level runner** on `BookV2Detail` ("Run pipeline for all topics in this chapter") that iterates every topic's pipeline — now truly in parallel because of a lock-refactor change.
4. **Deep links** from each stage row to its existing per-stage admin page for fine control.

No existing per-stage admin page changes behavior. The hub reads status it computes from existing artifacts + job history.

---

## Goals

- One view per topic that answers "what's done, what's next, what's blocked" in under 3 seconds
- One click to run end-to-end for a topic (or for every topic in a chapter)
- Accurate status including staleness when upstream changes invalidate downstream
- Topic-level parallelism within a chapter (remove chapter-wide job lock for post-sync stages)
- Zero disruption to existing per-stage admin pages

---

## Non-Goals

- **No approval/review workflow.** "Done" means the artifact exists + last job succeeded. No human-in-the-loop gate.
- **No replacement of per-stage admin pages.** They remain canonical for viewing generated content.
- **No cost/time estimates or historical analytics.** Future.
- **No cross-chapter pipeline runs.** Chapter-level runner iterates topics within one chapter only.
- **No changes to chapter-level preflight stages (OCR, extraction, finalization, sync).** Those remain on `BookV2Detail` and keep the chapter-wide lock.
- **No changes to refresher topic generation.** Stays on `BookV2Detail` next to each chapter.
- **No confirmation dialogs on destructive actions.** Regenerate just does it. Admin is trusted.

---

## User Experience

### Admin — Topic Hub

**Navigation path:** `BookV2Dashboard → BookV2Detail → Chapters tab → topic row → "Pipeline →" link`

**Layout**

Sticky header with breadcrumb, prev/next topic buttons (scoped to current chapter), and the super-button. Body is a vertical stage ladder:

```
┌─────────────────────────────────────────────────────────────────┐
│ Book  /  Chapter 3 · Fractions  /  Topic: Comparing Fractions  │
│ ← Prev topic    Next topic →           [▶ Run entire pipeline]  │
├─────────────────────────────────────────────────────────────────┤
│ ✓  Chapter preflight             Synced 2d ago                  │
├─────────────────────────────────────────────────────────────────┤
│ ①  Explanations     ✓ 1 variant · 18 cards                      │
│    [Open stage page →]  [Regenerate]                            │
├─────────────────────────────────────────────────────────────────┤
│ ②  Visuals          ⚠ 6/18 cards · 1 layout warning             │
│    [Open stage page →]  [Regenerate]           parallel w/ ③ ④  │
├─────────────────────────────────────────────────────────────────┤
│ ③  Check-ins        ✓ 4 check-ins                               │
│    [Open stage page →]  [Regenerate]           parallel w/ ② ④  │
├─────────────────────────────────────────────────────────────────┤
│ ④  Practice bank    ⚠ Stale — explanations regenerated 5m ago   │
│    [Open stage page →]  [Regenerate]           parallel w/ ② ③  │
├─────────────────────────────────────────────────────────────────┤
│ ⑤  Audio review     ⏳ Ready                                    │
│    [Open stage page →]  [Run]                                   │
├─────────────────────────────────────────────────────────────────┤
│ ⑥  Audio synthesis  🔒 Blocked — run ⑤ first                    │
│    [Open stage page →]  [Run anyway — skip review]              │
└─────────────────────────────────────────────────────────────────┘
```

**Status states** (exactly six):

| State | Icon | Meaning |
|---|---|---|
| Done | ✓ green | Artifact exists and meets success criteria (see below) |
| Warning | ⚠ amber | Exists but has warnings (layout warning, stale, partial coverage) |
| Running | 🔄 blue + progress | Active job for this topic (polled every 3s) |
| Ready | ⏳ grey | Prereqs met, never run or downstream of a failed stage that now needs re-run |
| Blocked | 🔒 grey-red | Prereqs not met; names the missing prereq |
| Failed | ✕ red | Last job failed; inline error summary + [Retry] |

**Super-button behavior**

- Opens a small popover: **Quality** selector (Fast / Balanced / Thorough) mapping to per-stage review rounds. Default: Balanced.
- Computes the set of stages to run (every stage not currently Done for this topic, skipping ones already Running).
- Executes in DAG order: `① → (② ∥ ③ ∥ ④) → ⑤ → ⑥`.
- Hard-stops on any stage failure. Downstream stages stay in ⏳ Ready (not ✕). A top-of-page banner reads *"Pipeline halted at Visuals. Fix and press Run to resume."*
- Polling: every 3s while any stage is Running; stops polling once everything is settled.

**Regenerate / Run buttons**

- `[Run]` appears on Ready and Blocked (with the skip-review override) stages.
- `[Regenerate]` appears on Done and Warning stages. Fires the same backend endpoint as existing per-stage pages with `force=true`. No confirmation dialog.
- `[Retry]` appears on Failed stages. Re-runs only that stage.
- All three buttons accept the same Quality setting selected at the top.

### Admin — Chapter-level Runner

On `BookV2Detail`, each chapter row gains:

- A **topic summary chip**: `"12 topics · 8 done · 3 partial · 1 not started"`.
- A button: **[▶ Run pipeline for all topics]**. Opens the same Quality selector popover.
- Iteration: runs every topic's pipeline in parallel (topics are independent after the lock refactor).
- Skips already-Done topics by default; **Force re-run all** toggle available.
- On one topic's pipeline failing, other topics continue. Failure is surfaced per-topic on the summary chip.

### Admin — Stage Page (No changes)

Existing per-stage admin pages (`ExplanationAdmin`, `VisualsAdmin`, `CheckInAdmin`, `PracticeBankAdmin`, etc.) are untouched. Jobs triggered from those pages show up as 🔄 Running on the hub if the admin has the hub open simultaneously.

### Student

No student-facing changes. This is an admin-ops feature.

---

## Per-Stage Success Criteria

Status computation rules the hub and the consolidated endpoint must implement:

| Stage | ✓ Done when… | ⚠ Warning when… |
|---|---|---|
| ① Explanations | ≥1 variant present in `topic_explanations` with ≥1 card | 0 variants present |
| ② Visuals | ≥1 card has `visual_explanation.pixi_code` AND no card has `layout_warning = true` | Any card has `layout_warning = true` |
| ③ Check-ins | ≥1 `check_in` card in any variant's `cards_json` | 0 check-ins |
| ④ Practice bank | ≥30 rows in `practice_questions` for this `guideline_id` AND not stale | 1–29 questions, or stale (upstream changed) |
| ⑤ Audio review | Most recent `v2_audio_text_review` job for this guideline has status `completed` AND not stale | Most recent job `completed_with_errors`, or stale |
| ⑥ Audio synthesis | Every `audio` line in every card of every variant has non-null `audio_url` | Some lines have `audio_url`, some do not (partial) |

**Stale detection rule:** an artifact is stale if `topic_explanations.updated_at > artifact.created_at_or_completed_at`. Practically only ④ Practice bank and ⑤ Audio review completion flag can go stale because ②③⑥ all live inside `cards_json` and get overwritten when explanations regenerate.

**Blocked rules:** Stage X is Blocked if any hard prereq is not Done.

| Stage | Hard prereq |
|---|---|
| ① Explanations | Chapter preflight (synced `teaching_guideline` exists) |
| ② Visuals | ① Explanations Done |
| ③ Check-ins | ① Explanations Done |
| ④ Practice bank | ① Explanations Done (hard — fails if missing) |
| ⑤ Audio review | ① Explanations Done (reviews explanation + check-in audio if present) |
| ⑥ Audio synthesis | ① Explanations Done. **Soft gate on ⑤** — HTTP 409 unless `confirm_skip_review=true` |

---

## Technical Considerations

### Backend changes

**Lock refactor (required for chapter-level parallelism):**

- `ChapterJobService.acquire_lock` currently enforces one active job per `chapter_id`. For post-sync stages (`V2JobType.EXPLANATION_GENERATION`, `VISUAL_ENRICHMENT`, `CHECK_IN_ENRICHMENT`, `PRACTICE_BANK_GENERATION`, `AUDIO_TEXT_REVIEW`, `AUDIO_GENERATION`), the lock must be on `(chapter_id, guideline_id)`.
- Chapter-level stages (`OCR`, `TOPIC_EXTRACTION`, `REFINALIZATION`, `REFRESHER_GENERATION`) keep the `chapter_id`-only lock.
- `chapter_processing_jobs` table gains (or uses existing) `guideline_id` column; partial unique index updated accordingly.

**New endpoints:**

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}/pipeline` | Consolidated per-topic status (all 6 stages, their state, summaries, warnings, last job id) |
| POST | `/admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}/run-pipeline` | Super-button. Body: `{ quality_level, force?, resume_from? }` |
| POST | `/admin/v2/books/{book_id}/chapters/{chapter_id}/run-pipeline-all` | Chapter-level runner. Body: `{ quality_level, skip_done? }` |

**New orchestration service:** `TopicPipelineOrchestrator` in `book_ingestion_v2/services/` encodes the DAG, spawns stage jobs in order via existing services, handles hard-stop-on-failure, and returns a `pipeline_run_id` for polling.

**Staleness query:** implemented in the consolidated GET endpoint. Timestamp comparison against `topic_explanations.updated_at`; no new DB columns.

### Frontend changes

- New page: `llm-frontend/src/features/admin/pages/TopicPipelineDashboard.tsx`
- New route: `/admin/books/:bookId/chapters/:chapterId/topics/:topicKey/pipeline` wired in the admin router
- New API client methods in `adminApiV2.ts`: `getTopicPipeline`, `runTopicPipeline`, `runChapterPipelineAll`
- `BookV2Detail.tsx` updates:
  - Per-topic "Pipeline →" deep link
  - Per-chapter topic summary chip + "Run pipeline for all topics" button
- Smart polling hook: poll `/pipeline` every 3s while any stage is Running or the run is in-flight; stop when settled

### Quality selector → review rounds mapping

| Quality | ① Exp | ② Vis | ③ Chk | ④ Prac |
|---|---|---|---|---|
| Fast | 0 | 0 | 0 | 0 |
| Balanced | 2 | 1 | 1 | 2 |
| Thorough | 3 | 2 | 2 | 3 |

Exact numbers tunable during implementation; existing per-stage pages retain full 0–5 control.

### Integration points

| Area | Module | Change |
|---|---|---|
| Backend | `book_ingestion_v2/services/chapter_job_service.py` | Lock refactor |
| Backend | `book_ingestion_v2/services/` (new file) | `topic_pipeline_orchestrator.py` |
| Backend | `book_ingestion_v2/api/sync_routes.py` | 3 new endpoints |
| Backend | `book_ingestion_v2/models/database.py` | Possibly add `guideline_id` to `chapter_processing_jobs` if not present + partial unique index |
| Frontend | `src/features/admin/pages/TopicPipelineDashboard.tsx` | New |
| Frontend | `src/features/admin/pages/BookV2Detail.tsx` | Chapter-level runner + per-topic link |
| Frontend | `src/features/admin/api/adminApiV2.ts` | New methods + types |
| Docs | `docs/technical/book-guidelines.md` | New section: Topic Pipeline Dashboard |

---

## Impact on Existing Features

| Feature | Impact | Details |
|---|---|---|
| `ExplanationAdmin`, `VisualsAdmin`, `CheckInAdmin`, `PracticeBankAdmin` | None | Unchanged |
| `BookV2Detail` | Minor | New chip + button per chapter; new "Pipeline →" link per topic |
| `ChapterJobService` | Significant | Lock refactor for post-sync stages |
| `chapter_processing_jobs` | Minor | Partial unique index change; `guideline_id` column may need to be added if absent |
| Existing per-stage endpoints (`/generate-explanations`, `/generate-visuals`, etc.) | None | Keep working exactly as today. Orchestrator calls them internally |
| Existing job tracking endpoints | None | Hub reads from same endpoints |
| Chapter-level stages (OCR, extraction, finalization, sync) | None | Chapter-wide lock retained |
| Student tutor runtime | None | Admin-ops feature |

---

## Edge Cases & Error Handling

| Scenario | Expected behavior |
|---|---|
| Admin opens hub before any stage has run | All 6 stages show ⏳ Ready except ②–⑥ which are 🔒 Blocked on ① |
| Admin clicks super-button twice rapidly | Second click no-ops if a pipeline run is in-flight for this topic |
| Admin triggers a stage from per-stage page while hub is open | Hub's next poll picks up the Running status; badge flips to 🔄 |
| Stage ② fails mid-run while ③ and ④ are also running | ③ and ④ continue to completion; ⑤ and ⑥ remain ⏳ Ready; banner shows "Pipeline halted at Visuals" |
| Admin regenerates ① Explanations | `cards_json` replaced → ② ③ ⑥ revert to ⏳ Ready automatically (artifacts gone). ④ Practice bank flips to ⚠ Stale. ⑤ Audio review flips to ⚠ Stale |
| Admin clicks Retry on a Failed stage | Only that stage re-runs; other stages' state unaffected |
| `topic_explanations` row absent but `teaching_guideline` synced | ① Ready; ②–⑥ Blocked |
| Quality=Fast selected but stage's review-refine already has snapshots | Same as existing behavior — reviewer runs 0 rounds, overwrites latest snapshot |
| Chapter-level runner: one topic's ① fails | That topic's pipeline halts at ①; other topics continue; chapter chip shows "1 failed" |
| Audio synthesis clicked with no audio review | HTTP 409; button on hub shows "Run anyway — skip review" which sends `confirm_skip_review=true` |
| Stale artifact exists (practice bank built against old explanations) | Hub shows ⚠; regenerating picks up the new explanations |
| Two admins open the hub for the same topic and both press super-button | Second press hits the lock; gets a 409 with "pipeline already running for this topic" |
| Hub open in background tab for 20 minutes with no active jobs | Polling idle (stopped once settled); one manual refresh needed to see late external changes |
| `chapter_processing_jobs` heartbeat goes stale on a Running job | Existing stale-detection auto-fails the job; hub sees Failed on next poll |

---

## Observability

- Every pipeline run gets a `pipeline_run_id` logged to backend logs with the stages it decided to run and their terminal states.
- Each stage's job retains its existing entry in `chapter_processing_jobs` with the normal `stage_snapshots_json` review-refine observability.
- Frontend surfaces inline error summaries on failed stages (pulled from `chapter_processing_jobs.error`); admin still has full per-stage admin page for deep dive.
- No new metrics dashboards in v1. If pipeline runs become a scale concern, cost/time analytics is the phase-4 follow-up.

---

## Rollout

### Phase 1 — Read-only hub

- Consolidated GET endpoint
- New `TopicPipelineDashboard.tsx` with stage ladder, status badges, deep links to per-stage admin pages, smart polling
- Per-topic "Pipeline →" link on `BookV2Detail`
- **No super-button yet.** Stage rows show only [Open stage page →] and existing Regenerate/Run routed to the per-stage page.
- Ships the admin UX win (one-view status) fastest; zero backend risk.

### Phase 2 — Super-button + lock refactor + staleness

- Lock refactor to `(chapter_id, guideline_id)` for post-sync stages
- `TopicPipelineOrchestrator`
- `POST /.../run-pipeline` endpoint
- Staleness query in the GET endpoint
- Super-button wired on the hub
- Quality selector popover
- Hard-stop-on-failure behavior + banner

### Phase 3 — Chapter-level runner + polish

- `POST /.../run-pipeline-all`
- Chapter summary chip + "Run pipeline for all topics" button on `BookV2Detail`
- Prev/next topic buttons
- Inline error summary + [Retry] on stage rows
- Polling edge-case hardening

**Rollback plan:**

- Phase 1: revert is one PR; no data changes.
- Phase 2: revert requires restoring the chapter-wide lock and deleting the new endpoint. Lock partial unique index is additive and can stay harmlessly.
- Phase 3: revert is one PR.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Lock refactor introduces race condition on shared `chapter_processing_jobs` writes | Every job already runs on an isolated DB session; lock is DB-level via unique partial index, not in-memory. Thorough unit coverage of `acquire_lock` for the new scope. |
| Super-button orchestration blocks on a stage that silently hangs | Rely on existing stale-detection (heartbeat threshold); orchestrator polls the job status and respects failure transitions. |
| Staleness query adds latency to every hub page load | Single timestamp comparison per topic; pre-joined in the GET endpoint. Expect <50ms overhead. |
| Chapter-level runner triggers all topics in parallel and saturates Claude Code subprocess throughput | Bound parallelism (e.g., max N topics in flight at once — configurable; default 4). Existing Claude Code adapter retries on rate-limit errors. |
| Admin regenerates explanations without noticing downstream staleness | Hub's ⚠ Stale badge is the explicit signal. Copy on the badge names the reason ("explanations regenerated"). |
| Two admins press super-button simultaneously for same topic | Per-topic lock returns 409; second press fails loudly. |
| Polling load across many open hub tabs | Polling runs only while stages are Running; idle hubs are quiet. |
| Quality-selector mapping is wrong for a given stage | Per-stage admin pages retain full rounds control. Admins who need precision use those. |

---

## Success Criteria

1. Admin can navigate from `BookV2Detail` → topic → Topic Pipeline Dashboard in ≤2 clicks.
2. The dashboard correctly reflects status for all 6 stages against the per-stage admin pages (no disagreement).
3. The super-button runs all Ready stages in DAG order for a fresh topic (6 stages → ≤2 click sequence: open popover, press Run).
4. Regenerating explanations flips ②/③/⑥ to ⏳ Ready and ④/⑤ to ⚠ Stale within one poll cycle.
5. Chapter-level runner completes a chapter of 10 topics substantially faster than clicking 10 super-buttons serially (parallelism is real).
6. Zero regressions on existing per-stage admin pages or on the chapter-level preflight flow.
7. Lock refactor enables two concurrent stage jobs on different topics of the same chapter (verified via integration test).

---

## References

- Pipeline principles: `docs/principles/book-ingestion-pipeline.md`
- Existing per-stage services: `llm-backend/book_ingestion_v2/services/`
- Existing admin pages: `llm-frontend/src/features/admin/pages/BookV2Detail.tsx`, `ExplanationAdmin.tsx`, `VisualsAdmin.tsx`, `PracticeBankAdmin.tsx`
- Job service: `llm-backend/book_ingestion_v2/services/chapter_job_service.py`
- Companion tech impl plan: `docs/feature-development/topic-pipeline-dashboard/impl-plan.md`

---

## Open Questions

- Parallelism cap for the chapter-level runner default — start conservative (4 concurrent topics) and tune. **Defer to tech impl plan.**
- Whether to add a `last_seen_at` column on `topic_explanations` or rely on existing `updated_at` for staleness detection. **Defer to tech impl plan.**
- Whether the hub should show job duration from history to give admins a rough ETA. **Out of scope for v1; revisit after usage.**
