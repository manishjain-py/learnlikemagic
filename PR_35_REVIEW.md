## PR #35 Review: Background Job Infrastructure, Guidelines Generation, Resume

### Summary
This PR converts synchronous, blocking book-processing endpoints (guidelines extraction, finalization, bulk OCR) into background jobs with a proper state machine, progress polling, and resume support. A solid piece of work — well-structured state machine, good test coverage (66 tests), and clean frontend polling integration.

### Architecture — What Works Well

1. **State machine design** (`pending → running → completed|failed`) with row-level locks (`SELECT ... FOR UPDATE`) and heartbeat-based stale detection is exactly the right approach for App Runner where containers can restart mid-job.
2. **Separation of concerns**: The `background_task_runner.py` cleanly decouples job lifecycle management from domain logic. Background functions (`run_extraction_background`, `run_bulk_ocr_background`) are top-level functions, not coupled to an orchestrator class.
3. **Metadata batching**: Flushing `metadata.json` every 5 pages instead of per-page is a smart optimization — ~80% fewer S3 writes.
4. **Resume**: Clean resume path using `last_completed_item` to pick up from where a failed job left off.
5. **Frontend polling**: `useJobPolling` hook with mount-time detection, interval-based polling, and automatic stop on terminal states. Good test coverage.

---

### Issues Found

#### Critical

**1. Double `release_lock` on exception — could mask the real error**
`background_task_runner.py:wrapper()` catches _all_ exceptions and calls `release_lock(failed)`. But `run_extraction_background` _also_ catches exceptions at the outer level and calls `release_lock(failed)`. If the domain function's `release_lock` succeeds, the runner's `release_lock` will hit the "cannot release in 'failed' state" guard and silently no-op — so it works in practice. However, if the domain function raises _before_ calling `release_lock` (e.g. during the loop), both could race. This is a latent bug; the runner should check if the job is already in a terminal state before attempting to mark it failed.

**File:** `background_task_runner.py:59-80` and `guideline_extraction_orchestrator.py:893-803`

**2. `asyncio.run()` in background threads**
`run_extraction_background` and `run_finalization_background` use `asyncio.run()` inside a thread. Each call creates a new event loop. If the orchestrator or its callees ever share state across pages (e.g., an aiohttp session), this will break. More importantly, `asyncio.run()` is not designed to be called inside threads and can produce warnings/errors if the main thread also runs an event loop (which FastAPI does). Consider using `asyncio.get_event_loop().run_until_complete()` or better yet, make the background functions sync by refactoring the orchestrator methods.

**File:** `guideline_extraction_orchestrator.py:750,836`

**3. `generate_guidelines` endpoint changed from `async def` to `def`**
The route handler was changed from `async def` to `def`. In FastAPI, `def` endpoints run in a threadpool. While this works, it means the endpoint now blocks a thread while doing I/O (S3 metadata fetch, DB queries). This is fine for low-concurrency admin endpoints, but should be documented as an intentional choice.

**File:** `routes.py:78,261`

#### Important

**4. `get_latest_job` returns `None` directly from a route with no `response_model`**
The `GET /books/{book_id}/jobs/latest` endpoint can return `None` when no job exists. FastAPI will serialize this as a JSON `null` response. The frontend `getLatestJob` expects `JobStatus | null`, so this technically works, but the endpoint has no `response_model` set, so there's no OpenAPI schema for the response. Consider adding `response_model=Optional[JobStatusResponse]`.

**File:** `routes.py:401-419`

**5. Import inside function bodies**
Several route handlers import `JobLockService`, `run_in_background`, etc. inside the function body. While this avoids circular imports, it adds import overhead on every request. These should be top-level imports or at worst module-level lazy imports.

**File:** `routes.py:107-109`, `routes.py:289-291`, `routes.py:463-465`

**6. `_mark_stale` doesn't handle stuck `pending` jobs**
In `acquire_lock`, when a pending job is found, stale detection only checks if the job is `running`. If a job is stuck in `pending` forever (background thread never starts), it won't be recovered. Consider adding a timeout for pending jobs too (e.g., 30 seconds without transitioning to running).

**File:** `job_lock_service.py:63-68`

**7. `run_bulk_ocr_background` sets `last_completed_item` even for failed pages**
In `page_service.py`, `last_completed_item` is set to `page_num` regardless of whether the page succeeded or failed. This means resume would skip a failed page instead of retrying it. Compare with `run_extraction_background` which conditionally sets `last_completed_item` only on success.

**File:** `page_service.py` (line within `run_bulk_ocr_background`, update_progress call after the try/except)

**8. `useJobPolling` has potential for infinite re-render loop**
`startPolling` and `stopPolling` are in the dependency array of `useEffect`. Since `startPolling` depends on `stopPolling`, and both are `useCallback`s, React _should_ memoize them. But `startPolling` creates a new closure referencing `bookId` and `jobType`. If either of those changes, `startPolling` gets a new identity, which re-triggers the effect. This is generally fine since `bookId` is stable, but worth being explicit about (maybe add a comment).

**File:** `useJobPolling.ts:74-91`

#### Minor / Suggestions

**9. Partial unique index syntax**
The `__table_args__` uses `postgresql_where` with `IN ('pending', 'running')`. The migration in `db.py` creates the index with raw SQL. These should stay in sync. If someone adds a new "active" status, they'd need to update both. Consider extracting the active statuses as a constant.

**10. `IMPLEMENTATION_PROGRESS.md` added**
This tracking file is useful during development but likely shouldn't be merged to main. Consider removing it or adding it to `.gitignore`.

**11. Frontend: Inline styles**
The new components (`JobProgressBar`, `OcrStatusIcon`, bulk upload UI) use inline styles extensively. This is consistent with the existing codebase pattern but becomes harder to maintain. Not a blocker, but worth noting.

**12. Error classification is string-based**
`_is_retryable_error` and `_is_retryable` both check `str(e).lower()` against patterns. This is fragile — different SDKs may format errors differently. Consider also checking exception types (e.g., `ConnectionError`, `TimeoutError`).

**13. `_convert_to_png` wrapper + static method**
The refactor introduces a static method `_convert_to_png_static` and an instance wrapper `_convert_to_png`. This is clean but the instance method just delegates. The old callers still use the instance method, and the new background code uses the static one. Both are fine but could be simplified to just the static method.

---

### Test Coverage Assessment

**Strong:**
- JobLockService: 24 tests covering all state transitions, stale detection, and edge cases
- Bulk OCR: 31 tests covering happy path, partial failures, metadata batching, retry, and error classification
- Frontend polling: 11 tests covering mount detection, polling lifecycle, cleanup, and error recovery

**Gaps:**
- No integration test for the full `background_task_runner` → domain function flow
- No test for the `resume` path in `generate_guidelines` endpoint
- No test for `retry_page_ocr` endpoint at the route level (only service-level)
- Terraform changes (health check path, network config) not testable in unit tests — should be verified in staging

---

### Verdict

**Approve with requested changes.** The core architecture is sound and the implementation is thorough. The critical issues (#1, #2, #6, #7) should be addressed before merge — they represent real risks around exception handling, async/thread interaction, and the stuck-pending edge case. The remaining items are improvements that could be addressed in follow-up PRs.
