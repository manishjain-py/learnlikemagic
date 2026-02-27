# Book & Guidelines

This feature lets admins upload textbooks and extract teaching guidelines that power the AI tutor. The pipeline takes book pages and transforms them into structured guidelines and study plans.

---

## Overview

```
Book Pages → OCR Text → Teaching Guidelines → Study Plans
```

1. Upload a book's pages as images (individually or in bulk)
2. The system reads each page using AI (OCR)
3. AI detects topics and subtopics, then extracts teaching guidelines
4. Admins finalize, review, and approve guidelines
5. AI generates step-by-step study plans from approved guidelines

---

## Uploading a Book

1. **Create a book** — Enter the book's title, author, edition, edition year, grade, subject, board, and country
2. **Upload pages** — Two options:
   - **Single upload** — Drag and drop one page image at a time (PNG, JPG, JPEG, TIFF, or WebP, max 20MB each). OCR runs immediately and returns the extracted text.
   - **Bulk upload** — Upload up to 200 page images at once. Images are uploaded first, then image conversion and OCR run in the background. Files are sorted by filename to ensure correct page ordering.
3. Each uploaded page is automatically processed with OCR to extract text (with automatic retry on failure)

Single-page uploads are blocked while a bulk OCR job is in progress to prevent data conflicts.

---

## Page OCR & Approval

After uploading, each page shows:
- The original page image (all formats are converted to PNG for consistency)
- The extracted text from OCR

For bulk uploads, pages may initially show OCR as "pending" or "processing" while background OCR is running. Pages that fail OCR show an error status and can be retried individually.

Admins can:
- **Approve** pages where the OCR looks correct
- **Retry OCR** for individual pages that failed during bulk processing
- **Delete** pages where the OCR is unusable or the page isn't needed (remaining pages are automatically renumbered)

A pages sidebar lets you navigate between pages and see their status. Clicking an approved page opens a view panel showing the image alongside the OCR text.

---

## Background Jobs & Progress

Extraction, finalization, and bulk OCR are long-running operations that run in the background. When one of these operations starts:

1. The system returns immediately with a job ID
2. The admin UI polls for progress every 3 seconds, showing:
   - Current page being processed
   - Pages completed and pages failed
   - Error details for individual page failures
3. Only one operation can run on a book at a time (the system prevents concurrent jobs)
4. If a background job is interrupted (e.g., server restart), it is automatically detected via heartbeat monitoring and marked as failed

If extraction fails partway through, it can be **resumed** from the last successfully processed page rather than restarting from the beginning.

---

## Generating Guidelines

Once pages are uploaded and reviewed:

1. **Start extraction** — Choose a page range and trigger guideline generation (runs in background)
2. The system processes each page in sequence:
   - Generates a detailed summary of the page content (5-6 lines)
   - Builds context from the 5 most recent page summaries and all open guidelines
   - Detects whether the page starts a new topic/subtopic or continues an existing one
   - Extracts teaching guidelines from the page in the same step as boundary detection
   - If continuing an existing subtopic, intelligently merges the new guidelines into the existing ones
   - Generates one-line summaries for each subtopic and topic
3. **Finalize** — A separate step that refines topic/subtopic names, deduplicates similar content, merges duplicate subtopics, and regenerates all topic summaries (also runs in background)

Extraction and finalization are separate actions. Progress can be monitored in real time. If extraction fails on individual pages, those errors are recorded but processing continues for remaining pages.

### How Topic Detection Works

The AI reads each page in context of recent pages and all existing guidelines, then decides:
- Is this page continuing the current topic? → Intelligently merge content into the existing guideline using AI
- Is this page starting something new? → Create a new guideline

A subtopic is considered "stable" when 5 pages pass without any updates to it.

### How Finalization Works

Finalization runs after all pages are extracted and performs these steps:
1. Marks all remaining open/stable subtopics as final
2. Refines topic and subtopic names using AI (based on complete guideline content)
3. Identifies duplicate subtopics using AI and merges them
4. Regenerates topic summaries to reflect final content
5. Optionally syncs to the production database

---

## Syncing to the Production Database

After finalization, guidelines must be synced to the production database before they become available for review and tutoring.

There are two ways to sync:

1. **Full snapshot sync** (recommended) — Deletes all previous guidelines for the book and inserts all current guidelines as new rows. All review statuses are reset to "to be reviewed." This is used by the dedicated sync action.
2. **Approve-and-sync** — Marks all non-final guidelines as final in the index, then syncs each guideline individually (upserts). This is used by the "approve all" action from the book detail view.

---

## Reviewing & Approving Guidelines

After syncing to the database, guidelines go through a two-level review:

### Book-Level Review
1. View all synced guidelines for a book
2. Filter by review status (to be reviewed, approved)

### Individual Guideline Review
1. Browse all guidelines across books with filters (country, board, grade, subject, review status)
2. See counts of total, pending, and approved guidelines
3. Review each guideline's content
4. Approve or reject individual guidelines (rejecting resets to "to be reviewed")
5. Delete guidelines that are not needed

Only approved guidelines become available for tutoring sessions.

---

## Study Plan Generation

After a guideline is synced to the database, a study plan can be generated:

1. **Generate** — AI creates an initial study plan with a structured todo list of 3-5 teaching steps
2. **AI Review** — A separate AI reviewer evaluates the plan's quality, providing a rating, feedback, and suggested improvements
3. **Improve** — If the reviewer does not approve, the plan is automatically refined based on the feedback (single revision pass)

Each study plan step includes a title, description, teaching approach, and success criteria. Plans include metadata such as estimated duration, difficulty level, and an optional creative theme.

Study plans can be generated individually or in bulk for multiple guidelines at once. The generator and reviewer can use different AI models and providers, configured independently in the admin settings. If a plan already exists, re-generation must be explicitly forced.

---

## Deleting a Book

Admins can delete a book entirely. This removes the book record from the database and all associated files from cloud storage (page images, OCR text, guideline shards, indexes).

---

## Key Details

- Each guideline maps to one subtopic within a topic
- Guidelines contain comprehensive teaching content in a single text field (natural language, not structured fields)
- Book status is derived at runtime from counts: page count, guideline count, approved guideline count, and whether an active job is running
- The AI model used for ingestion and study plan generation is configurable in the admin settings (not hardcoded)
- Pages are stored in cloud storage; guidelines are stored in both cloud storage (as JSON shards) and the production database
- Manual editing of guidelines is not supported; to change guidelines, re-run extraction and finalize
- If the study plan improvement step fails, the original plan is saved anyway
- Bulk uploads store raw images first, then convert and OCR in the background; individual uploads convert and OCR inline
- Background jobs use heartbeat monitoring to detect interrupted operations (e.g., server restarts) and automatically mark them as failed
