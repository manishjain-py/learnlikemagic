# Book Ingestion & Guidelines -- Technical

Pipeline architecture for extracting structured teaching guidelines from textbook page images using OCR + LLM processing.

---

## Pipeline Architecture

Two phases: **chapter-scope** (book → TOC → pages → topics → guidelines) and **topic-scope** post-sync DAG (8 stages keyed per guideline, declared in `book_ingestion_v2/dag/topic_pipeline_dag.py`).

```
─── Chapter scope ───
Create Book (metadata)
    │
    ▼
Define TOC (manual or OCR+LLM from TOC page images)
    │
    ▼
Upload Pages (per chapter, inline OCR on each page)
    │
    ▼
Chapter Topic Planning (LLM reads full chapter, produces topic skeleton)
    │
    ▼
Topic Extraction (3-page chunks; guided mode if planning ok)
    │
    ▼
Chapter Finalization (merge, dedup, sequence, curriculum context, deviation check)
    │
    ▼
Sync to teaching_guidelines table  ────┐  one row per topic
                                       │
─── Topic-scope DAG (per guideline) ───┘
explanations  ─┬─►  visuals
               ├─►  check_ins
               ├─►  practice_bank
               ├─►  baatcheet_dialogue ─►  baatcheet_visuals
               └─►  audio_review ─►  audio_synthesis (covers variant A + dialogue MP3s)

Refresher Topic Generation (chapter-scoped; produces a sequence-0 "get-ready" guideline + variant A cards)
Study Plan + Session Plan (runtime: tutor calls StudyPlanGeneratorService directly)
```

All ingestion code lives under `book_ingestion_v2/`. The DAG package is `book_ingestion_v2/dag/`; per-stage modules under `book_ingestion_v2/stages/`. Study plan generation is a separate module under `study_plans/`. Ingestion quality evaluation is `autoresearch/book_ingestion_quality/`.

---

## Chapter Status Machine

```
toc_defined -> upload_in_progress -> upload_complete -> topic_extraction -> chapter_finalizing -> chapter_completed
                                         |                   |                     |                     |
                                         v                   v                     v                     v
                                       failed <----------  failed <----------    failed            needs_review
```

| Status | Meaning |
|--------|---------|
| `toc_defined` | Chapter created from TOC, no pages uploaded |
| `upload_in_progress` | Some pages uploaded but not all (or some OCR failed) |
| `upload_complete` | All pages uploaded and OCR complete -- ready for processing |
| `topic_extraction` | Chunk-by-chunk extraction running in background |
| `chapter_finalizing` | Consolidation/finalization running |
| `chapter_completed` | All topics extracted and finalized |
| `needs_review` | Finalization complete but extraction deviated significantly from the topic plan (see deviation tracking below) |
| `failed` | Processing failed (retryable) |

Defined in `book_ingestion_v2/constants.py` as `ChapterStatus` enum.

Topic statuses (`TopicStatus` enum in same file): `draft` -> `consolidated` -> `final` -> `approved`.

---

## Book Management

**Service:** `book_ingestion_v2/services/book_v2_service.py` (`BookV2Service`)

- Creates books with `pipeline_version=2` in the shared `books` table
- Generates book IDs from metadata: `{author}_{subject}_{grade}_{year}` with auto-incrementing suffix for uniqueness
- Initializes S3 metadata at `books/{book_id}/metadata.json`
- Delete cascades to chapters, pages, chunks, topics, processing jobs, and S3 folder

**API routes:** `book_ingestion_v2/api/book_routes.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/v2/books` | Create book |
| GET | `/admin/v2/books` | List books (filterable by country, board, grade, subject) |
| GET | `/admin/v2/books/{book_id}` | Get book detail with chapters |
| DELETE | `/admin/v2/books/{book_id}` | Delete book and all child data |

---

## TOC Management

### TOC Extraction (OCR + LLM)

**Service:** `book_ingestion_v2/services/toc_extraction_service.py` (`TOCExtractionService`)

- Accepts 1-5 images of TOC pages (max 10 MB each)
- Converts all images to PNG format (via Pillow, supports HEIF)
- Runs OCR on each image via `OCRService`
- Sends combined OCR text to LLM with `toc_extraction.txt` prompt template
- Returns structured `TOCEntry` list -- does NOT save to DB (read-only extraction)
- Stores images and extraction result to S3 at `books/{book_id}/toc_pages/`

### TOC CRUD

**Service:** `book_ingestion_v2/services/toc_service.py` (`TOCService`)

- `save_toc`: Creates/replaces full TOC for a book. Validates sequential chapter numbers, positive page ranges, no overlaps. Blocked if any existing chapter has uploaded pages.
- `update_chapter`: Updates a single chapter entry. Blocked if pages uploaded.
- `delete_chapter`: Deletes a single chapter. Blocked if pages uploaded.
- Validation: chapter numbers must be sequential starting from 1, start_page > 0, end_page >= start_page, no range overlaps between chapters.

**API routes:** `book_ingestion_v2/api/toc_routes.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/v2/books/{book_id}/toc/extract` | Extract TOC from images (multipart form) |
| POST | `/admin/v2/books/{book_id}/toc` | Save full TOC |
| GET | `/admin/v2/books/{book_id}/toc` | Get TOC |
| PUT | `/admin/v2/books/{book_id}/toc/{chapter_id}` | Update single chapter |
| DELETE | `/admin/v2/books/{book_id}/toc/{chapter_id}` | Delete single chapter |

---

## Page Upload & OCR

**Service:** `book_ingestion_v2/services/chapter_page_service.py` (`ChapterPageService`)

Each page upload:
1. Validates page number is within chapter's range and not a duplicate
2. Validates file format (PNG, JPG, JPEG, TIFF, WEBP) and size (max 20 MB)
3. Uploads raw image to S3 at `books/{book_id}/chapters/{ch_num}/pages/raw/{page_number}.{ext}`
4. Converts to PNG and uploads to `books/{book_id}/chapters/{ch_num}/pages/{page_number}.png`
5. Runs OCR inline using `OCRService.extract_text_from_image()` with a custom education-focused prompt (`V2_OCR_PROMPT`)
6. Uploads OCR text to `books/{book_id}/chapters/{ch_num}/pages/{page_number}.txt`
7. Creates `ChapterPage` DB record
8. Updates chapter completeness: counts uploaded and OCR-completed pages, transitions status (`toc_defined` / `upload_in_progress` / `upload_complete`)

OCR model is determined by the `book_ingestion_v2` LLM config entry.

**Retry OCR:** Re-downloads PNG from S3, re-runs OCR, updates DB and S3 text file.

**Bulk OCR retry:** `bulk_ocr()` -- background task that re-runs OCR for all pending/failed pages in a chapter. Processes each page sequentially with job progress tracking.

**Bulk OCR rerun:** Resets all OCR status for a chapter to pending, reverts chapter to `upload_in_progress`, then runs `bulk_ocr()` on all pages.

**API routes:** Page CRUD/retry in `page_routes.py` (prefix `/admin/v2/books/{book_id}/chapters/{chapter_id}/pages`); bulk OCR jobs in `processing_routes.py` (prefix `/admin/v2/books/{book_id}/chapters/{chapter_id}`).

| Method | Path | Description |
|--------|------|-------------|
| POST | `.../pages` | Upload page (multipart form: image + page_number) |
| GET | `.../pages` | List pages with completeness |
| GET | `.../pages/{page_num}` | Get page metadata |
| GET | `.../pages/{page_num}/detail` | Get page with presigned image URL + OCR text |
| DELETE | `.../pages/{page_num}` | Delete page |
| POST | `.../pages/{page_num}/retry-ocr` | Retry failed OCR |
| POST | `.../ocr-retry` | Bulk retry OCR for all pending/failed pages (background job) |
| POST | `.../ocr-rerun` | Reset all OCR and re-run from scratch (background job) |

---

## Topic Extraction Pipeline

### Chapter Topic Planning

**Service:** `book_ingestion_v2/services/chapter_topic_planner_service.py` (`ChapterTopicPlannerService`)

Runs before chunk extraction to produce a topic skeleton for the entire chapter:
- Loads all OCR'd page texts for the chapter
- Sends the full chapter content to LLM with `chapter_topic_planning.txt` prompt template
- Uses `reasoning_effort="high"` since this makes structural decisions for the entire chapter
- Returns `ChapterTopicPlan`: a list of `PlannedTopic` items (topic_key, title, description, page_start, page_end, sequence_order, grouping_rationale, dependency_notes) plus chapter_overview and planning_rationale
- Retries up to 3 times with exponential backoff on failure

The plan is saved to the `ChapterProcessingJob.planned_topics_json` column and to S3 at `{run_base}/planned_topics.json` for audit.

If planning fails, extraction falls back to **unguided mode** where topics are discovered freely without a skeleton.

### Chunk Builder

**File:** `book_ingestion_v2/utils/chunk_builder.py`

Builds non-overlapping 3-page windows from sorted page numbers. Each window includes a reference to the previous page for context continuity.

```
Pages [1,2,3,4,5,6,7,8,9,10] -> Chunks:
  [0] pages=[1,2,3]  prev=None
  [1] pages=[4,5,6]  prev=3
  [2] pages=[7,8,9]  prev=6
  [3] pages=[10]     prev=9
```

Configured via `CHUNK_SIZE=3` and `CHUNK_STRIDE=3` in `constants.py`.

### Chunk Processor

**Service:** `book_ingestion_v2/services/chunk_processor_service.py` (`ChunkProcessorService`)

Processes a single chunk through the LLM. Supports two modes:

- **Guided mode** (when `planned_topics` provided): The prompt includes the planned topic skeleton and instructs the LLM to assign content to planned topics. The LLM sets `topic_assignment="planned"` or `"unplanned"` on each `TopicUpdate`.
- **Unguided mode** (when `planned_topics` is `None`): The LLM discovers topics freely, using the `is_new` flag to indicate new topics.

Details:
- Builds prompt from `chunk_topic_extraction.txt` template with book metadata, chapter metadata, current page texts, previous page context, chapter summary so far, existing topics, and (in guided mode) planned topics section
- Calls LLM with `json_mode=True` and `reasoning_effort="none"` for speed
- Parses response into `ChunkExtractionOutput`: updated chapter summary + list of `TopicUpdate` (topic_key, title, topic_assignment, guidelines_for_this_chunk, reasoning, unplanned_justification)
- Retries up to 3 times with exponential backoff (1s, 2s, 4s) on failure
- Tracks prompt hash for audit

### Extraction Orchestrator

**Service:** `book_ingestion_v2/services/topic_extraction_orchestrator.py` (`TopicExtractionOrchestrator`)

Runs the full planning + extraction + auto-finalization pipeline for a chapter:

1. Acquires job lock, builds LLM service from DB config
2. **Plans chapter topics** (new step): calls `ChapterTopicPlannerService.plan_chapter()` with all OCR'd page texts. On success, saves the plan to the job record and S3. On failure, falls back to unguided mode.
3. Pre-populates the topic accumulator map from planned topics (empty guidelines, page ranges from the plan)
4. Transitions chapter to `topic_extraction` status
5. Builds chunk windows from OCR'd pages
6. For each chunk:
   - Downloads page texts from S3
   - Builds `ChunkInput` with accumulated state (summary, topic map)
   - Calls `ChunkProcessorService.process_chunk(planned_topics=...)` -- passes the plan for guided mode
   - Updates running state: chapter summary, topic accumulator map. For unplanned topics, creates new accumulator entries; for planned topics, appends to existing ones.
   - Saves chunk input/output/state to S3 at `books/{book_id}/chapters/{ch_num}/processing/runs/{job_id}/chunks/{idx}/`
   - Creates `ChapterChunk` DB record
7. Persists all accumulated topics as draft `ChapterTopic` records, tagging each as `topic_assignment="planned"` or `"unplanned"`
8. Auto-triggers finalization if no chunks failed, passing planned topics to the finalization service
9. Sets final chapter status from `FinalizationResult.final_status` (`chapter_completed` or `needs_review`)
10. On failure: marks chapter as `failed` with `retryable` error type

**Resume support:** When `resume=True`, finds the last completed chunk from the previous job, restores topic map and chapter summary from DB/chunk records, restores the planned topics from the previous job's `planned_topics_json`, and resumes from the next chunk index.

### Chapter Finalization

**Service:** `book_ingestion_v2/services/chapter_finalization_service.py` (`ChapterFinalizationService`)

Runs after all chunks are extracted. Returns a `FinalizationResult` with the consolidation output, final status, deviation ratio, and deviation count.

1. Loads draft topics from DB
2. **LLM-merges** each topic's per-chunk appended guidelines into unified text using `topic_guidelines_merge.txt` prompt
3. **Consolidation LLM call** using `chapter_consolidation.txt` prompt -- analyzes all topics (and planned topics, if available) and produces:
   - `merge_actions`: topics that should be combined (dedup)
   - `topic_updates`: new keys, titles, summaries, sequence orders for each topic
   - `chapter_display_name` and `final_chapter_summary`
   - `deviations`: list of `ConsolidationDeviation` items (deviation_type: split, merge, unplanned_ratified, unplanned_merged; topic_key; affected_target_key; reasoning)
4. Executes merge actions (appends guidelines, expands page ranges, deletes merged-from topics)
5. Applies topic updates (new key, title, summary, sequence_order, status -> `final`)
6. **Deviation check** (plan-guided mode only): computes the ratio of planned topics affected by deviations. If deviation count >= `PLANNING_DEVIATION_MIN_COUNT` (3) and ratio > `PLANNING_DEVIATION_THRESHOLD` (30%), sets `final_status = "needs_review"` instead of `"chapter_completed"`.
7. **Curriculum context generation**: calls LLM with `curriculum_context_generation.txt` prompt to generate `prior_topics_context` for each topic (except the first). Each topic gets a summary of what earlier topics in the chapter cover, enabling curriculum continuity in the tutor. Non-fatal: topics are usable without context.
8. Updates chapter with display_name and summary
9. Saves final output to S3 at `books/{book_id}/chapters/{ch_num}/output/`

**Refinalization:** The `/refinalize` endpoint re-runs only the finalization step on existing topics without re-extracting from pages. Requires chapter status `chapter_completed`, `needs_review`, or `failed`. Restores planned topics from the most recent job record if available.

---

## Job Lock & Progress Tracking

**Service:** `book_ingestion_v2/services/chapter_job_service.py` (`ChapterJobService`)

State machine: `pending -> running -> completed | completed_with_errors | failed`

- **Reader-writer lock scopes:**
  - *Chapter-level* (`guideline_id IS NULL`) — OCR, extraction, finalization, refresher. One active job per chapter (partial unique index `idx_chapter_active_chapter_job`).
  - *Topic-level* (`guideline_id IS NOT NULL`) — post-sync stages (explanations, visuals, check-ins, practice bank, audio review, audio synthesis). One active job per `(chapter_id, guideline_id)` (partial unique index `idx_chapter_active_topic_job`).
  - Chapter-level and topic-level are mutually exclusive in the same chapter. Two topic-level jobs on different guidelines in one chapter can run concurrently.
- Stale detection: running jobs with no heartbeat for 30 minutes (`HEARTBEAT_STALE_THRESHOLD = 1800`) are auto-marked failed; pending jobs stuck for 5 minutes are marked abandoned. Threshold raised from 10 → 30 min because Opus + high reasoning effort calls can take 10+ min.
- Progress updates include `current_item` description, `completed_items`/`failed_items` counts, and heartbeat timestamp
- Jobs may save per-stage snapshots (`stage_snapshots_json`) for explanation generation runs — used by the admin UI to inspect how cards changed across refine rounds
- Jobs track LLM model provider and model ID for audit

**Background task runner:** `run_in_background_v2()` in `processing_routes.py` -- spawns a daemon thread with its own DB session, calls `start_job()`, runs the target function, and releases the lock on completion or failure.

**API routes:** `book_ingestion_v2/api/processing_routes.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `.../chapters/{chapter_id}/process` | Start topic extraction + finalization (also accepts resume from `needs_review`) |
| POST | `.../chapters/{chapter_id}/reprocess` | Wipe topics, reprocess from scratch |
| POST | `.../chapters/{chapter_id}/refinalize` | Re-run finalization only (accepts `chapter_completed`, `needs_review`, or `failed`) |
| GET | `.../chapters/{chapter_id}/jobs/latest` | Get latest job status (optional `job_type` query param) |
| GET | `.../chapters/{chapter_id}/jobs/{job_id}` | Get specific job |
| GET | `.../chapters/{chapter_id}/topics` | Get extracted topics |
| GET | `.../chapters/{chapter_id}/topics/{topic_key}` | Get single topic |

---

## Sync to Teaching Guidelines

**Service:** `book_ingestion_v2/services/topic_sync_service.py` (`TopicSyncService`)

Maps V2 data model to the shared `teaching_guidelines` table:
- V2 chapter -> `teaching_guidelines.chapter_key` (format: `chapter-{number}`)
- V2 topic -> one `teaching_guidelines` row per topic

For each topic, creates a `TeachingGuideline` record with:
- Curriculum fields: country, board, grade, subject (from book)
- Chapter fields: chapter_title (display_name or chapter_title), chapter_key, chapter_summary, chapter_sequence
- Topic fields: topic_key, topic_title, topic_summary, topic_sequence, guidelines (full text), source pages
- `prior_topics_context`: curriculum context from finalization (what earlier topics cover)
- Status: `approved` / review_status: `APPROVED`
- book_id reference for traceability

Sync accepts chapters with status `chapter_completed` or `needs_review`.

Sync is idempotent: deletes existing guidelines for the chapter before creating new ones. This also cascade-deletes any pre-computed explanations linked to those guidelines.

**API routes:** `book_ingestion_v2/api/sync_routes.py` (prefix `/admin/v2/books/{book_id}`). Post-sync `POST /generate-*` and `/review-baatcheet-audio` routes return `FanOutJobResponse` (see Topic Pipeline DAG above) and accept scoping `guideline_id` > `chapter_id` > book-wide.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sync` | Sync all completed/needs_review chapters |
| POST | `/chapters/{chapter_id}/sync` | Sync single chapter |
| GET | `/results` | Book-level results overview |
| GET | `/landing` | Chapter landing data: chapter summary + prerequisite concepts + refresher guideline_id (query: `chapter_id`) |
| **Guidelines admin** | | |
| GET | `/guideline-status` | Per-topic guideline status for a chapter (query: `chapter_id`) |
| GET | `/guidelines/{guideline_id}` | Full guideline detail |
| PUT | `/guidelines/{guideline_id}` | Update guideline text or review_status |
| DELETE | `/guidelines/{guideline_id}` | Delete a guideline (cascades to explanations + dialogue) |
| **Explanations** | | |
| POST | `/generate-explanations` | Generate/refine explanations (query: `force`, `mode` = `generate`/`refine_only`, `review_rounds` 0-5) |
| GET | `/explanation-jobs/latest` | Latest explanation job (query: `chapter_id`, `guideline_id`) |
| GET | `/explanation-jobs/{job_id}/stages` | Per-stage card snapshots for an explanation job |
| GET | `/explanation-status` | Per-topic variant counts for a chapter |
| GET | `/explanations` | Full card data for a topic (query: `guideline_id`) |
| DELETE | `/explanations` | Delete explanations (query: `guideline_id` or `chapter_id`) |
| **Visuals** | | |
| POST | `/generate-visuals` | Generate PixiJS visuals (query: `force`, `review_rounds`) |
| GET | `/visual-status` | Per-topic visual coverage for a chapter; includes `layout_warning_count` |
| GET | `/visual-jobs/latest` | Latest visual job |
| GET | `/visual-jobs/{job_id}/stages` | Per-stage snapshots for a visual job |
| DELETE | `/visuals` | Strip visuals from a topic's explanations |
| **Check-ins** | | |
| POST | `/generate-check-ins` | Generate inline check-in cards (query: `force`, `review_rounds`) |
| GET | `/check-in-status` | Per-topic check-in counts |
| GET | `/check-in-jobs/latest` | Latest check-in job |
| **Practice bank** | | |
| POST | `/generate-practice-banks` | Generate offline practice question bank (query: `force`, `review_rounds`) |
| GET | `/practice-bank-status` | Per-topic question counts |
| GET | `/practice-bank-jobs/latest` | Latest practice bank job |
| GET | `/practice-banks/{guideline_id}` | Full question payloads for a topic |
| **Audio review (LLM)** | | |
| POST | `/generate-audio-review` | LLM-review `audio` strings on cards; clears `audio_url` on revised lines (query: `language`) |
| GET | `/audio-review-jobs/latest` | Latest audio review job |
| **Audio synthesis (TTS)** | | |
| POST | `/generate-audio` | Google Cloud TTS for variant A + dialogue lines + check-in fields → S3 → stamp `audio_url` (query: `confirm_skip_review`). Idempotent at line+field granularity. Soft guardrail: 409 with `requires_confirmation:true` if no completed review exists for the scope. |
| **Baatcheet (conversational mode)** | | |
| POST | `/generate-baatcheet-dialogue` | Stage 5b — generate two-step lesson plan + dialogue cards anchored on variant A (query: `force`, `review_rounds`) |
| POST | `/generate-baatcheet-visuals` | Stage 5c — fill PixiJS on dialogue cards selected from `plan_json.card_plan` (query: `force`) |
| POST | `/review-baatcheet-audio` | Opt-in safety valve — runs audio review LLM against `topic_dialogues.cards_json` (not part of default DAG) |
| **Refresher** | | |
| POST | `/refresher/generate` | Generate prerequisite refresher topic for a chapter (query: `chapter_id`) |
| GET | `/refresher-jobs/latest` | Latest refresher job |

---

## Pre-Computed Explanations

**Service:** `book_ingestion_v2/services/explanation_generator_service.py` (`ExplanationGeneratorService`)

Generates multi-variant explanation cards for synced teaching guidelines. Runs after sync, independently triggered from the admin dashboard.

### Variant Configurations

| Key | Label | Approach |
|-----|-------|----------|
| A | Everyday Analogies | Analogy-driven with real-world examples |
| B | Visual Walkthrough | Diagram-heavy with visual step-by-step |
| C | Step-by-Step Procedure | Procedural walkthrough |

`DEFAULT_VARIANT_COUNT = 1` — only variant A is generated by default unless explicit `variant_keys` are passed.

### Pipeline Per Variant

1. **Generate**: Calls LLM with `explanation_generation.txt` prompt using `reasoning_effort="high"` and strict JSON schema (`GenerationOutput`). Produces 3-15 `ExplanationCardOutput` items (card_idx, card_type, title, content, optional visual, audio_text) plus `ExplanationSummaryOutput` (key_analogies, key_examples, teaching_notes). Includes `prior_topics_context` when available.
2. **Review-and-refine (N rounds)**: Calls LLM with `explanation_review_refine.txt` prompt using `reasoning_effort="high"`. Each round inspects the current cards from a student's perspective and rewrites weak ones in place, returning a fresh `GenerationOutput`. Default `DEFAULT_REVIEW_ROUNDS = 1`. The reviewer is given the cards stripped of `audio_text` and `visual` to save tokens.
3. **Validate**: After each round, drops the variant if final card count is below `MIN_CARDS=3`; trims to `MAX_CARDS=15`.
4. **Store**: Upserts to `topic_explanations` table via `ExplanationRepository`.

`refine_only_for_guideline()` / `refine_only_for_chapter()` skip step 1 and run only review-refine rounds against existing cards in the DB. Triggered via the `mode=refine_only` query param on `/generate-explanations`.

When the LLM provider is `claude_code`, the static instructions and JSON schema are loaded from `_system.txt` files via `--append-system-prompt-file`, leaving only dynamic data (topic, guideline, current cards) on stdin. Reduces stdin size ~30-40%.

`stage_collector` lists capture per-round card snapshots which are persisted on the `ChapterProcessingJob` record so the admin UI can display the diff across rounds via `/explanation-jobs/{job_id}/stages`.

### Card Fields

Each `ExplanationCardOutput` contains:
- `card_idx` (1-based index), `card_type` (concept/example/visual/analogy/summary), `title`, `content`
- `visual` (optional ASCII diagram or formatted visual)
- `audio_text` -- TTS-friendly spoken version. Pure words only, no symbols/markdown/emoji, math as natural speech. Shorter than content; warm conversational tone.

### Entry Points

- `generate_for_guideline(guideline, variant_keys)`: single guideline, optional subset of variants
- `generate_for_chapter(book_id, chapter_id, force=False)`: all synced guidelines in a chapter. Skips topics with existing explanations unless `force=True` (deletes and regenerates). Supports `job_service`/`job_id` for progress tracking.
- `generate_for_book(book_id)`: all synced guidelines in a book

API supports three scoping levels via query params: `guideline_id` (single topic) > `chapter_id` (chapter) > book-wide. Runs as a background job with the `v2_explanation_generation` job type.

### Storage

Each explanation is stored as a `TopicExplanation` row with:
- `guideline_id` (FK to `teaching_guidelines`, cascade delete)
- `variant_key` ("A", "B", "C")
- `variant_label` (human-readable name)
- `cards_json` (JSONB array of card objects, each with `audio_text`)
- `summary_json` (JSONB with card_titles, key_analogies, key_examples, approach_label, teaching_notes)
- `generator_model` (audit)
- Unique constraint on (guideline_id, variant_key)

**LLM config key:** `explanation_generator` (separate from `book_ingestion_v2` key)

---

## Visual Enrichment (PixiJS)

**Service:** `book_ingestion_v2/services/animation_enrichment_service.py` (`AnimationEnrichmentService`)

Enriches existing explanation cards with pre-computed PixiJS interactive visuals. Fully decoupled from explanation generation -- runs after, reads/writes the same `topic_explanations` table.

### Pipeline Per Variant

1. **Decision + Spec**: Calls LLM with `visual_decision_and_spec.txt` prompt and `reasoning_effort="medium"`. For each card, returns a `VisualDecision`: `decision` (no_visual / static_visual / animated_visual), `title`, `visual_summary`, `visual_spec`. Strips `audio_text` from cards to save tokens. When provider is `claude_code`, static instructions/schema are loaded from `visual_decision_and_spec_system.txt`.
2. **Code Generation**: For each card selected for visuals, calls LLM with `visual_code_generation.txt` prompt and `reasoning_effort="none"`. Returns raw PixiJS code (markdown fences are stripped).
3. **Validation**: Checks code is non-empty, under `MAX_CODE_LENGTH` (5000 chars), and contains `app.stage.addChild` or `stage.addChild`. On failure, retries once with error feedback appended to the prompt.
4. **Storage**: Writes `visual_explanation` object into the card's `cards_json` entry:
   ```json
   {
     "output_type": "static_visual | animated_visual",
     "title": "...",
     "visual_summary": "...",
     "visual_spec": "...",
     "pixi_code": "..."
   }
   ```

### Dual LLM Architecture

Uses two separate LLM instances:
- `llm_service` (config key: `animation_enrichment`): Lighter model for decision + spec generation
- `code_gen_llm` (config key: `animation_code_gen`): Heavier model for reliable PixiJS code generation

### Entry Points

- `enrich_guideline(guideline, force=False, variant_keys=None)`: single guideline
- `enrich_chapter(book_id, chapter_id=None, force=False)`: chapter or book-wide. Supports `job_service`/`job_id` for progress tracking.

### Skip Logic

Checks if cards already have `visual_explanation.pixi_code`. Skips unless `force=True`.

### Background Job

Runs as a background job with `v2_visual_enrichment` job type. Endpoint table is consolidated above in [Sync to Teaching Guidelines](#sync-to-teaching-guidelines).

### Visual Rendering Review (post-refine vision gate)

A sub-stage of `visuals` that catches defects (overlap, layout breakage, label-clipping) that `visual_code_review_refine.txt` cannot enforce from source — LLMs can't compute text bounding boxes from Pixi code. Observed defect: a place-value diagram for `5,23,476` rendered as `"Lakhs PeTioodsands Period"` because adjacent labels exceeded their group widths.

**Approach:**

1. **Render via Playwright** — `VisualRenderHarness.render()` stashes the Pixi code in the preview store, navigates to `/admin/visual-render-preview/{id}`, waits for `data-pixi-state="ready"`, takes a screenshot.
2. **Vision review** — `_visual_review` calls a vision LLM with the screenshot + decision spec to flag layout problems (`visual_review.txt` prompt).
3. **Targeted refine round** — when flagged, `_review_and_refine_code` runs with the reviewer's note, then re-renders and re-reviews.
4. **Retry exhaustion** — if still flagged after the second round, the code is stored anyway with `visual_explanation.layout_warning = true`. Admin UI surfaces this as an amber chip; student UI renders a subdued note.

**Components:**

| File | Role |
|---|---|
| `services/visual_render_harness.py` | Playwright wrapper. `render()` stashes code, navigates to the admin preview page, waits for `data-pixi-state="ready"`, returns screenshot path + bounds. `preflight()` HEADs localhost:3000 at job start as a fail-fast check. |
| `services/visual_preview_store.py` | In-memory TTL+LRU store keyed by random `secrets.token_urlsafe(24)`. Closes the reflected-XSS vector of carrying executable Pixi code in a URL query. 2-min TTL, 256-entry cap. |
| `api/visual_preview_routes.py` | `POST /admin/v2/visual-preview/prepare` (stash) + `GET /admin/v2/visual-preview/{id}` (read). |
| `frontend/.../pages/VisualRenderPreview.tsx` | Admin React page mounting Pixi directly (no sandboxed iframe — Playwright can't reach in). Exposes `window.__pixiApp` for `page.evaluate()`. |

**Harness failure discipline:** if the harness fails (playwright missing, localhost unreachable, Pixi threw), the gate passes the code WITHOUT setting `layout_warning=true`. We don't false-flag cards when the check itself failed.

**Dev prerequisite:** the frontend dev server must be running at `http://localhost:3000` when the `visuals` job runs. Playwright + Chromium installed locally. See `docs/technical/dev-workflow.md`.

**Admin observability:** `/visual-status` includes `layout_warning_count` per topic; `VisualsAdmin` renders an amber chip on affected topics. The `visuals` stage rolls up to state `warning` when warnings exist.

---

## Audio Text Review

**Service:** `book_ingestion_v2/services/audio_text_review_service.py` (`AudioTextReviewService`)

Per-card LLM reviewer that catches defects in the `audio` strings on variant A explanation + check-in cards before audio synthesis runs. Surgical scope — can only rewrite individual audio strings. Cannot edit `display` text, cannot split/merge/drop lines, cannot reshape cards. Runs after `explanations` and `check_ins`, before `audio_synthesis`. The Baatcheet variant (`BaatcheetAudioReviewService`) wraps the same machinery against `topic_dialogues.cards_json`.

### Defect Classes Caught

| Defect | Example |
|---|---|
| Symbol / markdown leak | `audio`: `"5+3=8"` or `"**bold**"` |
| Visual-only reference | `audio`: `"as you can see in the diagram"` |
| Run-on pacing | Single audio line > 35 words |
| Cross-line redundancy | Line 2 re-states line 1 verbatim |
| Hinglish / Indian place-value | `"1,23,456"` read as `"one hundred twenty-three thousand"` instead of `"one lakh twenty-three thousand"` |

### Pipeline Per Card

1. **LLM call**: `audio_text_review.txt` + `_system.txt`, with `{card_json}` stripped of `audio_url` (the reviewer has no use for it). Returns `CardReviewOutput` — zero or more `AudioLineRevision` entries.
2. **Validation**: Drops revisions whose `revised_audio` still contains banned patterns (markdown, standalone `=`, emoji). Logs each drop with card/line identifier.
3. **Drift guard**: Each revision's `original_audio` must match the current card value exactly; otherwise the revision is dropped (`logger.info`) — prevents clobbering concurrent admin edits.
4. **Apply**: For `kind="line"`, writes `line.audio = revised_audio` AND `line.audio_url = None`. For `kind="check_in_*"`, writes the corresponding check-in field. Clearing `audio_url` is the contract with `audio_synthesis` (skips lines with `audio_url` set), so re-synthesis is automatic and idempotent for only the revised lines.
5. **Snapshot**: Each card's review is captured in `stage_snapshots_json` with `revisions_proposed` + `revisions_applied` counts, for the admin stage viewer.

### LLM Config

`audio_text_review` in `llm_config` table, with fallback to `explanation_generator` if the primary key is missing. Claude Code is recommended for cost.

### Entry Points

- `review_guideline(guideline, *, variant_keys=None, ...)` — review all variants for a single topic
- `review_chapter(book_id, chapter_id=None, *, job_service=None, job_id=None)` — iterate approved guidelines, drive a job

### Triggers

- **Per-book / per-chapter**: `POST /admin/v2/books/{book_id}/generate-audio-review?chapter_id=&guideline_id=&language=` — kicks off a `v2_audio_text_review` fan-out (one job per APPROVED guideline).
- **Per-topic**: Same endpoint with `guideline_id` set, or the `Review audio` button on each topic row in `ExplanationAdmin`.
- **`audio_synthesis` soft guardrail**: If admin triggers synthesis without a prior completed review for the scope, `POST /generate-audio` returns HTTP 409 with `{code:"no_audio_review", requires_confirmation:true}`. Re-call with `?confirm_skip_review=true` to bypass.

### Observability

- `stage_snapshots_json` entries on the job row, viewable via the existing stage viewer
- `GET /admin/v2/books/{book_id}/audio-review-jobs/latest` mirrors `/explanation-jobs/latest` for this job type

### Gold / Defective Test Fixtures

- `tests/fixtures/audio_review/defective_set.json` — 20 handcrafted cards with deliberate single-defect injections (symbol-leak, visual-only, run-on, redundancy, hinglish)
- `tests/fixtures/audio_review/clean_set.json` — 20 known-clean cards, reviewer should return empty revisions
- `tests/manual/audio_review_gold_eval.py` — manual-run script measuring PRD SC2/SC3 against these sets

---

## Audio Synthesis (TTS)

**Service:** `book_ingestion_v2/services/audio_generation_service.py` (`AudioGenerationService`)

Pre-computes Google Cloud TTS MP3s for every `audio` line on variant A explanation cards, every dialogue card, and every check-in field. Uploads to S3 and writes back URLs into the appropriate JSON columns. Not an LLM stage.

### Provider & voices

Google Cloud TTS via API key (`GOOGLE_CLOUD_TTS_API_KEY`). MP3 encoding.

| Use | Language code | Voice name |
|---|---|---|
| `en` (default for variant A audio_text) | `en-US` | `en-US-Chirp3-HD-Kore` |
| `hi` / `hinglish` | `hi-IN` | `hi-IN-Chirp3-HD-Kore` |
| Baatcheet tutor (Mr. Verma) | `hi-IN` | `hi-IN-Chirp3-HD-Kore` |
| Baatcheet peer (Meera) | `hi-IN` | `hi-IN-Chirp3-HD-Leda` |

Pre-synthesis fixup: rewrites bare `\\bus\\b` → `uss` so Chirp 3 HD's normalizer doesn't read it as the country abbreviation under the hi-IN voices (`normalize_tts_text`). Chirp 3 HD doesn't support SSML.

### Pipeline

1. **Variant A explanations**: For each line in `cards_json`, skip if `line.audio_url` is set or `line.audio` empty. S3 key `audio/{guideline_id}/{variant_key}/{card_idx}/{line_idx}.mp3`.
2. **Check-in fields** (always: `audio_text` / `hint` / `success_message`; predict_then_reveal also: `reveal_text`): UUID-keyed S3 path `audio/{guideline_id}/{variant_key}/{card_id}/check_in/{key_suffix}.mp3`. Reinsert at a different `card_idx` doesn't serve stale audio.
3. **Baatcheet dialogue** (when `topic_dialogues` row exists): Routes voice per `card.speaker` (`peer` → Meera; otherwise tutor). S3 path `audio/{guideline_id}/dialogue/{card_id}/{line_idx}.mp3`. Skips lines where `includes_student_name=True` (runtime TTS handles those at session start with the actual name) or `audio` contains `{student_name}` placeholder.
4. **Stamp URL**: Set the corresponding `audio_url` field, `flag_modified(explanation_or_dialogue, "cards_json")`, commit.

`count_audio_items()` and `count_dialogue_audio_items()` are static — used by `audio_synthesis` stage status to count `total_clips / clips_with_audio` without instantiating a TTS client.

### Trigger & guardrail

`POST /generate-audio?confirm_skip_review=false|true` with scoping `guideline_id` > `chapter_id` > book-wide. Soft guardrail: if no completed `v2_audio_text_review` job exists for the scope, the endpoint returns HTTP 409 with `{code:"no_audio_review", requires_confirmation:true}`. Frontend re-calls with `confirm_skip_review=true` to bypass.

### Entry points

- `generate_for_cards(cards_json, guideline_id, variant_key)` — mutate cards in place
- `generate_for_topic_explanation(explanation, dry_run=False)` — variant-A path
- `generate_for_topic_dialogue(dialogue, dry_run=False)` — Baatcheet path

### Background job

`v2_audio_generation`. Per-topic granularity. Errors (first 10) surfaced in job `detail`. Idempotent at line+field granularity — no `force`. To regenerate a single line, clear its `audio_url` first.

---

## Practice Bank Generation

**Service:** `book_ingestion_v2/services/practice_bank_generator_service.py` (`PracticeBankGeneratorService`)

Generates 30-40 mixed-format practice questions per topic, stored in `practice_questions` (one row per question, JSONB payload). Mutable — `force` wipes and regenerates.

### Pipeline

1. **Pre-flight**: Fail if `v2_explanation_generation` / `v2_visual_enrichment` / `v2_check_in_enrichment` is running on the same chapter.
2. **Load grounding**: Pull variant A `cards_json` (visual/audio stripped) for prompt context.
3. **Generate**: LLM with `practice_bank_generation.txt` prompt and strict `PracticeBankOutput` schema. `reasoning_effort` per `practice_bank_generator` LLM config.
4. **Review-refine N rounds**: `practice_bank_review_refine.txt` (correctness-focused, fail-open).
5. **Validate**: Format-specific structural checks (option counts, no duplicates, sensible bucket distributions, etc.); free-form bound `MIN_FREE_FORM=0` to `MAX_FREE_FORM=3`; deduped on question text.
6. **Top-up**: If valid count < `TARGET_BANK_SIZE = 30`, run another generation pass (max `MAX_GENERATION_ATTEMPTS = 3`).
7. **Wipe + bulk insert** (with `force` only): delete existing rows, bulk insert via `PracticeQuestionRepository.bulk_insert`.

If after all attempts valid_count < 30, the run fails (operations aborts insert). Cap at `MAX_BANK_SIZE = 40` before insert.

### Question formats

`pick_one`, `true_false`, `fill_blank`, `match_pairs`, `sort_buckets`, `sequence`, `spot_the_error`, `odd_one_out`, `predict_then_reveal`, `swipe_classify`, `tap_to_eliminate`, `free_form`. Each row stores `format`, `difficulty` (easy/medium/hard), `concept_tag`, and the full format-specific payload in `question_json` (including `correct_*`, `explanation_why`, `expected_answer`+`grading_rubric` for free_form).

### Entry points

- `enrich_guideline(guideline, force, review_rounds, heartbeat_fn)` — one topic
- `enrich_chapter(book_id, chapter_id, force, review_rounds, job_service, job_id)` — chapter-wide

### Background job

`v2_practice_bank_generation`. LLM config key: `practice_bank_generator` (falls back to `explanation_generator`).

---

## Baatcheet Dialogue Generation (Stage 5b)

**Service:** `book_ingestion_v2/services/baatcheet_dialogue_generator_service.py` (`BaatcheetDialogueGeneratorService`)

Two-step LLM generation of a conversational dialogue between Mr. Verma (tutor) and Meera (peer) for one guideline, anchored on variant A explanations. Stored as a single row in `topic_dialogues`.

### Pipeline

1. **Lesson plan** (Step 1): LLM with `baatcheet_lesson_plan_generation.txt` produces a `plan_json` containing misconceptions, spine, macro_structure, and `card_plan` (per-slot intent + `visual_required` flag). Validates required top-level keys.
2. **Generate cards 2..N** (Step 2): LLM with `baatcheet_dialogue_generation.txt` using `plan_json` as the spec. Welcome card 1 is NOT LLM-generated.
3. **Review-refine N rounds** (Step 3): `baatcheet_dialogue_review_refine.txt` with `validator_issues` from each round fed back to the next as a self-correction signal. Early-exits when validators come back clean.
4. **Prepend welcome card 1**: Server-side template `WELCOME_CARD_TEMPLATE` substitutes `{student_name}` and `{topic_name}`; sets `card_idx=1`, `includes_student_name=True`, `card_type="welcome"`. Re-indexes the deck.
5. **Final validation** (`raise_on_fail=True`): Card-count bounds (`MIN_TOTAL_CARDS=25`, `MAX_TOTAL_CARDS=42`), banned audio patterns (markdown `**`, naked `=`, emoji), check-in spacing (`MIN_CHECK_IN_SPACING=4`), `includes_student_name`/`{student_name}` placeholder consistency, supported activity types. No silent truncation — failure raises `DialogueValidationError`.
6. **Persist with content hash**: `compute_explanation_content_hash(variant_a.cards_json, variant_a.summary_json)` stamped on the dialogue row as `source_content_hash`. Drives staleness via `DialogueRepository.is_stale()`.

`_refresh_db_session()` is called after each long LLM call so the connection isn't held during minutes of generation. Refresher topics (`is_refresher=true`) are skipped at the route level — the service is unaware.

### Card schema

Cards are stored as JSON: `card_id` (UUID, mandatory), `card_idx`, `card_type` (welcome/tutor_turn/peer_turn/visual/check_in/summary), `speaker` (tutor/peer), `lines: [{display, audio}]`, optional `visual_intent`, optional `check_in` (11 supported activity types — same set as practice bank minus `free_form`).

### Background job

`v2_baatcheet_dialogue_generation`. LLM config key: `baatcheet_dialogue_generator` (falls back to `explanation_generator`). Uses split-prompt (`_system.txt` files) for `claude_code` provider.

### Stale signal

`DialogueRepository.is_stale()` returns True iff variant A's current content hash differs from the dialogue's stored `source_content_hash`. Stage status surfaces this as a warning + "(stale)" suffix.

---

## Baatcheet Visual Enrichment (Stage 5c)

**Service:** `book_ingestion_v2/services/baatcheet_visual_enrichment_service.py` (`BaatcheetVisualEnrichmentService`)

Fills `visual_explanation.pixi_code` slots on Baatcheet dialogue cards. Two paths.

**V2 path (dialogue.plan_json present):** LLM selector picks 12-18 cards from the lesson plan + dialogue based on the plan's `visual_required` flags and a default-generate rule, returning `visual_intent` per selected card. `PixiCodeGenerator` (reused from runtime tutor service) turns each intent into PixiJS code.

**V1 fallback (no plan_json):** iterate cards where `card_type == "visual"` — V1 dialogues already named those out and attached `visual_intent`.

Idempotent per `(guideline_id, card_idx)`: cards with existing `visual_explanation.pixi_code` are skipped unless `force=True`.

### Stage `done` rule

V2: stage is `done` only when every plan slot with `visual_required=True` has `pixi_code`. Default-generate cards (selector picked but plan didn't require) are surfaced as "extras" in the status summary but do NOT gate `done`. V1: `done` when every `card_type=="visual"` card has `pixi_code`.

### Background job

`v2_baatcheet_visual_enrichment`. Reuses `animation_code_gen` LLM config for code generation.

---

## Baatcheet Audio Review (opt-in)

**Service:** `book_ingestion_v2/services/baatcheet_audio_review_service.py` (`BaatcheetAudioReviewService`)

Wraps `AudioTextReviewService._review_card` + `_apply_revisions` against `topic_dialogues.cards_json` instead of variant A. Same defect classes, same drift guard. Stage 5b validators already enforce deterministic audio defects (markdown/equals/emoji); this is an admin safety valve for subtle defects an LLM reviewer might catch.

Trigger: `POST /review-baatcheet-audio` (admin button, NOT auto-run during the default DAG). Job type `v2_baatcheet_audio_review`. Not part of the DAG (`launcher_map.JOB_TYPE_TO_STAGE_ID` intentionally omits it).

---

## Check-In Enrichment

**Service:** `book_ingestion_v2/services/check_in_enrichment_service.py` (`CheckInEnrichmentService`)

Inserts inline interactive `check_in` cards between explanation cards. Reads/writes the same `topic_explanations.cards_json` array. Decoupled from explanation generation — runs after explanations (and optionally visuals) exist.

### Activity Types

| Type | Fields |
|------|--------|
| `pick_one` | 2-3 `options`, `correct_index` |
| `true_false` | `statement`, `correct_answer` |
| `fill_blank` | 2-3 `options`, `correct_index` |
| `match_pairs` | 2-3 `pairs` (left/right) |
| `sort_buckets` | 2 `bucket_names`, 4-6 `bucket_items` (each with `correct_bucket` 0/1) |
| `sequence` | 3-4 `sequence_items` in correct order |

### Pipeline Per Variant

1. **Pre-flight**: Fail-fast if a `v2_explanation_generation` or `v2_visual_enrichment` job is running on the same chapter.
2. **Skip check**: If any card is already `card_type == "check_in"` and not `force`, skip the variant. Strip existing check-ins before regenerating.
3. **Generate**: Calls LLM with `check_in_generation.txt` prompt and `reasoning_effort="medium"`. Cards passed to the prompt are stripped of `visual_explanation` and `audio_text` to save tokens. Returns `CheckInGenerationOutput` with a flat list of `CheckInDecision` items (one per check-in to insert).
4. **Validate**: Drops check-ins with unknown activity_type, invalid `insert_after_card_idx`, placement before card 3, missing hint/success_message, type-specific failures (wrong option count, duplicates, all items in one bucket, etc.), or insufficient gap (`MIN_GAP=1`) from the previous accepted check-in.
5. **Insert**: Builds new `card_type="check_in"` cards (each with a UUID `card_id` and `check_in` payload), inserts at the correct positions, then re-numbers `card_idx` 1-based.
6. **Persist**: Updates `cards_json` via `flag_modified` and commits.

### Entry Points

- `enrich_guideline(guideline, force=False, variant_keys=None, heartbeat_fn=None)`: single guideline
- `enrich_chapter(book_id, chapter_id=None, force=False, job_service, job_id)`: chapter or book-wide

### LLM Config

Reads config key `check_in_enrichment` first, falls back to `explanation_generator` if missing.

Runs as a background job with `v2_check_in_enrichment` job type.

---

## Refresher Topic Generation

**Service:** `book_ingestion_v2/services/refresher_topic_generator_service.py` (`RefresherTopicGeneratorService`)

Generates a "Get Ready" prerequisite refresher topic for a chapter. Stored as a special `TeachingGuideline` with `topic_key="get-ready"` and `topic_sequence=0`.

### Pipeline

1. Loads all non-refresher guidelines for the chapter and their explanation cards
2. Loads other chapters' topics (cross-chapter context for prerequisite identification)
3. Deletes any existing refresher for the chapter (idempotent)
4. Calls LLM with `refresher_topic_generation.txt` prompt and `reasoning_effort="high"` returning `RefresherOutput`:
   - `skip_refresher` + `skip_reason` — if true, no refresher is created
   - `prerequisite_concepts` (list of concept + why_needed)
   - `refresher_guideline` (teaching guideline text)
   - `topic_summary`
   - `cards` (list of `ExplanationCardOutput`)
5. Stores `TeachingGuideline` with `metadata_json={"is_refresher": true, "prerequisite_concepts": [...]}`
6. Stores `TopicExplanation` variant `"A"` (label "Prerequisite Refresher") via `ExplanationRepository.upsert`

### Entry Points

- `generate_for_chapter(book_id, chapter_key)`: returns guideline_id or None if skipped

### LLM Config

Uses the `explanation_generator` config key.

Runs as a background job with `v2_refresher_generation` job type. The chapter must already have synced (non-refresher) guidelines.

The `/landing` endpoint reads the refresher's `metadata_json` to surface prerequisite concepts on the chapter landing screen.

---

## Topic Pipeline DAG

Single source of truth: `book_ingestion_v2/dag/topic_pipeline_dag.py` composes a `TopicPipelineDAG` from the per-stage `STAGE` exports under `book_ingestion_v2/stages/`. Adding a stage = create `stages/{stage_id}.py` exporting `STAGE = Stage(...)` and append to `STAGES`. `DAG.validate_acyclic()` runs at import.

**8 stages** with these declared dependencies:

```
explanations  ──┬─►  visuals
                ├─►  check_ins
                ├─►  practice_bank
                ├─►  baatcheet_dialogue ──►  baatcheet_visuals
                └─►  audio_review ──►  audio_synthesis
```

`audio_synthesis` declares only `audio_review` as a hard dep. Baatcheet dialogue is a **soft join** at runtime: if a dialogue exists, synthesis covers its MP3s too; otherwise just variant A. (Modelling it as a hard dep would make a dialogue regen mark synthesis fully stale even though variant-A MP3s are unchanged.)

**Per-topic serialization.** Partial unique index `idx_chapter_active_topic_job` on `chapter_processing_jobs` enforces ≤1 active job per `(chapter_id, guideline_id)`. visuals / check_ins / audio_synthesis all mutate `topic_explanations.cards_json` in-place — concurrent writes would race. Throughput comes from cross-topic parallelism (chapter runner spawns multiple orchestrators).

**Stage states:** `done` / `warning` / `running` / `ready` / `blocked` / `failed`.

**Staleness anchor:** `max(topic_explanations.created_at)` for the guideline. Explanation regeneration delete+inserts (advances anchor); visuals / check_ins / audio synthesis write `cards_json` in-place (do NOT advance anchor). practice_bank, audio_review, baatcheet_dialogue carry stale flags. baatcheet_dialogue uses `source_content_hash` (not timestamps) because variant A is mutated in-place.

### Stage modules

Each module under `book_ingestion_v2/stages/` exports a `STAGE = Stage(...)` with `id`, `scope`, `label`, `depends_on`, `launch`, `status_check`. The Stage dataclass lives in `dag/types.py`. `StatusContext` bundles `db`, `guideline_id`, `chapter_id`, preloaded `explanations`, and `content_anchor`.

| Stage | File | Job type | Launcher | Depends on |
|---|---|---|---|---|
| `explanations` | `stages/explanations.py` | `v2_explanation_generation` | `launch_explanation_job` | (none) |
| `baatcheet_dialogue` | `stages/baatcheet_dialogue.py` | `v2_baatcheet_dialogue_generation` | `launch_baatcheet_dialogue_job` | `explanations` |
| `baatcheet_visuals` | `stages/baatcheet_visuals.py` | `v2_baatcheet_visual_enrichment` | `launch_baatcheet_visual_job` | `baatcheet_dialogue` |
| `visuals` | `stages/visuals.py` | `v2_visual_enrichment` | `launch_visual_job` | `explanations` |
| `check_ins` | `stages/check_ins.py` | `v2_check_in_enrichment` | `launch_check_in_job` | `explanations` |
| `practice_bank` | `stages/practice_bank.py` | `v2_practice_bank_generation` | `launch_practice_bank_job` | `explanations` |
| `audio_review` | `stages/audio_review.py` | `v2_audio_text_review` | `launch_audio_review_job` | `explanations` |
| `audio_synthesis` | `stages/audio_synthesis.py` | `v2_audio_generation` | `launch_audio_synthesis_job` | `audio_review` |

`v2_baatcheet_audio_review` is an opt-in safety valve, NOT part of the default DAG.

### Two orchestrators

**`TopicPipelineOrchestrator`** (`services/topic_pipeline_orchestrator.py`) — synchronous, polls each launched stage's `job_id` to terminal state. Used by the legacy super-button. Halts on failure. `run_chapter_pipeline_all()` wraps it with bounded parallelism (`TOPIC_PIPELINE_MAX_PARALLEL_TOPICS = 4` default); per-topic failures do not halt other topics.

Polls by the `job_id` returned from each launcher (NOT `get_latest_job`, which would race with a freshly-committed job row). Two safety nets against orphaned jobs: heartbeat staleness (`HEARTBEAT_STALE_THRESHOLD = 30 min`, primary) and absolute wall-time cap (`MAX_POLL_WALL_TIME_SEC = 4 h`, fallback).

**`CascadeOrchestrator`** (`dag/cascade.py`) — event-driven, in-memory singleton. Triggered by terminal-write hook in `run_in_background_v2`. State is keyed on `guideline_id`; one cascade per topic at a time. Process-restart drops active cascades. Halt-on-failure clears the pending queue and clears stale flags this cascade flagged at kickoff (failed rerun left upstream unchanged). `cancel()` = soft-cancel (running stage finishes, no further launches).

### Quality levels

`QUALITY_ROUNDS` in `topic_pipeline_orchestrator.py`:

| Quality | explanations | visuals | check_ins | practice_bank | baatcheet_dialogue |
|---|---|---|---|---|---|
| fast | 0 | 0 | 0 | 0 | 0 |
| balanced | 2 | 1 | 1 | 2 | 1 |
| thorough | 3 | 2 | 2 | 3 | 2 |

`baatcheet_visuals`, `audio_review`, `audio_synthesis` take no review_rounds.

### Topic Pipeline endpoints

`book_ingestion_v2/api/sync_routes.py` (prefix `/admin/v2/books/{book_id}`):

| Method | Path | Description |
|---|---|---|
| GET | `.../chapters/{chapter_id}/topics/{topic_key}/pipeline` | Consolidated 8-stage status for one topic |
| POST | `.../chapters/{chapter_id}/topics/{topic_key}/run-pipeline` | Legacy super-button (TopicPipelineOrchestrator) |
| GET | `.../chapters/{chapter_id}/pipeline-summary` | Per-topic stage_counts roll-up for chapter chip |
| POST | `.../chapters/{chapter_id}/run-pipeline-all` | Chapter-wide fan-out via `run_chapter_pipeline_all()` |

### DAG cascade endpoints

`book_ingestion_v2/api/dag_routes.py` (prefix `/admin/v2`):

| Method | Path | Description |
|---|---|---|
| GET | `/dag/definition` | Static DAG topology (stages, edges) |
| GET | `/topics/{guideline_id}/dag` | Per-stage durable state from `topic_stage_runs` + cascade summary; lazy-backfills missing rows |
| POST | `/topics/{guideline_id}/stages/{stage_id}/rerun` | Cascade from one stage; descendants flagged stale |
| POST | `/topics/{guideline_id}/dag/run-all` | Cascade over every not-done stage |
| POST | `/topics/{guideline_id}/dag/cancel` | Soft-cancel any active cascade |
| GET | `/topics/{guideline_id}/cross-dag-warnings` | Phase 6 cross-DAG warning banner (chapter_resynced) |

Cascade conflicts return 409 with `code` ∈ `cascade_active`, `upstream_not_done`, `stage_running`. Test-only POST endpoints `cross-dag-warnings/_test/diverge` and `_test/restore` exist for E2E (not in OpenAPI schema).

### Cross-DAG warnings (Phase 6)

`dag/cross_dag_warnings.py` — surfaces when upstream DAG events (topic_sync, refresher generation, in-place admin edits) leave the live guideline diverging from the hash captured at the last successful `explanations` run. Banner kind: `chapter_resynced`. Clears automatically on the next successful explanations run.

- **Hash inputs:** `(guideline_text, prior_topics_context, topic_title)` joined with `\x1f` (mirrors `ExplanationGeneratorService`'s effective inputs). NULL == empty string.
- **Storage:** `topic_content_hashes` table keyed on stable `(book_id, chapter_key, topic_key)` tuple, NOT `guideline_id` — `topic_sync` deletes-and-recreates guideline rows on every chapter resync; the hash row survives.
- **Capture point:** terminal-write hook in `run_in_background_v2`, fired only when `stage_id == "explanations" AND terminal_state == "done"`. Wrapped in its own try/except so a hash-write hiccup can't break the terminal write.
- **Read path:** `GET /admin/v2/topics/{guideline_id}/cross-dag-warnings` recomputes the live hash, compares to stored. Returns `{warnings: []}` if no captured baseline, no key (legacy guidelines without book_id/chapter_key/topic_key), or hashes match.

### Fan-out on legacy routes

`POST /generate-explanations`, `/generate-visuals`, `/generate-check-ins`, `/generate-practice-banks`, `/generate-audio-review`, `/generate-audio`, `/generate-baatcheet-dialogue`, `/generate-baatcheet-visuals`, `/review-baatcheet-audio` all return `FanOutJobResponse = { launched: int, job_ids: list[str], skipped_guidelines: list[str] }`. When `guideline_id` is omitted, the route resolves all APPROVED guidelines in scope (chapter or book) and launches one topic-level job per guideline. Topics with an active job are reported in `skipped_guidelines` rather than aborting the batch. Helper: `_fan_out` + `_resolve_lookup_scope` in `sync_routes.py`.

### Stage launchers

`book_ingestion_v2/services/stage_launchers.py` — each `launch_<stage>_job(db, *, book_id, chapter_id, guideline_id, ...)` acquires the topic-level lock via `ChapterJobService.acquire_lock`, calls `run_in_background_v2` with the stage's `_run_*` background task body (located in `sync_routes.py` to avoid import cycles), and returns the `job_id`. `LAUNCHER_BY_STAGE` lives in `dag/launcher_map.py` (derived from `DAG.stages`); stage_launchers exposes a PEP 562 shim for legacy import paths.

### Topic stage runs (Phase 2)

`topic_stage_runs` table — durable per-stage state, one row per `(guideline_id, stage_id)`. Written by the `run_in_background_v2` hook on stage entry (`state='running'`) and on terminal (`state in ('done','failed')`). Historical runs live in `chapter_processing_jobs`; this table is the queryable view used by the DAG dashboard and cascade orchestrator. `is_stale` flips via cascade kickoff/cleanup. `summary_json` carries arbitrary per-stage payload (e.g. `{error: "..."}`). Repository: `topic_stage_run_repository.py`.

`TopicPipelineStatusService.run_backfill_for_guideline()` — read-time lazy backfill so legacy topics from before Phase 2 populate rows on first dashboard view.

---

## Ingestion Quality Evaluation

**Module:** `autoresearch/book_ingestion_quality/`

Automated evaluation pipeline that scores topic extraction quality using an LLM judge. Runs offline from the command line, not from the web UI.

### How It Works

1. **Pipeline Runner** (`evaluation/pipeline_runner.py`, `PipelineRunner`) loads existing extracted topics from the DB (or optionally re-runs extraction fresh) and collects the full pipeline output: chapter metadata, book metadata, all topics with guidelines, and original OCR page texts.

2. **Evaluator** (`evaluation/evaluator.py`, `IngestionEvaluator`) sends the pipeline output to an LLM judge that scores across three dimensions:
   - **Granularity** -- Are topics split at the right level (not too broad, not too narrow)?
   - **Coverage depth** -- Do the guidelines cover the source material thoroughly?
   - **Copyright safety** -- Do the guidelines avoid verbatim or close-paraphrase copying?

   The evaluator returns per-dimension scores (1-10), per-topic assessments, a list of problems with root cause categories, and a summary.

3. **Report Generator** (`evaluation/report_generator.py`, `IngestionReportGenerator`) saves all run artifacts to a timestamped directory under `evaluation/runs/`:
   - `config.json` -- Run configuration
   - `pipeline_output.json` -- Raw topics and pages
   - `topics.md` -- Human-readable topic listing
   - `evaluation.json` -- Machine-readable scores and problems
   - `review.md` -- Human-readable evaluation review with score tables, per-topic assessment, and problems

4. **Email Report** (`email_report.py`) optionally sends a plain-text summary email with a comprehensive HTML report attached (uses macOS Mail.app via osascript).

### Configuration

**Config class:** `evaluation/config.py` (`IngestionEvalConfig`)

- **Evaluator provider:** OpenAI (default), Anthropic, or `claude_code`, set via `EVAL_LLM_PROVIDER` env var or `--provider` flag. Can also be read from DB via `IngestionEvalConfig.from_db()` using the `eval_evaluator` LLM config key.
- **OpenAI evaluator:** `gpt-5.2` with `reasoning_effort="high"` and JSON output mode
- **Anthropic evaluator:** `claude-opus-4-6` with extended thinking (budget: 20000 tokens)
- **claude_code provider:** Delegates to Claude Code as the evaluator
- **API keys:** Read from `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` environment variables

### CLI Usage

```bash
cd llm-backend

# Evaluate existing topics (no re-extraction)
python -m autoresearch.book_ingestion_quality.run_experiment --chapter-id <id> --skip-extraction

# Run fresh extraction + evaluate
python -m autoresearch.book_ingestion_quality.run_experiment --chapter-id <id>

# Multiple runs for variance reduction
python -m autoresearch.book_ingestion_quality.run_experiment --chapter-id <id> --skip-extraction --runs 3

# Use Anthropic as evaluator
python -m autoresearch.book_ingestion_quality.run_experiment --chapter-id <id> --skip-extraction --provider anthropic

# With email report
python -m autoresearch.book_ingestion_quality.run_experiment --chapter-id <id> --skip-extraction --email user@example.com
```

Results are appended to `evaluation/results.tsv` when `--description` is provided.

### Root Cause Categories

The judge classifies problems into: `over_splitting`, `under_splitting`, `missing_coverage`, `shallow_guidelines`, `verbatim_copy`, `paraphrase_copy`, `wrong_scope`, `missing_prerequisites`, `missing_misconceptions`, `sequence_error`, `other`.

### Judge Prompt

**File:** `evaluation/prompts/judge.txt` -- Rubric and instructions for the LLM judge.

---

## Study Plan Generation

**Module:** `study_plans/`

Study plans are generated from teaching guidelines and consumed by the tutor at session start. Two plan types exist. There is no longer a `StudyPlanOrchestrator` — the tutor (`tutor/services/session_service.py`) instantiates `StudyPlanGeneratorService` directly and persists the result to `study_plans`.

### Standard Study Plan Generator

**Service:** `study_plans/services/generator_service.py` (`StudyPlanGeneratorService`)

- Loads `study_plan_generator` prompt template via `shared/prompts/loader.py` (`PromptLoader`)
- Calls LLM with `reasoning_effort="high"` and strict JSON schema (`StudyPlan` Pydantic model via `LLMService.make_schema_strict()`)
- Output structure (`StudyPlan` model in `generator_service.py`):
  - `todo_list`: 3-5 `StudyPlanStep` items, each with step_id, title, description, teaching_approach, success_criteria, building_blocks, analogy, status
  - `metadata`: `StudyPlanMetadata` with plan_version, estimated_duration_minutes, difficulty_level, is_generic, creative_theme
- Validates output against both Pydantic model and legacy schema checks (`_validate_plan_schema()`)
- Supports optional student personalization via `StudentContext` (imported from `tutor.models.messages`) with fields: student_name, student_age, preferred_examples, attention_span, tutor_brief
- `generate_plan_with_feedback()`: generates adjusted plan mid-session based on parent/student feedback. Appends feedback context (feedback text, concepts already covered, progress) to the prompt.

### Session Plan Generator

**Service:** `study_plans/services/generator_service.py` (`StudyPlanGeneratorService.generate_session_plan()`)

Generated after a student reads explanation cards and indicates understanding. Creates an interactive follow-up plan tailored to the explanation variants the student saw.

- Loads `session_plan_generator` prompt template
- Calls LLM with `reasoning_effort="high"` and strict JSON schema (`SessionPlan`)
- Input context: explanation summaries (teaching_notes, key_analogies, key_examples), card titles, variants shown, guideline text, common misconceptions from metadata
- Output structure (`SessionPlan` model):
  - `steps`: 3-5 `SessionPlanStep` items, each with step_id, type (check_understanding / guided_practice / independent_practice / extend), concept, description, card_references, misconceptions_to_probe, success_criteria, difficulty, personalization_hint
  - `metadata`: `SessionPlanMetadata` with plan_version=2, variants_shown, estimated_duration_minutes, is_generic

### Reviewer (legacy, currently unused)

**Service:** `study_plans/services/reviewer_service.py` (`StudyPlanReviewerService`)

Reviews a generated plan using the `study_plan_reviewer` prompt and returns approved/rejected with feedback. Not currently called from any code path — kept in the module for potential future use. Plans are saved without a review pass.

---

## Database Tables

| Table | Purpose |
|-------|---------|
| `books` | Shared book table (V2 uses `pipeline_version=2`) |
| `book_chapters` | TOC entries and chapter state |
| `chapter_pages` | Individual pages with OCR tracking |
| `chapter_processing_jobs` | Background jobs for chapter-scope OCR/extraction/finalization AND topic-scope post-sync stages. Two partial unique indexes: chapter-level (`guideline_id IS NULL`) and topic-level (`(chapter_id, guideline_id)` when not null). Tracks heartbeat, `planned_topics_json`, `stage_snapshots_json`, `pipeline_run_id` (in `progress_detail`), and `model_provider`/`model_id` audit. |
| `chapter_chunks` | Per-chunk processing audit trail (3-page windows) |
| `chapter_topics` | Extracted topics (draft → consolidated → final); includes `prior_topics_context` and `topic_assignment` |
| `topic_stage_runs` | Phase 2 — durable per-stage state for the topic-pipeline DAG. PK `(guideline_id, stage_id)`. Written by the `run_in_background_v2` hook on stage entry/terminal. Carries `state`, `is_stale`, `started_at`, `completed_at`, `duration_ms`, `last_job_id`, `summary_json`. ON DELETE CASCADE from teaching_guidelines. |
| `topic_content_hashes` | Phase 6 — durable cross-DAG warning anchor. PK `(book_id, chapter_key, topic_key)` so it survives `topic_sync`'s delete-recreate. Stores `explanations_input_hash` + `last_explanations_at`. |
| `teaching_guidelines` | Synced guidelines used by the tutor; includes `prior_topics_context`. Refresher rows live here too: `topic_key="get-ready"`, `topic_sequence=0`, `metadata_json.is_refresher=true`. |
| `topic_explanations` | Pre-computed explanation card variants per guideline (JSONB cards including check-in cards, `visual_explanation` blobs, `audio_url` per line). Cascade-deleted with guideline. |
| `topic_dialogues` | Pre-computed Baatcheet dialogue per guideline. JSONB `cards_json` + `plan_json` (V2 lesson plan). `source_content_hash` snapshots variant A at generation time for staleness detection. Cascade-deleted with guideline. |
| `practice_questions` | Offline practice question bank (one row per question). 30-40 rows per guideline. JSONB `question_json` carries format-specific payload. Cascade-deleted with guideline. |
| `practice_attempts` | One row per practice attempt; `questions_snapshot_json` freezes the question payload at attempt time so bank regen can't orphan history. Partial unique index on `(user_id, guideline_id)` WHERE `status='in_progress'`. |
| `study_plans` | Generated study plans (per-guideline, optionally per-user) |

See `book_ingestion_v2/models/database.py` for V2 ORM models (`BookChapter`, `ChapterPage`, `ChapterProcessingJob`, `ChapterChunk`, `ChapterTopic`, `TopicStageRun`, `TopicContentHash`). `TopicExplanation`, `TopicDialogue`, `PracticeQuestion`, `PracticeAttempt`, `StudyPlan`, `TeachingGuideline` are in `shared/models/entities.py`.

---

## S3 Storage Layout

```
books/{book_id}/
  metadata.json
  toc_pages/
    page_1.png, page_2.png, ...
    extraction_result.json
  chapters/{ch_num}/
    pages/
      raw/{page_number}.{ext}      # Original upload
      {page_number}.png             # Converted PNG
      {page_number}.txt             # OCR text
    processing/
      runs/{job_id}/
        config.json
        planned_topics.json          # Topic skeleton from planning phase
        chunks/{idx}/
          input.json
          output.json
          state_after.json
        pre_consolidation.json
        consolidation_output.json
    output/
      chapter_result.json
      topics/{topic_key}.json       # Includes prior_topics_context and topic_assignment
```

---

## LLM Prompts

All prompts under `book_ingestion_v2/prompts/` unless noted. `_system.txt` files are loaded via `--append-system-prompt-file` for the `claude_code` provider.

| Prompt File | Used By | Purpose |
|-------------|---------|---------|
| `chapter_topic_planning.txt` | `ChapterTopicPlannerService` | Chapter-level topic skeleton before extraction |
| `toc_extraction.txt` | `TOCExtractionService` | Structured TOC from OCR text |
| `ocr_page_extraction.txt` | `OCRService` (V2_OCR_PROMPT) | Education-focused OCR prompt |
| `chunk_topic_extraction.txt` | `ChunkProcessorService` | Topic extraction from 3-page chunks (guided + unguided) |
| `topic_guidelines_merge.txt` | `ChapterFinalizationService` | Merge per-chunk guidelines |
| `chapter_consolidation.txt` | `ChapterFinalizationService` | Dedup, rename, sequence; track deviations |
| `curriculum_context_generation.txt` | `ChapterFinalizationService` | `prior_topics_context` for continuity |
| `explanation_generation.txt` (+ `_system.txt`) | `ExplanationGeneratorService` | Generate explanation cards |
| `explanation_review_refine.txt` (+ `_system.txt`) | `ExplanationGeneratorService` | Review + rewrite cards in place |
| `visual_decision_and_spec.txt` (+ `_system.txt`) | `AnimationEnrichmentService` | Decide which cards get visuals; write specs |
| `visual_code_generation.txt` | `AnimationEnrichmentService` | Generate PixiJS code from spec |
| `visual_code_review_refine.txt` | `AnimationEnrichmentService` | Refine PixiJS code; supports `{collision_report}` substitution from overlap detector |
| `visual_review.txt` | `AnimationEnrichmentService` | Visual quality review |
| `check_in_generation.txt` | `CheckInEnrichmentService` | Generate inline check-in activities |
| `check_in_review_refine.txt` | `CheckInEnrichmentService` | Review + refine check-in activities |
| `practice_bank_generation.txt` | `PracticeBankGeneratorService` | Generate 30-40 practice questions across 12 formats |
| `practice_bank_review_refine.txt` | `PracticeBankGeneratorService` | Correctness-focused review of practice questions |
| `audio_text_review.txt` (+ `_system.txt`) | `AudioTextReviewService` | Per-card review of audio strings; surgical revisions |
| `baatcheet_lesson_plan_generation.txt` (+ `_system.txt`) | `BaatcheetDialogueGeneratorService` | V2 lesson plan (misconceptions, spine, card_plan) |
| `baatcheet_dialogue_generation.txt` (+ `_system.txt`) | `BaatcheetDialogueGeneratorService` | Dialogue cards 2..N realizing the plan |
| `baatcheet_dialogue_review_refine.txt` (+ `_system.txt`) | `BaatcheetDialogueGeneratorService` | Refine dialogue with validator-issue feedback |
| `baatcheet_visual_intent.txt` | `BaatcheetVisualEnrichmentService` | LLM selector picks 12-18 cards + writes `visual_intent` |
| `baatcheet_visual_pass.txt` (+ `_system.txt`) | `BaatcheetVisualEnrichmentService` | Single-pass selector for V2 dialogues |
| `refresher_topic_generation.txt` | `RefresherTopicGeneratorService` | Identify prerequisites + generate "Get Ready" topic |
| `shared/prompts/templates/study_plan_generator.txt` | `StudyPlanGeneratorService` | 3-5 step study plan |
| `shared/prompts/templates/session_plan_generator.txt` | `StudyPlanGeneratorService.generate_session_plan()` | Post-explanation session plan |
| `shared/prompts/templates/study_plan_reviewer.txt` | `StudyPlanReviewerService` (legacy/unused) | Plan quality review |
| `autoresearch/book_ingestion_quality/evaluation/prompts/judge.txt` | `IngestionEvaluator` | Score extraction quality across granularity/coverage/copyright |

Legacy/unused prompts kept in `prompts/`: `explanation_critique.txt`, `explanation_refinement.txt` — replaced by `explanation_review_refine.txt`.

---

## Configuration

LLM config keys (rows in `llm_config` table; admin-tunable provider/model_id/reasoning_effort):

| Key | Used by | Fallback |
|---|---|---|
| `book_ingestion_v2` | OCR, planning, chunk extraction, finalization | — |
| `explanation_generator` | Explanation generation, refresher generation | — |
| `animation_enrichment` | Visual decide+spec | — |
| `animation_code_gen` | Visual + Baatcheet visual PixiJS code generation | — |
| `check_in_enrichment` | Check-in enrichment | `explanation_generator` |
| `practice_bank_generator` | Practice bank | `explanation_generator` |
| `audio_text_review` | Audio text review | `explanation_generator` |
| `baatcheet_dialogue_generator` | Baatcheet dialogue (Stage 5b) | `explanation_generator` |
| `study_plan_generator` | Study plans (runtime) | — |

Constants:

- **Chunk size / stride / retries:** `CHUNK_SIZE=3`, `CHUNK_STRIDE=3`, `CHUNK_MAX_RETRIES=3` (`constants.py`)
- **Heartbeat stale threshold:** `HEARTBEAT_STALE_THRESHOLD = 1800` (30 min) — accommodates Opus + high-effort
- **Pending stale threshold:** `PENDING_STALE_THRESHOLD = 300` (5 min)
- **Planning deviation gate:** `PLANNING_DEVIATION_THRESHOLD = 0.30`, `PLANNING_DEVIATION_MIN_COUNT = 3`
- **Explanation card limits:** `MIN_CARDS=3`, `MAX_CARDS=15` (`explanation_generator_service.py`)
- **Default variant count:** `DEFAULT_VARIANT_COUNT=1`; default review-refine rounds: `DEFAULT_REVIEW_ROUNDS=1`
- **Visual code max length:** `MAX_CODE_LENGTH=5000` (`animation_enrichment_service.py`)
- **IoU overlap threshold:** `0.05` (visual_overlap_detector)
- **Check-in placement:** never before card 3; `MIN_GAP=1` between check-ins
- **Practice bank target/max:** `TARGET_BANK_SIZE=30`, `MAX_BANK_SIZE=40`, `MAX_GENERATION_ATTEMPTS=3`, free-form bound `MIN_FREE_FORM=0`/`MAX_FREE_FORM=3`
- **Baatcheet card-count bounds:** `MIN_TOTAL_CARDS=25`, `MAX_TOTAL_CARDS=42`, `MIN_CHECK_IN_SPACING=4`
- **Topic pipeline parallelism:** `TOPIC_PIPELINE_MAX_PARALLEL_TOPICS = 4` (settings; `run_chapter_pipeline_all` default)
- **Orchestrator poll bounds:** `POLL_INTERVAL_SEC = 5`, `MAX_POLL_WALL_TIME_SEC = 4 * 60 * 60` (4 h)
- **Page image limits:** max 20 MB; PNG / JPG / JPEG / TIFF / WEBP
- **TOC image limits:** max 5 images, 10 MB each

---

## Frontend

| Component | File | Purpose |
|-----------|------|---------|
| BookV2Dashboard | `pages/BookV2Dashboard.tsx` | Lists all V2 books with card grid |
| CreateBookV2 | `pages/CreateBookV2.tsx` | Two-step wizard: metadata form → TOC editor (upload or manual) |
| BookV2Detail | `pages/BookV2Detail.tsx` | Expandable chapters, page grid, upload, processing, sync, refresher, jump links to per-chapter admin pages, jump to per-topic DAG dashboard |
| OCRAdmin | `pages/OCRAdmin.tsx` | Per-chapter OCR: grid, page detail modal, retry/bulk OCR controls |
| TopicsAdmin | `pages/TopicsAdmin.tsx` | Per-chapter extracted topics review; reprocess/refinalize |
| GuidelinesAdmin | `pages/GuidelinesAdmin.tsx` | Per-chapter synced guideline editing (text edit, approve, delete) |
| ExplanationAdmin | `pages/ExplanationAdmin.tsx` | Per-chapter explanation generation: variant counts, generate/refine_only, stage snapshot diff viewer, audio review button per topic |
| VisualsAdmin | `pages/VisualsAdmin.tsx` | Per-chapter visual enrichment: coverage stats, generate/strip, layout warning chip |
| PracticeBankAdmin | `pages/PracticeBankAdmin.tsx` | Per-chapter practice bank: question counts, generate/regenerate, full payloads |
| TopicDAGView | `components/TopicDAGView.tsx` | Per-topic React Flow DAG dashboard. BFS-depth auto-layout. Polls `topic_stage_runs` durably; click a node for the side panel with rerun + deep-link. Surfaces cross-DAG warning banner. |
| QualitySelector | `components/QualitySelector.tsx` | fast/balanced/thorough picker shared by run-pipeline buttons |
| VisualRenderPreview | `pages/VisualRenderPreview.tsx` | Admin-only Pixi preview at `/admin/visual-render-preview/:id`; the Playwright harness reaches in via `window.__pixiApp` |
| Admin API V2 | `api/adminApiV2.ts` | TypeScript client for V2 endpoints: books, TOC, pages, OCR, topics, sync, guidelines, explanations + stages, visuals, check-ins, practice bank, audio review, audio synthesis, baatcheet dialogue + visuals + audio review, refresher, landing, topic-pipeline (legacy), DAG topology + cascade + cross-dag-warnings |

All paths are relative to `llm-frontend/src/features/admin/`.

**Routes** (declared in `App.tsx`):
- `/admin/books-v2` — dashboard
- `/admin/books-v2/new` — create
- `/admin/books-v2/:id` — book detail
- `/admin/books-v2/:bookId/ocr/:chapterId` — OCR admin
- `/admin/books-v2/:bookId/topics/:chapterId` — topics admin
- `/admin/books-v2/:bookId/guidelines/:chapterId` — guidelines admin
- `/admin/books-v2/:bookId/explanations/:chapterId` — explanation admin (also surfaces baatcheet controls)
- `/admin/books-v2/:bookId/visuals/:chapterId` — visuals admin
- `/admin/books-v2/:bookId/practice-banks/:chapterId` — practice bank admin
- `/admin/books-v2/:bookId/pipeline/:chapterId/:topicKey` — `TopicDAGView` per-topic DAG dashboard
- `/admin/visual-render-preview/:id` — Pixi render preview (used by overlap harness)

**Polling:** Per-chapter admin pages poll `GET .../jobs/latest` every ~3s for active jobs; polling stops at terminal state. `TopicDAGView` polls `GET /admin/v2/topics/{guideline_id}/dag` and `/cross-dag-warnings`.

---

## Key Files

All paths relative to `llm-backend/` unless noted.

### Constants & models

| File | Purpose |
|------|---------|
| `book_ingestion_v2/constants.py` | Enums (`ChapterStatus`, `V2JobType` [13 job types incl. `v2_practice_bank_generation`, `v2_audio_text_review`, `v2_baatcheet_dialogue_generation`, `v2_baatcheet_visual_enrichment`, `v2_baatcheet_audio_review`], `V2JobStatus`, `OCRStatus`, `TopicStatus`), `HEARTBEAT_STALE_THRESHOLD=1800`, deviation thresholds |
| `book_ingestion_v2/models/database.py` | ORM: `BookChapter`, `ChapterPage`, `ChapterProcessingJob` (chapter + topic-level partial unique indexes), `ChapterChunk`, `ChapterTopic`, `TopicStageRun`, `TopicContentHash` |
| `book_ingestion_v2/models/schemas.py` | Pydantic request/response schemas — `StageId`, `StageState`, `StageStatus`, `TopicPipelineStatusResponse`, `RunPipelineRequest/Response`, `RunChapterPipelineAllRequest/Response`, `ChapterPipelineSummaryResponse`, `FanOutJobResponse`, `DAGStageDefinition`, `DAGDefinitionResponse`, `TopicDAGStageRow`, `TopicDAGResponse`, `CascadeInfo`, `StartCascadeRequest`, `RunAllCascadeRequest`, `CascadeKickoffResponse`, `CascadeCancelResponse`, `CrossDagWarning`, `CrossDagWarningsResponse`, plus per-domain status responses |
| `book_ingestion_v2/models/processing_models.py` | Pipeline internals: `ChunkWindow`, `TopicAccumulator`, `RunningState`, `PlannedTopic`, `ChapterTopicPlan`, `ChunkInput`, `ChunkExtractionOutput`, `ConsolidationOutput` (with `deviations`), `ConsolidationDeviation`, `FinalizationResult`, `TopicCurriculumContext` |
| `book_ingestion_v2/exceptions.py` | `StageGateRejected` (raised by `stage_gating.require_stage_ready`) |

### DAG package

| File | Purpose |
|------|---------|
| `book_ingestion_v2/dag/topic_pipeline_dag.py` | Single source of truth — composes `TopicPipelineDAG` from per-stage `STAGE` exports. `validate_acyclic()` runs at import. |
| `book_ingestion_v2/dag/types.py` | `Stage`, `TopicPipelineDAG` dataclasses; `StatusContext`, `StageScope`, `StageStatusOutput`, `LaunchFn`, `StatusCheckFn`, `StalenessCheckFn` |
| `book_ingestion_v2/dag/cascade.py` | Event-driven `CascadeOrchestrator` singleton. Halt-on-failure, soft-cancel, stale flag bookkeeping. `get_cascade_orchestrator()` / `reset_cascade_orchestrator()`. |
| `book_ingestion_v2/dag/launcher_map.py` | Derived `LAUNCHER_BY_STAGE` from DAG; `JOB_TYPE_TO_STAGE_ID` reverse lookup used by terminal-write hook (`v2_baatcheet_audio_review` intentionally omitted) |
| `book_ingestion_v2/dag/status_helpers.py` | Free functions used by every stage's `status_check`: `latest_job_for_guideline`, `derive_state`, `overlay_job_state`, `build_stage`, `build_blocked`, `job_failed`, `fmt_ago` |
| `book_ingestion_v2/dag/cross_dag_warnings.py` | Phase 6 — input hash compute + `topic_content_hashes` upsert/get; `capture_explanations_input_hash` is called from the terminal-write hook |

### Stages

| File | Purpose |
|------|---------|
| `book_ingestion_v2/stages/explanations.py` | Stage anchor; sets `content_anchor` for downstream staleness |
| `book_ingestion_v2/stages/visuals.py` | Variant A PixiJS coverage; surfaces `layout_warning_count` |
| `book_ingestion_v2/stages/check_ins.py` | Counts `card_type=="check_in"` cards on variant A |
| `book_ingestion_v2/stages/practice_bank.py` | Counts `practice_questions` rows; stale when `min(created_at) < content_anchor`; `_PRACTICE_DONE_THRESHOLD = 30` |
| `book_ingestion_v2/stages/audio_review.py` | Latest `v2_audio_text_review` job state; stale when `completed_at < content_anchor` |
| `book_ingestion_v2/stages/audio_synthesis.py` | Combined variant A + dialogue clip counting via `AudioGenerationService.count_audio_items` / `count_dialogue_audio_items` |
| `book_ingestion_v2/stages/baatcheet_dialogue.py` | Reads `topic_dialogues`; stale signal via `DialogueRepository.is_stale()` (content hash) |
| `book_ingestion_v2/stages/baatcheet_visuals.py` | V2 path: `done` only when every plan slot with `visual_required=True` has `pixi_code`; V1 fallback for legacy dialogues |

### Services

| File | Purpose |
|------|---------|
| `services/book_v2_service.py` | Book CRUD with cascade delete (S3 + chapters + topics + jobs) |
| `services/toc_extraction_service.py` | OCR + LLM TOC extraction (HEIF supported) |
| `services/toc_service.py` | TOC CRUD with validation (no overlap, sequential numbers, no edit after pages uploaded) |
| `services/chapter_page_service.py` | Page upload with inline OCR; `bulk_ocr()` |
| `services/chapter_topic_planner_service.py` | Chapter-level topic planning before extraction |
| `services/chunk_processor_service.py` | Single-chunk LLM processing (guided + unguided) |
| `services/topic_extraction_orchestrator.py` | Plan + extract + finalize chapter pipeline |
| `services/chapter_finalization_service.py` | Merge, consolidate, sequence; deviation tracking; curriculum context |
| `services/topic_sync_service.py` | Sync to `teaching_guidelines` (delete-recreate; cascades dialogue + practice + explanations) |
| `services/explanation_generator_service.py` | Variant generation + review-refine; `refine_only_for_guideline`/`_for_chapter` |
| `services/animation_enrichment_service.py` | PixiJS visual decide+spec → code → validate; post-refine overlap gate via render harness |
| `services/check_in_enrichment_service.py` | Insert check-in cards (`MIN_GAP=1`, never before card 3) |
| `services/practice_bank_generator_service.py` | 30-40 mixed-format practice questions; review-refine; structural validation; top-up generation |
| `services/audio_text_review_service.py` | Per-card LLM review of `audio` strings; surgical revisions; drift guard; clears `audio_url` |
| `services/audio_generation_service.py` | Google Cloud TTS for variant A + dialogue + check-in fields; per-speaker voice routing; `count_audio_items` / `count_dialogue_audio_items` |
| `services/baatcheet_dialogue_generator_service.py` | Stage 5b — two-step plan + dialogue; welcome card; validators; `_refresh_db_session()` between LLM calls |
| `services/baatcheet_visual_enrichment_service.py` | Stage 5c — V2 selector (plan + dialogue) + `PixiCodeGenerator` |
| `services/baatcheet_audio_review_service.py` | Wraps `AudioTextReviewService` against dialogue cards (opt-in) |
| `services/refresher_topic_generator_service.py` | "Get Ready" prerequisite topic + cards (special `topic_key="get-ready"`) |
| `services/chapter_job_service.py` | Lock acquisition (chapter + topic level), heartbeat, stale detection, snapshot persistence, stale-job reaper |
| `services/stage_launchers.py` | `launch_*` helpers for all 8 stages + opt-in baatcheet audio review; each acquires lock and spawns background task; PEP 562 shim for `LAUNCHER_BY_STAGE` |
| `services/stage_gating.py` | `require_stage_ready` — chapter-status prerequisites for chapter-scoped stages |
| `services/topic_pipeline_status_service.py` | Computes 8-stage pipeline status by delegating to each `Stage.status_check`; backfills `topic_stage_runs` on read |
| `services/topic_pipeline_orchestrator.py` | Synchronous super-button orchestrator. `QUALITY_ROUNDS`. `run_chapter_pipeline_all` wraps with bounded parallelism. |
| `services/visual_render_harness.py` | Playwright wrapper around the admin preview page; `preflight()` HEADs localhost:3000 at job start |
| `services/visual_preview_store.py` | TTL+LRU keyed store for Pixi code (closes reflected-XSS vector) |

### Repositories

| File | Purpose |
|------|---------|
| `book_ingestion_v2/repositories/chapter_repository.py` | `BookChapter` CRUD |
| `book_ingestion_v2/repositories/chapter_page_repository.py` | `ChapterPage` CRUD |
| `book_ingestion_v2/repositories/chunk_repository.py` | `ChapterChunk` audit |
| `book_ingestion_v2/repositories/topic_repository.py` | `ChapterTopic` CRUD |
| `book_ingestion_v2/repositories/processing_job_repository.py` | `ChapterProcessingJob` queries (incl. heartbeat staleness) |
| `book_ingestion_v2/repositories/topic_stage_run_repository.py` | `TopicStageRun` upsert (`upsert_started`, `upsert_terminal`, `mark_stale`, `list_for_topic`) |
| `shared/repositories/book_repository.py` | Shared book data access |
| `shared/repositories/explanation_repository.py` | `topic_explanations` CRUD (written by ingestion, read by tutor) |
| `shared/repositories/dialogue_repository.py` | `topic_dialogues` CRUD; `is_stale()` (content hash); `parse_cards()` |
| `shared/repositories/practice_question_repository.py` | `practice_questions` CRUD; `bulk_insert`, `count_by_guideline`, `delete_by_guideline` |
| `shared/repositories/practice_attempt_repository.py` | `practice_attempts` (snapshot-based) |
| `shared/repositories/guideline_repository.py` | `TeachingGuideline` queries; metadata parsing |

### API routes

| File | Purpose |
|------|---------|
| `book_ingestion_v2/api/book_routes.py` | Book CRUD |
| `book_ingestion_v2/api/toc_routes.py` | TOC extraction + CRUD |
| `book_ingestion_v2/api/page_routes.py` | Page upload, retry-OCR, page detail |
| `book_ingestion_v2/api/processing_routes.py` | `/process`, `/reprocess`, `/refinalize`, bulk OCR, `/jobs/latest`, `/topics`. `run_in_background_v2()` daemon-thread runner — also writes `topic_stage_runs` started/terminal rows, captures explanations input hash, and fires the cascade hook. |
| `book_ingestion_v2/api/sync_routes.py` | Sync, results, landing, guidelines admin, explanations + visuals + check-ins + practice bank + audio review + audio synthesis + baatcheet (dialogue / visuals / opt-in audio review) + refresher; legacy super-button (`/run-pipeline`, `/run-pipeline-all`, `/pipeline`, `/pipeline-summary`); `_run_*` background tasks + `_fan_out` + `_resolve_lookup_scope` helpers |
| `book_ingestion_v2/api/dag_routes.py` | Phase 3+ DAG admin: `/dag/definition`, `/topics/{guideline_id}/dag`, cascade rerun/run-all/cancel, `/cross-dag-warnings` (+ test-only diverge/restore endpoints, hidden from OpenAPI schema) |
| `book_ingestion_v2/api/visual_preview_routes.py` | `POST /admin/v2/visual-preview/prepare`, `GET /admin/v2/visual-preview/{id}` for Playwright overlap harness |

### Other

| File | Purpose |
|------|---------|
| `shared/models/entities.py` | ORM: `StudyPlan`, `TopicExplanation`, `TopicDialogue`, `PracticeQuestion`, `PracticeAttempt`, `TeachingGuideline`, `Book`, `LLMConfig`, etc. |
| `shared/utils/dialogue_hash.py` | `compute_explanation_content_hash` — semantic identity for dialogue staleness |
| `shared/utils/s3_client.py` | Wrapper around AWS S3 used by ingestion + audio synthesis |
| `study_plans/services/generator_service.py` | `StudyPlanGeneratorService` — `StudyPlan`/`StudyPlanStep`/`StudyPlanMetadata`/`SessionPlan`/`SessionPlanStep`/`SessionPlanMetadata` Pydantic models; `generate_plan`, `generate_plan_with_feedback`, `generate_session_plan` |
| `study_plans/services/reviewer_service.py` | Legacy/unused study plan reviewer |
| `tutor/services/session_service.py` | Tutor session entry — instantiates `StudyPlanGeneratorService` directly |
| `tutor/services/pixi_code_generator.py` | PixiJS code generation reused by Stage 5c |
| `scripts/reprocess_chapter_pipeline.py` | CLI for full chapter reprocessing |
| `.claude/scripts/super_pipeline.py` | Wrapper invoked by the `super-pipeline` slash command — resolves natural-language inputs, calls `/run-pipeline`, polls `/pipeline` |
| `autoresearch/book_ingestion_quality/run_experiment.py` | CLI entry point for ingestion evaluation |
| `autoresearch/book_ingestion_quality/evaluation/{evaluator,pipeline_runner,report_generator,config}.py` | LLM judge + report generation + run config |
| `autoresearch/book_ingestion_quality/evaluation/prompts/judge.txt` | Judge rubric |
