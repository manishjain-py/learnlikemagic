# Book Ingestion & Guidelines -- Technical

Pipeline architecture for extracting structured teaching guidelines from textbook page images using OCR + LLM processing.

---

## Pipeline Architecture

```
Create Book (metadata)
    |
    v
Define TOC (manual or OCR+LLM from TOC page images)
    |
    v
Upload Pages (per chapter, inline OCR on each page)
    |
    v
Chapter Topic Planning (LLM reads full chapter, produces topic skeleton)
    |
    v
Topic Extraction (3-page chunks, LLM assigns content to planned topics — guided mode)
    |
    v
Chapter Finalization (LLM merges, dedup, names, sequences, generates curriculum context)
    |
    v
Deviation Check (if extraction deviates from plan → needs_review, otherwise → completed)
    |
    v
Sync to teaching_guidelines table
    |
    v
Pre-Computed Explanations (LLM generate → critique → refine per variant)
    |
    v
Study Plan Generation (LLM generate → review → improve loop)
    |
    v
Session Plan Generation (post-explanation interactive plan, triggered at runtime)
```

All book ingestion code lives under `book_ingestion_v2/`. Study plan generation is a separate module under `study_plans/`. The ingestion quality evaluation pipeline lives under `autoresearch/book_ingestion_quality/`.

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

**API routes:** `book_ingestion_v2/api/page_routes.py` and `processing_routes.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `.../chapters/{chapter_id}/pages` | Upload page (multipart form: image + page_number) |
| GET | `.../chapters/{chapter_id}/pages` | List pages with completeness |
| GET | `.../chapters/{chapter_id}/pages/{page_num}` | Get page metadata |
| GET | `.../chapters/{chapter_id}/pages/{page_num}/detail` | Get page with presigned image URL + OCR text |
| DELETE | `.../chapters/{chapter_id}/pages/{page_num}` | Delete page |
| POST | `.../chapters/{chapter_id}/pages/{page_num}/retry-ocr` | Retry failed OCR |
| POST | `.../chapters/{chapter_id}/ocr-retry` | Bulk retry OCR for all pending/failed pages (background job) |
| POST | `.../chapters/{chapter_id}/ocr-rerun` | Reset all OCR and re-run from scratch (background job) |

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

- Only one active job (pending/running) per chapter, enforced by partial unique index
- Stale detection: running jobs with no heartbeat for 10 minutes are auto-marked failed; pending jobs stuck for 5 minutes are marked abandoned
- Progress updates include `current_item` description, `completed_items`/`failed_items` counts, and heartbeat timestamp
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

**API routes:** `book_ingestion_v2/api/sync_routes.py`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/v2/books/{book_id}/sync` | Sync all completed/needs_review chapters |
| POST | `/admin/v2/books/{book_id}/chapters/{chapter_id}/sync` | Sync single chapter |
| POST | `/admin/v2/books/{book_id}/generate-explanations` | Generate pre-computed explanations (query params: `chapter_id`, `guideline_id`, `force`) |
| GET | `/admin/v2/books/{book_id}/explanation-jobs/latest` | Latest explanation generation job (query params: `chapter_id`, `guideline_id`) |
| GET | `/admin/v2/books/{book_id}/explanation-status` | Per-topic variant counts for a chapter (required `chapter_id` query param) |
| GET | `/admin/v2/books/{book_id}/explanations` | Full card data for a topic (required `guideline_id` query param) |
| DELETE | `/admin/v2/books/{book_id}/explanations` | Delete explanations (requires `guideline_id` or `chapter_id` query param) |
| GET | `/admin/v2/books/{book_id}/results` | Book-level results overview |

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

### Pipeline Per Variant

1. **Generate**: Calls LLM with `explanation_generation.txt` prompt using `reasoning_effort="high"` and strict JSON schema (`GenerationOutput`). Produces 3-15 `ExplanationCardOutput` items (card_idx, card_type, title, content, optional visual, audio_text) plus `ExplanationSummaryOutput` (key_analogies, key_examples, teaching_notes). Includes `prior_topics_context` when available.
2. **Critique**: Calls LLM with `explanation_critique.txt` prompt using `reasoning_effort="medium"`. Returns `CritiqueOutput`: list of issues (card_idx, principle_violated, description), suggestions, and `overall_quality` (good / needs_improvement / poor).
3. **Refine** (if `needs_improvement`): Re-generates cards incorporating critique feedback. Uses same strict schema.
4. **Discard** (if `poor`): Variant is skipped entirely.
5. **Store**: Upserts to `topic_explanations` table via `ExplanationRepository`.

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

Study plans are generated from teaching guidelines and used by the tutor during sessions. Two plan types exist.

### Standard Study Plan Generator

**Service:** `study_plans/services/generator_service.py` (`StudyPlanGeneratorService`)

- Loads `study_plan_generator` prompt template via `shared/prompts/loader.py` (`PromptLoader`)
- Calls LLM with `reasoning_effort="high"` and strict JSON schema (`StudyPlan` Pydantic model via `LLMService.make_schema_strict()`)
- Output structure (`StudyPlan` model in `generator_service.py`):
  - `todo_list`: 3-5 `StudyPlanStep` items, each with step_id, title, description, teaching_approach, success_criteria, building_blocks, analogy, status
  - `metadata`: `StudyPlanMetadata` with plan_version, estimated_duration_minutes, difficulty_level, is_generic, creative_theme
- Validates output against both Pydantic model and legacy schema checks (`_validate_plan_schema()`)
- Supports optional student personalization via `StudentContext` (imported from `tutor.models.messages`) with fields: student_name, student_age, preferred_examples, attention_span, tutor_brief
- `generate_plan_with_feedback()`: generates adjusted plan mid-session based on parent/student feedback. Appends feedback context (feedback text, concepts already covered, progress) to the prompt. Skips the reviewer pass for speed.

### Session Plan Generator

**Service:** `study_plans/services/generator_service.py` (`StudyPlanGeneratorService.generate_session_plan()`)

Generated after a student reads explanation cards and indicates understanding. Creates an interactive follow-up plan tailored to the explanation variants the student saw.

- Loads `session_plan_generator` prompt template
- Calls LLM with `reasoning_effort="high"` and strict JSON schema (`SessionPlan`)
- Input context: explanation summaries (teaching_notes, key_analogies, key_examples), card titles, variants shown, guideline text, common misconceptions from metadata
- Output structure (`SessionPlan` model):
  - `steps`: 3-5 `SessionPlanStep` items, each with step_id, type (check_understanding / guided_practice / independent_practice / extend), concept, description, card_references, misconceptions_to_probe, success_criteria, difficulty, personalization_hint
  - `metadata`: `SessionPlanMetadata` with plan_version=2, variants_shown, estimated_duration_minutes, is_generic

### Reviewer

**Service:** `study_plans/services/reviewer_service.py` (`StudyPlanReviewerService`)

- Reviews generated plans using `study_plan_reviewer` prompt
- Returns approved/rejected with feedback and suggested improvements

### Orchestrator

**Service:** `study_plans/services/orchestrator.py` (`StudyPlanOrchestrator`)

- Takes separate `generator_llm` and `reviewer_llm` `LLMService` instances (can be different models)
- Generate -> Review -> (optional) Improve loop:
  1. `generator.generate_plan(guideline)` produces initial plan
  2. `reviewer.review_plan(plan, guideline)` returns approved/rejected with feedback and suggested_improvements
  3. If rejected, `_improve_plan()` calls the reviewer LLM with `study_plan_improve` prompt for a single revision pass
  4. If improvement fails, saves the original plan anyway
- Persists to `study_plans` table with generator_model, reviewer_model, generation_reasoning, reviewer_feedback, was_revised flag, version tracking
- `get_study_plan()` returns cached plan if exists; `generate_study_plan(force_regenerate=True)` regenerates

---

## Database Tables

| Table | Purpose |
|-------|---------|
| `books` | Shared book table (V2 uses `pipeline_version=2`) |
| `book_chapters` | TOC entries and chapter state |
| `chapter_pages` | Individual pages with OCR tracking |
| `chapter_processing_jobs` | Background job tracking with heartbeat; also stores `planned_topics_json` |
| `chapter_chunks` | Per-chunk processing audit trail |
| `chapter_topics` | Extracted topics (draft -> consolidated -> final); includes `prior_topics_context` and `topic_assignment` |
| `teaching_guidelines` | Synced guidelines used by the tutor; includes `prior_topics_context` |
| `topic_explanations` | Pre-computed explanation card variants per guideline (JSONB cards, cascade-deleted with guideline) |
| `study_plans` | Generated study plans (per-guideline, optionally per-user) |

See `book_ingestion_v2/models/database.py` for V2 ORM models. `TopicExplanation` and `StudyPlan` ORM models are in `shared/models/entities.py`.

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

| Prompt File | Used By | Purpose |
|-------------|---------|---------|
| `prompts/chapter_topic_planning.txt` | `ChapterTopicPlannerService` | Plan chapter-level topic skeleton before extraction |
| `prompts/toc_extraction.txt` | `TOCExtractionService` | Extract structured TOC from OCR text |
| `prompts/chunk_topic_extraction.txt` | `ChunkProcessorService` | Extract/update topics from a 3-page chunk (supports guided and unguided mode) |
| `prompts/topic_guidelines_merge.txt` | `ChapterFinalizationService` | Merge per-chunk appended guidelines into unified text |
| `prompts/chapter_consolidation.txt` | `ChapterFinalizationService` | Dedup, rename, sequence, summarize topics; track deviations from plan |
| `prompts/curriculum_context_generation.txt` | `ChapterFinalizationService` | Generate prior-topics context for curriculum continuity |
| `prompts/explanation_generation.txt` | `ExplanationGeneratorService` | Generate explanation cards for a teaching variant |
| `prompts/explanation_critique.txt` | `ExplanationGeneratorService` | Critique explanation cards against quality principles |
| `shared/prompts/templates/study_plan_generator.txt` | `StudyPlanGeneratorService` | Generate 3-5 step study plan from guideline |
| `shared/prompts/templates/session_plan_generator.txt` | `StudyPlanGeneratorService.generate_session_plan()` | Generate post-explanation interactive session plan |
| `shared/prompts/templates/study_plan_reviewer.txt` | `StudyPlanReviewerService` | Review plan quality, approve/reject with feedback |
| `shared/prompts/templates/study_plan_improve.txt` | `StudyPlanOrchestrator._improve_plan()` | Revise rejected plan using reviewer feedback |
| `autoresearch/book_ingestion_quality/evaluation/prompts/judge.txt` | `IngestionEvaluator` | Evaluate topic extraction quality across granularity, coverage, copyright |

---

## Configuration

- **LLM config key (extraction):** `book_ingestion_v2` -- stored in the `llm_configs` table, specifies provider and model_id for OCR, planning, chunk extraction, and finalization
- **LLM config key (explanations):** `explanation_generator` -- separate config for explanation generation
- **Chunk size:** 3 pages (`CHUNK_SIZE` in `constants.py`)
- **Chunk retries:** 3 attempts with exponential backoff (`CHUNK_MAX_RETRIES`)
- **Heartbeat stale threshold:** 600 seconds / 10 minutes (`HEARTBEAT_STALE_THRESHOLD`)
- **Pending stale threshold:** 300 seconds / 5 minutes (`PENDING_STALE_THRESHOLD`)
- **Planning deviation threshold:** 30% (`PLANNING_DEVIATION_THRESHOLD` in `constants.py`)
- **Planning deviation min count:** 3 (`PLANNING_DEVIATION_MIN_COUNT` in `constants.py`)
- **Explanation card limits:** 3 minimum, 15 maximum (`MIN_CARDS`, `MAX_CARDS` in `explanation_generator_service.py`)
- **Max TOC images:** 5
- **Max TOC image size:** 10 MB
- **Max page image size:** 20 MB
- **Supported page formats:** PNG, JPG, JPEG, TIFF, WEBP

---

## Frontend

| Component | File | Purpose |
|-----------|------|---------|
| BookV2Dashboard | `llm-frontend/src/features/admin/pages/BookV2Dashboard.tsx` | Lists all V2 books with card grid |
| CreateBookV2 | `llm-frontend/src/features/admin/pages/CreateBookV2.tsx` | Two-step wizard: metadata form, then TOC editor (upload or manual) |
| BookV2Detail | `llm-frontend/src/features/admin/pages/BookV2Detail.tsx` | Book detail with expandable chapters, page grid, upload, processing, topics, sync, explanation generation |
| Admin API V2 | `llm-frontend/src/features/admin/api/adminApiV2.ts` | TypeScript API client for all V2 endpoints (includes explanation generation with `guideline_id`/`force` support, explanation status, detail, delete, bulk OCR retry/rerun) |

**Routes:** `/admin/books-v2`, `/admin/books-v2/new`, `/admin/books-v2/{id}`

**Polling:** BookV2Detail polls `GET .../jobs/latest` every 3 seconds for chapters in `topic_extraction` or `chapter_finalizing` status. Polling stops when job reaches a terminal state.

---

## Key Files

| File | Purpose |
|------|---------|
| `book_ingestion_v2/constants.py` | Enums (ChapterStatus, V2JobType [includes `v2_explanation_generation`], V2JobStatus, OCRStatus, TopicStatus), config constants, deviation thresholds |
| `book_ingestion_v2/models/database.py` | ORM models: BookChapter, ChapterPage, ChapterProcessingJob (with `planned_topics_json`), ChapterChunk, ChapterTopic (with `prior_topics_context`, `topic_assignment`) |
| `book_ingestion_v2/models/schemas.py` | Pydantic request/response schemas for all V2 APIs including `ExplanationGenerationResponse` |
| `book_ingestion_v2/models/processing_models.py` | Internal pipeline models: ChunkWindow, TopicAccumulator, RunningState, PlannedTopic, ChapterTopicPlan, ChunkInput, ChunkExtractionOutput (TopicUpdate with `topic_assignment`, `reasoning`, `unplanned_justification`), ConsolidationOutput (with `deviations`), ConsolidationDeviation, FinalizationResult, TopicCurriculumContext, CurriculumContextOutput |
| `book_ingestion_v2/services/book_v2_service.py` | Book CRUD with cascade delete |
| `book_ingestion_v2/services/toc_extraction_service.py` | OCR + LLM TOC extraction |
| `book_ingestion_v2/services/toc_service.py` | TOC CRUD with validation |
| `book_ingestion_v2/services/chapter_page_service.py` | Page upload with inline OCR |
| `book_ingestion_v2/services/chapter_topic_planner_service.py` | Chapter-level topic planning before extraction (produces topic skeleton) |
| `book_ingestion_v2/services/chunk_processor_service.py` | Single-chunk LLM processing (guided and unguided modes) |
| `book_ingestion_v2/services/topic_extraction_orchestrator.py` | Full planning + extraction + finalization pipeline |
| `book_ingestion_v2/services/chapter_finalization_service.py` | Topic merge, consolidation, sequencing, deviation tracking, curriculum context generation |
| `book_ingestion_v2/services/topic_sync_service.py` | Sync to teaching_guidelines table (includes `prior_topics_context`) |
| `book_ingestion_v2/services/explanation_generator_service.py` | Multi-variant pre-computed explanation generation (generate -> critique -> refine per variant) |
| `book_ingestion_v2/services/chapter_job_service.py` | Job lock, progress tracking, stale detection |
| `book_ingestion_v2/utils/chunk_builder.py` | Build 3-page processing windows |
| `book_ingestion_v2/repositories/` | Data access: chapter_repository, chapter_page_repository, chunk_repository, topic_repository, processing_job_repository |
| `shared/repositories/book_repository.py` | Shared book data access |
| `shared/repositories/explanation_repository.py` | CRUD for `topic_explanations` table (written by ingestion pipeline, read by tutor) |
| `shared/models/entities.py` | ORM models: `StudyPlan` (study_plans table), `TopicExplanation` (topic_explanations table, JSONB cards) |
| `study_plans/services/orchestrator.py` | Study plan generate -> review -> improve loop |
| `study_plans/services/generator_service.py` | LLM-based study plan generation with strict schema; defines `StudyPlan`, `StudyPlanStep`, `StudyPlanMetadata`, `SessionPlan`, `SessionPlanStep`, `SessionPlanMetadata` Pydantic models |
| `study_plans/services/reviewer_service.py` | LLM-based study plan quality review |
| `shared/prompts/templates/study_plan_*.txt` | Prompts for study plan generation, review, and improvement |
| `shared/prompts/templates/session_plan_generator.txt` | Prompt for post-explanation session plan generation |
| `autoresearch/book_ingestion_quality/run_experiment.py` | CLI entry point for ingestion evaluation (runs extraction + LLM judge) |
| `autoresearch/book_ingestion_quality/evaluation/evaluator.py` | LLM judge that scores extraction quality across 3 dimensions |
| `autoresearch/book_ingestion_quality/evaluation/pipeline_runner.py` | Runs or loads extraction pipeline output for evaluation |
| `autoresearch/book_ingestion_quality/evaluation/report_generator.py` | Generates markdown and JSON evaluation reports |
| `autoresearch/book_ingestion_quality/evaluation/config.py` | Evaluation config: judge model, provider, API keys |
| `autoresearch/book_ingestion_quality/email_report.py` | Sends HTML evaluation report via macOS Mail.app |
| `autoresearch/book_ingestion_quality/evaluation/prompts/judge.txt` | Judge prompt with evaluation rubric |
