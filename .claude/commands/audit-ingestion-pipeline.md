# Audit Ingestion Pipeline — Deep Code Audit of Book-to-Study-Plan Pipeline

Perform an exhaustive code-level audit of the book ingestion pipeline (OCR → guidelines extraction → finalization → DB sync → study plan generation) to identify issues that could cause topic loss, content degradation, or inaccurate study plans.

## Input
- Optional `$ARGUMENTS` = book_id to audit a specific book's S3 artifacts. If omitted, audit is code-only (no live data).

## ENVIRONMENT SETUP

**All Python commands MUST use the project virtual environment.** The venv is at `llm-backend/venv` (NOT `.venv`).

```bash
cd llm-backend && source venv/bin/activate && python ...
```

## AUTOMATION DIRECTIVE

This is a **fully automated pipeline**. The user will NOT be present to review plans, approve decisions, or give go-ahead between steps.

- **Do NOT** use `EnterPlanMode` or `AskUserQuestion` at any point.
- **Do NOT** pause for user confirmation between steps.
- Make all decisions autonomously.
- Execute every step end-to-end without stopping.
- If something fails, attempt to fix and retry (3 max).
- Log all decisions and rationale to the progress file so the user can review after the fact.

---

## Step 0: Initialize

```bash
SLUG="${ARGUMENTS:-audit-ingestion-$(date +%Y%m%d-%H%M%S)}"
ROOT="$(pwd)"
REPORT_DIR="$ROOT/reports/audit-ingestion"
mkdir -p "$REPORT_DIR"
LOG_FILE="$REPORT_DIR/${SLUG}.log"
PROGRESS_FILE="$REPORT_DIR/${SLUG}.progress.json"
REPORT_FILE="$REPORT_DIR/${SLUG}.audit-report.md"

BRANCH="$(git -C "$ROOT" branch --show-current)"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"
NOW="$(date '+%Y-%m-%d %H:%M:%S %Z')"

echo "[$NOW] audit-ingestion started on $BRANCH@$COMMIT" | tee "$LOG_FILE"
echo '{"status":"running","step":"init","branch":"'"$BRANCH"'","commit":"'"$COMMIT"'","started":"'"$NOW"'"}' > "$PROGRESS_FILE"
```

Keep `$PROGRESS_FILE` updated with current status/step as the pipeline progresses.

---

## Step 1: Understand the Current Pipeline

Before auditing, read all pipeline documentation and code to build a mental model of the current state. This is critical — the pipeline may have changed since this skill was written.

**Read documentation first:**
- `docs/functional/book-guidelines.md` — What the pipeline should do
- `docs/technical/book-guidelines.md` — How it's built (pipeline phases, data models, LLM calls, S3 structure)

**Then read ALL active V2 pipeline source files (in dependency order):**

1. `llm-backend/book_ingestion/models/guideline_models.py` — Data models (SubtopicShard, GuidelinesIndex, ContextPack, BoundaryDecision)
2. `llm-backend/book_ingestion/services/ocr_service.py` — OCR via OpenAI Vision
3. `llm-backend/book_ingestion/services/minisummary_service.py` — Page summarization
4. `llm-backend/book_ingestion/services/context_pack_service.py` — Context building for LLM
5. `llm-backend/book_ingestion/services/boundary_detection_service.py` — Topic detection + guideline extraction
6. `llm-backend/book_ingestion/services/guideline_merge_service.py` — LLM-based guideline merging
7. `llm-backend/book_ingestion/services/topic_subtopic_summary_service.py` — Summary generation
8. `llm-backend/book_ingestion/services/index_management_service.py` — Index CRUD
9. `llm-backend/book_ingestion/services/topic_name_refinement_service.py` — Name polishing
10. `llm-backend/book_ingestion/services/topic_deduplication_service.py` — Duplicate detection
11. `llm-backend/book_ingestion/services/db_sync_service.py` — PostgreSQL sync
12. `llm-backend/book_ingestion/services/guideline_extraction_orchestrator.py` — Main orchestrator
13. `llm-backend/book_ingestion/services/background_task_runner.py` — Background execution
14. `llm-backend/book_ingestion/services/page_service.py` — Page upload + OCR
15. `llm-backend/book_ingestion/api/routes.py` — API endpoints

**Read ALL active V2 prompt templates:**
- `llm-backend/book_ingestion/prompts/minisummary_v2.txt`
- `llm-backend/book_ingestion/prompts/boundary_detection.txt`
- `llm-backend/book_ingestion/prompts/guideline_merge_v2.txt`
- `llm-backend/book_ingestion/prompts/subtopic_summary.txt`
- `llm-backend/book_ingestion/prompts/topic_summary.txt`
- `llm-backend/book_ingestion/prompts/topic_name_refinement.txt`
- `llm-backend/book_ingestion/prompts/topic_deduplication_v2.txt`

**Read study plan pipeline:**
- `llm-backend/study_plans/services/orchestrator.py`
- `llm-backend/study_plans/services/generator_service.py`
- `llm-backend/study_plans/services/reviewer_service.py`
- `llm-backend/shared/prompts/templates/study_plan_generator.txt`
- `llm-backend/shared/prompts/templates/study_plan_reviewer.txt`
- `llm-backend/shared/prompts/templates/study_plan_improve.txt`

Log what you read to `$LOG_FILE`.

---

## Step 2: Audit Category 1 — Content Loss & Silent Truncation

Examine every point in the pipeline where content could be silently lost or truncated. For each finding, record:
- **Location**: file:line
- **Severity**: CRITICAL / HIGH / MEDIUM / LOW
- **Description**: What happens
- **Impact**: How it affects the final study plan
- **Recommendation**: How to fix it

**Specific checks (check ALL of these, plus any others you find):**

### 2a. Token/Character Limits
- MinisummaryService: `page_text[:3000]` truncation — does this lose content on dense pages?
- BoundaryDetectionService: `max_tokens=1000` — is this enough for guidelines extraction?
- GuidelineMergeService: `max_tokens=1500` — can merged guidelines exceed this?
- TopicNameRefinementService: `guidelines[:2000]` — does truncation affect name quality?
- TopicDeduplicationService: `shard.guidelines[:200]` preview — is 200 chars enough for accurate dedup?
- Context pack: `guidelines_preview[:300]` in boundary detection prompt — enough for matching?
- Study plan generator: any token limits on the guideline text passed?

### 2b. Empty/Missing Content
- What happens when OCR returns empty text?
- What happens when minisummary returns empty?
- What happens when boundary detection returns empty page_guidelines?
- What happens when merge returns empty text?
- What happens when a shard file is missing from S3?

### 2c. Error Swallowing
- Which `except` blocks silently continue vs. raise?
- Are there `logger.warning` calls that mask data loss?
- Does `fallback: simple concatenation` in merge service preserve all content?

---

## Step 3: Audit Category 2 — Topic Boundary Accuracy

Analyze whether the boundary detection logic can produce incorrect topic assignments.

**Specific checks:**

### 3a. Context Pack Completeness
- Does the context pack include ALL existing topics, or only "open" ones?
- If a topic was marked "stable" (5-page gap), can it be re-merged if the book revisits it?
- What happens when the context pack becomes very large (many topics)?
- Are there edge cases at page 1 (empty context)?

### 3b. Boundary Detection Prompt Quality
- Does the prompt give enough guidance to avoid over-segmentation (too many subtopics)?
- Does the prompt give enough guidance to avoid under-segmentation (merged unrelated content)?
- Is `max_tokens=1000` sufficient for the combined boundary + guidelines response?
- How does the prompt handle non-content pages (table of contents, index, blank pages, appendix)?
- How does the prompt handle pages that span two topics?

### 3c. Stability Logic
- Does the 5-page stability threshold work well for short chapters?
- What happens if the same topic appears in chapter 1 and chapter 5?

---

## Step 4: Audit Category 3 — Guideline Quality & Completeness

Analyze whether the extracted guidelines are comprehensive enough for the tutor.

**Specific checks:**

### 4a. Guideline Extraction
- Does the boundary detection prompt extract ALL pedagogically important elements?
  - Learning objectives
  - Examples and worked problems
  - Common misconceptions
  - Assessment questions
  - Teaching strategies
  - Prerequisites
  - Visual aids / diagrams (noted as present)
- Is the "natural language" format sufficient for the tutor, or does it lose structure?

### 4b. Guideline Merging
- Does the LLM merge intelligently, or does it sometimes drop content?
- After many merges (e.g., 10-page subtopic), does the guideline become too long or lose focus?
- Does the merge prompt enforce "keep all unique information"?
- Is the fallback (simple concatenation) a risk for downstream quality?

### 4c. Deduplication Risks
- Can deduplication incorrectly merge distinct subtopics?
- Does dedup consider page ranges to avoid false positives?
- After dedup merge, is the surviving shard's summary updated?

---

## Step 5: Audit Category 4 — Data Integrity Through Pipeline Stages

Trace data flow from OCR text through to study plans and verify nothing is corrupted.

**Specific checks:**

### 5a. Index Consistency
- Can the GuidelinesIndex and actual S3 shard files get out of sync?
- What happens if a shard save succeeds but index update fails?
- What happens if name refinement renames a shard but index update fails?
- Are there race conditions with background tasks?

### 5b. DB Sync Integrity
- Full snapshot sync (DELETE + INSERT) — what if it fails mid-way?
- Are topic_summary values correctly propagated to the DB?
- Are all shard fields correctly mapped to DB columns?
- What happens to existing study_plans when guidelines are re-synced?

### 5c. Study Plan Generation
- Does the study plan generator receive the FULL guideline text?
- Is the "single revision pass" sufficient for quality?
- What happens when the improvement step fails? (documented: saves original)
- Are study plans invalidated when their source guideline is updated?

---

## Step 6: Audit Category 5 — Page Coverage Verification

Check whether the pipeline guarantees that every page in the book maps to a guideline.

**Specific checks:**
- Is there any mechanism to verify all pages are assigned to subtopics?
- Can pages "fall through" if boundary detection fails on them?
- Does the page index track coverage?
- After errors on specific pages, are those pages' content reflected anywhere?
- What happens with non-content pages (preface, table of contents, index)?

---

## Step 7: Audit Category 6 — Prompt Engineering Quality

Evaluate each prompt template for clarity, specificity, and resistance to LLM drift.

**For each prompt, check:**
- Is the instruction clear and unambiguous?
- Are there examples or few-shot demonstrations?
- Is the output format strictly defined?
- Are there guardrails against common LLM failure modes?
- Is the prompt appropriate for the configured temperature?
- Does the prompt handle edge cases (empty input, very short text, non-educational content)?

---

## Step 8: (Optional) Live Data Audit

**Only if a book_id was provided in $ARGUMENTS.**

If a specific book was provided, audit its actual S3 artifacts and DB records:

```bash
cd "$ROOT/llm-backend" && source venv/bin/activate
python -c "
import json, sys
sys.path.insert(0, '.')
from book_ingestion.utils.s3_client import S3Client

book_id = '$ARGUMENTS'
if not book_id or book_id.startswith('audit-ingestion'):
    print('No book_id provided, skipping live audit')
    sys.exit(0)

s3 = S3Client()

# 1. Load metadata
meta = s3.download_json(f'books/{book_id}/metadata.json')
total_pages = meta.get('total_pages', 0)
print(f'Book: {book_id}, Total pages: {total_pages}')

# 2. Load guidelines index
try:
    index = s3.download_json(f'books/{book_id}/guidelines/index.json')
    topics = index.get('topics', [])
    total_subtopics = sum(len(t.get('subtopics', [])) for t in topics)
    print(f'Topics: {len(topics)}, Subtopics: {total_subtopics}')
except:
    print('No guidelines index found')
    sys.exit(0)

# 3. Check page coverage
try:
    page_index = s3.download_json(f'books/{book_id}/guidelines/page_index.json')
    assigned_pages = set(int(p) for p in page_index.get('pages', {}).keys())
    all_pages = set(range(1, total_pages + 1))
    unassigned = all_pages - assigned_pages
    if unassigned:
        print(f'WARNING: {len(unassigned)} unassigned pages: {sorted(unassigned)}')
    else:
        print(f'All {total_pages} pages are assigned to subtopics')
except:
    print('No page index found')

# 4. Check each shard
empty_shards = []
short_shards = []
for topic in topics:
    for sub in topic.get('subtopics', []):
        try:
            key = f\"books/{book_id}/guidelines/topics/{topic['topic_key']}/subtopics/{sub['subtopic_key']}.latest.json\"
            shard = s3.download_json(key)
            guidelines = shard.get('guidelines', '')
            if not guidelines:
                empty_shards.append(f\"{topic['topic_key']}/{sub['subtopic_key']}\")
            elif len(guidelines) < 100:
                short_shards.append(f\"{topic['topic_key']}/{sub['subtopic_key']} ({len(guidelines)} chars)\")
        except Exception as e:
            print(f\"Shard missing: {topic['topic_key']}/{sub['subtopic_key']}: {e}\")

if empty_shards:
    print(f'CRITICAL: {len(empty_shards)} empty shards: {empty_shards}')
if short_shards:
    print(f'WARNING: {len(short_shards)} very short shards: {short_shards}')

# 5. Summary
print(f'\\n--- Coverage Summary ---')
print(f'Pages: {total_pages}')
print(f'Topics: {len(topics)}')
print(f'Subtopics: {total_subtopics}')
print(f'Empty shards: {len(empty_shards)}')
print(f'Short shards: {len(short_shards)}')
print(f'Unassigned pages: {len(unassigned) if \"unassigned\" in dir() else \"unknown\"} ')
"
```

---

## Step 9: Compile Audit Report

**Keep the report compact, clear, and to the point.** No filler text, no verbose explanations. Use tables for findings. Use short, direct sentences. Every word must earn its place.

Create the report at `$REPORT_FILE` with this structure:

```markdown
# Book Ingestion Pipeline Audit Report

**Date:** YYYY-MM-DD
**Branch:** branch-name @ commit-hash
**Auditor:** Claude Code (automated)

## Executive Summary

- Total findings: X
- Critical: X | High: X | Medium: X | Low: X
- Top 3 risks to study plan quality:
  1. ...
  2. ...
  3. ...

## Findings by Category

### Category 1: Content Loss & Silent Truncation
| # | Severity | Location | Description | Impact | Recommendation |
|---|----------|----------|-------------|--------|----------------|
| 1 | CRITICAL | file:line | ... | ... | ... |

### Category 2: Topic Boundary Accuracy
(same table format)

### Category 3: Guideline Quality & Completeness
(same table format)

### Category 4: Data Integrity
(same table format)

### Category 5: Page Coverage
(same table format)

### Category 6: Prompt Engineering Quality
(same table format)

## Live Data Audit Results (if applicable)
- Book ID: ...
- Page coverage: X/Y pages assigned
- Empty shards: ...
- Short shards: ...

## Priority Fix List

Table format, ordered by impact on study plan quality:

| # | Severity | Fix | Effort | Confidence | Rationale |
|---|----------|-----|--------|------------|-----------|
| 1 | CRITICAL | Description | S/M/L | **X%** | Why this fix works, what assumptions it makes, risks |

**Confidence scoring guide:**
- **95%** = Pure code fix, deterministic, no behavioral unknowns
- **85-90%** = Code fix with minor tuning needed (thresholds, limits)
- **70-80%** = Depends on LLM behavior or needs real-data calibration
- **<70%** = Architectural change, needs testing/iteration

For each fix, the Rationale column MUST explain:
1. Why the fix addresses the root cause (not just the symptom)
2. What assumptions or dependencies exist
3. What could go wrong or need tuning

## Architecture Recommendations

Long-term suggestions for pipeline resilience (compact, 1-2 lines each):
1. ...
2. ...
```

---

## Step 10: Final Output

Print to console:
- Path to the full audit report
- Number of findings by severity
- Top 3 most impactful findings
- Path to log file

```
Audit complete!

Report:   $REPORT_FILE
Log:      $LOG_FILE

Findings: X total (Y critical, Z high)

Top risks:
1. [CRITICAL] ...
2. [HIGH] ...
3. [HIGH] ...
```
