# Tech Implementation Plan: Backend Refactor

**Date:** 2026-04-23
**Status:** Draft — audit complete, awaiting review
**Scope:** `llm-backend/` (286 Python files, ~70k LOC excluding venv/tests)
**Goal:** Prioritized refactor backlog. No behavior changes; every item below is a structural cleanup that must preserve existing functionality end-to-end.
**Principles:** `docs/technical/architecture-overview.md` (API → Service → Agent/Orchestration → Repository)

---

## 1. Overview

This document captures findings from a five-dimension audit of `llm-backend/` (dead code, readability, modularity, state hygiene, best practices) and bundles them into a prioritized, sequenced refactor plan.

**Headline findings:**
- Backend is healthy overall — no dead endpoints, no SQL injection risk, config is centralized, input validation via Pydantic is consistent.
- **Three structural smells dominate:** (a) a handful of 900–2200-line "god modules," (b) API routes bypassing services to import repositories directly, (c) inconsistent error handling that silently swallows exceptions in production paths.
- **Two concrete safety issues:** (a) `pixi_poc.py` admin endpoint is unauthenticated, (b) async endpoints in `tts.py` / `transcription.py` make blocking I/O calls on the event loop.

Each work item below is scoped so it can ship as its own PR, keeping blast radius small and regressions cheap to isolate.

---

## 2. Audit Summary

### 2.1 Dead code
One real item: the **pixi-poc admin PoC** is obsolete. It existed to prototype Pixi.js code generation before the integrated tutor pixi flow (`tutor/services/pixi_code_generator.py`) shipped; now that the integrated flow is live, the standalone PoC page and endpoint are unused. Handled as P0.1 below. Otherwise clean — no other dead endpoints, orphan modules, or unused config.

One naming-clarity issue: `db.py` is a migration CLI — not a data-access library — and shares the namespace with `database.py` (session management). Low priority.

### 2.2 Readability
Five files dominate: `sync_routes.py` (2258 LOC), `session_service.py` (1387), `orchestrator.py` (1099), `db.py` (934), `master_tutor.py` (928). Inside those files, ~10 functions exceed 150 lines. Mastery thresholds, turn limits, and grade cutoffs are scattered as magic numbers (`0.7`, `0.6`, `grade <= 5`) instead of named constants.

### 2.3 Modularity
Primary contract breach: **API routes importing repositories directly**, found in at least 8 sites across `sync_routes.py`, `sessions.py`, `profile_routes.py`, `enrichment_routes.py`, `processing_routes.py`, `toc_routes.py`. A secondary breach: **services raising `fastapi.HTTPException`** (e.g., `session_service.py:73`, `stage_gating.py:11`), which couples the service layer to the HTTP transport.

The six `autoresearch/*/evaluation/` pipelines duplicate an identical evaluator scaffold (LLM init, prompt loading, loop, report generation) — candidate for a shared `BaseEvaluator`.

### 2.4 State hygiene
DB session handling is **mostly** clean (`Depends(get_db)` with FastAPI auto-close), but inconsistent: some services hold a long-lived session via `self.db = get_db_manager().get_session()` in `__init__`, while others accept a session per-request. A few singletons (`_tts_client`, `_jwks_cache`) lack a lock and can produce duplicate client instances under concurrent cache-miss races (benign but sloppy). Multiple `autoresearch/*/evaluation/config.py` modules call `load_dotenv()` at import time.

### 2.5 Best practices
- **Bare `except Exception:`** in API routes (`processing_routes.py:89`, `sync_routes.py` in 11+ places) that silently swallow the traceback and return `detail=str(e)` to the client.
- **Missing `exc_info=True`** on `logger.error()` in exception handlers (`tts.py:90`, `transcription.py:76`, `pixi_poc.py:114`).
- **`print()` in `main.py` startup** (lines 131/137/139/141) bypasses the JSON log formatter.
- **Blocking I/O in async endpoints** — `tts.py:76` (`client.synthesize_speech`) and `transcription.py:70` (`client.audio.transcriptions.create`) block the event loop.
- **Obsolete PoC endpoint** — `POST /api/admin/pixi-poc/generate` is also unauthenticated, but since the PoC has been superseded by the integrated tutor pixi flow, the right fix is deletion, not auth.
- **Hardcoded logger names** in a few files (`"auth.middleware"`, `"tutor.session_service"`) vs. the standard `__name__`.

---

## 3. Prioritized Refactor Plan

Priorities map to risk/reward, not effort. **P0 ships first regardless of size.** P1/P2/P3 can be reordered or parallelized based on team availability.

Each item lists: **What / Why / Files / Approach / Regression surface / Effort**. Effort is rough — S = < 1 day, M = 1–3 days, L = 3–5 days.

---

### P0 — Safety (ship first)

These change runtime behavior under failure (exceptions, concurrency, auth) and are individually small. Bundle them or split by file — but do not defer.

#### P0.1 — Remove the obsolete pixi-poc PoC
**What.** Delete the standalone Pixi.js code-generation PoC. It was built before the integrated tutor pixi flow (`tutor/services/pixi_code_generator.py`) shipped; now that the integrated flow is live in-session, the PoC is unused dead code that also happens to be unauthenticated.

**Why.** Removes a cost/abuse vector (the endpoint is unauthenticated and spends OpenAI tokens) and trims dead code. Deleting is simpler than authenticating something nobody uses.

**Files to delete (backend).**
- `llm-backend/api/pixi_poc.py`
- Remove the imports and `app.include_router(pixi_poc_router)` in `llm-backend/main.py:24, 124`.

**Files to delete (frontend, companion PR — required to avoid a dead nav link).**
- `llm-frontend/src/features/admin/pages/PixiJsPocPage.tsx`
- Remove the route registration in `llm-frontend/src/App.tsx`.
- Remove the nav link in `llm-frontend/src/features/admin/components/AdminLayout.tsx`.
- Remove the link card in `llm-frontend/src/features/admin/pages/AdminHome.tsx`.

**Docs to update.** `docs/technical/architecture-overview.md` lines 25, 193, 271, 333 — remove pixi-poc references.

**Keep unchanged.** `llm-backend/tutor/services/pixi_code_generator.py` (used by the orchestrator for in-session `visual_explanation` rendering) and the `pixi_code_generator` seed row in `db.py` (still consumed by the integrated generator) stay exactly as they are.

**Regression surface.** Minimal. The PoC page has no upstream callers in the student flow. Verify by (a) grepping for any other caller of the endpoint path `/api/admin/pixi-poc`, (b) confirming the tutor's in-session pixi still renders after the change — `tutor/services/pixi_code_generator.py` continues to import the `pixi_code_generator` LLM config by the same name.

**Effort.** S.

#### P0.2 — Move blocking I/O off the event loop in async endpoints
**What.** `tutor/api/tts.py:76` calls the synchronous `client.synthesize_speech(...)` inside an `async def` route. `tutor/api/transcription.py:70` calls sync `client.audio.transcriptions.create(...)` inside an `async def` route. Both block the asyncio event loop for the duration of the external API call.
**Why.** On a single-worker dev server the symptom is latent; under load, concurrent requests stall. The canonical pattern is already present in `api/pixi_poc.py:94` (`await asyncio.to_thread(llm.call, ...)`).
**Files.** `llm-backend/tutor/api/tts.py`, `llm-backend/tutor/api/transcription.py`.
**Approach.** Wrap the blocking calls in `await asyncio.to_thread(...)`. Do not change the route signatures or response shapes.
**Regression surface.** Unit tests for tts/transcription (if any) + manual smoke test of the student voice flow.
**Effort.** S.

#### P0.3 — Replace silent `except Exception:` in API routes
**What.** Several API routes catch `Exception`, drop the traceback, and return `detail=str(e)` as the HTTP response. Examples:
- `book_ingestion_v2/api/processing_routes.py:89-92`, `126-129`
- `book_ingestion_v2/api/sync_routes.py` (11+ occurrences)
- `auth/api/profile_routes.py:84` (inline handler)

**Why.** This makes prod bugs invisible (no log line, no traceback) *and* leaks internal error messages to clients. When a mid-pipeline LLM call fails, the admin UI sees a cryptic string while the backend log shows nothing.
**Files.** All three above.
**Approach.** Standard pattern:
```python
except Exception:
    logger.exception("start_processing failed")
    raise HTTPException(
        status_code=500,
        detail="Internal server error while starting processing",
    )
```
Rules:
- Always `logger.exception(...)` (includes `exc_info=True` automatically).
- Return a **generic** message to the client — never `str(e)`.
- Re-raise `HTTPException` unchanged (already done in most places).
**Regression surface.** Client-side error messages change from "specific internal string" to a generic sentence. Confirm frontend does not parse `detail` text for branching (grep `error.detail` in `llm-frontend/src/`).
**Effort.** M (mechanical but touches ~15 call sites).

#### P0.4 — Add `exc_info=True` to error logging
**What.** `logger.error(f"... {e}")` appears in several handlers without `exc_info=True`, so no stack trace is captured. Examples: `tts.py:90`, `transcription.py:76`, `pixi_poc.py:114`.
**Why.** When these fail in prod, we get only the exception message. Root causes that live two frames deep are invisible.
**Files.** `llm-backend/tutor/api/tts.py`, `llm-backend/tutor/api/transcription.py`, `llm-backend/api/pixi_poc.py`, plus any other `logger.error` handlers in `llm-backend/**/api/*.py` (audit with grep before shipping).
**Approach.** Prefer `logger.exception("context message")` over `logger.error("...", exc_info=True)`. Both are equivalent; `.exception` is idiomatic inside `except` blocks.
**Regression surface.** None — purely additive logging.
**Effort.** S.

#### P0.5 — Replace `print()` with logger in `main.py` startup
**What.** `main.py:131/137/139/141` emits startup banners via `print()`, which bypasses the JSON formatter configured 60 lines earlier.
**Why.** Prod logs are structured JSON; `print()` leaves unparsed strings in the stream, breaking log aggregation and alerting.
**Files.** `llm-backend/main.py`.
**Approach.** Replace with `logger.info(...)`. Keep emoji in the message if you like — the JSON formatter passes them through.
**Regression surface.** None.
**Effort.** S.

---

### P1 — Modularity (high-leverage structural fixes)

These break dependency cycles and unblock further cleanup. They are bigger, but they change *shape*, not behavior.

#### P1.1 — Stop API routes from importing repositories directly
**What.** ~8 confirmed sites where API modules import from `*/repositories/` and instantiate repositories inline:
- `book_ingestion_v2/api/sync_routes.py:39-40, 629, 687, 739`
- `tutor/api/sessions.py:38, 213, 623`
- `auth/api/profile_routes.py:74` (inline inside function)
- `auth/api/enrichment_routes.py`, `book_ingestion_v2/api/toc_routes.py`, `processing_routes.py` (multiple)

**Why.** Violates the architecture contract in `CLAUDE.md`. API → Repository skips the service layer, which means (a) business rules get duplicated inline in routes, (b) the routes are untestable without a live DB, (c) adding cross-cutting concerns (logging, caching, permissions) requires touching every route.

**Files.** The six API files above, plus new/extended service modules as needed.

**Approach.** One-PR-per-route-file, ordered by size (smallest first for pattern validation):
1. `auth/api/profile_routes.py` + `enrichment_routes.py` — smallest, validate the pattern.
2. `book_ingestion_v2/api/toc_routes.py`, `processing_routes.py`.
3. `tutor/api/sessions.py`.
4. `book_ingestion_v2/api/sync_routes.py` — last (biggest, ties into P2.1).

For each file:
- Identify the inline repository call.
- Move the logic into the matching service (e.g., `session_service`, `book_v2_service`, `topic_sync_service`). If no service exists, create one named `<domain>_service.py`.
- Route now calls `service.method(db, ...)` — the service owns the repository interaction.

**Regression surface.** Every moved endpoint needs a targeted integration test. Prefer tests that hit the HTTP layer so the response contract is verified.

**Effort.** L overall; each sub-PR is M.

#### P1.2 — Services should not raise `fastapi.HTTPException`
**What.** Services raise HTTP-transport exceptions. Confirmed sites:
- `tutor/services/session_service.py:73, 267, 556, 836, 840, 850, 855, 974, 1023, 1087` (often via inline `from fastapi import HTTPException` inside methods)
- `book_ingestion_v2/services/stage_gating.py:11`

**Why.** Makes the service layer unreusable outside FastAPI (CLI tasks, background workers, tests that don't spin up the app). Also hides semantic errors behind HTTP status codes.

**Files.** `tutor/services/session_service.py`, `book_ingestion_v2/services/stage_gating.py`, plus one new `exceptions.py` per domain.

**Approach.**
1. Create `tutor/exceptions.py` (a `tutor/exceptions.py` already exists per `ls` — extend it) and `book_ingestion_v2/exceptions.py` with domain types: `SessionLocked`, `InvalidStateTransition`, `StageGateRejected`, etc.
2. Replace `raise HTTPException(...)` in service code with domain exceptions.
3. In API routes, translate domain exceptions to HTTP responses via a FastAPI exception handler (`@app.exception_handler(SessionLocked)`) **or** a try/except at the route level — pick one convention and document it.

**Regression surface.** Error response bodies and status codes must stay identical. Add contract tests that assert `(exception, status_code, detail_key)` before and after.

**Effort.** M.

#### P1.3 — Split `sync_routes.py` (2258 LOC)
**What.** The single largest file in the backend. Mixes route dispatch, stage runners (explanation/audio/visual/check-in/animation/simplification enrichments), shared error handling, and background-task orchestration.

**Why.** Unmaintainable. Every new enrichment stage adds 50–100 lines to the same file. Also the primary site of the layer violations in P1.1.

**Files.** `llm-backend/book_ingestion_v2/api/sync_routes.py` → split into:
- `api/sync_routes.py` — thin route dispatch (~300 LOC)
- `services/enrichment_runners/` — one module per enrichment stage (explanation, audio, visual, check-in, animation, simplification). Each exports a `run_<stage>(...)` function.
- `services/enrichment_runners/_common.py` — shared helpers (LLM init, job progress logging, error shape).

**Approach.** Land **after P1.1 and P1.2** so routes are already thin and service exceptions exist. Do this in staged PRs: one stage-runner extraction at a time. Run the full book-ingestion happy path after each.

**Regression surface.** High — this is the book ingestion pipeline. Recommend pausing production ingestion during the splits (happy coincidence: all ingestion is localhost per project memory, so no prod risk).

**Effort.** L.

---

### P2 — Structural cleanup

Long-term maintainability wins. None of these are urgent; each can land in a calm week.

#### P2.1 — Split `session_service.py` (1387 LOC)
**What.** `tutor/services/session_service.py` holds session lifecycle + LLM config loading + student context building + guideline resolution + card-phase handling + feedback-driven plan regeneration.

**Files → proposed split:**
- `tutor/services/session_service.py` — create/get/close session (~400 LOC)
- `tutor/services/session_context_builder.py` — build student context from profile
- `tutor/services/session_plan_manager.py` — feedback ingestion + plan regeneration + plan splicing
- `tutor/services/card_phase_service.py` — card simplify/next/completion

**Approach.** Extract one concern at a time; keep `session_service` as a thin facade initially to minimize blast radius on callers.

**Effort.** L.

#### P2.2 — Split `orchestrator.py` (1099 LOC) and `master_tutor.py` (928 LOC)
**What.** `process_turn` is 206 lines (`orchestrator.py:150-356`). `_compute_pacing_directive` is 138 lines (`master_tutor.py:403-540`). Both can be decomposed without changing semantics.

**Approach.**
- Extract orchestrator helpers: `_run_safety_checks()`, `_translate_student_message()`, `_handle_question_lifecycle()`, `_apply_state_updates()`.
- Extract tutor pacing: `_get_pacing_for_step_type()`, `_get_pacing_for_mastery()`, `_apply_attention_span_warning()`.

**Regression surface.** These are the hot path of the tutor conversation. Must run the full tutor eval suite (`autoresearch/tutor_teaching_quality/`) before and after; scores must not regress.

**Effort.** M each.

#### P2.3 — Split `db.py` (934 LOC) into migration modules
**What.** `db.py` is a single script holding ~30 migration functions, seed data, and a CLI dispatcher.

**Files → proposed:**
- `db/migrations.py` — schema migrations (column/table adds)
- `db/seeds.py` — default seed data (LLM config, feature flags)
- `db/__main__.py` — CLI dispatcher (keeps `python -m db migrate` etc.)

**Regression surface.** Migration idempotency must be preserved. Run the migrations on a fresh DB and on the existing one; both must be no-ops by the end.

**Effort.** M.

#### P2.4 — Extract shared `BaseEvaluator` for autoresearch pipelines
**What.** Six `autoresearch/*/evaluation/` pipelines duplicate the evaluator scaffold (LLM init, prompt loading, evaluation loop, report).

**Files → new:** `autoresearch/base_evaluator.py`.

**Approach.** Extract the common interface first; migrate one pipeline at a time; keep the old subclasses working until all are converted.

**Regression surface.** Each pipeline's outputs (eval reports) must be byte-identical before/after for a fixed seed/input.

**Effort.** M.

#### P2.5 — Unify DB session lifecycle for services
**What.** Inconsistency: some services hold a session in `__init__` (`chapter_finalization_service`), others accept per-call. Long-lived sessions can expire mid-job.

**Approach.** Convention: **services do not store sessions**. Every public method accepts `db: Session` as a parameter. Background jobs create fresh sessions per task (pattern already in `processing_routes.py:438-483`).

**Regression surface.** Background-job correctness. Ensure every worker still commits/closes cleanly.

**Effort.** M.

#### P2.6 — Centralize `load_dotenv()` and stray `os.getenv`
**What.** `autoresearch/*/evaluation/config.py` modules each call `load_dotenv()` at import time. Should happen once, at process start.

**Approach.** Remove all module-level `load_dotenv()` calls. Ensure `config.get_settings()` is the single entry point. Scripts that run standalone can continue to call `load_dotenv()` at script start (in `if __name__ == "__main__":`).

**Effort.** S.

---

### P3 — Readability polish

Individually trivial; collectively raise the floor. Batch them into one PR when convenient.

#### P3.1 — Name the magic numbers
Define a `tutor/constants.py` (or extend existing) with:
```python
STRONG_MASTERY_THRESHOLD = 0.7      # master_tutor.py:403-540
WEAK_MASTERY_THRESHOLD = 0.4
ATTENTION_SPAN_TURN_LIMITS = {"short": 8, "medium": 14, "long": 20}  # master_tutor.py:531
SIMPLE_LANGUAGE_MAX_GRADE = 5       # session_service.py:83, 418, 433
MAX_EXTENSION_TURNS = 10            # orchestrator.py:192
```
**Effort.** S.

#### P3.2 — Introduce enums for string status/mode constants
- `SessionMode` — `"teach_me"`, `"clarify_doubts"`, etc.
- `JobStatus` — `"active"`, `"completed"`, `"failed"`, etc.
- `GuidelineReviewStatus` — `"APPROVED"`, etc.

**Files.** `shared/models/enums.py` (new), consumed across tutor/book_ingestion_v2.

**Effort.** S but touches many call sites — good candidate for a big-but-mechanical PR.

#### P3.3 — Standardize logger initialization
Replace hardcoded logger names (`"auth.middleware"`, `"tutor.session_service"`) with `logging.getLogger(__name__)`. Update any alerting/filter rules that depend on old names.

**Effort.** S.

#### P3.4 — Clarify `db.py` vs `database.py` naming
After P2.3 ships and `db.py` is replaced by `db/` package, rename the package to `migrations/` (or leave as `db/` if the CLI name matters). Goal: zero ambiguity between "migrations" and "session/engine management."

**Effort.** S.

#### P3.5 — Add missing type hints
Gap is small (~2–3% of service signatures). Run `mypy --strict` on `shared/services/` and `book_ingestion_v2/services/` to get a targeted list; fix in one PR.

**Effort.** S.

---

## 4. Regression Safety Plan

Every refactor PR must:

1. **Keep public contracts unchanged.** API routes: same path, same request/response model, same status codes. Services: same method signatures where callers exist outside the service module.
2. **Run the full test suite** — `cd llm-backend && make test` — must pass before merge.
3. **Run the tutor eval sanity pass** — for any changes in `tutor/orchestration/`, `tutor/agents/`, or `tutor/services/session_service.py`. Confirmed via `autoresearch/tutor_teaching_quality/` run on a small fixed scenario set; scores must not regress.
4. **Manual smoke test the affected feature path.** For API/service changes: run the relevant student flow end-to-end on localhost (per project memory, ingestion is localhost-only).
5. **No behavior changes.** If a refactor tempts you to "also fix" an adjacent bug, stop and file it separately. Mixing refactor + fix defeats the regression-isolation story.

Per the project's concise-doc rule, this list is intentionally minimal. Ops burden stays proportional to the change.

---

## 5. Rollout Sequence

Recommended order (each step lands independently; later steps may unblock earlier-listed items):

1. **Week 1.** P0.1–P0.5 — five small safety fixes. Ship as a single PR or five, reviewer's choice.
2. **Week 2.** P1.2 (service exceptions) — unblocks P1.1 and P1.3 because now services have a clean error-raising idiom.
3. **Weeks 3–4.** P1.1 (layer-violation fixes), ordered smallest file → largest.
4. **Weeks 5–6.** P1.3 (split `sync_routes.py`) — one enrichment-stage-runner at a time.
5. **Later.** P2 items in any order; each is independent.
6. **Convenient downtime.** P3 items, batched.

---

## 6. Out of Scope

- **Frontend changes.** Backend-only, with one exception: P0.1 (pixi-poc removal) requires a companion frontend PR to delete the dead admin page — listed inline in P0.1.
- **Test coverage increases.** Refactors should preserve or slightly improve testability, but adding net-new tests is a separate workstream.
- **Infrastructure / deployment changes.** No Terraform, no Dockerfile edits.
- **Performance optimization.** P0.2 fixes a correctness bug around blocking I/O; broader perf work is out of scope.
- **New features or behavior changes.** Explicitly none.

---

## 7. Appendix — Audit Method

Five parallel read-only audits, each scoped to one dimension:

| Dimension | Method summary |
|-----------|----------------|
| Dead code | Grep each imported symbol + endpoint path across repo (including `llm-frontend/src/`); trace one level past `__init__.py` re-exports. |
| Readability | `find \| wc -l \| sort -rn` to find large files; read top 10 manually; measure function length, nesting, param count. |
| Modularity | Grep cross-layer imports (`from.*repository` in `api/`, `from fastapi` in `services/`); inspect `__init__.py`; read one representative file per layer. |
| State hygiene | Grep module-level `=\s*\{`, `=\s*\[`, `global`, `load_dotenv`, `os.environ`; inspect `database.py`, `config.py`, `main.py`. |
| Best practices | Grep `except:`, `except Exception:`, `print(`, `execute(f`, `os.getenv`, `requests.`; inspect `main.py`, representative API/service/repo. |

Spot-checked the highest-severity claims against file contents before writing this plan. Raw audit reports are available in the refactor-audit PR description.
