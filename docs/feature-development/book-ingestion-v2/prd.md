# PRD: Book Ingestion V2 — Chapter-Aware Pipeline

**Date:** 2026-03-02
**Status:** Draft
**Author:** PRD Generator + Manish

---

## 1. Problem Statement

The current book ingestion pipeline treats a book as a flat sequence of pages. It processes pages one at a time, detects topic and subtopic boundaries using AI, and produces teaching guidelines at the subtopic level. This approach has three problems:

1. **No chapter awareness.** Real textbooks are organized by chapters, but the pipeline ignores this structure. The AI must figure out topic boundaries from scratch on every page, which produces inconsistent groupings and occasionally splits or merges content that the textbook author deliberately separated.

2. **Slow processing.** Each page requires its own LLM call for boundary detection and guideline extraction (~4-5 LLM calls per page). A 200-page book means ~800-1000 LLM calls, taking 30-60 minutes. Batching multiple pages per call would significantly reduce cost and processing time.

3. **Missing chapter-level context.** The tutor needs to know what order to cover topics within a chapter, and what the chapter is about at a high level. The current pipeline produces topic/subtopic-level outputs but no chapter-level summary or topic sequencing within a chapter's pedagogical context.

---

## 2. Goal

Admins can define a book's chapter structure via a Table of Contents, upload pages per chapter with completion tracking, and process chapters independently — producing chapter summaries with topic ordering and per-topic guidelines with study plans, all with ~3x fewer LLM calls.

---

## 3. User Stories

- As an **admin**, I want to enter a book's Table of Contents (chapter names + page ranges) when creating a book, so that the system knows the book's structure before I upload pages.
- As an **admin**, I want to select a chapter and upload its pages, with the system tracking which pages are uploaded vs missing, so that I know when a chapter is ready for processing.
- As an **admin**, I want to see per-chapter upload progress (e.g., "8 of 12 pages uploaded for Chapter 1") so that I know exactly what's still needed.
- As an **admin**, I want to trigger processing for a single chapter independently, so that I don't have to wait for the entire book's pages to be uploaded.
- As an **admin**, I want the system to process pages in batches of 3 instead of one at a time, so that processing is faster and cheaper.
- As an **admin**, I want the system to produce a chapter summary and a pedagogical ordering of topics within each chapter, so that the tutor knows the chapter's purpose and the right sequence to teach topics.
- As an **admin**, I want the system to produce per-topic guidelines and study plans (same quality as today's per-subtopic outputs), so that the tutor has detailed teaching material.

---

## 4. Functional Requirements

### 4.1 Table of Contents (ToC) Management

- **FR-1:** When creating a book, the admin MUST be able to enter a Table of Contents consisting of one or more chapters, each with a chapter name and a page range (start page, end page) using the book's **printed page numbers**.
- **FR-2:** The system MUST compute the total pages per chapter from the page range (e.g., pages 5-16 = 12 pages) and the total pages for the book from all chapter ranges.
- **FR-3:** The system MUST validate that chapter page ranges do not overlap and are in ascending order.
- **FR-4:** The admin SHOULD be able to edit the ToC after book creation (add, remove, or modify chapters) as long as no processing has started for affected chapters.
- **FR-5:** The ToC MUST be stored as part of the book's metadata (in S3 `metadata.json` and/or the database).

### 4.2 Chapter-Aware Page Upload

- **FR-6:** The admin MUST select a chapter from the ToC before uploading pages for that chapter.
- **FR-7:** When uploading pages for a chapter, page numbers MUST be automatically assigned starting from the chapter's start page in the ToC, based on upload order within the chapter.
- **FR-8:** The system MUST track per-chapter upload completeness: how many pages are uploaded out of the total expected (derived from the ToC page range).
- **FR-9:** The UI MUST display per-chapter progress, e.g., "8 of 12 pages uploaded for Chapter 1", and indicate which specific page numbers are still missing.
- **FR-10:** Both single-page and bulk upload flows MUST work within the chapter context. Bulk upload uploads multiple pages for the selected chapter at once.
- **FR-11:** The admin MUST be able to view pages organized by chapter, with chapter headers and progress indicators.

### 4.3 Three-Page Batch Processing

- **FR-12:** When processing a chapter, the system MUST group pages into batches of 3 consecutive pages.
- **FR-13:** The last batch of a chapter MAY have fewer than 3 pages (1 or 2). The system MUST handle this naturally without special casing.
- **FR-14:** Each batch MUST be processed in a single LLM call that receives all pages' OCR text together and performs boundary detection + guideline extraction for the entire batch at once.
- **FR-15:** The batch LLM call MUST return, for each page in the batch: whether it starts a new topic or continues an existing one, the topic key/title, and extracted guidelines.
- **FR-16:** Context building MUST include: recent page summaries (from previous batches), all open topic guidelines, book/chapter metadata, and ToC hints (current chapter, position within chapter).

### 4.4 Per-Chapter Processing

- **FR-17:** The admin MUST be able to trigger processing for a single chapter independently, without requiring all chapters to have their pages uploaded.
- **FR-18:** Processing a chapter MUST be gated on chapter completeness — all pages for that chapter (per ToC) MUST be uploaded before processing can start.
- **FR-19:** Each chapter processing job runs as a background job with progress tracking (same infrastructure as current pipeline: `BookJob`, heartbeat, polling).
- **FR-20:** Multiple chapters MUST NOT be processed concurrently for the same book (one active job per book, same as current constraint).
- **FR-21:** Processing MUST be resumable — if processing fails mid-chapter, the admin can resume from the last successfully processed batch.

### 4.5 Chapter-Level Outputs

- **FR-22:** During chapter processing, the system MUST incrementally build a **chapter summary** (2-4 sentences) that describes what the chapter covers, updated as each batch is processed.
- **FR-23:** During chapter processing, the system MUST track the **topic ordering** — the sequence in which topics appear in the chapter, based on the page order in which they are first encountered.
- **FR-24:** During finalization (per-chapter), the chapter summary MUST be refined using the complete set of topics and their guidelines.
- **FR-25:** During finalization (per-chapter), the topic ordering MUST be refined into a **pedagogical sequence** — the recommended teaching order — which may differ from the page-appearance order if the LLM determines a better pedagogical flow.

### 4.6 Simplified Hierarchy: Chapter → Topic

- **FR-26:** V2 eliminates the subtopic level. The hierarchy is: **Book → Chapter → Topic**. What was previously a "subtopic" is now a "topic". What was previously a "topic" is now a "chapter" (defined by the ToC).
- **FR-27:** Each topic MUST have: a `topic_key`, `topic_title`, `topic_summary`, `guidelines` (teaching content), `source_page_start`, `source_page_end`, and belong to exactly one chapter.
- **FR-28:** A topic MUST NOT span multiple chapters. If similar content appears in different chapters, they are separate topics.
- **FR-29:** Guidelines and study plans MUST be generated at the **topic** level (one guideline + one study plan per topic).

### 4.7 Finalization

- **FR-30:** Finalization MUST run in two passes:
  1. **Per-chapter pass:** Topic name refinement, deduplication of topics within the chapter, topic sequencing within the chapter, chapter summary refinement.
  2. **Book-level pass:** Chapter ordering (pedagogical sequence of chapters), cross-chapter naming consistency check.
- **FR-31:** The admin MUST be able to trigger finalization per-chapter (for the per-chapter pass) after that chapter's processing is complete.
- **FR-32:** The admin MUST be able to trigger a book-level finalization pass after all desired chapters have been individually finalized.
- **FR-33:** Finalization runs as a background job with progress tracking (same as current).

### 4.8 Database Sync & Review

- **FR-34:** After finalization, the admin MUST be able to sync a chapter's guidelines to the production database (same sync patterns as current: full snapshot or upsert).
- **FR-35:** Synced guidelines MUST include the `chapter_key`, `chapter_title`, `chapter_sequence`, `topic_sequence` (within chapter), and `chapter_summary` fields.
- **FR-36:** The existing review workflow (approve/reject individual guidelines) MUST continue to work, now with chapter context visible.

---

## 5. UX Requirements

- **UX-1:** The ToC entry interface MUST allow the admin to add chapters one at a time, each with a name, start page, and end page. It SHOULD support reordering and deleting chapters before saving.
- **UX-2:** The book detail page MUST show chapters as an accordion or list, each showing: chapter name, page range, upload progress (X of Y pages), and processing status (not started / processing / processed / finalized).
- **UX-3:** When the admin selects a chapter, the page upload panel MUST scope to that chapter and show which page numbers are still missing.
- **UX-4:** The chapter processing button MUST be disabled with a clear message when the chapter is incomplete (e.g., "Upload 4 more pages to process this chapter").
- **UX-5:** During processing, the progress UI MUST show batch-level progress (e.g., "Processing batch 3 of 6 — pages 11-13").
- **UX-6:** After processing, the chapter view MUST show extracted topics in their pedagogical order with the chapter summary at the top.
- **UX-7:** The guidelines review screen MUST group guidelines by chapter and display them in topic sequence order within each chapter.

---

## 6. Technical Considerations

### Integration Points

- **Backend modules affected:** `book_ingestion` (major: new chapter layer, batch processing, ToC management), `study_plans` (minor: topic-level instead of subtopic-level), `shared` (entities, DB migration)
- **Database changes:**
  - New `book_chapters` table (chapter metadata, sequence, summary)
  - Modify `teaching_guidelines`: add `chapter_id` FK, `chapter_sequence`, `topic_sequence`; deprecate `subtopic_key`, `subtopic_title`, `subtopic_summary` columns
  - Migration for new columns and table
- **API endpoints:**
  - New: `POST/PUT/DELETE /admin/books/{id}/chapters` (ToC CRUD)
  - New: `POST /admin/books/{id}/chapters/{chapter_id}/generate-guidelines` (per-chapter processing)
  - New: `POST /admin/books/{id}/chapters/{chapter_id}/finalize` (per-chapter finalization)
  - New: `POST /admin/books/{id}/finalize` (book-level finalization pass)
  - Modified: Page upload endpoints scoped to chapter
  - Modified: Book detail endpoint returns chapter structure + per-chapter progress
- **Frontend screens:**
  - Modified: `CreateBook.tsx` — add ToC entry form
  - Modified: `BookDetail.tsx` — chapter-based layout with per-chapter progress and actions
  - Modified: `PageUploadPanel.tsx` — chapter-scoped upload
  - Modified: `GuidelinesPanel.tsx` — chapter-grouped guidelines view
  - Modified: `GuidelinesReview.tsx` — chapter-grouped review
  - Modified: `BooksDashboard.tsx` — chapter count / progress in book list

### Architecture Notes

**New entity: Chapter.** Chapters become a first-class entity with their own database table (`book_chapters`) and S3 directory structure. This is the cleanest approach since chapters have their own lifecycle (upload tracking, processing, finalization).

**Batch processing service.** The existing `BoundaryDetectionService` processes one page per LLM call. V2 introduces a new `BatchBoundaryDetectionService` (or modifies the existing one) to handle 3 pages per call. The prompt template must be redesigned to accept multiple pages and return per-page decisions.

**Chapter-scoped S3 structure:**
```
books/{book_id}/
  metadata.json                         # Book metadata + ToC
  chapters/
    {chapter_key}/
      metadata.json                     # Chapter metadata + summary
      pages/
        {page_num:03d}.png              # Page images
        {page_num:03d}.txt              # OCR text
        {page_num:03d}.page_guideline.json
      guidelines/
        index.json                      # Topics registry for this chapter
        topics/
          {topic_key}.latest.json       # Topic guideline shard
```

**Context pack changes.** The context pack builder must be chapter-aware: it only includes topics and recent pages from the current chapter. Cross-chapter context is not needed since topics don't span chapters.

**Guideline model simplification.** The `SubtopicShard` model is renamed/refactored to `TopicShard` (dropping the subtopic concept). Fields like `subtopic_key`, `subtopic_title`, `subtopic_summary` become `topic_key`, `topic_title`, `topic_summary`. The `GuidelinesIndex` is similarly simplified.

### New Database Table

**`book_chapters`**

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `book_id` | VARCHAR | FK → books (CASCADE delete) |
| `chapter_key` | VARCHAR | Slugified chapter identifier |
| `chapter_title` | VARCHAR | Human-readable chapter name (from ToC) |
| `chapter_sequence` | INT | Order in the book (1-indexed, from ToC) |
| `page_start` | INT | Start page (printed page number) |
| `page_end` | INT | End page (printed page number) |
| `total_pages` | INT | Computed: page_end - page_start + 1 |
| `uploaded_pages` | INT | Count of uploaded pages (default 0) |
| `chapter_summary` | TEXT | AI-generated chapter summary (nullable) |
| `processing_status` | VARCHAR | `not_started`, `processing`, `processed`, `finalized` |
| `created_at` | DATETIME | Timestamp |
| `updated_at` | DATETIME | Timestamp |

**Indexes:** `idx_book_chapters_book` (book_id), unique `(book_id, chapter_key)`

---

## 7. Impact on Existing Features

| Feature | Impact | Details |
|---------|--------|---------|
| Book ingestion pipeline | **Major** | Restructured around chapters. Batch processing replaces per-page. Hierarchy simplified to Chapter → Topic. |
| Guideline extraction | **Major** | New batch boundary detection (3 pages per call). Context packs scoped to chapter. |
| Finalization | **Major** | Two-pass finalization (per-chapter + book-level). Chapter summary generation added. |
| DB sync | **Moderate** | New chapter fields mapped. Chapter table synced. |
| Guidelines review (admin) | **Moderate** | Guidelines grouped by chapter. Topic sequence visible. |
| Study plan generation | **Minor** | Now generates at topic level (was subtopic). Same generation logic. |
| Student topic/subtopic navigation | **Moderate** | Navigation becomes Subject → Chapter → Topic (was Subject → Topic → Subtopic). |
| Tutor sessions | **Minor** | Sessions now reference topics (not subtopics). Guidelines content unchanged. |
| Evaluation | **Minor** | Sessions reference topics. Evaluation logic unchanged. |
| Scorecard / Report Card | **Minor** | Progress tracked at topic level within chapters. |
| Auth & onboarding | None | No changes. |

---

## 8. Edge Cases & Error Handling

| Scenario | Expected Behavior |
|----------|-------------------|
| Chapter has only 1 page | Single page processed as a batch of 1. Works naturally. |
| Chapter has exactly 3 pages | One batch of 3. No special handling. |
| Chapter has 0 pages uploaded | Processing button disabled. Message: "Upload all X pages to process this chapter." |
| Admin uploads duplicate page number | System rejects the upload with a clear error: "Page X already uploaded for this chapter." |
| Admin modifies ToC after pages uploaded | Only allow modifications to chapters that have no uploaded pages. Chapters with pages must have their pages deleted first. |
| Admin modifies ToC after processing | Block ToC modification for processed chapters. Must re-process if chapter structure changes. |
| Processing fails mid-batch | Job records last completed batch. Resume starts from the next batch. Pages within a failed batch are not partially processed. |
| A batch produces no new topics | Valid scenario (e.g., 3 pages all continue the same topic). Guidelines merged into existing topic. |
| A single page within a batch starts a new topic | The batch LLM call identifies the boundary within the batch and creates the new topic starting from that page. |
| Chapter with very few pages (1-2) | Processed as a single batch. Chapter summary may be brief. |
| Book with only 1 chapter | Works normally. Book-level finalization pass is minimal (chapter ordering is trivial). |
| Admin processes chapters out of order (Chapter 3 before Chapter 1) | Allowed. Each chapter is independent. Book-level finalization handles ordering. |
| Page image fails OCR | Same as current: per-page error tracking, retry option. Does not block batch processing of other pages. OCR must succeed for all pages before chapter processing starts. |

---

## 9. Out of Scope

- **Migration of existing V1 books** — Existing books without ToC are not migrated. Focus on V2 for new books.
- **Cross-chapter topics** — Topics are strictly scoped to one chapter. If similar content spans chapters, they become separate topics.
- **Automatic ToC extraction from book** — Admin manually enters the ToC. AI-powered ToC detection from scanned pages is future work.
- **Concurrent chapter processing** — Only one processing job per book at a time (same as current). Parallel chapter processing is future work.
- **Manual editing of guidelines** — Same as current: to change guidelines, re-run processing.
- **Chapter-level study plans** — Chapters have summaries and topic ordering, but no chapter-level study plan. Study plans are per-topic only.
- **Student-facing chapter navigation changes** — Frontend navigation changes (Subject → Chapter → Topic) will be specified in a follow-up PRD.

---

## 10. Open Questions

- **Batch prompt design:** The prompt for processing 3 pages simultaneously needs careful design and iteration. Key questions: How to format 3 pages clearly? How to handle topic boundaries that fall mid-batch? Initial prompt should be tested against 2-3 chapters and manually reviewed.
- **LLM cost comparison:** Batch processing should reduce calls by ~3x, but each call processes more tokens. Net cost savings should be measured on a real book.
- **Chapter summary quality:** Incremental summary generation (updated with each batch) may produce lower quality than a single post-processing pass. The finalization refinement step should address this, but testing is needed.
- **Minisummary in batch mode:** Currently, a minisummary is generated per page before boundary detection. With 3-page batches, should minisummaries still be per-page (separate calls) or folded into the batch call? Folding into the batch call further reduces LLM calls but increases batch call complexity.

---

## 11. Success Metrics

- **Processing speed:** ~3x reduction in LLM calls per chapter compared to V1 (measured on a 50-page chapter).
- **Chapter completeness tracking:** Admin can see per-chapter upload progress and knows exactly which pages are missing.
- **Chapter summary quality:** Admin reviews chapter summaries for 3+ books and confirms they accurately describe the chapter content.
- **Topic ordering quality:** Admin reviews topic ordering for 3+ chapters and confirms >90% of topics are in a reasonable pedagogical sequence.
- **End-to-end workflow:** Admin can process a full book (create → ToC → upload → process → finalize → sync) in under 60 minutes of active work for a 200-page book.
- **No regression:** Topic-level guidelines and study plans are at least as good as current subtopic-level outputs.
