# Books and Teaching Guidelines

The Books and Teaching Guidelines system lets administrators ingest physical textbooks into the platform so the AI tutor can teach from them. An admin uploads a textbook chapter by chapter, the system extracts topics and generates teaching guidelines, and those guidelines become the knowledge base the tutor uses during learning sessions.

---

## What It Is

A textbook ingestion pipeline that turns scanned textbook pages into structured, topic-level teaching guidelines. The pipeline is chapter-first: each chapter is processed independently, and the output is a set of topics with detailed guidelines that tell the tutor how to teach each concept.

The end-to-end flow: **Create book -> Define chapters -> Upload pages -> Extract topics -> Sync to tutor**.

---

## How It Works

### 1. Create a Book

An admin creates a new book by entering metadata:
- **Title** (e.g., "Math Magic")
- **Author** (e.g., "NCERT")
- **Country**, **Board**, **Grade**, **Subject** (e.g., India, CBSE, Grade 3, Mathematics)
- **Edition** and **Edition Year** (optional)

The book appears on the V2 Books Dashboard with a chapter count and metadata summary.

### 2. Define the Table of Contents

The admin defines which chapters the book contains and what page range each chapter covers. There are two ways to do this:

- **Upload TOC Pages** -- Upload screenshots of the book's table of contents pages (up to 5 images). The system uses OCR and AI to extract chapters automatically. The admin reviews the results and can edit before saving.
- **Manual Entry** -- Type in chapter titles and page ranges by hand. Each chapter needs a sequential number, a title, a start page, and an end page.

Each chapter entry can also include optional **notes** (themes, subtopics, activities) that give the AI more context during topic extraction.

Validation rules:
- Chapter numbers must be sequential starting from 1
- Page ranges must be valid (start > 0, end >= start)
- Page ranges must not overlap between chapters
- Once pages are uploaded to a chapter, the TOC entry for that chapter is locked (delete pages first to unlock)

### 3. Upload Pages

For each chapter, the admin uploads scanned page images (PNG, JPG, JPEG, TIFF, or WEBP, up to 20 MB each). Pages are uploaded one at a time, and each page number must fall within the chapter's defined page range.

On upload, the system immediately runs OCR (optical character recognition) to extract the text from the image. The OCR focuses on educational content -- headings, body text, math problems, equations, questions, table data -- and ignores decorative elements like illustrations, mascots, and borders.

The admin can view any uploaded page to see the original image side by side with the extracted text. If OCR fails for a page, the admin can retry it. Pages can also be re-uploaded (delete and re-upload) if the original scan was poor.

A page grid shows upload progress visually: each page number appears as a small tile colored green (OCR complete), red (OCR failed), yellow (pending), or gray (not yet uploaded).

The chapter automatically transitions to "Ready to Process" once all pages in its range are uploaded and OCR is complete.

### 4. Process Chapters

Once a chapter is ready, the admin clicks "Start Processing." The system then:

1. **Extracts topics** -- Pages are processed in 3-page chunks. For each chunk, an AI reads the text and identifies topics, building up a running map of all topics and their teaching guidelines as it moves through the chapter.
2. **Finalizes the chapter** -- After all chunks are processed, a second AI pass consolidates the results: it merges duplicate topics, assigns clean names, creates summaries, and determines the optimal teaching order.

Processing runs in the background. A progress bar shows how many chunks have been completed, and the admin can navigate away and come back.

If processing fails partway through, the admin can **Resume** (pick up from where it stopped) or **Reprocess** (start from scratch). Completed chapters can also be **Re-finalized** (re-run only the consolidation step without re-extracting topics).

### 5. Review Results

When processing completes, the chapter shows its extracted topics. Each topic displays:
- **Title** and **topic key** (a short identifier)
- **Summary** (a brief description of what the topic covers)
- **Guidelines** (detailed teaching instructions for the AI tutor)
- **Source pages** (which book pages the topic was extracted from)
- **Sequence order** (the recommended teaching order within the chapter)
- **Status** (draft, consolidated, final, or approved)
- **Version number**

The admin can expand any topic to read its full guidelines.

### 6. Sync to Teaching Database

Once satisfied with the results, the admin syncs the chapter (or the entire book) to the teaching guidelines database. This makes the topics available to the AI tutor for use in learning sessions.

Syncing can be done per chapter ("Sync to DB" on each chapter) or for the whole book at once ("Sync All to DB").

After syncing, the tutor can teach any synced topic during student sessions.

---

## Key Principles

- **Chapter-first processing** -- Each chapter is processed independently, making it easy to fix or reprocess individual chapters without affecting others.
- **Human-in-the-loop** -- The admin reviews and can edit TOC entries, view OCR results, and inspect extracted topics before syncing. The system does not automatically make content available to students.
- **Resumable processing** -- If extraction fails (e.g., due to an API timeout), the admin can resume from the last successful chunk rather than restarting.
- **Full audit trail** -- Every step is recorded: raw images, OCR text, AI inputs and outputs, chunk-by-chunk processing logs. This makes debugging and quality review straightforward.

---

## Key Details

### Chapter Statuses

| Status | Meaning |
|--------|---------|
| TOC Defined | Chapter entry exists but no pages uploaded |
| Uploading | Some pages uploaded, but not all |
| Ready to Process | All pages uploaded and OCR complete |
| Extracting Topics | Topic extraction is running |
| Finalizing | Chapter consolidation is running |
| Completed | Processing finished, topics available |
| Failed | Processing encountered an error (can resume or reprocess) |

### Study Plans

After guidelines are synced, the platform can generate **study plans** for each topic. A study plan is a structured set of teaching steps (3-5 items) that the tutor follows during a "Teach Me" session. Study plans are generated by AI and reviewed by a second AI for quality, with an optional revision pass if the reviewer flags issues.

### Navigation

- **V2 Books Dashboard** -- Lists all books with chapter counts
- **Book Detail** -- Shows all chapters with their statuses, pages, and topics
- **Create New Book** -- Two-step wizard (metadata, then TOC)
