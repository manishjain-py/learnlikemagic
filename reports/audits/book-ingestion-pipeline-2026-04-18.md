# Book Ingestion Pipeline — Gap Audit

**Date:** 2026-04-18
**Audited against:** `docs/principles/book-ingestion-pipeline.md`
**Method:** Agent exploration + manual verification of high-impact claims.

## Scope & Key Finding

Verified the 6 declared stages **plus 2 additional LLM stages found in code** that the principles doc does not mention: check-in enrichment and practice bank generation. Both are post-sync, LLM-driven, review-refine-capable — they should probably be part of the principles.

## Summary

Infrastructure is solid across the board: background jobs, state machine, heartbeat, stale detection, session isolation, and per-stage admin UIs all exist. The primary gaps are feature-parity issues — mostly concentrated on **Visual Enrichment (stage 6)** and the **missing "retry failed job" semantics** across LLM stages.

## Per-Stage Compliance

| Stage | BG job | Admin UI | Live track | View content | Generate | Regenerate | Review-refine N | Retry failed | State machine | Session iso | Gating |
|-------|--------|----------|-----------|--------------|----------|-----------|-----------------|--------------|---------------|-------------|--------|
| 1. OCR | ✅ | ✅ `OCRAdmin.tsx` | ✅ | ✅ | ✅ | ✅ `ocr_rerun` | N/A | ✅ `ocr_retry` (explicit) | ✅ | ✅ | ✅ |
| 2. Topic Extraction | ✅ | ✅ `TopicsAdmin.tsx` | ✅ | ✅ | ✅ | ✅ (reprocess) | ⚠️ (on finalize only) | ⚠️ (resume from FAILED, no explicit retry) | ✅ | ✅ | ⚠️ loose |
| 3. Finalization | ✅ | ❌ embedded in Topics | ✅ | ✅ | N/A | ✅ refinalize | ⚠️ | ⚠️ | ✅ | ✅ | ✅ |
| 4. Sync | N/A (sync) | ✅ `BookV2Dashboard.tsx` | N/A | ✅ | N/A | N/A | N/A | N/A | N/A | ✅ | ✅ |
| 5. Explanations | ✅ | ✅ `ExplanationAdmin.tsx` | ✅ | ✅ (+ stage snapshots) | ✅ | ✅ `force=true` | ✅ 0-5 configurable | ⚠️ implicit via `force=false` | ✅ | ✅ | ✅ |
| 6. Visual Enrichment | ✅ | ✅ `VisualsAdmin.tsx` | ✅ | ✅ | ✅ | ✅ `force=true` | ❌ | ⚠️ implicit via `force=false` | ✅ | ✅ | ✅ |
| 7*. Check-ins | ✅ | ⚠️ (check-ins admin page TBD) | ✅ | ⚠️ | ✅ | ✅ `force=true` | ✅ 0-5 configurable | ⚠️ | ✅ | ✅ | ✅ |
| 8*. Practice Bank | ✅ | ✅ `PracticeBankAdmin.tsx` | ✅ | ✅ | ✅ | ✅ `force=true` | ✅ 0-5 configurable | ⚠️ | ✅ | ✅ | ✅ |

*Stages 7 and 8 are not in the current principles doc.

## Gap List

### Critical

- **Principles doc is incomplete** — missing check-in enrichment (stage 7) and practice bank generation (stage 8). Both follow the same background-job + review-refine pattern.

### High

- **Visual Enrichment (stage 6) lacks `review_rounds` param.** Every other LLM stage exposes 0-5 configurable rounds. Visuals only has `force` (wipe + regenerate). File: `sync_routes.py:406` — `generate_visuals` signature.
- **Visual Enrichment does not collect stage snapshots.** Once `review_rounds` is added, intermediate outputs won't be viewable. Compare `explanation_generator_service.py` (has `stage_collector`) vs. `animation_enrichment_service.py` (no snapshots).
- **No explicit "retry failed job" endpoint** for LLM stages 2, 3, 5, 6, 7, 8. `force=false` acts as implicit retry (skip items with results, process missing ones), but partial-state cleanup for the failed run is not documented. OCR is the only stage with an explicit `retry` endpoint (`ocr_retry`).
- **Finalization has no dedicated admin page.** Controls are inside `TopicsAdmin.tsx`. No standalone UI for status/progress/trigger.

### Medium

- **Stage gating is status-based, not dependency-based.** Each endpoint checks `chapter.status`; no centralized "stage N-1 must be complete" helper. Results in slightly inconsistent gating: extraction accepts `[UPLOAD_COMPLETE, TOPIC_EXTRACTION (resume), FAILED, NEEDS_REVIEW]`; post-sync stages filter by `guideline.status == APPROVED` but don't verify sync-level completion.
- **Topic extraction review-refine only runs at finalization time.** Principles say "review-refine wherever possible"; extraction itself is a single pass.

### Nits / Clarifications

- **Claude Code adapter usage is conditional on provider config.** `LLMService._call_claude_code` dispatches when `provider == "claude_code"` is set in admin config. Works correctly — worth documenting in principles that the cost principle depends on provider being set to `claude_code`.

## Recommendations (Priority Order)

1. **Update principles doc** to include stages 7 (check-ins) and 8 (practice bank) — or clarify the doc covers "any post-sync LLM stage."
2. **Add `review_rounds` param to visual enrichment** — mirror the pattern in `generate_explanations`/check-ins/practice bank.
3. **Add stage-snapshot collection to visual enrichment** — port the `stage_collector` pattern from `explanation_generator_service.py`.
4. **Formalize retry-failed-job semantics** — either: (a) document that `force=false` is retry and add partial-state cleanup to each service, or (b) add an explicit `retry` endpoint per stage that targets only failed/pending items.
5. **Centralize stage gating** in a helper (e.g. `require_prior_stage_complete(chapter, stage)`) rather than per-endpoint status checks.
6. **Extract finalization UI** out of `TopicsAdmin` — either its own page or a dedicated section with status + trigger controls.

## Corrections to Initial Agent Report

The first-pass exploration agent had several factual errors that manual spot-checking caught. Listed here so they aren't propagated:

| Agent claimed | Reality |
|---------------|---------|
| "Visual Enrichment admin page missing" | `VisualsAdmin.tsx` is routed at `/admin/books-v2/:bookId/visuals/:chapterId` (`App.tsx:160`) and linked from `BookV2Detail.tsx:991`. |
| "Claude Code adapter never called in V2 pipeline" | `LLMService._call_claude_code` dispatches correctly when provider config is `claude_code`. V2 services call LLMService, which routes through the adapter. |
| "Retry failed job mode completely missing" | OCR has explicit `ocr_retry` for pending/failed pages (`processing_routes.py:200`). Post-sync stages use `force=false` as implicit retry. Gap is narrower than originally reported. |
| "review_rounds only exposed for explanations" | Also exposed for check-ins and practice bank. Missing only in visual enrichment. |
