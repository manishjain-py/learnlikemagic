# Principles: Book Ingestion Pipeline

Operational principles for the multi-stage pipeline that turns raw textbook pages into teachable topics.

## Pipeline Stages

1. **Page Upload + OCR** — upload page images, convert to PNG, extract text via vision LLM
2. **Topic Extraction** — plan chapter topics, then chunk pages and extract draft topics + guidelines via LLM
3. **Finalization** — merge per-chunk guidelines, consolidate/dedup/reorder topics, generate curriculum context
4. **Sync** — write finalized topics to teaching guidelines DB
5. **Explanation Generation** — pre-compute explanation card sets per topic (generate → review-refine)
6. **Visual Enrichment** — decide which explanation cards need visuals, generate PixiJS code for interactive animations

## 1. Heavy Stages Run as Background Jobs

Any stage that calls an LLM or processes multiple items must run as a background job — never inline in an API request. Stages 1 (bulk OCR), 2, 3, 5, and 6 qualify. Stage 4 (sync) is fast enough to run synchronously.

## 2. Every Background Job Has: Progress, Retry, Rerun

Each background job must support:
- **Progress tracking** — heartbeat + completed/failed/total counts, polled by the frontend
- **Retry** — re-process only failed/pending items without touching successful ones
- **Rerun** — wipe all results and re-process from scratch

## 3. Job State Machine

All jobs follow: `pending → running → completed | completed_with_errors | failed`. Stale detection auto-fails jobs whose heartbeat exceeds the threshold. Only one active job (pending/running) per chapter at a time, enforced by lock acquisition.

## 4. Session Isolation for Background Tasks

Background tasks run in their own DB session on a daemon thread. The task function receives the background session as its first argument and rebinds all repositories/services to it. The API handler's session is never shared across threads.

## 5. Stages Gate on Prior Stage Completion

Each stage requires the prior stage to be complete before it can start. Topic extraction requires `upload_complete`; finalization requires extraction done; sync requires `chapter_completed` or `needs_review`; explanation generation requires sync; visual enrichment requires explanations to exist. OCR jobs are allowed during `upload_in_progress` or `upload_complete`.
