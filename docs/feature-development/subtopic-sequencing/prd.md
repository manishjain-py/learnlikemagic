# PRD: Pedagogical Sequencing & Overlap Resolution for Topics and Subtopics

**Date:** 2026-02-28
**Status:** Draft
**Author:** PRD Generator + Manish

---

## 1. Problem Statement

When admins process a textbook through the book ingestion pipeline, the system extracts topics and subtopics page-by-page. The resulting subtopics have two problems that undermine teaching quality:

1. **No pedagogical ordering.** Subtopics within a topic (and topics within a book) have no explicit teaching sequence. The only implicit order is page number, which isn't surfaced as a first-class concept. The tutor has no way to know that "Understanding Fractions" should be taught before "Adding Fractions" — it treats them as independent, unrelated units.

2. **Content overlap between subtopics.** The page-by-page boundary detection can produce subtopics that partially cover the same concepts. The existing deduplication step catches obvious name-level duplicates ("Data Handling" vs "data-handling-basics") but misses deeper semantic overlap where two subtopics teach similar ideas with different names.

Without sequencing and clean boundaries, the tutor can't build on prior knowledge. A student jumping into "Subtopic 3" may encounter concepts that assume knowledge from "Subtopic 1" — but nobody told the system (or the student) that Subtopic 1 comes first.

---

## 2. Goal

Every topic has a clear, ordered teaching storyline: non-overlapping subtopics arranged in a pedagogical sequence with a rationale explaining how they build on each other. Topics within a book are similarly ordered.

---

## 3. User Stories

- As an **admin**, I want the finalization step to produce subtopics in an explicit pedagogical order, so that I can review whether the teaching sequence makes sense.
- As an **admin**, I want the system to detect and merge semantically overlapping subtopics (not just name-level duplicates), so that each subtopic covers a distinct piece of the topic.
- As an **admin**, I want each topic to have a short storyline explaining how its subtopics build on each other, so that I can verify the teaching progression.
- As an **admin**, I want topics within a book to also be ordered pedagogically, so that the entire subject has a coherent learning path.
- As an **admin**, I want regeneration (re-extract + re-finalize) to cleanly overwrite all existing guidelines and study plans, so that I don't have to manually resolve conflicts between old and new content.

---

## 4. Functional Requirements

### 4.1 Subtopic Sequencing (within a topic)

- **FR-1:** During finalization, the system MUST assign an explicit `subtopic_sequence` number (1-indexed) to each subtopic within a topic, representing the recommended teaching order.
- **FR-2:** The sequence MUST be determined by an LLM that analyzes all subtopics within a topic holistically — considering their summaries, page ranges, and guideline content — and produces a pedagogically sound ordering.
- **FR-3:** The system MUST generate a `topic_storyline` (2-4 sentences) for each topic explaining how its subtopics build on each other and why they are in this order.

### 4.2 Topic Sequencing (within a book)

- **FR-4:** During finalization, the system MUST assign an explicit `topic_sequence` number (1-indexed) to each topic within a book, representing the recommended teaching order.
- **FR-5:** The topic sequence MUST be determined by an LLM that analyzes all topics holistically — considering their summaries and subtopic summaries — and produces a pedagogically sound ordering.

### 4.3 Enhanced Semantic Overlap Detection

- **FR-6:** The existing deduplication step MUST be enhanced to detect semantic overlap, not just name-level duplicates. Two subtopics that teach similar concepts with different names MUST be identified as candidates for merging.
- **FR-7:** When semantic overlap is detected, the overlapping subtopics MUST be merged using the existing `GuidelineMergeService` (extend, don't replace, the current pattern).
- **FR-8:** Semantic overlap detection SHOULD happen before sequencing, so that the sequencing step works with clean, non-overlapping subtopics.

### 4.4 Data Model Changes

- **FR-9:** The `SubtopicShard` (S3) MUST include a `subtopic_sequence` field (int).
- **FR-10:** The `SubtopicIndexEntry` in `GuidelinesIndex` (S3) MUST include a `subtopic_sequence` field (int).
- **FR-11:** The `TopicIndexEntry` in `GuidelinesIndex` (S3) MUST include `topic_sequence` (int) and `topic_storyline` (str) fields.
- **FR-12:** The `teaching_guidelines` DB table MUST add `topic_sequence` (INT, nullable) and `subtopic_sequence` (INT, nullable) columns.
- **FR-13:** The `teaching_guidelines` DB table MUST add a `topic_storyline` (TEXT, nullable) column.
- **FR-14:** The DB sync process MUST map the sequence and storyline fields from S3 shards/index to the corresponding DB columns.

### 4.5 Clean Regeneration

- **FR-15:** When guidelines for a book are regenerated (full snapshot sync), the system MUST delete all existing `study_plans` rows whose `guideline_id` references the guidelines being deleted, before inserting new guidelines.
- **FR-16:** The full snapshot sync (already deletes all `teaching_guidelines` for a book and inserts fresh) remains the recommended sync mechanism for regeneration. No changes needed to the delete-then-insert pattern itself.

### 4.6 Finalization Pipeline Order

- **FR-17:** The finalization pipeline MUST execute in this order:
  1. Mark all open/stable shards as final
  2. Refine topic/subtopic names (existing)
  3. Detect and merge semantic duplicates (enhanced)
  4. Sequence subtopics within each topic + generate topic storylines (new)
  5. Sequence topics within the book (new)
  6. Regenerate topic summaries (existing)
  7. Optionally sync to database

---

## 5. UX Requirements

This PRD focuses on admin-side backend changes. Student-facing UX changes (e.g., showing subtopics in pedagogical order on the topic selection screen) are **out of scope** and will be addressed in a follow-up.

- **UX-1:** The admin guidelines review screen SHOULD display subtopics within a topic in their `subtopic_sequence` order (not alphabetical or insertion order).
- **UX-2:** The admin guidelines review screen SHOULD display the `topic_storyline` for each topic, so the admin can verify the teaching rationale.
- **UX-3:** The admin guidelines review screen SHOULD display topics in their `topic_sequence` order.

---

## 6. Technical Considerations

### Integration Points

- **Backend modules affected:** `book_ingestion` (finalization pipeline, models, prompts, DB sync), `shared` (entities, DB migration)
- **Database changes:** Add 3 columns to `teaching_guidelines`: `topic_sequence` (INT), `subtopic_sequence` (INT), `topic_storyline` (TEXT). Add cascade delete of `study_plans` in full snapshot sync.
- **API endpoints:** No new endpoints. Existing finalization and sync endpoints gain new behavior.
- **Frontend screens:** Minor changes to guidelines review display order (UX-1 through UX-3). No new screens.

### Architecture Notes

**New service: `PedagogicalSequencingService`**
- Follows existing service pattern (LLM call with prompt template, Pydantic structured output)
- Two methods: `sequence_subtopics(topic_key, subtopics)` and `sequence_topics(topics)`
- Prompt templates: `subtopic_sequencing.txt` and `topic_sequencing.txt`
- Temperature: 0.2 (consistent, deterministic outputs)
- Uses same LLM config as other book ingestion services (`book_ingestion` component key)

**Enhanced `TopicDeduplicationService`**
- Extend the existing dedup prompt to instruct the LLM to detect semantic overlap, not just name-level duplicates
- Add criteria: "Two subtopics covering the same learning objectives with different names or framing"
- No new service needed — enhance the existing one

**Finalization orchestrator changes**
- Add sequencing step after dedup, before summary regeneration
- Sequencing needs final, deduplicated subtopics to work with

**DB sync changes**
- `DBSyncService.sync_book_guidelines()` (full snapshot): Before deleting `teaching_guidelines` rows, first delete all `study_plans` whose `guideline_id` matches the guidelines being deleted
- Map `subtopic_sequence`, `topic_sequence`, `topic_storyline` from index/shard to DB columns

### Key Files to Modify

| File | Change |
|------|--------|
| `book_ingestion/models/guideline_models.py` | Add `subtopic_sequence` to `SubtopicShard`, `SubtopicIndexEntry`. Add `topic_sequence`, `topic_storyline` to `TopicIndexEntry`. |
| `book_ingestion/services/guideline_extraction_orchestrator.py` | Add sequencing step to finalization flow |
| `book_ingestion/services/topic_deduplication_service.py` | Enhance prompt for semantic overlap detection |
| `book_ingestion/services/db_sync_service.py` | Map new fields to DB; cascade-delete study plans on full snapshot |
| `book_ingestion/services/index_management_service.py` | Handle sequence fields in index updates |
| `shared/models/entities.py` | Add `topic_sequence`, `subtopic_sequence`, `topic_storyline` columns to `TeachingGuideline` |
| `db.py` | Migration to add new columns |
| `book_ingestion/prompts/topic_deduplication_v2.txt` | Enhance for semantic overlap |

### New Files

| File | Purpose |
|------|---------|
| `book_ingestion/services/pedagogical_sequencing_service.py` | LLM-based sequencing service |
| `book_ingestion/prompts/subtopic_sequencing.txt` | Prompt for ordering subtopics within a topic |
| `book_ingestion/prompts/topic_sequencing.txt` | Prompt for ordering topics within a book |

---

## 7. Impact on Existing Features

| Feature | Impact | Details |
|---------|--------|---------|
| Guideline extraction (per-page) | None | Extraction pipeline unchanged. Sequencing happens in finalization. |
| Finalization | Major | Two new steps added (subtopic sequencing, topic sequencing). Dedup prompt enhanced. |
| DB sync | Minor | Maps 3 new fields. Cascade-deletes study plans on full snapshot. |
| Study plan generation | Minor | Study plans are deleted on regeneration. Must be re-generated after new guidelines are approved. |
| Admin guidelines review | Minor | Display order changes to use sequence fields. Storyline displayed. |
| Tutoring sessions | None (for now) | Topic/subtopic selection order is a future follow-up. Existing sessions not affected. |
| Evaluation | None | No changes. |
| Scorecard | None | No changes. |
| Auth & onboarding | None | No changes. |

---

## 8. Edge Cases & Error Handling

| Scenario | Expected Behavior |
|----------|-------------------|
| Topic has only 1 subtopic | `subtopic_sequence = 1`. Storyline states this is the only subtopic. |
| Book has only 1 topic | `topic_sequence = 1`. No cross-topic ordering needed. |
| Sequencing LLM call fails | Log error, fall back to page-order sequencing (assign sequence numbers by `source_page_start`). Finalization still completes. |
| Dedup merges subtopics after sequencing has run | Sequencing runs AFTER dedup (FR-17), so this can't happen. |
| Existing guidelines have NULL sequence fields | Acceptable. Old guidelines without sequences continue to work. Frontend falls back to existing display order. |
| Regeneration while a tutoring session is active on old guidelines | Active sessions reference `guideline_id`. The old guideline row is deleted. Active sessions become orphaned — they'll still work (state is self-contained in `state_json`) but their `guideline_id` FK will be dangling. This is acceptable for an admin-driven regeneration operation. |
| Very large topic with 20+ subtopics | LLM can handle this in a single call. If context limits are hit, chunk by sending summaries only (not full guidelines). |

---

## 9. Out of Scope

- **Student-facing subtopic ordering** — Showing subtopics in pedagogical order on the topic/subtopic selection screens. This is a follow-up.
- **Prerequisite tracking** — Explicitly marking that "Subtopic B requires Subtopic A". The storyline captures this implicitly; formal prerequisite graphs are future work.
- **Cross-book sequencing** — Ordering across different books/grades. One book = one subject for one grade.
- **Manual reordering by admin** — Admin cannot drag-and-drop to reorder subtopics. If the AI order is wrong, the admin re-runs finalization (which may produce a different order).
- **Partial regeneration** — Regenerating guidelines for specific topics only. Regeneration is always full-book.
- **Tutor awareness of sequence** — Making the tutor aware that "you're teaching Subtopic 3, the student should already know Subtopics 1-2". This is a follow-up that uses the sequence data.

---

## 10. Open Questions

- **Prompt quality iteration:** The sequencing prompt will need iteration based on real textbook results. Initial prompt should be tested against 2-3 books and manually reviewed before broad rollout.
- **LLM cost:** Each finalization adds 2 more LLM calls (subtopic sequencing per topic + topic sequencing). For a book with 10 topics, that's ~11 additional calls. Cost is modest (~$0.50-1.00 per book finalization) but worth monitoring.

---

## 11. Success Metrics

- **No duplicate/overlapping subtopics** after finalization (verified by admin review of 3+ books).
- **Pedagogical order matches human expectation** — Admin reviews sequence for 3+ books and confirms >90% of subtopics are in a reasonable teaching order.
- **Storyline is useful** — Admin can read each topic's storyline and understand the teaching progression without looking at individual subtopics.
- **Clean regeneration** — Re-running extraction + finalization + sync produces a fresh, conflict-free set of guidelines with no orphaned study plans.
