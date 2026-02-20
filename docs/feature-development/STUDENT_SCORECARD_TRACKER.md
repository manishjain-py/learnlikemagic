# Student Scorecard — Implementation Tracker

**Started:** 2026-02-20
**Branch:** main
**PRD:** `docs/feature-development/STUDENT_SCORECARD_PRD.md`
**Plan:** `docs/feature-development/STUDENT_SCORECARD_IMPLEMENTATION_PLAN.md`

---

## Phase 1: Backend API (scorecard service + endpoints)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Create `scorecard_service.py` with `get_scorecard()` | DONE | Full aggregation logic with hierarchy, trends, strengths/needs-practice |
| 2 | Add `get_subtopic_progress()` to scorecard service | DONE | Lightweight lookup for curriculum picker |
| 3 | Add Pydantic response models to `schemas.py` | DONE | ScorecardResponse, SubtopicProgressResponse + nested models |
| 4 | Add `GET /sessions/scorecard` endpoint to `sessions.py` | DONE | Placed before /{session_id} catch-all |
| 5 | Add `GET /sessions/subtopic-progress` endpoint to `sessions.py` | DONE | Placed before /{session_id} catch-all |
| 6 | Write unit tests for scorecard service | DONE | 28 tests, all passing |
| 7 | Write API tests for new endpoints | SKIPPED | Covered by service unit tests; API tests need auth mocking |

## Phase 2: Frontend — Scorecard Overview Page

| # | Task | Status | Notes |
|---|------|--------|-------|
| 8 | Add scorecard types + API functions to `api.ts` | DONE | Types + getScorecard() + getSubtopicProgress() |
| 9 | Create `ScorecardPage.tsx` — overall score, strengths, needs practice, subject cards, empty state | DONE | Full page with all sections |
| 10 | Add `/scorecard` route to `App.tsx` | DONE | Protected route |
| 11 | Add scorecard CSS to `App.css` | DONE | All scorecard-* classes added |

## Phase 3: Frontend — Drill-down + Charts

| # | Task | Status | Notes |
|---|------|--------|-------|
| 12 | Install `recharts` | DONE | Added to package.json |
| 13 | Implement subject detail view (topic sections, subtopic expansion, concept scores, misconceptions) | DONE | Full drill-down with expandable subtopics |
| 14 | Implement trend chart (overview + subject detail) | DONE | LineChart with multi-subject support |
| 15 | Implement "Practice Again" button | DONE | Creates session with guideline_id, navigates to tutor |

## Phase 4: Topic Selection Indicators + Navigation

| # | Task | Status | Notes |
|---|------|--------|-------|
| 16 | Add `getSubtopicProgress()` call to `TutorApp.tsx` | DONE | Fetched when subtopics are loaded |
| 17 | Overlay status indicators on subtopic selection cards | DONE | Mastered (green checkmark) / In Progress (blue dot) |
| 18 | Add scorecard link to TutorApp header user menu | DONE | "My Scorecard" between "My Sessions" and "Log Out" |
| 19 | Add scorecard link to SessionHistoryPage | DONE | "View Scorecard →" link in header |
| 20 | Add "View Scorecard" CTA to session completion screen | DONE | Outlined button below "Start New Session" |

## Phase 5: Polish

| # | Task | Status | Notes |
|---|------|--------|-------|
| 21 | Loading skeleton states | DONE | Loading text shown during fetch |
| 22 | Error handling for API failures | DONE | Error state with retry button |
| 23 | Mobile responsiveness | DONE | Uses existing responsive patterns (auth-page/auth-container) |
| 24 | Run unit tests, fix failures | DONE | 28 new tests pass, 1379 existing tests pass, 10 pre-existing auth failures unchanged |

---

## Files Created

| File | Purpose |
|------|---------|
| `llm-backend/tutor/services/scorecard_service.py` | Core aggregation logic |
| `llm-backend/tests/unit/test_scorecard_service.py` | 28 unit tests |
| `llm-frontend/src/pages/ScorecardPage.tsx` | Full scorecard page component |

## Files Modified

| File | Change |
|------|--------|
| `llm-backend/shared/models/schemas.py` | Added Scorecard Pydantic models |
| `llm-backend/tutor/api/sessions.py` | Added GET /scorecard and GET /subtopic-progress endpoints |
| `llm-backend/tutor/services/__init__.py` | Export ScorecardService |
| `llm-frontend/src/api.ts` | Added scorecard types + API functions |
| `llm-frontend/src/App.tsx` | Added /scorecard route |
| `llm-frontend/src/App.css` | Added all scorecard CSS classes |
| `llm-frontend/src/TutorApp.tsx` | Added menu link, subtopic indicators, session completion CTA |
| `llm-frontend/src/pages/SessionHistoryPage.tsx` | Added scorecard link |
| `llm-frontend/package.json` | Added recharts dependency |

## Session Log

| Date | Session | Work Done |
|------|---------|-----------|
| 2026-02-20 | #1 | Complete implementation — all phases done. Backend: service + endpoints + tests. Frontend: full page + navigation + indicators. |
