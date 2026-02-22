# Book & Guidelines

This feature lets admins upload textbooks and extract teaching guidelines that power the AI tutor. The pipeline takes book pages and transforms them into structured guidelines and study plans.

---

## Overview

```
Book Pages → OCR Text → Teaching Guidelines → Study Plans
```

1. Upload a book's pages as images
2. The system reads each page using AI (OCR)
3. AI detects topics and subtopics, then extracts teaching guidelines
4. Admins finalize, review, and approve guidelines
5. AI generates step-by-step study plans from approved guidelines

---

## Uploading a Book

1. **Create a book** — Enter the book's title, author, edition, grade, subject, board, and country
2. **Upload pages** — Drag and drop page images (PNG, JPG, JPEG, TIFF, or WebP, max 20MB each)
3. Each uploaded page is automatically processed with OCR to extract text

---

## Page OCR & Approval

After uploading, each page shows:
- The original page image
- The extracted text from OCR

Admins can:
- **Approve** pages where the OCR looks correct
- **Delete** pages where the OCR is unusable or the page isn't needed

A pages sidebar lets you navigate between pages and see their status. Clicking an approved page opens a view panel showing the image alongside the OCR text.

---

## Generating Guidelines

Once pages are uploaded and reviewed:

1. **Start extraction** — Choose a page range and trigger guideline generation
2. The system processes each page in sequence:
   - Generates a detailed summary of the page content (5-6 lines)
   - Builds context from the 5 most recent page summaries and all open guidelines
   - Detects whether the page starts a new topic/subtopic or continues an existing one
   - Extracts teaching guidelines from the page in the same step as boundary detection
   - If continuing an existing subtopic, intelligently merges the new guidelines into the existing ones
   - Generates one-line summaries for each subtopic and topic
3. **Finalize** — A separate step that refines topic/subtopic names, deduplicates similar content, merges duplicate subtopics, and regenerates all topic summaries

Extraction and finalization are separate actions. Only one operation can run on a book at a time (the system prevents concurrent jobs).

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

Syncing is a **full snapshot operation**: it deletes all previous guidelines for the book and inserts all current guidelines as new rows. All review statuses are reset to "to be reviewed" after each sync.

---

## Reviewing & Approving Guidelines

After syncing to the database, guidelines go through a two-level review:

### Book-Level Approval
1. View all generated guidelines for a book
2. Approve the entire set at once

### Individual Guideline Review
1. Browse guidelines with filters (country, board, grade, subject, review status)
2. Review each guideline's content
3. Approve or reject individual guidelines (rejecting resets to "to be reviewed")
4. Delete guidelines that are not needed

Only approved guidelines become available for tutoring sessions.

---

## Study Plan Generation

After a guideline is synced to the database, a study plan can be generated:

1. **Generate** — AI creates an initial study plan with a structured todo list of 3-5 teaching steps
2. **AI Review** — A separate AI reviewer evaluates the plan's quality, providing a rating, feedback, and suggested improvements
3. **Improve** — If the reviewer does not approve, the plan is automatically refined based on the feedback

Each study plan step includes a title, description, teaching approach, and success criteria. Plans include metadata such as estimated duration, difficulty level, and an optional creative theme.

Study plans can be generated individually or in bulk for multiple guidelines at once. The generator and reviewer can use different AI models and providers, configured independently in the system.

---

## Key Details

- Each guideline maps to one subtopic within a topic
- Guidelines contain comprehensive teaching content in a single text field (natural language, not structured fields)
- Book status is derived at runtime from counts: page count, guideline count, approved guideline count, and whether an active job is running
- The AI model used for ingestion and study plan generation is configurable in the admin settings (not hardcoded)
- Pages are stored in cloud storage; guidelines are stored in both cloud storage (as JSON shards) and the production database
- Manual editing of guidelines is not supported; to change guidelines, re-run extraction and finalize
