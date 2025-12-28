# Book Guidelines Pipeline Documentation Changes Justification

**Date:** 2025-12-28
**Document Updated:** `docs/features/BOOK_GUIDELINES_PIPELINE.md`

This document captures all changes made to the Book Guidelines Pipeline documentation and the evidence supporting each change.

---

## Summary of Changes

| Category | Changes Made | Files Examined |
|----------|--------------|----------------|
| New Features | Added Phase 9 (Study Plans), added DELETE /admin/books/{id} | `admin_guidelines.py`, `routes.py` |
| Missing Files | Added 4 frontend files to Key Files Reference | Frontend file listing |
| Accuracy Fixes | Fixed book_id slug format, clarified review status behavior | `book_service.py`, `admin_guidelines.py` |
| Model Updates | Added PageAssignment.provisional, V1 legacy fields note | `guideline_models.py`, `models/database.py` |
| Architecture | Added StudyPlanOrchestrator to diagram | `admin_guidelines.py` |
| Corrections | Updated process_page steps ordering, removed stability_detector_service | `guideline_extraction_orchestrator.py` |

---

## Detailed Change Justification

### 1. Added Phase 9: Study Plan Generation

**Change:** Added new Phase 9 documenting study plan generation endpoints and flow.

**Evidence:**
- File: `llm-backend/routers/admin_guidelines.py:725-795`
- Endpoints found:
  - `POST /{guideline_id}/generate-study-plan` (line 725)
  - `GET /{guideline_id}/study-plan` (line 752)
  - `POST /bulk-generate-study-plans` (line 772)
- `StudyPlanOrchestrator` imported from `features.study_plans.services.orchestrator` (line 27)

**Impact:** Critical new feature completely missing from documentation.

---

### 2. Added DELETE /admin/books/{id} Endpoint

**Change:** Added "Delete Book" section to Phase 1-3 documentation.

**Evidence:**
- File: `llm-backend/features/book_ingestion/api/routes.py:137-169`
```python
@router.delete("/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_book(book_id: str, db: Session = Depends(get_db)):
```
- Calls `BookService.delete_book()` which deletes S3 files and DB row

**Impact:** Missing endpoint documentation.

---

### 3. Fixed Book ID Slug Format

**Change:** Changed slug format from `title-edition-year-grade-subject` to `author_subject_grade_year`.

**Evidence:**
- File: `llm-backend/features/book_ingestion/services/book_service.py:211-236`
```python
def _generate_book_id(self, request: CreateBookRequest) -> str:
    author_slug = request.author.lower().replace(" ", "_") if request.author else "unknown"
    subject_slug = request.subject.lower().replace(" ", "_")
    grade = request.grade
    edition_year = request.edition_year or datetime.now().year
    base_id = f"{author_slug}_{subject_slug}_{grade}_{edition_year}"
```

**Impact:** Documentation showed incorrect ID format.

---

### 4. Added Missing Frontend Files to Key Files Reference

**Change:** Added `CreateBook.tsx`, `PageViewPanel.tsx`, `PagesSidebar.tsx` to frontend files table.

**Evidence:**
- Glob result from `llm-frontend/src/features/admin/**/*.{ts,tsx}`:
```
llm-frontend/src/features/admin/pages/CreateBook.tsx
llm-frontend/src/features/admin/components/PageViewPanel.tsx
llm-frontend/src/features/admin/components/PagesSidebar.tsx
```

**Impact:** Incomplete file listing.

---

### 5. Clarified Review Status Behavior (No REJECTED Status)

**Change:** Added note: "Rejecting a guideline sets it back to `TO_BE_REVIEWED` (there is no `REJECTED` status)."

**Evidence:**
- File: `llm-backend/routers/admin_guidelines.py:681-700`
```python
@router.post("/{guideline_id}/approve")
async def approve_guideline(...):
    guideline.review_status = "APPROVED" if approved else "TO_BE_REVIEWED"
```

**Impact:** Previous documentation implied existence of REJECTED status.

---

### 6. Added PageAssignment.provisional Field

**Change:** Added `provisional: bool` to PageAssignment model documentation.

**Evidence:**
- File: `llm-backend/features/book_ingestion/models/guideline_models.py:96-101`
```python
class PageAssignment(BaseModel):
    topic_key: str
    subtopic_key: str
    confidence: float = Field(ge=0.0, le=1.0)
    provisional: bool = Field(default=False)
```

**Impact:** Missing field in model documentation.

---

### 7. Added V1 Legacy Fields Note to TeachingGuideline

**Change:** Added note about V1 legacy fields kept for backward compatibility.

**Evidence:**
- File: `llm-backend/models/database.py:60-120`
- V1 fields still present:
  - `objectives_json`, `examples_json`, `misconceptions_json`, `assessments_json`
  - `teaching_description`, `description`, `evidence_summary`, `confidence`
  - `metadata_json`, `source_pages`
- Comment in code: `# V1 structured fields (REMOVE in V2 migration)`

**Impact:** Documentation should clarify these fields exist but aren't actively used.

---

### 8. Added cover_image_s3_key to Book Table

**Change:** Added `cover_image_s3_key` column to Book table documentation.

**Evidence:**
- File: `llm-backend/features/book_ingestion/models/database.py:24`
```python
cover_image_s3_key = Column(String, nullable=True)
```

**Impact:** Missing column in table schema.

---

### 9. Added Note About Book.status Removal

**Change:** Added note: "`status` field has been removed from Book model - status is now derived from counts."

**Evidence:**
- File: `llm-backend/features/book_ingestion/services/book_service.py:79,134`
```python
# status="draft",  <-- Removed
# status=book.status,  <-- Removed
```
- Status is computed at runtime from counts

**Impact:** Documentation mentioned Book status but code comment shows it was removed.

---

### 10. Updated process_page Steps Ordering

**Change:** Reordered steps to match actual code flow, now 11 steps instead of 10.

**Evidence:**
- File: `llm-backend/features/book_ingestion/services/guideline_extraction_orchestrator.py:228-430`
- Actual order:
  1. Load OCR text
  2. Generate minisummary
  3. Build context pack
  4. Boundary detection + extract guidelines
  5. Create or merge shard (GuidelineMergeService)
  6. Generate subtopic summary (TopicSubtopicSummaryService)
  7. Save shard to S3
  8. Generate topic summary
  9. Update indices
  10. Save page guideline
  11. Check stability

**Impact:** Step ordering was slightly different and topic summary step was merged incorrectly.

---

### 11. Removed stability_detector_service.py from Active Services

**Change:** Noted that stability logic is inlined in orchestrator, added design decision #10.

**Evidence:**
- File: `llm-backend/features/book_ingestion/services/guideline_extraction_orchestrator.py:596-633`
```python
def _check_and_mark_stable_subtopics(self, book_id: str, current_page: int) -> int:
    # Stability logic is inline here, not using separate service
```
- While `stability_detector_service.py` exists in file listing, orchestrator doesn't import it

**Impact:** Documentation listed service that isn't actively used.

---

### 12. Added StudyPlanOrchestrator to Architecture Diagram

**Change:** Added StudyPlanOrchestrator box to backend architecture section.

**Evidence:**
- File: `llm-backend/routers/admin_guidelines.py:27`
```python
from features.study_plans.services.orchestrator import StudyPlanOrchestrator
```

**Impact:** Architecture diagram should show all major services.

---

### 13. Added Study Plans to Frontend Types Documentation

**Change:** Updated adminApi.ts description to include "study plans".

**Evidence:**
- File: `llm-frontend/src/features/admin/api/adminApi.ts:249-263`
```typescript
export async function generateStudyPlan(guidelineId: string, ...): Promise<StudyPlan>
export async function getStudyPlan(guidelineId: string): Promise<StudyPlan>
```

**Impact:** API client functions for study plans existed but weren't documented.

---

### 14. Added Study Plan Endpoints to Guidelines Review Table

**Change:** Added 3 study plan endpoints to the endpoint reference table.

**Evidence:**
- See Change #1 evidence

**Impact:** Complete endpoint reference.

---

### 15. Added Study Plans Section to Backend Key Files

**Change:** Added `Backend - Study Plans` section with `services/orchestrator.py`.

**Evidence:**
- File exists: `llm-backend/features/study_plans/services/orchestrator.py` (imported in admin_guidelines.py:27)

**Impact:** Missing file reference.

---

## Files Examined During Audit

### Backend Files
1. `llm-backend/features/book_ingestion/api/routes.py`
2. `llm-backend/routers/admin_guidelines.py`
3. `llm-backend/features/book_ingestion/models/database.py`
4. `llm-backend/features/book_ingestion/models/guideline_models.py`
5. `llm-backend/features/book_ingestion/services/book_service.py`
6. `llm-backend/features/book_ingestion/services/guideline_extraction_orchestrator.py`
7. `llm-backend/features/book_ingestion/services/ocr_service.py`
8. `llm-backend/features/book_ingestion/services/boundary_detection_service.py`
9. `llm-backend/features/book_ingestion/services/db_sync_service.py`
10. `llm-backend/models/database.py`

### Frontend Files
1. `llm-frontend/src/features/admin/api/adminApi.ts`
2. `llm-frontend/src/features/admin/types/index.ts`
3. `llm-frontend/src/features/admin/utils/bookStatus.ts`

---

## Not Changed (Verified Accurate)

The following documentation sections were verified as accurate:
- S3 folder structure
- BoundaryDecision output format
- LLM Calls Summary (all models are gpt-4o-mini)
- Workflow state transitions diagram
- Count sources for derived status
- Two-level review explanation
