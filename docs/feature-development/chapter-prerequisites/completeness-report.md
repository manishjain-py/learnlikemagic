# Completeness Report: Chapter Prerequisites

## Backend — New Modules
- [x] `book_ingestion_v2/services/refresher_topic_generator_service.py` — service + pydantic models
- [x] `book_ingestion_v2/prompts/refresher_topic_generation.txt` — LLM prompt

## Backend — Modified Modules
- [x] `book_ingestion_v2/constants.py` — `REFRESHER_GENERATION` job type
- [x] `shared/models/domain.py` — `is_refresher` + `prerequisite_concepts` on GuidelineMetadata
- [x] `tutor/models/session_state.py` — `is_refresher` flag + `is_complete` fix
- [x] `tutor/services/topic_adapter.py` — 0-step plan for refresher
- [x] `tutor/services/session_service.py` — refresher detection, mode rejection, card phase short-circuit
- [x] `book_ingestion_v2/api/sync_routes.py` — `/refresher/generate`, `/landing`, `/refresher-jobs/latest`
- [x] `book_ingestion_v2/models/schemas.py` — `refresher_deleted` on SyncResponse
- [x] `book_ingestion_v2/services/topic_sync_service.py` — refresher deletion warning
- [x] `shared/models/schemas.py` — `topic_key` on TopicInfo, `refresher_guideline_id` on ChapterInfo
- [x] `shared/repositories/guideline_repository.py` — expose topic_key + refresher_guideline_id

## Frontend
- [x] `ChatSession.tsx` — session_complete handling, hide variant switching, "I'm Ready" button
- [x] `ModeSelection.tsx` — hide Exam/Clarify for refresher
- [x] `ChapterSelect.tsx` — exclude refresher from progress %
- [x] `ReportCardPage.tsx` — exclude refresher from scorecard
- [x] `TopicSelect.tsx` — chapter landing section (what you'll learn + prerequisites)
- [x] `ModeSelectPage.tsx` — pass topicKey through navigation
- [x] `api.ts` — topic_key + refresher_guideline_id types

## Tests
- [x] 17 unit tests — all passing
- [x] State persistence round-trip
- [x] is_complete semantics (before/after cards)
- [x] Zero-step plan for refresher
- [x] Default plan preserved for regular topics
- [x] RefresherOutput model validation

## Database
- [x] No new tables (by design) — refresher is a TeachingGuideline row

## Missing / Deferred
- [ ] `test_refresher_session_cards_only` — needs integration test with real session service (mocked in unit tests)
- [ ] `test_chapter_landing_page` — needs integration test with DB
- [ ] `test_resync_deletes_refresher` — needs integration test with DB
- [ ] `test_refresher_excluded_from_progress` — needs frontend E2E test
- [ ] `POST .../refresher/generate-all` book-level batch endpoint — mentioned in plan, not critical for MVP
