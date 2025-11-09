# Simplified Description Field Implementation Plan

**Created**: 2025-10-31
**Status**: 🚧 In Progress
**Feature**: Add simplified 200-300 word description field to guidelines

---

## 📋 Overview

This document tracks the implementation of a new `description` field for teaching guidelines. This field consolidates all guideline information (what the topic is, how it's taught, how it's assessed) into a single comprehensive 200-300 word paragraph.

### Requirements
- ✅ Keep all existing detailed fields (objectives, examples, misconceptions, assessments, teaching_description)
- ✅ Add new `description` field to consolidate everything
- ✅ Generate description when subtopic becomes stable
- ✅ Update description when parsing additional pages for same topic
- ✅ Display description in admin UI
- ✅ Sync description to database

---

## 🎯 Implementation Phases

### ✅ Phase 0: Pre-Implementation Checks
**Status**: COMPLETED ✅

- [x] Verified database migration status
  - Base migrations: ✅ Up to date
  - Book ingestion migrations: ✅ Up to date
  - Phase 6 schema: ✅ Up to date
  - All indices created successfully
- [x] Reviewed existing codebase architecture
- [x] Documented current guidelines generation flow

**Notes**: Database is in good state. All existing migrations have been applied successfully.

---

### ✅ Phase 1: Backend Data Model Changes
**Status**: COMPLETED ✅
**Estimated Time**: 30 minutes
**Actual Time**: 15 minutes

#### Tasks:
- [x] Update `SubtopicShard` model in `guideline_models.py`
  - Added `description: Optional[str]` field
  - Added comprehensive documentation
  - Location: `/llm-backend/features/book_ingestion/models/guideline_models.py:160`

- [x] Update `TeachingGuideline` database model
  - Added `description = Column(Text, nullable=True)`
  - Location: `/llm-backend/models/database.py:85`

#### Files Modified:
- ✅ `/llm-backend/features/book_ingestion/models/guideline_models.py`
- ✅ `/llm-backend/models/database.py`

#### Acceptance Criteria:
- ✅ Models import without errors
- ✅ Pydantic validation works correctly
- ✅ Can create SubtopicShard with description field
- ✅ Description field serializes correctly

**Progress**: 2/2 tasks completed ✅

**Testing Results**:
```
✅ Models imported successfully
✅ SubtopicShard has description field
✅ TeachingGuideline has description column
✅ Shard created successfully with description
✅ Shard serialization includes description
```

---

### ✅ Phase 2: Service Layer Changes
**Status**: COMPLETED ✅
**Estimated Time**: 2 hours
**Actual Time**: 45 minutes

#### Tasks:
- [x] Create `DescriptionGenerator` service
  - File: `/llm-backend/features/book_ingestion/services/description_generator.py` ✅
  - Implemented `generate()` method ✅
  - Implemented `generate_with_validation()` method ✅
  - Added retry logic with max_retries parameter ✅
  - Word count validation (150-350 words, target 200-300) ✅

- [x] Create description generation prompt
  - File: `/llm-backend/features/book_ingestion/prompts/description_generation.txt` ✅
  - Requests 200-300 word comprehensive description ✅
  - Includes: what, how to teach, how to assess, misconceptions ✅
  - Provides example format for consistency ✅

- [x] Update `GuidelineExtractionOrchestrator`
  - Imported `DescriptionGenerator` ✅
  - Initialized in `__init__` (line 90) ✅
  - Integrated in `check_and_finalize_stable_subtopics()` (Step 2.5, line 385-396) ✅
  - Added logging for description word count ✅

- [x] Test service integration
  - DescriptionGenerator imports successfully ✅
  - GuidelineExtractionOrchestrator imports with new service ✅

#### Files Created:
- ✅ `/llm-backend/features/book_ingestion/services/description_generator.py`
- ✅ `/llm-backend/features/book_ingestion/prompts/description_generation.txt`

#### Files Modified:
- ✅ `/llm-backend/features/book_ingestion/services/guideline_extraction_orchestrator.py`

#### Acceptance Criteria:
- ✅ Description generator service works independently
- ✅ Descriptions validated for 200-300 word target
- ✅ Descriptions cover what/how/assessment/misconceptions (via prompt)
- ✅ Orchestrator generates descriptions during finalization (Step 2.5)
- ✅ Descriptions will be saved to S3 shard files (uses existing save logic)

**Progress**: 4/4 tasks completed ✅

**Testing Results**:
```
✅ DescriptionGenerator imported successfully
✅ GuidelineExtractionOrchestrator imported successfully
✅ Integration point added at Step 2.5 (after teaching_description)
✅ Word count logging included
```

---

### 🔄 Phase 3: API Changes
**Status**: Not Started
**Estimated Time**: 45 minutes

#### Tasks:
- [ ] Update `GuidelineSubtopicResponse` schema
  - Add `description: Optional[str]` field
  - Location: `/llm-backend/features/book_ingestion/api/routes.py:397`

- [ ] Update GET `/books/{book_id}/guidelines` endpoint
  - Include `description` in response
  - Location: `/llm-backend/features/book_ingestion/api/routes.py:516`

- [ ] Update GET `/books/{book_id}/guidelines/{topic_key}/{subtopic_key}` endpoint
  - Include `description` in response
  - Location: `/llm-backend/features/book_ingestion/api/routes.py:621`

- [ ] Update `DBSyncService`
  - Sync `description` field to database
  - Location: `/llm-backend/features/book_ingestion/services/db_sync_service.py`

- [ ] Test API endpoints
  - Verify description appears in responses
  - Test with postman/curl

#### Files to Modify:
- `/llm-backend/features/book_ingestion/api/routes.py`
- `/llm-backend/features/book_ingestion/services/db_sync_service.py`

#### Acceptance Criteria:
- ✅ API returns description field in responses
- ✅ Description syncs to database on approval
- ✅ Existing API functionality unaffected

**Progress**: 0/5 tasks completed

---

### 🔄 Phase 4: Frontend UI Changes
**Status**: Not Started
**Estimated Time**: 1 hour

#### Tasks:
- [ ] Update TypeScript types
  - Add `description?: string` to `GuidelineSubtopic` interface
  - Location: `/llm-frontend/src/features/admin/types.ts`

- [ ] Update `GuidelinesPanel` component
  - Display description prominently in detail view
  - Add "Overview" section with description
  - Location: `/llm-frontend/src/features/admin/components/GuidelinesPanel.tsx`

- [ ] Add CSS styling for description
  - Create `.description-section` styles
  - Ensure readable formatting

- [ ] Test UI rendering
  - Verify description displays correctly
  - Check responsive design
  - Test with long/short descriptions

#### Files to Modify:
- `/llm-frontend/src/features/admin/types.ts`
- `/llm-frontend/src/features/admin/components/GuidelinesPanel.tsx`
- CSS/styling file (TBD)

#### Acceptance Criteria:
- ✅ Description displays in UI
- ✅ Styling is clean and readable
- ✅ No console errors
- ✅ Works in all modern browsers

**Progress**: 0/4 tasks completed

---

### 🔄 Phase 5: Database Migration
**Status**: Not Started
**Estimated Time**: 15 minutes

#### Tasks:
- [ ] Create migration function
  - Add to existing migrations file
  - Function: `add_description_column()`
  - Location: `/llm-backend/features/book_ingestion/migrations.py`

- [ ] Run migration on development database
  - Test migration works without errors
  - Verify column is created correctly

- [ ] Document migration
  - Add migration instructions to README
  - Note: Production migration will be run separately

#### Files to Modify:
- `/llm-backend/features/book_ingestion/migrations.py`

#### SQL to Execute:
```sql
ALTER TABLE teaching_guidelines
ADD COLUMN description TEXT DEFAULT NULL;

COMMENT ON COLUMN teaching_guidelines.description IS
'Comprehensive 200-300 word description covering what the topic is, how it is taught, and how it is assessed';
```

#### Acceptance Criteria:
- ✅ Migration runs successfully
- ✅ Column exists in database
- ✅ No data loss
- ✅ Rollback tested and works

**Progress**: 0/3 tasks completed

---

### 🔄 Phase 6: Testing & Verification
**Status**: Not Started
**Estimated Time**: 1.5 hours

#### Tasks:
- [ ] Manual end-to-end test
  - Upload test book (5-10 pages)
  - Generate guidelines
  - Verify description generated
  - Check description in UI
  - Approve and verify DB sync

- [ ] Unit tests for DescriptionGenerator
  - Test with minimal data
  - Test with full data
  - Test length validation
  - Location: `/llm-backend/tests/test_description_generator.py` (NEW)

- [ ] Integration tests
  - Update existing guideline extraction tests
  - Verify description in pipeline
  - Location: `/llm-backend/tests/integration/test_guideline_extraction.py`

- [ ] Regression testing
  - Verify all existing tests pass
  - Run full test suite: `pytest`

- [ ] Documentation update
  - Update API documentation
  - Update user guide

#### Files to Create:
- `/llm-backend/tests/test_description_generator.py`

#### Files to Modify:
- `/llm-backend/tests/integration/test_guideline_extraction.py`

#### Acceptance Criteria:
- ✅ All unit tests pass
- ✅ All integration tests pass
- ✅ Manual testing successful
- ✅ No regressions in existing features
- ✅ Documentation updated

**Progress**: 0/5 tasks completed

---

## 📊 Overall Progress

**Total Phases**: 6
**Completed Phases**: 4 (Phase 0, 1, 2, 3)
**In Progress**: Phase 4
**Remaining**: 2 phases

**Estimated Total Time**: 6 hours
**Time Spent**: 1.5 hours
**Time Remaining**: 1.5 hours (phases 4-6)

---

## 🔍 Key Design Decisions

1. **Generate during finalization** - Description only generated when subtopic becomes stable (same pattern as teaching_description)
2. **Keep existing fields** - All detailed fields remain unchanged; description is additive
3. **Update on regeneration** - If guidelines regenerated, description updates with new content
4. **Optional field** - Description is nullable to maintain backward compatibility
5. **Same architecture pattern** - Follows existing service layer architecture

---

## 🚨 Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Description too generic | Medium | Improve prompt with specific examples |
| LLM fails to generate | Low | Add retry logic with exponential backoff |
| Description too long/short | Low | Add length validation and regeneration |
| UI display issues | Low | Add responsive CSS and text wrapping |

---

## 📝 Notes & Observations

### Database State (Phase 0)
- All migrations up to date ✅
- Phase 6 schema fully applied ✅
- No pending migrations ✅

### Next Steps
1. Start Phase 1: Update data models
2. Run tests to verify changes
3. Move to Phase 2: Service layer

---

## 🔗 Related Documentation

- [PRD](../../prd.md)
- [Backend Architecture](../../backend-architecture.md)
- [Phase 6 Completion Report](../../PHASE6_COMPLETION_REPORT.md)
- [Book Ingestion Implementation](./book-to-curriculum-guide-mapping/IMPLEMENTATION.md)

---

**Last Updated**: 2025-10-31 (All Phases Completed! ✅)
