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
4. Admins review and approve guidelines
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

A pages sidebar lets you navigate between pages and see their status.

---

## Generating Guidelines

Once pages are uploaded and reviewed:

1. **Start extraction** — Choose a page range and trigger guideline generation
2. The system processes each page in sequence:
   - Summarizes the page content
   - Detects whether the page starts a new topic/subtopic or continues an existing one
   - Extracts teaching guidelines from the page
   - Merges new content with existing guidelines for the same subtopic
3. **Finalize** — Refines topic/subtopic names, deduplicates similar content, and regenerates summaries

### How Topic Detection Works

The AI reads each page in context of recent pages and decides:
- Is this page continuing the current topic? → Merge content into the existing guideline
- Is this page starting something new? → Create a new guideline

A subtopic is considered "stable" when 5 pages pass without any updates to it.

---

## Reviewing & Approving Guidelines

After generation, guidelines go through a two-level review:

### Book-Level Approval
1. View all generated guidelines for a book
2. Approve the entire set → This syncs guidelines to the production database

### Individual Guideline Review
1. Browse guidelines with filters (country, board, grade, subject, review status)
2. Review each guideline's content
3. Approve or send back for re-review

Only approved guidelines become available for tutoring sessions.

---

## Study Plan Generation

After a guideline is approved, a study plan can be generated:

1. **Generate** — AI creates an initial study plan
2. **AI Review** — A second AI reviews the plan and provides feedback
3. **Improve** — The plan is refined based on feedback

Study plans define the step-by-step teaching sequence (explain → check → practice) that the tutor follows during sessions.

Study plans can be generated individually or in bulk for multiple guidelines at once.

---

## Key Details

- Each guideline maps to one subtopic within a topic
- Guidelines contain comprehensive teaching content in a single text field (not structured fields)
- Book status is derived from the current state: no pages, ready for extraction, processing, pending review, or approved
- The pipeline uses lightweight AI models for cost-effective processing
- Pages are stored in cloud storage; guidelines are stored in both cloud storage (as JSON) and the production database
