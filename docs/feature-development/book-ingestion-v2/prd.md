# PRD: Book Ingestion Pipeline V2 (Chapter-First, Topic-Only)

**Status:** Draft
**Date:** 2026-03-01
**Owner:** Admin Ingestion / AI Content Structuring

---

## 1) Why This Exists

The current ingestion flow tries to infer structure across the full book and multiple hierarchy levels (chapter/subtopic/topic), which makes boundary detection brittle, hard to debug, and difficult to trust for downstream tutoring quality.

Pipeline V2 introduces one foundational change:

- **Book structure starts from an explicit Table of Contents (TOC)** entered by admin.
- TOC becomes the authoritative first-level boundary (**Book → Chapters**).
- AI processing is constrained to one chapter at a time.
- Within chapter, AI only solves one semantic task: **Topic detection and guideline map building** (**Chapter → Topics**).

Final hierarchy becomes:

**Book → Chapter → Topic** (no subtopic layer in V2).

---

## 2) Product Goals

1. **Improve structural accuracy** by replacing inferred chapter boundaries with explicit TOC boundaries.
2. **Improve reliability and traceability** by forcing chapter completeness before OCR/topic generation starts.
3. **Improve learning usability** by producing small, teachable topics suitable for ~10–20 minute instruction units.
4. **Preserve robustness standards** from existing ingestion system (logging, resumability/retriability, auditability, modular code).
5. **Ship as a parallel system** without modifying existing ingestion pipeline behavior.

---

## 3) Non-Goals

- Replacing/deleting current pipeline (V1 remains intact).
- Introducing subtopic extraction in V2.
- Changing tutoring runtime behavior in this phase (V2 provides improved chapter/topic artifacts consumed downstream).
- Migrating all historical books immediately.

---

## 4) Core Requirements (As Understood)

### 4.1 TOC as First-Class Input

After entering book metadata, admin must define TOC entries with at least:

- `chapter_number` (or sequence index)
- `chapter_title` (source/book title)
- `start_page`, `end_page` (inclusive page range)

System treats this as authoritative structure for ingestion and validation.

### 4.2 Chapter-Bound Upload Workflow

- Admin uploads pages **within a selected chapter context**.
- Upload is sequence-aware and range-aware.
- Chapter is marked **complete** only when all pages in TOC-defined range are present.
- OCR/topic processing for a chapter can only start after chapter completeness is satisfied.

### 4.3 AI Processing Unit and Inputs

Chapter pages are processed in rolling page windows of size 3:

- Current chunk: pages `[n, n+1, n+2]`
- Previous-page context: page `n-1` text (if exists)
- Running state:
  - `chapter_summary_so_far`
  - `topic_guidelines_map_so_far`

Primary AI question per chunk:

- Which topics are taught in these pages?
- For each detected topic: is it new vs existing?
- Update existing topic guidance and chapter summary incrementally.

### 4.4 Chapter Finalization

After all chapter chunks are processed:

- Run chapter-level consolidation:
  - deduplication of semantically overlapping topics
  - naming normalization
  - coherence clean-up
- Produce final chapter output:
  - `chapter_display_name` (can differ from original TOC title based on actual content)
  - `final_chapter_summary`
  - `final_topic_guidelines_map`

---

## 5) Functional Specification

## 5.1 Admin UX (under `/admin`)

Create V2-specific flow under admin routes with parity for useful conveniences from recent ingestion UX:

1. **Book Metadata Step**
2. **TOC Authoring Step** (create/edit/reorder chapters, ranges, validation)
3. **Chapter Upload Step**
   - chapter selector
   - range progress (e.g., 7/12 pages uploaded)
   - missing-page indicators
4. **Chapter Processing Step**
   - Start OCR + topic extraction (only when chapter complete)
   - progress bar + per-chunk status
   - last processed page/chunk
   - retry/resume controls
5. **Chapter Results Step**
   - chapter output preview (title, summary, topics)
   - optional admin approval/edit hooks if applicable to existing pattern

## 5.2 Validation Rules

- TOC ranges cannot overlap.
- TOC ranges must be positive and bounded.
- Chapter cannot enter processing state if any page in range missing.
- Upload must reject pages outside selected chapter range unless explicitly reassigned.
- Duplicate page index within chapter handled via replace/confirm flow.

## 5.3 Topic Granularity Heuristics (LLM + Rules)

Topic segmentation should bias toward teachability:

- A topic should generally fit a 10–20 minute learning unit.
- Prefer conceptually atomic skills/concepts over broad umbrellas.
- Merge only when concepts are inseparable in pedagogical use.
- Split when independent practice, explanation, or assessment can exist.

### Decision guide: New Topic vs Existing Topic

Treat as **existing** when:

- same learning objective
- same core concept with continuation/examples
- primarily deepening previously introduced explanation

Treat as **new** when:

- introduces a new learning objective or conceptual unit
- introduces a new method/process requiring independent mastery
- would be taught as a distinct mini-lesson

---

## 6) System Architecture (V2, parallel track)

## 6.1 Repository/Module Layout

Introduce a parallel package/folder set (names indicative):

- `book_ingestion_v2/` (backend domain package)
  - `toc/`
  - `chapter_upload/`
  - `ocr/`
  - `topic_extraction/`
  - `chapter_finalization/`
  - `jobs/`
  - `api/`

Frontend parallel admin flow (indicative):

- `llm-frontend/.../admin/book-ingestion-v2/...`

No behavioral regressions to V1 endpoints/components.

## 6.2 Pipeline States

Per chapter:

1. `toc_defined`
2. `upload_in_progress`
3. `upload_complete`
4. `ocr_processing`
5. `topic_extraction_processing`
6. `chapter_finalizing`
7. `chapter_completed`
8. `failed` (with retryable metadata)

## 6.3 Data Model (Conceptual)

New entities (or extensions) expected:

- `book_toc_entries`
- `chapter_page_assets`
- `chapter_processing_jobs`
- `chapter_topic_map_versions`
- `chapter_summaries`

Auditability fields:

- status timestamps
- actor/admin IDs
- model config + prompt version IDs
- per-chunk input/output references
- error taxonomy (`retryable`, `terminal`, `validation`)

---

## 7) AI Prompting + Model Configuration

- Reuse existing configurable model-selection pattern used in ingestion (same mechanism, V2 component key).
- Default to codex-5.3 where configured, but keep model/provider runtime-configurable.
- Prompt contracts should be strict JSON schema outputs for:
  - chunk topic updates
  - chapter summary updates
  - final consolidation outputs
- Enforce deterministic post-validation of AI output before persistence.

---

## 8) Reliability / NFR Requirements

Same robustness bar as current ingestion system:

- **Resumability:** chunk-level progress checkpointing
- **Retryability:** transient failures recover without restarting chapter from scratch
- **Observability:** structured logs, job metrics, per-chunk traces
- **Auditability:** reproducible chain from input pages → topic map output
- **Performance:** bounded memory and latency per chunk
- **Idempotency:** safe reprocessing for same chunk/chapter version
- **Modularity/readability:** clear service boundaries and testable components

---

## 9) Quality Guardrails

To protect tutoring quality:

1. **Boundary correctness guardrail**
   - never process cross-chapter pages in same run
2. **Topic quality guardrail**
   - reject overly broad topic names when confidence low; force refinement pass
3. **Continuity guardrail**
   - use previous-page context to prevent false topic splits at chunk boundaries
4. **Consolidation guardrail**
   - enforce semantic dedup threshold during finalization
5. **Human review readiness**
   - expose explainability metadata (why merged/split/new/existing)

---

## 10) Rollout Strategy

1. Build V2 behind admin feature flag.
2. Internal pilot on representative books (short, medium, long chapters).
3. Compare V1 vs V2 on:
   - topic coherence
   - duplication rate
   - manual correction effort
4. Graduate to default for new books once acceptance criteria met.
5. Keep V1 available for rollback until stabilization window ends.

---

## 11) Acceptance Criteria

A chapter can be considered production-ready in V2 when:

- TOC range fully uploaded and validated.
- OCR complete for all pages in range.
- Chunk pipeline finishes with no unresolved errors.
- Final chapter output exists (name, summary, topic map).
- Logs/artifacts allow chunk-by-chunk reconstruction.
- Retry/resume has been validated in at least one induced-failure scenario.

Program-level acceptance:

- V2 runs end-to-end on pilot books without V1 regression.
- Admin UX clearly communicates chapter completeness and processing readiness.
- Output topics are judged teachable and sufficiently granular by content reviewers.

---

## 12) Open Questions (Need Product/Engineering Decisions)

1. **TOC flexibility:** Should admins be allowed to edit TOC ranges after uploads begin? If yes, what remapping behavior is required?
2. **Page indexing source of truth:** Human-entered page number vs detected printed page vs upload sequence index?
3. **Chunk stride:** Strict non-overlapping chunks (1-3, 4-6...) vs sliding windows with overlap?
4. **Chapter rename policy:** Should generated chapter name auto-replace TOC name or be stored as alternate “covered content title”?
5. **Human approval gate:** Is explicit admin approval required before chapter topics are finalized/published?
6. **Cross-page artifacts:** How should diagrams/tables spanning chunk boundaries be handled in OCR/topic pass?
7. **Multi-language support:** Is V2 expected to support non-English books from day one?
8. **Backfill plan:** Do we need a migration tool to generate TOC for existing books that lack explicit entries?

---

## 13) Implementation Planning Note

This PRD intentionally focuses on product/behavior contracts. Detailed technical implementation plan (API schema, DB migrations, job orchestration, prompt contracts, tests, rollout checklist) should be authored next as a separate engineering design doc under this V2 folder.
