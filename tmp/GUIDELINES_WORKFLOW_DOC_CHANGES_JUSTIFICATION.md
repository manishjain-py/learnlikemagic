# Book Guidelines Pipeline - Documentation Changes Justification

**Date:** 2025-12-30
**Document Updated:** `docs/BOOK_GUIDELINES_PIPELINE.md`

---

## Summary of Changes

| Category | Changes Made | Evidence |
|----------|--------------|----------|
| Path Corrections | Updated all backend paths after folder reorganization | `ls llm-backend/` - no `features/` or `routers/` folders |
| Service List | Removed V1 parked services from active list | Orchestrator header comments lines 5-8 |
| Model Location | TeachingGuideline moved to shared/models | `grep "class TeachingGuideline"` |

---

## Detailed Changes

### 1. Backend Path Corrections

**All paths updated after recent folder reorganization:**

| Old Path | New Path | Verification |
|----------|----------|--------------|
| `llm-backend/features/book_ingestion/` | `llm-backend/book_ingestion/` | `ls llm-backend/` shows no `features/` folder |
| `llm-backend/routers/admin_guidelines.py` | `llm-backend/study_plans/api/admin.py` | `grep "admin/guidelines"` found file at new location |
| `llm-backend/features/study_plans/` | `llm-backend/study_plans/` | Direct folder verification |
| `llm-backend/models/database.py` (TeachingGuideline) | `llm-backend/shared/models/entities.py` | `grep "class TeachingGuideline"` |

---

### 2. Service List Cleanup

**Removed from "active services" documentation:**
- `facts_extraction_service.py`
- `quality_gates_service.py`
- `reducer_service.py`
- `teaching_description_generator.py`
- `description_generator.py`

**Evidence:** `llm-backend/book_ingestion/services/guideline_extraction_orchestrator.py` lines 5-8:
```python
# V2 Simplifications:
# - No FactsExtractionService (done in boundary detection)
# - No ReducerService (replaced with GuidelineMergeService)
# - No TeachingDescriptionGenerator (single guidelines field)
# - No QualityGatesService (parked for V2)
```

These files still exist but are NOT imported by the V2 orchestrator.

---

### 3. Key Files Reference Updates

**Backend sections updated:**
- `book_ingestion/` path prefix (was `features/book_ingestion/`)
- `study_plans/api/admin.py` for guidelines review endpoints (was `routers/admin_guidelines.py`)
- `shared/models/entities.py` for TeachingGuideline (was `models/database.py`)

---

## Verification Commands

```bash
# Confirm no features folder
ls /Users/manishjain/repos/learnlikemagic/llm-backend/
# Output: book_ingestion, study_plans, shared, tutor, ... (no features/)

# Find guidelines admin routes
grep -r "admin/guidelines" llm-backend/
# Output: llm-backend/study_plans/api/admin.py

# Find TeachingGuideline model
grep -r "class TeachingGuideline" llm-backend/
# Output: llm-backend/shared/models/entities.py

# Verify V2 orchestrator imports
head -60 llm-backend/book_ingestion/services/guideline_extraction_orchestrator.py
# Shows V2 imports without facts_extraction, reducer, etc.
```

---

## Previous Changes (2025-12-28) - Kept As-Is

The following changes from the previous documentation update remain valid:
- Phase 9 Study Plans documentation
- DELETE /admin/books/{id} endpoint
- Book ID slug format (author_subject_grade_year)
- Review status behavior (no REJECTED status)
- V1 legacy fields note in TeachingGuideline
- Inlined stability logic design decision
