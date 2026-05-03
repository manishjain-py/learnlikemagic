# Report Card — Technical

Service architecture, aggregation algorithm, and API for the student report card.

The report card is **deterministic only** — it shows coverage completion percentages (from Teach Me sessions) and latest practice scores (from graded practice attempts). There are no AI-interpreted mastery scores, no aggregate scores at any level, no trend charts, no strengths/weaknesses rankings, and no misconception tracking.

---

## API Endpoints

| Method | Path | Auth | Response Model | Description |
|--------|------|------|----------------|-------------|
| `GET` | `/sessions/report-card` | Required | `ReportCardResponse` | Full student report card with coverage and practice data |
| `GET` | `/sessions/topic-progress` | Required | `TopicProgressResponse` | Lightweight progress map for curriculum picker badges |
| `GET` | `/sessions/resumable?guideline_id=` | Required | `ResumableSessionResponse` | Find paused Teach Me session for a topic (404 if none) |
| `GET` | `/sessions/guideline/{guideline_id}` | Required | `GuidelineSessionsResponse` | List sessions for a topic (mode selection, resume detection) |

All endpoints are in `tutor/api/sessions.py`. The first two delegate to `ReportCardService`; the resumable endpoint queries `SessionModel` directly for paused teach_me sessions and validates state via `SessionState.model_validate_json`; the guideline sessions endpoint delegates to `SessionRepository.list_by_guideline()`.

Practice-attempt endpoints (`POST /practice/start`, `GET /practice/attempts/*`, etc.) are documented in `docs/technical/practice-mode.md`. The report card reads practice attempt data via a direct `db.query(PracticeAttempt)` inside `ReportCardService._load_user_practice_attempts` (not through `PracticeAttemptRepository`), so it can apply the `(guideline_id ASC, graded_at DESC)` sort needed for head-of-group latest-attempt selection.

---

## ReportCardService

**File:** `tutor/services/report_card_service.py`

**Class:** `ReportCardService(db)`

### Public Methods

- `get_report_card(user_id)` → Full report card dict (used by `/report-card`)
- `get_topic_progress(user_id)` → `{user_progress: {guideline_id: {coverage, session_count, status}}}`

### Private Methods

| Method | Purpose |
|--------|---------|
| `_load_user_sessions(user_id)` | Query sessions for user (columns: `id`, `state_json`, `subject`, `mastery`, `created_at`), ordered `created_at ASC`, `id ASC` |
| `_load_user_practice_attempts(user_id)` | Query `practice_attempts` for `status='graded'` with non-null `graded_at` and `total_score`, ordered `guideline_id ASC`, `graded_at DESC` — so `attempts[0]` per group is latest |
| `_build_guideline_lookup(sessions, practice_attempts)` | Batch-query `teaching_guidelines` from BOTH source lists to build `guideline_id → {subject, chapter, topic, keys}` map. Practice-only topics resolve hierarchy via this extension. |
| `_group_sessions(sessions, guideline_lookup)` | Group Teach Me + Clarify sessions into subject/chapter/topic hierarchy; accumulate coverage from teach_me sessions only |
| `_merge_practice_attempts_into_grouped(grouped, guideline_lookup, practice_attempts)` | Group graded attempts by guideline_id in Python, take head-of-group as latest, count the group, augment or CREATE the topic row if practice-only |
| `_build_report(grouped)` | Build flat report structure with coverage + practice chip per topic |
| `_empty_report_card()` | Return zero-valued report card for users with no sessions AND no practice attempts |

---

## Data Flow

```
Sessions (DB)                           PracticeAttempts (DB, status='graded')
    │                                       │
    └──────────────┬────────────────────────┘
                   v
       _build_guideline_lookup — batch-query teaching_guidelines
       from BOTH source lists (subject + chapter + topic)
                   │
                   v
       _group_sessions — Teach Me → coverage accumulation
                         Clarify → session count only
                   │
                   v
       _merge_practice_attempts_into_grouped
         — sorted fetch (guideline_id ASC, graded_at DESC)
         — head-of-group = latest_practice_score + total
         — len(group) = practice_attempt_count
         — creates the topic row if practice-only
                   │
                   v
       _build_report — per topic:
         coverage               = |covered ∩ plan| / |plan| × 100
         latest_practice_score  = attempts[0].total_score (if any graded)
         latest_practice_total  = attempts[0].total_possible
         practice_attempt_count = len(attempts)
         last_studied           = most recent teach_me session date
```

### Coverage Computation

Coverage is computed in `_build_report` from accumulated data:

```python
plan_concepts = set(topic_info.get("plan_concepts", []))
covered = set(topic_info.get("concepts_covered", []))
coverage = round(len(covered & plan_concepts) / len(plan_concepts) * 100, 1)
```

Key details:
- Only **Teach Me** sessions contribute to coverage. Clarify Doubts sessions and practice attempts are excluded.
- `concepts_covered` is a **union** across all Teach Me sessions for the topic.
- `plan_concepts` comes from the **latest** Teach Me session's `mastery_estimates` keys (not a union). This prevents denominator drift when the study plan is updated.
- If `plan_concepts` is empty, coverage is 0.

### Practice Score Merge (Python, Not SQL)

`_load_user_practice_attempts` returns a SQLAlchemy result pre-sorted by `(guideline_id ASC, graded_at DESC)`. `_merge_practice_attempts_into_grouped` then groups in Python — no SQL `array_agg ORDER BY`:

- Per-user attempt volumes are tiny, so Python grouping is fast enough.
- Keeps the code portable between SQLite (tests) and Postgres (prod) without dialect-specific aggregates.
- `attempts[0]` per group is automatically the latest thanks to the ORDER BY on the fetch.

Practice-only topics — i.e., a student completed a practice attempt but never a Teach Me session on the topic — still appear in the report card response because `_build_guideline_lookup` was extended to accept practice attempts as a second source of guideline_ids, and `_merge_practice_attempts_into_grouped` creates a fresh `(subject, chapter, topic)` row in `grouped` when none exists.

**Caveat:** the frontend's empty-state guard short-circuits on `total_sessions === 0` (which counts only `Session` rows, not practice attempts). A student with practice-only attempts and zero teach_me/clarify sessions sees the empty state even though `subjects` is populated. Aligning these would require either counting practice attempts toward `total_sessions` or changing the frontend guard to `subjects.length === 0`.

### Cross-Session Accumulation

| Field | Source | Logic |
|-------|--------|-------|
| `concepts_covered` | `state.concepts_covered_set` (teach_me only) | Union across all Teach Me sessions |
| `plan_concepts` | `state.mastery_estimates` keys (teach_me only) | Latest Teach Me session's plan concepts (overwrites) |
| `last_studied` | Session date | Updated by teach_me sessions |
| `latest_practice_score` | `practice_attempts.total_score` (graded only) | Latest graded attempt (first in sorted fetch) |
| `latest_practice_total` | `practice_attempts.total_possible` (graded only) | Latest graded attempt |
| `practice_attempt_count` | Count of graded attempts per guideline_id | Simple `len(attempts)` |

### Topic Progress (Lightweight)

Used by the curriculum picker to show coverage indicators. Both `ChapterSelect.tsx` and `TopicSelect.tsx` call `getTopicProgress()` on mount and use the returned map to render progress badges alongside each chapter or topic.

**Backend** (`ReportCardService.get_topic_progress`):
- Only counts **Teach Me** sessions (Clarify Doubts sessions are excluded entirely)
- Coverage uses `mastery_estimates` keys from the latest teach_me session as the plan denominator (same logic as the full report card)
- Returns map keyed by `topic_id` (the session's `state.topic.topic_id`, which is the guideline id)
- Returned `status` is always `"studied"` in practice — entries only exist for guidelines the user has touched. The frontend treats missing keys as "not started" implicitly
- Returns `{user_progress: {guideline_id: {coverage, session_count, status}}}`

**Frontend badge mapping** — Both components define a local `ProgressStatus` type (`completed | in_progress | not_started`) derived from backend coverage values:

- `TopicSelect.tsx`: missing entry or `coverage === 0` = not_started; `coverage >= 80` = completed; else in_progress. Shows "X% covered" text when coverage > 0. The `get-ready` refresher topic is rendered separately as a "Get Ready" CTA in the chapter landing block, not in the regular topic list.
- `ChapterSelect.tsx`: averages coverage across all `guideline_ids` in the chapter, **excluding `refresher_guideline_id`** so the Get Ready warm-up doesn't drag the chapter status down. `avg >= 80` = completed, `avg > 0` = in_progress, else not_started.

Completed items show a checkmark; in_progress and not_started show the sequence number with different styling.

---

## Response Schemas

### ReportCardResponse (`/sessions/report-card`)

```python
{
    "total_sessions": int,
    "total_chapters_studied": int,
    "subjects": [
        {
            "subject": str,
            "chapters": [
                {
                    "chapter": str,
                    "chapter_key": str,
                    "topics": [
                        {
                            "topic": str,
                            "topic_key": str,
                            "guideline_id": str | None,
                            "coverage": float,                        # 0-100%, teach_me only
                            "latest_practice_score": float | None,    # e.g., 7.5
                            "latest_practice_total": int | None,      # e.g., 10
                            "practice_attempt_count": int | None,     # graded attempts only
                            "last_studied": str | None                # ISO date
                        }
                    ]
                }
            ]
        }
    ]
}
```

### TopicProgressResponse (`/sessions/topic-progress`)

```python
{
    "user_progress": {
        "<guideline_id>": {
            "coverage": float,       # 0-100%
            "session_count": int,    # teach_me sessions only
            "status": str            # "studied" | "not_started"
        }
    }
}
```

### ResumableSessionResponse (`/sessions/resumable`)

```python
{
    "session_id": str,
    "mode": str,                       # always "teach_me"
    "teach_me_mode": str | None,       # "explain" | "baatcheet" | None
    "coverage": float,                 # 0-100%
    "current_step": int,
    "total_steps": int,
    "concepts_covered": [str]
}
```

### GuidelineSessionsResponse (`/sessions/guideline/{guideline_id}`)

```python
{
    "sessions": [
        {
            "session_id": str,
            "mode": str,                      # "teach_me" | "clarify_doubts"
            "teach_me_mode": str | None,      # "explain" | "baatcheet" (teach_me only)
            "created_at": str | None,         # ISO datetime
            "is_complete": bool,
            "coverage": float | None          # 0-100% (teach_me only)
        }
    ]
}
```

---

## Guideline Sessions

The `/sessions/guideline/{guideline_id}` endpoint powers the mode selection screen. It returns all chat sessions (Teach Me, Clarify Doubts) for a user+guideline pair, with optional `mode` and `finished_only` query parameters.

`SessionRepository.list_by_guideline()` computes per-session metadata from `state_json`:

| Field | Logic |
|-------|-------|
| `is_complete` | Delegates to `SessionState.is_complete` property (single source of truth): clarify_doubts → `clarify_complete`; teach_me Explain → `card_phase.completed`; teach_me Baatcheet → `dialogue_phase.completed`; refresher → `card_phase.completed`; legacy v1 fallback → `current_step > total_steps` |
| `coverage` | teach_me only: `|concepts_covered_set & plan_concepts| / |plan_concepts| * 100`. `plan_concepts` is the **canonical concept list** — pulled from the most recent teach_me session's `mastery_estimates` keys via `_get_canonical_concepts(guideline_id)` (returns `[]` for practice-only users) |

The frontend (`ModeSelection.tsx`) uses this to detect incomplete teach_me sessions with progress (`coverage > 0`) and show "Continue Lesson".

Refresher topics (`topic.topic_key === 'get-ready'`) suppress everything except the Teach Me ("Get Ready") card: no Clarify Doubts option, no Let's Practice tile.

Practice attempts are NOT returned by this endpoint. Practice history is fetched separately via `GET /practice/attempts/for-topic/{guideline_id}` and lives on the practice landing page, not on the mode selection screen.

---

## Topic Hierarchy Resolution

The service resolves chapter/topic names from two sources, in order of preference:

1. **TeachingGuideline table** — If the session's `topic_id` or the attempt's `guideline_id` matches a guideline, use `chapter_title` / `topic_title` (with fallback to `chapter` / `topic`), plus `chapter_key` / `topic_key`, and include `subject` so practice-only topics can resolve their subject for report-card grouping.
2. **Topic name splitting** — If no guideline match (session-only fallback), split `topic_name` on `" - "` to derive chapter and topic.
3. **Raw name** — If no separator found, use the full `topic_name` as both chapter and topic.

---

## Frontend

### Report Card Page

**File:** `llm-frontend/src/pages/ReportCardPage.tsx`

The frontend calls `getReportCard()` which hits `/sessions/report-card`. It renders the report card in two views:

- **Overview** — Title "My Report Card", session/chapter counts, subject cards grid
- **Subject Detail** — Back navigation, chapter/topic tree with coverage bars, practice-score chips, last-studied dates, and "Practice Again" buttons

`ChapterSection` filters out topics where `topic_key === 'get-ready'` so refresher/prerequisite warm-ups don't pollute the report card. "Practice Again" is only rendered when `topic.guideline_id` is set (sessions without a guideline link can't be replayed).

**Practice chip rendering:** when `latest_practice_score != null && latest_practice_total != null`, the chip renders `{formatPracticeScore(score)}/{total} · {count} attempt(s)`. `formatPracticeScore` returns `8` for whole numbers and `7.5` for halves — `toFixed(1)` across the board would produce `8.0` which is noisy.

### Mode Selection

**File:** `llm-frontend/src/components/ModeSelection.tsx`

`ModeSelection` calls `getGuidelineSessions(topic.guideline_id)` on mount. Practice availability is **not** fetched here — it arrives as the `practiceAvailable` prop from `ModeSelectPage` (which calls `getPracticeAvailability()`). The component then:
- Renders "Continue Lesson" with `{coverage}% covered` + "Start Fresh" buttons when an incomplete teach_me session with `coverage > 0` exists; else a single "Teach Me" tile
- Renders "Let's Practice" as enabled/disabled based on `practiceAvailable`
- Renders "Clarify Doubts"
- Suppresses "Let's Practice" and "Clarify Doubts" when `topic.topic_key === 'get-ready'` (refresher) — only the "Get Ready" Teach Me tile is shown

### Practice Again Flow

The "Practice Again" button on the report card is a misnomer — it starts a fresh **Teach Me** session, not a practice attempt. Practice attempts are launched from the mode-selection screen via the "Let's Practice" tile.

1. User taps "Practice Again" on a topic row in the subject detail view
2. Frontend calls `createSession()` with the topic's `guideline_id` (no explicit mode → defaults to `teach_me`)
3. Navigates to `/session/{session_id}` with `location.state = {firstTurn, mode: 'teach_me', subject}`
4. Button is hidden when `topic.guideline_id` is null (orphan rows from session_only fallback hierarchy)

### Routing

| Path | Component | Description |
|------|-----------|-------------|
| `/report-card` | `ReportCardPage` | Report card view |

The practice history UI (`PracticeLandingPage`) is documented in `docs/technical/practice-mode.md`, not here.

All routes are protected (require authentication).

### Frontend API

| Function | Endpoint | Return Type |
|----------|----------|-------------|
| `getReportCard()` | `GET /sessions/report-card` | `ReportCardResponse` |
| `getTopicProgress()` | `GET /sessions/topic-progress` | `Record<string, TopicProgress>` |
| `getResumableSession(guidelineId)` | `GET /sessions/resumable?guideline_id=` | `ResumableSession \| null` |
| `getGuidelineSessions(guidelineId, mode?, finishedOnly?)` | `GET /sessions/guideline/{id}` | `GuidelineSessionEntry[]` |

Types are defined in `llm-frontend/src/api.ts`.

### Navigation Entry Points

The report card is accessible from:
- User menu in `AppShell.tsx` ("My Report Card" button, navigates to `/report-card`)
- Session history page (`SessionHistoryPage.tsx`, "View Report Card" link)

---

## Key Files

| File | Purpose |
|------|---------|
| `tutor/services/report_card_service.py` | Aggregation logic: coverage computation, practice score merge, hierarchy grouping |
| `tutor/api/sessions.py` | `/report-card`, `/topic-progress`, `/resumable`, `/guideline/{id}` endpoints |
| `shared/models/schemas.py` | Response schemas (`ReportCardResponse`, `ReportCardSubject`, `ReportCardChapter`, `ReportCardTopic`, `TopicProgressResponse`, `TopicProgressEntry`, `ResumableSessionResponse`, `GuidelineSessionsResponse`, `GuidelineSessionEntry`) |
| `shared/repositories/session_repository.py` | `list_by_guideline()` — computes per-session completion and coverage from `state_json`, including `teach_me_mode` |
| `shared/models/entities.py` | `PracticeAttempt` model (queried directly by `ReportCardService._load_user_practice_attempts`) |
| `llm-frontend/src/pages/ReportCardPage.tsx` | Report card UI (overview + subject detail) |
| `llm-frontend/src/components/ModeSelection.tsx` | Mode selection with resume detection and practice-availability tile |
| `llm-frontend/src/pages/ModeSelectPage.tsx` | Hosts `ModeSelection`, fetches practice availability, handles autostart query |
| `llm-frontend/src/pages/ChapterSelect.tsx` | Consumes `getTopicProgress()` to show progress badges per chapter |
| `llm-frontend/src/pages/TopicSelect.tsx` | Consumes `getTopicProgress()` to show progress badges per topic |
| `llm-frontend/src/api.ts` | Frontend API functions and TypeScript types |
| `tests/unit/test_report_card_service.py` | Unit tests for coverage, practice score merge, practice-only rows, hierarchy resolution, and resilience |
