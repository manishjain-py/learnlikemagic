# Book Ingestion & Guidelines

Book ingestion is the process of turning a physical textbook into structured teaching content that the AI tutor uses during learning sessions. An admin uploads book pages, and the system extracts topics and teaching guidelines from them automatically.

---

## What It Is

The book ingestion pipeline takes textbook page images and produces teaching guidelines -- detailed instructions that tell the tutor what to teach, how to teach it, and in what order. Each guideline maps to a specific topic within a chapter. The entire process is managed through an admin dashboard.

---

## How It Works

### Step 1: Create a Book

The admin creates a new book entry with metadata:

- **Title** -- The book's name (e.g., "Math Magic")
- **Author** -- Who wrote or published it (e.g., "NCERT")
- **Country, Board, Grade, Subject** -- Curriculum details that determine where this content is used
- **Edition and Edition Year** -- For version tracking

### Step 2: Define the Table of Contents

The admin defines which chapters the book contains and their page ranges. There are two ways to do this:

1. **Upload TOC pages** -- Take screenshots of the book's Table of Contents pages (up to 5 images). The system uses OCR and AI to automatically extract chapter titles and page ranges. The admin reviews and edits the extracted results before saving.

2. **Manual entry** -- Type in chapter titles and page ranges directly using a table editor. Each chapter needs a number, title, start page, and end page. Optional notes can capture themes or subtopics.

The system validates that page ranges do not overlap and chapter numbers are sequential.

### Step 3: Upload Page Images

For each chapter, the admin uploads images of the textbook pages (one image per page). Pages must fall within the chapter's defined page range.

- Supported formats: PNG, JPG, JPEG, TIFF, WEBP (up to 20 MB each)
- Each page is automatically processed through OCR as soon as it is uploaded (inline, not batched)
- A visual page grid shows upload progress with color-coded status: green for successful OCR, red for failed OCR, gray for missing pages
- Failed OCR pages can be retried individually
- Bulk OCR retry: re-runs OCR for all pending/failed pages in a chapter at once
- Bulk OCR rerun: resets all OCR results for a chapter and re-runs from scratch
- Pages can be viewed in a detail modal showing the original image side-by-side with the extracted OCR text
- Pages can be re-uploaded or deleted individually

A chapter becomes "Ready to Process" once all pages in its range are uploaded and OCR is complete.

### Step 4: Process the Chapter

When a chapter is ready, the admin clicks "Start Processing" to begin topic extraction. The system runs a two-phase approach:

1. **Plans the chapter** -- Before extracting anything, the system reads all pages in the chapter and produces a topic skeleton: a list of planned topics with titles, descriptions, page ranges, and a recommended teaching sequence. This plan guides the extraction phase.

2. **Extracts topics** -- Reads through the chapter's pages in 3-page chunks, assigning content to the planned topics and building teaching guidelines for each one. Topics accumulate across chunks, so a topic that spans multiple pages gets combined automatically. The system can also discover unplanned topics if the pages contain material not covered by the plan.

3. **Finalizes** -- After all chunks are processed, the system consolidates the results: merging duplicate topics, improving topic names, assigning a teaching sequence order, generating chapter and topic summaries, and tracking any deviations from the original plan. It also generates curriculum context for each topic, describing what prior topics the student has already covered in the chapter.

If planning fails (e.g., due to AI model errors), extraction falls back to an unguided mode where topics are discovered freely without a plan.

Processing runs in the background. A progress bar shows the current step and how many chunks are complete. The admin can navigate away and come back -- the status updates automatically.

If the extraction deviates significantly from the plan (many topics were split, merged, or discovered unexpectedly), the chapter is flagged as "Needs Review" instead of completing automatically. The admin can review the results and decide whether to accept them or reprocess.

### Step 5: Review Results

Once processing completes, the admin can expand a chapter to see its extracted topics. Each topic shows:

- **Title and key** -- The topic's name and identifier
- **Summary** -- A brief description of what the topic covers
- **Guidelines** -- The full teaching instructions extracted from the book
- **Source pages** -- Which pages the content came from
- **Status** -- Draft, consolidated, final, or approved
- **Sequence order** -- The recommended teaching order
- **Version** -- Tracks revisions when a topic is reprocessed
- **Topic assignment** -- Whether the topic was planned or discovered during extraction
- **Prior topics context** -- A summary of what earlier topics in the chapter cover, providing curriculum continuity

### Step 6: Sync to Teaching Database

Completed chapters (and chapters flagged for review) can be synced to the teaching guidelines database, which is what the tutor uses during live sessions. Syncing can be done per-chapter or for the entire book at once.

Once synced, the guidelines appear in the tutor's knowledge base, organized by chapter and topic. Each synced guideline includes its curriculum context so the tutor knows what the student has already covered.

### Step 6.5: Review and Edit Guidelines

Before generating explanations, the admin can open a chapter's guidelines admin page to inspect each synced guideline. Each topic shows the full guideline text, source pages, and review status. The admin can edit the guideline text in place, mark a guideline as approved, or delete a guideline (which cascade-deletes its explanations and visuals).

### Step 7: Generate Explanations

After syncing, the admin can generate pre-computed explanation cards for each topic. Each topic gets one or more explanation variants, each using a different teaching approach:

- **Everyday Analogies** -- Explanation driven by real-world analogies and examples
- **Visual Walkthrough** -- Diagram-heavy, visual step-by-step explanation
- **Step-by-Step Procedure** -- Procedural walkthrough of the concept

Each variant produces a set of explanation cards (3-15 per variant). Each card has a type (concept, example, visual, analogy, or summary), a title, content text, an optional visual (such as an ASCII diagram), and an audio text -- a short spoken version for text-to-speech playback. The audio text uses pure natural language (no symbols, markdown, or math notation) as a warm, conversational companion to the full card content.

Each variant also includes a summary with key analogies, key examples, and teaching notes describing the conceptual progression.

Explanations are generated by an AI in two phases per variant: first an initial generation pass, then one or more review-and-refine rounds where a second AI call inspects the cards and rewrites weak ones in place. The number of refine rounds is configurable per run.

Explanation generation can be triggered per-book, per-chapter, or per-topic from the admin dashboard. By default it skips topics that already have explanations, so it is safe to run multiple times. A force-regenerate option deletes existing explanations before regenerating. A separate "refine only" mode skips initial generation and runs review-refine rounds against existing cards -- useful for improving previously generated content without starting over.

The admin can view explanation status per chapter (which topics have explanations and how many variants each has), view full explanation card details per topic, inspect stage-by-stage snapshots of how the cards changed across refine rounds, and delete explanations per topic or per chapter.

### Step 8: Enrich with Interactive Visuals

After explanations exist, the admin can enrich explanation cards with pre-computed interactive visuals (PixiJS-based). This is a separate pipeline that runs after explanation generation.

For each explanation variant, the system:

1. **Decides** which cards benefit from a visual and produces a specification (title, summary, detailed spec). Cards can be tagged as needing a static visual or an animated visual, or no visual.
2. **Generates PixiJS code** from each spec -- code that renders the visual in the browser.
3. **Validates** the generated code (non-empty, within size limits, correctly uses the rendering API). Failed code is retried once with error feedback.
4. **Stores** the visual data (output type, title, summary, spec, PixiJS code) back into the explanation card's `visual_explanation` field.

Visual enrichment can be triggered per-book, per-chapter, or per-topic. By default it skips cards that already have visuals; a force option re-generates them. Runs as a background job. The admin can view per-topic visual coverage (cards with visuals vs total cards) and strip visuals from a topic.

### Step 9: Add Interactive Check-Ins

After explanations exist, the admin can run check-in enrichment to insert quick interactive activities between explanation cards. Each check-in is an inline mini-activity placed at a concept boundary so the student practises what they just read before moving on.

Six activity types are supported:

- **Pick one** -- Choose the correct answer from 2-3 options
- **True/false** -- Decide whether a statement is correct
- **Fill blank** -- Pick the missing word from 2-3 options
- **Match pairs** -- Match 2-3 left items to right items
- **Sort buckets** -- Sort 4-6 items into two labeled buckets
- **Sequence** -- Put 3-4 items in the correct order

Each check-in card has a title, instruction, hint, success message, and audio text. The system decides where check-ins fit, validates each one (correct number of options, no duplicates, sensible placement), and inserts only the valid ones. Check-ins are never inserted before card 3 (so the student gets context first) and are never placed back-to-back.

Check-in enrichment can be scoped per-book, per-chapter, or per-topic. By default it skips variants that already have check-ins; a force option strips and re-generates them. Runs as a background job. Cannot run while explanation generation or visual enrichment is running for the same chapter.

### Step 10: Generate a Get-Ready Refresher

For any chapter, the admin can generate a "Get Ready" refresher topic. This is a special prerequisite topic that warms the student up before starting the chapter. The system reads all the chapter's existing topics (and the rest of the book), identifies foundational concepts the student is expected to already know, and produces:

- A list of prerequisite concepts with brief reasons
- A teaching guideline for the refresher
- A short topic summary
- A full set of explanation cards for the refresher topic

If the AI decides the chapter needs no prerequisite warm-up, the refresher is skipped. Generating a refresher replaces any existing refresher for the chapter (idempotent). The refresher appears as a special "Get Ready for [Chapter]" topic at sequence position 0 in the chapter, and the chapter landing screen surfaces the prerequisite concepts and a link to start the refresher.

---

## Recovery and Reprocessing

Processing can fail due to AI model errors or network issues. The system provides several recovery options:

- **Resume** -- If processing failed partway through, resume picks up from the last successful chunk rather than starting over. The topic plan from the original run is restored automatically.
- **Reprocess** -- Wipes all extracted topics and starts processing from scratch
- **Re-finalize** -- Re-runs only the finalization step (consolidation, naming, sequencing, curriculum context generation) on existing draft topics without re-extracting from pages
- **Bulk OCR retry** -- Re-runs OCR for all pending/failed pages in a chapter
- **Bulk OCR rerun** -- Resets all OCR for a chapter and re-runs from scratch

---

## Study Plans

After guidelines are synced, the system can generate study plans from them. Two plan types exist:

### Standard Study Plans

A study plan breaks a topic into 3-5 teaching steps, each with:

- A title and description
- A teaching approach (e.g., visual, gamification, hands-on)
- Success criteria for knowing when the student has mastered the step
- Building blocks (ordered sub-ideas from simplest to most complex)
- A real-world analogy

Each plan also includes metadata: estimated duration in minutes, difficulty level, and an optional creative theme (e.g., "Space Adventure").

Study plans are generated on demand by the tutor when a student starts a topic. They can optionally be personalized for a specific student's interests and learning style.

During a live tutoring session, the study plan can also be regenerated mid-session based on parent or student feedback. This adjusted plan skips concepts already covered and reshapes the remaining steps per the feedback.

### Session Plans

Session plans are generated after a student reads explanation cards and says "I understand." They create an interactive follow-up sequence (3-5 steps) tailored to the explanation the student just saw. Each step has:

- A type (check understanding, guided practice, independent practice, or extend)
- The concept it focuses on
- References to specific explanation card concepts and analogies
- Misconceptions to probe
- Success criteria and difficulty level
- A personalization hint for using student interests

Session plans know which explanation variants the student saw and build on those specific analogies and examples.

---

## Key Details

- OCR runs inline on every page upload; bulk OCR retry and rerun are also available for batch recovery
- Topic extraction uses a plan-first approach: the system reads the full chapter to produce a topic skeleton before processing chunks
- If planning fails, the system falls back to unguided extraction where topics are discovered freely
- Topic extraction processes pages in non-overlapping 3-page windows, with the previous page providing context for continuity
- The system stores all intermediate processing data (chunk inputs, outputs, state snapshots, topic plans) for debugging and reproducibility
- Chapters progress through defined statuses: TOC Defined, Uploading, Ready to Process, Extracting Topics, Finalizing, Completed, Needs Review, or Failed
- A chapter flagged "Needs Review" has significant deviations from the plan but can still be synced
- A chapter can only have one active processing job at a time; stale jobs are automatically detected and cleaned up
- TOC entries cannot be edited or deleted once pages have been uploaded to that chapter
- Deleting a book removes all associated data including S3 files, chapters, pages, topics, and processing history
- Pre-computed explanations are cascade-deleted when a guideline is deleted (e.g., during re-sync)
- Check-in enrichment cannot run while explanation generation or visual enrichment is running on the same chapter
- Each chapter can have at most one refresher topic; regenerating replaces the existing one
- Guideline edits, explanation generation, visuals, check-ins, and refresher all have their own per-chapter admin pages with status views and progress polling
