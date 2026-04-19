# Tech Impl Plan Review — Topic Pipeline Dashboard (PR #106)

**Reviewed:** `docs/feature-development/topic-pipeline-dashboard/PRD.md` + `impl-plan.md`
**Method:** Claims in the plan cross-checked against actual codebase.

---

## Tier 1 — Material flaws (address before implementation)

### 1. Wrong premise: topic-level jobs already DON'T block each other

**Plan claim (impl-plan.md §1, §3.3; PRD parallelism row):** *"`ChapterJobService` enforces one active job per `chapter_id`; running Topic A stalls Topic B"* — this motivates the lock refactor.

**Reality:** every post-sync route already does `lock_chapter_id = guideline_id` and sends *that* into `acquire_lock` as `chapter_id`. See `llm-backend/book_ingestion_v2/api/sync_routes.py:150, 463, 546, 1407, 1649` — all six post-sync routes.

So two topics in the same chapter **already run concurrently today**. The refactor's real value is *correctness* (clean semantics, preventing chapter-level ↔ topic-level races, proper FK integrity) — not parallelism. The PRD's headline problem is false.

**Impact:**
- Phase 2's risk-to-value pitch is overstated.
- Phase 3's "chapter runner parallelism gain vs. 10 serial super-buttons" is also overstated — a current chapter-level runner could already parallelise.

**Fix:** reframe the refactor as hygiene + correctness; re-justify Phase 2 on those grounds.

> **AI author response — AGREE.** Verified at `sync_routes.py:150` (`lock_chapter_id = guideline_id`). The parallelism premise in the PRD and impl plan is wrong. Reframing to correctness/hygiene: today `chapter_processing_jobs.chapter_id` is overloaded — for post-sync jobs it holds a guideline_id, which breaks FK integrity, makes status queries ambiguous, and entangles chapter-level vs topic-level invariants. The refactor's real value is a clean data model and unambiguous status queries. This also changes the pitch on Phase 3: the chapter-level runner's "parallelism gain" is about one-click-walk-away, not throughput.

---

### 2. Orchestrator can't "just call the `_run_*` helpers"

**Plan claim (§3.4):** *"Extract `_run_*` helpers from `sync_routes.py` to `stage_runners.py`; orchestrator imports and calls them."*

**Reality:** the `_run_*` helpers (e.g. `_run_explanation_generation` at `sync_routes.py:889`) **require a pre-existing `job_id`**. It's created earlier in the route via `acquire_lock` + `run_in_background_v2`, and `run_in_background_v2` (`processing_routes.py:451-459`) internally calls `job_service.start_job(job_id)` before invoking the helper.

So extracting just `_run_*` doesn't give the orchestrator what it needs. The orchestrator has to replicate more of the route pattern: `acquire_lock` → `run_in_background_v2(_run_X, ...)` → poll until terminal.

**Fix:** extract a higher-level helper per stage (e.g. `launch_explanation_job(db, book_id, chapter_id, guideline_id, force, review_rounds) -> job_id`) that encapsulates the full lock+launch sequence. Have both the route and the orchestrator call it.

> **AI author response — AGREE.** Verified at `sync_routes.py:889` — `_run_explanation_generation` takes `job_id` as a parameter; job creation happens in the route via `acquire_lock` + `run_in_background_v2`. Fix: the new module will be `stage_launchers.py` exposing `launch_<stage>_job(db, book_id, chapter_id, guideline_id, force, review_rounds) -> job_id` per stage. Each helper owns `acquire_lock` + `run_in_background_v2(_run_<stage>, job_id, ...)`. Routes and orchestrator both call the launcher. `_run_*` stays inside `sync_routes.py` as the background task bodies.

---

### 3. Completion-detection race in the orchestrator

**Plan (§3.4):** *"Orchestrator thread `joins` on each by polling the per-stage `ChapterJobService.get_latest_job` until a terminal state is reached."*

`get_latest_job(chapter_id, job_type)` returns the most recent row by `created_at`. Between the orchestrator submitting stage N+1 and the new job row being committed, `get_latest_job` returns **the previous terminal job** — already `completed`. The orchestrator concludes "stage done" and advances the DAG immediately, before the stage actually starts.

**Fix:** capture the `job_id` returned by `acquire_lock` for each stage and poll `get_job(job_id)` — not `get_latest_job(...)`.

> **AI author response — AGREE.** Verified at `chapter_job_service.py:172`. The orchestrator will capture `job_id` from each `launch_<stage>_job()` return value and poll `ChapterJobService.get_job(job_id)` for terminal state. `get_latest_job` stays the read path for the hub's initial render and for "latest by job_type" displays.

---

### 4. Staleness anchor is wrong — `topic_explanations.updated_at` advances for non-substantive reasons

**Plan (§3.6, PRD Stale Rule):** *"Stale = `artifact.completed_at < topic_explanations.updated_at`"*, justified as *"updated_at only advances when the row is written."*

But `topic_explanations.cards_json` is written in-place during ② Visuals (pixi_code added) and ⑥ Audio synthesis (audio_url added) — see `_run_audio_generation` at `sync_routes.py:683-687` (`attributes.flag_modified(explanation, "cards_json"); db.commit()`). That write advances `updated_at` via `onupdate=datetime.utcnow` (`shared/models/entities.py:349`).

Consequences:
- After ⑥ Audio synthesis completes, ⑤ Audio review and ④ Practice bank both flip to ⚠ Stale — neither was actually invalidated.
- After ② Visuals completes, ⑤ Audio review flips stale.

**Fix:** anchor staleness to a dedicated marker that only advances on substantive content changes — either a `content_updated_at` column on `topic_explanations`, or the `created_at` of the latest explanation row (delete + re-insert is how regen already works, per `sync_routes.py:939`).

> **AI author response — AGREE.** Verified at `sync_routes.py:683-687` — audio synthesis writes `cards_json` and commits, advancing `updated_at`. Taking the reviewer's second option: **anchor staleness to `max(topic_explanations.created_at) for this guideline`**. No schema change. Explanation regen does delete + insert (verified at `sync_routes.py:939`), which gives a clean boundary. Visual/check-in/audio writes only mutate `cards_json` on existing rows without touching `created_at`. If we ever add an "in-place explanation refine" mode that doesn't delete + insert, we'll revisit with a dedicated `content_version` column.

---

### 5. Chapter-wide / book-wide post-sync invocations not addressed

Existing routes accept **no `guideline_id`** — `generate_explanations?chapter_id=X` or book-wide iterates *all* APPROVED guidelines in scope (`sync_routes.py:152-169, 464-481, 548-563, 1408-1425, 1650-1667`). These land in the `lock_chapter_id = chapter_id or book_id` branch.

After Phase 2's rule *"post-sync jobs require `guideline_id`"* (impl-plan.md:330), those invocations have no single guideline_id. The plan doesn't say:
- Are they removed?
- Do they fan out into N topic-level jobs?
- Do they keep the chapter-wide lock (violating the "post-sync always topic-scoped" invariant)?

These code paths are used by existing admin UI and the plan has no answer.

**Fix:** explicitly define the behavior — most likely the route fans out to N `acquire_lock(guideline_id=...)` calls, one per approved guideline.

> **AI author response — AGREE.** Verified at `sync_routes.py:152-169`. The route iterates approved guidelines and uses `chapter_id or book_id` as the lock scope today. Post-Phase-2 behavior: **fan out**. When a caller omits `guideline_id`, the route resolves all approved guidelines in scope, then launches **N separate per-topic jobs** via the new launcher helpers — one per guideline, each with its own `guideline_id` lock. This is the same fan-out pattern Phase 3's chapter-level runner will use, so we get one implementation for both. Routes return a summary response `{ launched: N, job_ids: [...] }` instead of a single `ProcessingJobResponse`. This is a small API shape change for existing clients but only affects the return payload; `getLatestExplanationJob(chapterId)` remains the way to poll.

---

### 6. Polling hook code has a bug that causes infinite recursion

**Plan (§2.6):**
```ts
timer = window.setTimeout(tick, anyRunning ? 3000 : /* idle */ 0 && null);
if (!anyRunning && timer === null) return; // stop polling
```

`0 && null` evaluates to `0`, so when nothing is running, `setTimeout(tick, 0)` fires immediately. `timer === null` is never true (it was just assigned). The "idle" branch never stops polling.

**Fix:** early-return before scheduling the next tick:
```ts
if (!anyRunning) return;
timer = window.setTimeout(tick, 3000);
```

> **AI author response — AGREE.** My snippet was wrong. Adopting the early-return form verbatim.

---

## Tier 2 — Real gaps worth addressing

### 7. Migration pollution — pre-refactor topic jobs have `chapter_id = guideline_id`

Historical post-sync job rows have `chapter_id` literally holding a guideline UUID (see Flaw 1). After Phase 2, queries like "jobs for chapter X" or "latest job for guideline Y" will either miss them or surface them as bogus results — e.g. a "failed" historical job appearing for a chapter it was never actually for.

The plan says *"Backfill: none. Historical jobs are terminal"* — but the new status service reads historical rows for the ⚠/✕ computation.

**Fix:** either (a) backfill: set `guideline_id = chapter_id` for historical post-sync rows + populate a real `chapter_id`, or (b) cutover: exclude rows with `created_at < migration_timestamp` from the new status queries.

> **AI author response — AGREE; hybrid fix.** Going with: **(a) for `guideline_id`, (b) for `chapter_id`.** Backfill `guideline_id` via SQL (straightforward — for any post-sync row whose `chapter_id` resolves to a `teaching_guidelines.id`, copy it to `guideline_id`). Do NOT rewrite `chapter_id` on historical rows (the 3-way join through `book_chapters.chapter_number` is messy and error-prone). Instead, the status service excludes post-sync rows where `guideline_id IS NULL AND created_at < <migration_ts>` from chapter-scoped queries. Post-migration, all new rows have both columns correct. Historical rows with recovered `guideline_id` are still queryable by topic.

---

### 8. Refactor scope larger than the plan enumerates

Plan mentions threading `guideline_id` through `acquire_lock` call sites. But ~6 other call sites use the same `lock_chapter_id = guideline_id or chapter_id or book_id` pattern to look up jobs, and all need updating:

- `get_latest_explanation_job` (`sync_routes.py:207`)
- `get_latest_audio_review_job` (`sync_routes.py:240`)
- `get_latest_check_in_job` (`sync_routes.py:1520`)
- `get_latest_practice_bank_job` (`sync_routes.py:1756`)
- Audio-generation soft guardrail (`sync_routes.py:572-574`)
- Likely similar latest-visual-job endpoint

**Fix:** enumerate these sites as explicit Phase 2 steps.

> **AI author response — AGREE.** Adding a Phase 2 step: "Audit and update all `lock_chapter_id = guideline_id or chapter_id or book_id` sites to pass the new `guideline_id` parameter to `get_latest_job`." Enumerating: `get_latest_explanation_job:207`, `get_latest_audio_review_job:240`, `get_latest_visual_job:1351`, `get_latest_check_in_job:1520`, `get_latest_practice_bank_job:1756`, audio-synthesis soft-guardrail lookup at `sync_routes.py:572-574`. `ChapterJobService.get_latest_job` gains an optional `guideline_id` parameter.

---

### 9. Phase 1 "read-only, zero backend risk" overstates simplicity

Phase 1 promises per-topic `running`/`failed` status *before* the migration, while job rows are still keyed by the `chapter_id = guideline_id` hack. The status service has to emulate the hack on read — not the clean `guideline_id`-column query §2.3 implies.

When Phase 2 lands, the status service must flip its query path simultaneously with the migration — Phase 1 and Phase 2 status queries are not independent.

**Fix:** call this out in §2.3 and §9 "Deployment Considerations."

> **AI author response — AGREE.** Phase 1 still has low *write-path* risk (no DB mutations), but the read-path has to emulate the `chapter_id-holds-guideline_id` hack. Adding an explicit note to §2.3 and §9 that the status service has two query paths: one during Phase 1 (detect post-sync job_types and treat `chapter_id` as guideline_id) and one post-migration (native `guideline_id` column). The query-path flip is part of Phase 2, coordinated with the migration deploy.

---

## Tier 3 — Smaller issues

- **Quality=Fast (review_rounds=0)**: plan assumes every stage service accepts 0 — not verified against `check_in_enrichment_service` or `practice_bank_generator_service`.
- **Chapter summary chip (Phase 3)** fires N concurrent `/pipeline` GETs per chapter load — 10–15 topics × 5+ DB queries each. Plan dismisses with "defer until measured"; worth benchmarking before shipping.
- **Phase 2 rollback** claims split indexes can be left in place harmlessly. True, but the `acquire_lock` revert still requires routes to also revert passing `guideline_id=...` — rollback is not as clean as stated.
- **`@dataclass` vs Pydantic** inconsistency in `StageStatus` example (§2.2) — pick one.
- **`topic_key` URL-encoding** not addressed. topic_keys are slugified (`entities.py:130`) so probably safe, but worth a note.

> **AI author responses (Tier 3):**
> - **review_rounds=0 support**: AGREE — adding an implementation-order step to grep each stage service for lower-bound checks before Phase 2 lands. If any service rejects 0, fall back to 1 for that stage in the `_QUALITY_ROUNDS["fast"]` map.
> - **Chapter chip N×GETs**: AGREE — promoting to Phase 3 first-class work. Adding a new endpoint `GET /admin/v2/books/{book_id}/chapters/{chapter_id}/pipeline-summary` that returns per-topic summary (stage counts only, no per-stage warnings detail) in one trip.
> - **Phase 2 rollback**: AGREE — updating the §9 rollback note to say routes must also revert. Not "one PR revert."
> - **`@dataclass` vs Pydantic**: AGREE — switching `StageStatus` to Pydantic `BaseModel` for consistency with the rest of the schemas module.
> - **topic_key URL encoding**: AGREE — adding a one-line note. `topic_key` is slugified per `entities.py:130` so it's URL-path-safe; no encoding needed, but worth documenting.

---

## What's good

- Phasing (Phase 1 before DB migration) is sound.
- Two partial unique indexes vs COALESCE — correct choice.
- Reader/writer model between chapter-level and topic-level locks — correct.
- Bounded parallelism for Phase 3 — sensible default.
- DAG layering and hard-stop-on-failure — cleanly specified.

---

## Recommendation

Tier-1 flaws **1–6** should be addressed before implementation starts:
- **2, 3, 4, 6** are implementation-blocking bugs.
- **1** affects how the plan is pitched internally and the rollback calculus.
- **5** is a concrete code path the plan has no answer for.

Tier-2 items **7–9** are real gaps but can be tackled as the refactor proceeds.
