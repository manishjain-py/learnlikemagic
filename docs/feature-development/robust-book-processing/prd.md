# PRD: Robust Book Processing Pipeline

**Status:** Draft
**Date:** 2026-02-27

---

## 1. Problem Statement

The book ingestion pipeline — where admins upload textbook pages, run OCR, and generate teaching guidelines — is fragile in ways that make it impractical for real use with books of any significant size.

**Three core problems:**

### 1.1 Guidelines Generation Dies Mid-Process

Today, when an admin clicks "Generate Guidelines," the backend processes every page sequentially inside a single HTTP request. For a 100-page book with ~4-5 LLM calls per page, this takes 30-60 minutes. The backend runs on AWS App Runner, which has HTTP request timeouts. The request **will** time out for any book with more than a handful of pages.

Even if it didn't time out: if the admin closes their browser tab, the HTTP connection drops and processing stops. There's no way to know which pages were processed before it died, and no way to resume from that point.

The infrastructure for background jobs already exists in the codebase (`BookJob` table, `JobLockService`) but is **not actually used** by the guidelines generation or finalization endpoints.

### 1.2 Page Upload is Painfully Manual

Admins must upload pages one at a time: select a file → wait 10-15 seconds for OCR → review the OCR text → approve or reject → repeat. For a 100-page textbook, this is 1-2 hours of active, tedious clicking.

There is no bulk upload capability. The frontend has a single-file input. The backend processes one image per request with OCR happening synchronously inline.

### 1.3 No Visibility Into What's Happening

During guidelines generation, the UI shows "Generating..." with no progress indicator. The admin has no idea if page 5 or page 95 is being processed. If they leave and come back, there's no way to see that a job is running or where it is.

For OCR, since it's one page at a time, "progress" is implicit — but there's no dashboard showing which pages have OCR done, which are pending, or which failed.

---

## 2. Solution Overview

Three capabilities that work together:

| Capability | What It Solves |
|-----------|----------------|
| **Background job processing with progress tracking** | Guidelines generation and finalization run independently of the HTTP request. Admin can start the process and leave. Progress is tracked per-page in the database. |
| **Resume from failure** | If processing fails at page 50 of 100, admin sees exactly where it stopped and why, and can click "Resume" to continue from page 51. |
| **Bulk page upload with background OCR** | Admin selects 100 images at once. They upload to S3 quickly. OCR runs in the background page by page. Admin sees per-page OCR status (pending / processing / completed / failed). |

**Design principle:** The admin should be able to kick off a long-running operation, close their laptop, come back hours later, and see exactly what happened — what succeeded, what failed, and how to proceed.

---

## 3. Background Guidelines Generation

### 3.1 Current Flow (Broken)

```
Admin clicks "Generate" → HTTP request blocks for 30-60 minutes → Times out or drops
```

### 3.2 New Flow

```
Admin clicks "Generate"
  → Backend creates a job record in the database
  → Backend starts processing in a background thread
  → API returns immediately with job_id
  → Frontend polls for progress every few seconds
  → Admin sees: "Processing page 45 of 100 (45%)"
  → Admin can leave and come back — progress persists
  → On completion: admin sees full stats
  → On failure: admin sees error + "Resume from page X" button
```

### 3.3 What the Admin Sees During Processing

```
┌───────────────────────────────────────────────┐
│  Generating Guidelines                        │
│                                               │
│  ████████████████░░░░  78/100 pages (78%)     │
│  Currently processing: Page 79                │
│  Subtopics found so far: 14                   │
│  Failed pages: 1                              │
│  Elapsed: 12m 34s                             │
│                                               │
│  ⚠ You can leave this page — processing       │
│  continues in the background.                 │
└───────────────────────────────────────────────┘
```

### 3.4 What the Admin Sees After Failure

```
┌───────────────────────────────────────────────┐
│  ⚠ Generation stopped at page 78/100          │
│  Error: OpenAI API rate limit exceeded        │
│                                               │
│  Pages completed: 77                          │
│  Pages failed: 1 (page 78)                    │
│  Pages remaining: 22                          │
│                                               │
│  [Resume from Page 78]  [Restart from Page 1] │
└───────────────────────────────────────────────┘
```

### 3.5 Finalization Gets the Same Treatment

The "Refine & Consolidate" step (topic name refinement, deduplication) also runs as a background job with the same progress tracking pattern.

---

## 4. Resume from Failure

### 4.1 How It Works

Every page that completes successfully is recorded in the job progress. When a job fails:

1. The `last_completed_item` field records the last page that finished successfully
2. The `progress_detail` JSON records per-page errors (which page failed and why)
3. The admin sees a clear summary: what succeeded, what failed, where to resume

When the admin clicks "Resume":
- A new job is created starting from `last_completed_item + 1`
- Existing guidelines from already-processed pages are preserved (they're already saved to S3)
- Processing continues for remaining pages

### 4.2 Per-Page Error Visibility

The admin can see errors for individual pages:

```
Page 45: ✅ Completed — topic: "fractions", subtopic: "adding-like-fractions"
Page 46: ❌ Failed — "OpenAI rate limit exceeded after 3 retries"
Page 47: ✅ Completed — topic: "fractions", subtopic: "subtracting-fractions"
...
```

This is especially useful for identifying patterns (e.g., all failures are rate limits → wait and resume; or a specific page's OCR text is malformed → fix that page and resume).

---

## 5. Bulk Page Upload with Background OCR

### 5.1 Current Flow (Tedious)

```
For each of 100 pages:
  Select file → Upload → Wait 10-15s for OCR → Review → Approve → Repeat
  Total: ~1-2 hours of active clicking
```

### 5.2 New Flow

```
Admin selects 100 images (multi-file picker or drag-and-drop)
  → All images upload to S3 quickly (just file transfer, no OCR yet)
  → OCR job starts in background
  → Admin sees per-page OCR status updating in real-time
  → Admin can review and approve completed pages while OCR continues on remaining pages
  Total: ~2 minutes of active work + passive background processing
```

### 5.3 What the Admin Sees

```
┌─────────────────────────────────────────────┐
│  Upload Pages                               │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  📁 Drag & drop page images here    │    │
│  │  or click to select multiple files  │    │
│  │                                     │    │
│  │  PNG, JPG, TIFF, WebP (max 10MB)   │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  Selected: 85 images                        │
│  [Upload All & Start OCR]                   │
│                                             │
│  ── OCR Progress ──────────────────────     │
│  ████████████░░░░░░░░  45/85 (53%)          │
│  Currently processing: Page 46              │
│  Failed: 2 pages                            │
│                                             │
│  Page 1  ✅ OCR Complete                    │
│  Page 2  ✅ OCR Complete                    │
│  ...                                        │
│  Page 23 ❌ Failed — Rate limit  [Retry]    │
│  ...                                        │
│  Page 46 ⏳ Processing...                   │
│  Page 47 ⬜ Pending                         │
│  ...                                        │
└─────────────────────────────────────────────┘
```

### 5.4 Per-Page OCR Status

Each page has an OCR status visible in the sidebar:

| Status | Icon | Meaning |
|--------|------|---------|
| Pending | ⬜ Gray | Image uploaded, OCR not started |
| Processing | ⏳ Spinner | OCR currently running |
| Completed | ✅ Green | OCR done, text available for review |
| Failed | ❌ Red | OCR failed (with retry button) |

### 5.5 Reviewing OCR Results

After OCR completes for a page, the admin can click on it to see the side-by-side image + OCR text view (same as today's single-upload flow) and approve or reject. This can happen while OCR is still running on later pages.

### 5.6 Individual OCR Retry

If OCR fails for a specific page (e.g., rate limit, malformed image), the admin can retry just that page without re-uploading the image. The image is already in S3 — only the OCR step needs to re-run.

### 5.7 Single-Page Upload Preserved

The existing single-page upload flow is kept alongside the bulk upload. It's useful for adding or replacing individual pages after the initial bulk upload.

---

## 6. Job Status on Return

When an admin navigates to a book's detail page, the system checks for any active jobs:

- **If an extraction job is running:** Show the progress UI immediately (no need to re-trigger)
- **If an OCR job is running:** Show per-page OCR status with progress bar
- **If the last job failed:** Show the failure summary with resume option
- **If the last job completed:** Show the completion stats

This means the admin can close the browser, reopen it later, and see exactly where things stand.

---

## 7. What Does NOT Change

| Area | Impact |
|------|--------|
| **Core extraction logic** | The orchestrator, boundary detection, guideline merge, summaries, and deduplication logic stay exactly the same. Only the execution wrapper changes (HTTP-bound → background thread). |
| **S3 storage structure** | Same directory layout, same file formats. |
| **Database schema** | `teaching_guidelines`, `books`, `book_guidelines` tables unchanged. Only `book_jobs` gets enhanced with progress columns. |
| **Guidelines review workflow** | Approve, reject, sync to DB — all unchanged. |
| **Study plan generation** | Unchanged. |
| **Teaching/tutoring** | Unchanged. |
| **Authentication** | Unchanged. |

---

## 8. Key Design Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| **Background threads on provisioned App Runner (not Celery/SQS)** | This is a single-tenant admin tool. Adding message queue infrastructure (Redis, SQS, Celery workers) adds significant operational overhead. Threading + database-tracked progress is the right complexity level. **Requires:** App Runner must use provisioned instances (not request-driven CPU), so background threads get continuous CPU. Cost: ~$25/mo for one always-on instance — acceptable for an admin tool. |
| **Database-tracked progress with heartbeat** | Progress must survive page reloads and container restarts. The `book_jobs` table already exists — we enhance it with progress columns + a `heartbeat_at` timestamp. If the container dies, the server detects stale heartbeats and auto-marks the job as failed with resume instructions. |
| **Lightweight request path, heavy background path** | The HTTP request only does fast work (validation, stream raw files to S3). All heavy work (image conversion, OCR, guideline extraction) runs in background threads. This prevents request timeouts and OOM on large batches. |
| **Polling (not WebSockets)** | The admin panel already uses request-response patterns everywhere. Adding WebSocket infrastructure for one feature isn't worth the complexity. Polling every 3-5 seconds is perfectly adequate for a progress bar. |
| **S3 upload first, OCR second** | S3 uploads are fast (~200ms per raw image). OCR is slow (~10s per page). By separating them, we get all images stored durably in seconds, then conversion + OCR runs at its own pace. If OCR fails, the images are safe and OCR can be retried. |
| **Per-page error granularity with error taxonomy** | A bulk "failed" status isn't useful. Each page error is classified as `retryable` (rate limit, timeout) or `terminal` (corrupt data, empty OCR). This lets the admin make an informed decision: wait and retry, fix the image, or skip it. |
| **Keep single-page upload** | Bulk upload is for initial book loading. Single-page upload remains useful for corrections, replacements, or adding pages after initial upload. Blocked during bulk OCR (409) to prevent metadata.json write conflicts. |
