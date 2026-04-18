# Principles: Book Ingestion Pipeline

Operational principles for the multi-stage pipeline that turns raw textbook pages into teachable topics.

## Goal: Great Quality Content

Use the best model, max effort. Initial generation + N review-refine rounds wherever possible. Quality over speed — these are **offline pipelines, can take as long as needed**.

## Cost Discipline

Use Claude Code (subprocess) for LLM work — direct API calls are way too expensive at this volume. All LLM calls route through `LLMService`, which dispatches to Claude Code when the admin-configured provider is `claude_code`. Keep the provider set accordingly in prod.

## Pipeline Stages

1. **Page Upload + OCR** — upload page images, convert to PNG, extract text via vision LLM
2. **Topic Extraction** — plan chapter topics, then chunk pages and extract draft topics + guidelines via LLM
3. **Finalization** — merge per-chunk guidelines, consolidate/dedup/reorder topics, generate curriculum context
4. **Sync** — write finalized topics to teaching guidelines DB
5. **Explanation Generation** — pre-compute explanation card sets per topic (generate → review-refine)
6. **Visual Enrichment** — decide which explanation cards need visuals, generate PixiJS code for interactive animations
7. **Check-in Enrichment** — generate interactive check-in activities at concept boundaries inside explanation cards (11 activity types, light+heavy pairs, review-refine)
8. **Practice Bank Generation** — generate per-topic practice question banks (30-40 questions across 12 formats, review-refine, structural validation, top-up)

Stages 7 and 8 are decoupled — both consume explanations and can run in parallel. Stage 7 can optionally wait for stage 6 (visuals) if check-ins reference visual content.

## 1. Heavy Stages Run as Background Jobs

Any stage that calls an LLM or processes multiple items must run as a background job — never inline in an API request. Stages 1 (bulk OCR), 2, 3, 5, 6, 7, and 8 qualify. Stage 4 (sync) is fast enough to run synchronously.

## 2. Every Stage Has an Admin UI Page

Each stage gets a **separate admin page** with:
- **Latest stage status** visible (e.g. "generated / not generated" for explanations).
- **Live job tracking** — heartbeat + completed/failed/total counts; state persists across browser close/revisit.
- **View generated content.**
- **Four trigger modes:**
  - **Generate** — produce from nothing.
  - **Regenerate (rerun)** — wipe existing results and generate again.
  - **Review-refine N rounds** — N review-refine passes over existing content. **N configurable per trigger.**
  - **Retry failed job** — re-process only failed/pending items; partial state from the failed run is cleaned up so the retrigger is safe.

## 3. Job State Machine

All jobs follow: `pending → running → completed | completed_with_errors | failed`. Stale detection auto-fails jobs whose heartbeat exceeds the threshold. Only one active job (pending/running) per chapter at a time, enforced by lock acquisition.

## 4. Session Isolation for Background Tasks

Background tasks run in their own DB session on a daemon thread. The task function receives the background session as its first argument and rebinds all repositories/services to it. The API handler's session is never shared across threads.

## 5. Stages Gate on Prior Stage Completion

Each stage requires the prior stage to be complete before it can start. Topic extraction requires `upload_complete`; finalization requires extraction done; sync requires `chapter_completed` or `needs_review`; explanation generation requires sync; visual enrichment requires explanations to exist. OCR jobs are allowed during `upload_in_progress` or `upload_complete`.
