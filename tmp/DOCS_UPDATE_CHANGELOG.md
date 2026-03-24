# Docs Update Changelog — 2026-03-23

13 docs updated, 0 new docs created.

---

## Updated Docs

### Agent 1 — App Overview & Architecture

| Doc | Changes |
|-----|---------|
| `docs/functional/app-overview.md` | Added 3 features: Report Issue, Interactive Visuals PoC, Issue Management; added student journey step 12 (report issue); added admin journey steps 9-10 (interactive visuals, manage issues) |
| `docs/technical/architecture-overview.md` | Added `/report-issue` route, `issue_service` to shared services, `issues` DB table; added issues router; added ReportIssuePage, InteractiveVisualsPocPage, AdminIssuesPage; added 3 routes; added Issue Reporting section; updated autoresearch pipeline count 4→6 |

**Code fix:** `llm-backend/main.py` — corrected TTS router comment from "OpenAI TTS" to "Google Cloud TTS"

### Agent 2 — Learning Session

| Doc | Changes |
|-----|---------|
| `docs/functional/learning-session.md` | Added per-card simplification (4 help options + escalation); added Rule 0: radical simplicity; added first-instinct-right validation to Rule 6 |
| `docs/technical/learning-session.md` | Added `POST /sessions/{id}/simplify-card` endpoint; updated teaching rules 15→16 (0-15); added Rule 0 description; added Per-Card Simplification subsection (REASON_MAP, flow, SimplifiedCardOutput); expanded CardPhaseState with RemedialCard/ConfusionEvent; updated bridge types 2→3 (card_stuck); added Card Simplification LLM call; updated 7 Key Files entries |

### Agent 3 — Evaluation

| Doc | Changes |
|-----|---------|
| `docs/functional/evaluation.md` | No changes needed |
| `docs/technical/evaluation.md` | Added clarification: `topic_info` only passed in session evaluation path, not simulated evaluations |

### Agent 4 — Scorecard

| Doc | Changes |
|-----|---------|
| `docs/functional/scorecard.md` | Documented 3 progress badge statuses with thresholds (Completed ≥80%, In Progress >0%, Not Started); documented hidden Take Exam button during incomplete exams |
| `docs/technical/scorecard.md` | Added `/sessions/resumable` endpoint; added frontend ProgressStatus badge mapping; added exam review rendering note (only next_steps used); added Take Exam hiding logic; added ResumableSessionResponse schema; updated Key Files |

### Agent 5 — Book & Guidelines

| Doc | Changes |
|-----|---------|
| `docs/functional/book-guidelines.md` | Added Step 8: Enrich with Interactive Visuals (scoping, generation, validation) |
| `docs/technical/book-guidelines.md` | Added Visual Enrichment (PixiJS) pipeline section; added `POST /generate-visuals` endpoint; added `v2_visual_enrichment` job type; added `animation_enrichment` + `animation_code_gen` LLM config keys; added 2 LLM prompts; added AnimationEnrichmentService + reprocess_chapter_pipeline.py to Key Files |

### Agent 6 — Auth & Onboarding

| Doc | Changes |
|-----|---------|
| `docs/functional/auth-and-onboarding.md` | Added "Report an Issue" to user menu items |
| `docs/technical/auth-and-onboarding.md` | Added report-an-issue to AppShell description; added `/report-issue` route; added ReportIssuePage.tsx to Key Files |

### Agent 7 — Infrastructure

| Doc | Changes |
|-----|---------|
| `docs/technical/database.md` | Added Issues table (10 columns, types, indexes, FKs); added Issue to relationships diagram; added migration step 19; updated Key Files entities list |
| `docs/technical/dev-workflow.md` | No changes needed — verified current |
| `docs/technical/deployment.md` | No changes needed — verified current |

---

## Newly Created Docs

None — all functionality adequately covered by existing docs.

---

## Coverage Matrix

| Feature/Module | Functional Doc | Technical Doc |
|---|---|---|
| App overview & user journey | app-overview.md | architecture-overview.md |
| Learning sessions (tutor) | learning-session.md | learning-session.md |
| Card phase & simplification | learning-session.md | learning-session.md |
| Interactive questions | learning-session.md | learning-session.md |
| Evaluation pipeline | evaluation.md | evaluation.md |
| Scorecard / progress badges | scorecard.md | scorecard.md |
| Book ingestion & guidelines | book-guidelines.md | book-guidelines.md |
| Visual enrichment (PixiJS) | book-guidelines.md | book-guidelines.md |
| Explanation cards & TTS | book-guidelines.md | book-guidelines.md |
| Session plan generation | book-guidelines.md | book-guidelines.md |
| Auth & onboarding | auth-and-onboarding.md | auth-and-onboarding.md |
| Report an Issue | app-overview.md | architecture-overview.md |
| Issue management (admin) | app-overview.md | architecture-overview.md |
| Interactive Visuals PoC | app-overview.md | architecture-overview.md |
| Dev workflow & testing | N/A (dev-facing) | dev-workflow.md |
| Deployment & infra | N/A (ops-facing) | deployment.md |
| Database schema | N/A (dev-facing) | database.md |
| Autoresearch | N/A (internal) | auto-research/overview.md |
| AI agent files | N/A (internal) | ai-agent-files.md |

No coverage gaps identified.

---

## Deferred Items

None.
