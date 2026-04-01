# Session: Explanation Pipeline Overhaul (2026-04-01)

## What We Did

### 1. Simplified Explanation Generation Prompt
**File**: `llm-backend/book_ingestion_v2/prompts/explanation_generation.txt`

- Reduced principles from 12 to 9 (removed variant approach, forced sentence length, variant differentiation)
- Removed `{variant_approach}` template variable — all variants now use same prompt
- Simplified wording throughout

**A/B tested** with `compare_prompts.py` across 5 Grade 1 math topics x 2 iterations:
- Overall: 7.14 → 7.40 (+0.26)
- Biggest gains: Structure & Flow (+0.70), Concept Clarity (+0.50)

### 2. Replaced Critique + Refinement with Review-and-Refine Agent
**Old flow**: generate → critique (separate LLM call) → maybe refine (third LLM call) → maybe skip if "poor"
**New flow**: generate → review-and-refine (single agent, N configurable rounds)

- New prompt: `llm-backend/book_ingestion_v2/prompts/explanation_review_refine.txt`
- Single agent reads cards as a struggling student, finds issues, fixes directly, returns updated cards
- Same JSON output format as generation — no intermediate feedback format

**A/B tested** (0 rounds vs 2 rounds):
- Overall: 7.30 → 7.52 (+0.22)
- Biggest gains: Concept Clarity (+0.40), Overall Effectiveness (+0.40)

### 3. Made Variant Count and Review Rounds Configurable
**File**: `llm-backend/book_ingestion_v2/services/explanation_generator_service.py`

- `DEFAULT_VARIANT_COUNT = 1` (was hardcoded 3)
- `DEFAULT_REVIEW_ROUNDS = 1` (new)
- `generate_for_guideline()` accepts `variant_count`, `review_rounds`, `stage_collector`
- Old critique/refinement code and Pydantic models removed
- `VARIANT_CONFIGS` list kept for future multi-variant use

### 4. Added Refine-Only Mode
New methods in `ExplanationGeneratorService`:
- `refine_only_for_guideline()` — loads existing cards from DB, runs N review-refine rounds, saves back
- `refine_only_for_chapter()` — same for all topics in a chapter

### 5. Built Explanation Admin Page (Frontend + Backend)

**Backend changes**:
- `stage_snapshots_json` column on `ChapterProcessingJob` — stores intermediate card sets per pipeline stage
- `append_stage_snapshots()` / `get_stage_snapshots()` on `ChapterJobService`
- `_generate_variant()` captures snapshots via `stage_collector` list after each step
- API: `POST /generate-explanations` now accepts `mode` (generate/refine_only) and `review_rounds` (0-5)
- API: `GET /explanation-jobs/{job_id}/stages` — fetch stage snapshots for a job

**Frontend**:
- `ExplanationAdmin.tsx` at route `/admin/books-v2/:bookId/explanations/:chapterId`
- Topic list with status badges (Not Generated / Running / Generated / Failed)
- Chapter-level buttons: Generate All, Refine All, Force Regenerate All (with tooltips)
- Per-topic buttons: Generate, Refine, View, Stages, Delete
- Review rounds selector (0-3)
- Stage Viewer modal — tabs for each pipeline stage (Initial → Refine 1 → Refine 2)
- Async job polling (resumes on page reload)
- "Manage Explanations" button added to BookV2Detail per chapter

### 6. Comparison Script
**File**: `llm-backend/autoresearch/explanation_quality/compare_prompts.py`
- Reusable A/B comparison tool
- Supports `--before-rounds` / `--after-rounds` for review-refine comparisons
- Generates HTML + JSON reports in `evaluation/runs/`

### Commits
- `fce8934` — refactor: simplify explanation pipeline — single variant, review-refine agent
- (pending) — feat: explanation admin page with stage viewer + refine-only mode

---

## What's Next

### Immediate (Explanation Pipeline Polish)
1. **Test the full flow end-to-end**: Generate from admin page, view stages, refine-only, verify cards look good
2. **Iterate on the review-refine prompt** (`explanation_review_refine.txt`) — run autoresearch to optimize it
3. **Delete old prompt files** (`explanation_critique.txt`, `explanation_refinement.txt`) once confident

### Next Pipelines (Same Admin Page Pattern)
The explanation admin page establishes a reusable pattern: dedicated chapter-level page, async jobs, stage snapshots, configurable pipeline. Replicate for:

4. **Guidelines Admin Page** — view/edit/regenerate teaching guidelines per topic
5. **OCR Admin Page** — view/rerun/review OCR results per page
6. **PixiJS Visual Generation Admin Page** — generate/review/refine interactive visuals per card (separate pipeline from explanations)

### Architecture Note
- Each pipeline gets its own admin page, navigable from the book detail page
- All use `ChapterProcessingJob` with `stage_snapshots_json` for intermediate results
- All follow the pattern: generate → review-refine (N rounds) → store
