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

Before generating explanations, the admin can open a chapter's guidelines admin page to inspect each synced guideline. Each topic shows the full guideline text, source pages, and review status. The admin can edit the guideline text in place, mark a guideline as approved, or delete a guideline (which cascade-deletes its explanations, dialogues, and practice questions).

### Step 7: Topic Pipeline (post-sync stages)

After a chapter is synced, every topic enters an 8-stage post-sync pipeline. Each stage produces a different artifact the student session uses at runtime. Stages run independently per topic and the admin can trigger any stage individually, run them in dependency order from a chosen starting point, or run everything not-done in one click.

**The 8 stages and their order:**

1. **Explanations** — Generates the main explanation deck (variant A, "Everyday Analogies"). Two more variants ("Visual Walkthrough", "Step-by-Step Procedure") exist as options but are not generated by default.
2. **Visuals** — Adds interactive PixiJS visuals to explanation cards.
3. **Check-ins** — Inserts inline interactive activities between explanation cards.
4. **Practice bank** — Generates an offline pool of 30-40 practice questions.
5. **Baatcheet dialogue** — Generates a conversational version of the lesson with a peer character (Meera) alongside the tutor (Mr. Verma).
6. **Baatcheet visuals** — Adds PixiJS visuals to dialogue cards.
7. **Audio review** — An AI re-reads the spoken text on every card and rewrites lines that have markdown leaks, visual-only references, or other defects.
8. **Audio synthesis** — Pre-renders MP3 audio for every line via Google Cloud TTS so the student hears it instantly.

Stages 2-7 all depend on Step 1 (Explanations). Audio synthesis depends on Audio review. Baatcheet visuals depend on Baatcheet dialogue.

### Step 7.1: Generate Explanations

The admin generates an explanation deck for each topic. The deck is 3-15 cards. Each card has a type (concept, example, visual, analogy, or summary), a title, content text, an optional visual hint, and per-line audio text — a TTS-friendly spoken version using pure natural language (no symbols, markdown, or math notation). Each deck also has a summary with key analogies, key examples, and teaching notes.

Explanations are generated by an AI in two phases: first an initial generation pass, then one or more review-and-refine rounds where the AI inspects the cards from a student's perspective and rewrites weak ones in place. The number of review rounds is configurable per run.

Explanation generation can be triggered per-book, per-chapter, or per-topic. By default it skips topics that already have explanations. A force-regenerate option wipes and regenerates. A separate "refine only" mode skips initial generation and runs review-refine rounds against existing cards.

The admin can view explanation status per chapter, view full card details per topic, inspect stage-by-stage snapshots of how cards changed across refine rounds, and delete explanations per topic or per chapter.

### Step 7.2: Enrich with Interactive Visuals

Adds pre-computed PixiJS visuals to explanation cards. The system decides which cards benefit from a static or animated visual, generates the PixiJS code, validates it (length, API usage), and stores it back on the card. After the last refine round, the system actually renders the code and asks a vision AI to look at the screenshot — if the layout is broken (overlapping labels, clipped text), it runs one targeted refine round. If the issue persists the card is stored with a "layout warning" flag and the admin sees an amber chip; the student UI shows a subdued note.

Triggers: per-book, per-chapter, or per-topic. Skip-if-exists by default; force option regenerates. Runs as a background job. The admin can view per-topic coverage and strip visuals from a topic.

### Step 7.3: Add Interactive Check-Ins

Inserts quick inline activities between explanation cards so the student practises what they just read before moving on. Each check-in has a title, instruction, hint, success message, and audio text.

Six activity types: **Pick one** (2-3 options), **True/false**, **Fill blank** (2-3 options), **Match pairs** (2-3 pairs), **Sort buckets** (4-6 items into 2 buckets), **Sequence** (3-4 items in order).

Check-ins are never inserted before card 3 and are never placed back-to-back. The system decides placement, validates each check-in, and inserts only valid ones. Cannot run while explanation generation or visual enrichment is running on the same chapter.

### Step 7.4: Generate Practice Bank

Generates an offline bank of 30-40 mixed-format practice questions per topic, used by the student-facing Let's Practice mode. Questions span 12 formats including pick-one, true/false, fill-blank, match-pairs, sort-buckets, sequence, spot-the-error, odd-one-out, predict-then-reveal, swipe-classify, tap-to-eliminate, and free-form (open-ended).

Generation runs initial + review-refine rounds, then validates structure (option counts, no duplicates, sensible distributions) and tops up with another generation pass if the valid count falls short of 30. If after several attempts the bank still has fewer than 30 valid questions the run fails. Force-regenerate wipes the existing bank before generating.

The practice bank is decoupled from runtime: the student's practice attempt freezes a snapshot of the questions at the moment they start, so regenerating the bank later cannot corrupt their attempt history.

### Step 7.5: Generate Baatcheet Dialogue (conversational mode)

Generates a "Baatcheet" (Hindi for "conversation") version of the lesson — a dialogue between Mr. Verma (the tutor) and Meera (a peer-aged learner). The student watches the conversation unfold turn by turn instead of reading single-author cards.

The system runs a two-step generation. First it produces a lesson plan: the misconceptions to probe, the conceptual spine, and a slot-by-slot script with flags for which slots need a visual. Then it generates 25-42 dialogue cards realizing the plan. A welcome card greeting the student by name is always added as the first card. Validators reject any card that has markdown leaks, naked equals signs, emoji, or back-to-back check-ins.

Triggers per-book, per-chapter, or per-topic. Requires explanations to exist. Refresher topics are skipped — no Baatcheet for "Get Ready" cards.

### Step 7.6: Add Baatcheet Visuals

Same idea as the explanation visuals step, but for the dialogue cards. The lesson plan flags certain slots as needing a visual; an AI selector picks 12-18 cards (the required slots plus a few extras) and writes a one-line description of what the visual should show for each. The system then generates the rendered code for each.

The stage is considered done only when every required slot has a working visual. The extras are generated too but don't gate completion.

### Step 7.7: Review Audio Text

An AI re-reads the audio text on every card and rewrites lines that have defects:

- Symbol or markdown leaks (e.g. an equation written with literal plus and equals signs that a TTS voice would read awkwardly, or stray bold markers)
- Visual-only references (e.g. "as you can see in the diagram")
- Run-on pacing (a single line over 35 words)
- Cross-line redundancy (line 2 re-states line 1)
- Hinglish or Indian place-value reading errors (e.g. an Indian-format number read using American comma grouping)

Revisions are surgical — only the audio strings are rewritten; display text, line ordering, and card structure are never touched. The reviewer drops any revision that still contains banned patterns, and a drift guard prevents clobbering admin edits made between read and write. Revised lines have their stored audio file URL cleared so the next synthesis pass re-renders only those lines.

The admin can also run a separate Baatcheet audio review against dialogue cards via a manual "Review Baatcheet audio" button — opt-in safety valve for subtle defects.

### Step 7.8: Synthesize Audio (TTS)

Generates MP3 audio for every line on variant A explanation cards, every dialogue card (when present), and every check-in field (audio text, hint, success message, predict-then-reveal text) using Google Cloud TTS. MP3s upload to S3 and the public URLs are stamped back onto each card.

Voice routing: variant A and check-ins use a smooth tutor voice; Baatcheet routes by speaker — Mr. Verma uses the tutor voice, Meera uses a distinct peer voice. Lines containing the `{student_name}` placeholder are skipped because runtime TTS handles them at session start with the actual student's name.

Idempotent at line+field granularity: a line that already has an audio URL is skipped. Soft guardrail: if no audio review has run for the scope, the synthesis endpoint asks for explicit confirmation before proceeding (so the admin doesn't waste TTS quota on unreviewed text).

### Step 8: Generate a Get-Ready Refresher

For any chapter, the admin can generate a "Get Ready" refresher topic — a prerequisite warm-up that runs before the first real topic. The system reads the chapter's existing topics and the rest of the book, identifies foundational concepts the student is expected to already know, and produces:

- A list of prerequisite concepts with brief reasons
- A teaching guideline for the refresher
- A short topic summary
- A full set of explanation cards for the refresher

If the AI decides no prerequisite warm-up is needed, the refresher is skipped. Generating a refresher replaces any existing refresher for the chapter. The refresher appears as a special "Get Ready for [Chapter]" topic at sequence position 0, and the chapter landing screen surfaces its prerequisite concepts and a link to start it.

### Step 9: Topic Pipeline Dashboard

Each topic gets a per-topic dashboard showing all 8 stages laid out as a directed graph. Each node displays the stage's current state — done, warning, running, ready, blocked, or failed — plus a one-line summary (e.g. "12 cards", "30 questions", "8/12 audio clips").

From the dashboard the admin can:

- **Re-run one stage** — kicks off a cascade that re-runs the chosen stage and any stages downstream of it. Marks downstream stages stale at kickoff.
- **Run all** — runs every stage that isn't already done.
- **Cancel** — soft-cancels an active cascade. The currently running stage finishes; nothing further is launched.
- **Open the stage's full admin page** — deep-link to the per-chapter Explanations / Visuals / Practice Bank / etc. surface for detailed work.

A chapter-level summary chip on the book detail page shows "X topics · Y done · Z partial" so the admin can see at a glance how much work is left. A chapter-wide "Run pipeline for all topics" button fans out the per-topic pipeline across multiple topics in parallel (default 4 at once); a per-topic failure does not halt the chapter run.

A "Quality" selector (fast / balanced / thorough) controls how many AI review-refine rounds each stage uses. Thorough is the highest quality; fast is the cheapest.

### Step 10: Cross-DAG warnings

When upstream chapter content changes (a chapter resync, a refresher regen, a manual guideline edit) after a topic's explanations were generated, the system flags the topic with a "chapter content changed" banner on the dashboard. The admin can rerun explanations to refresh; the banner clears automatically the next time explanations runs successfully.

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
- A chapter can only have one active chapter-scope job at a time; topic-scope post-sync stages on different topics in the same chapter can run in parallel; stale jobs are automatically detected and cleaned up
- TOC entries cannot be edited or deleted once pages have been uploaded to that chapter
- Deleting a book removes all associated data including S3 files, chapters, pages, topics, dialogues, practice questions, and processing history
- Within a single topic, only one post-sync stage runs at a time (the system serializes them because several stages mutate the same card data in place)
- Pre-computed explanations, dialogues, and practice questions are all cascade-deleted when a guideline is deleted (e.g., during chapter re-sync)
- Check-in enrichment cannot run while explanation generation or visual enrichment is running on the same chapter
- Practice bank generation cannot run while explanations, visuals, or check-ins are running on the same chapter
- Audio synthesis asks for explicit confirmation if no audio text review has run on the scope yet
- Each chapter can have at most one refresher topic; regenerating replaces the existing one
- A failed re-run cascade halts at the failed stage; downstream stages stay in their previous state (the failed run didn't actually change upstream artifacts)
- Re-running explanations after the chapter has been resynced clears the "chapter content changed" banner automatically
