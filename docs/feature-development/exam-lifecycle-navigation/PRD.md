# PRD: Exam Lifecycle, Navigation Overhaul & Past Exam Review

## Context & Problem

### Current Pain Points
1. **"End Exam Early" is destructive** — It marks the exam as finished and scores only answered questions. There's no way to come back. Similarly, "Pause Session" for teach_me shows a completion screen with scorecard, which is misleading — it's not complete.
2. **No exam resumability** — The resumable endpoint only finds paused `teach_me` sessions. If a student leaves mid-exam (closes browser, navigates away), the exam is lost. They'd have to start a new one.
3. **No exam history** — Students can't see past exam attempts or review their detailed results after leaving the session.
4. **Flat session URL** — `/session/:id` doesn't encode the mode or the learn context. Back navigation relies on `location.state` which is lost on refresh. No way to deep-link to a specific mode selection screen with context.
5. **Multiple exams allowed but unmanaged** — No constraint prevents creating duplicate active exams. No UI to resume an in-progress exam.

### Desired Outcome
- Students can leave any session (exam or teach_me) and come back to it seamlessly via a "Back" button
- Each screen in the learn flow has its own URL for proper browser navigation
- Mode selection shows "Resume Exam" if there's an incomplete exam, just like teach_me
- Past completed exams are viewable from the mode selection screen with full question review

---

## Requirements

### R1: Replace "End Exam Early" and "Pause Session" with "Back"
- Remove the "End Exam Early" button from exam mode
- Remove the "Pause Session" button from teach_me mode
- Add a single "Back" button (←) in all session modes that navigates to the mode selection screen
- Back does NOT end/finish/pause the session — it simply navigates away, leaving session state as-is in the DB
- The session completion screen (summary card) should ONLY appear when the session is genuinely complete (all steps done for teach_me, all questions answered+submitted for exam, student says done for clarify)

### R2: Exam Resumability
- On the mode selection screen, if there's an incomplete exam (`exam_finished=False` and has exam questions), show the Exam button as "Resume Exam" with progress info (e.g., "3/7 answered")
- Clicking "Resume Exam" navigates to the existing exam session, hydrating state from the DB
- Similarly for teach_me: if there's an incomplete teach_me session (not paused — just not finished), show "Resume" instead of creating a new session
- Backend: Update the resumable endpoint (or add a new one) to find incomplete sessions of any mode for a given guideline_id

### R3: URL-Based Navigation for Learn Flow
Current URLs are already good for the selection flow:
- `/learn` → subjects
- `/learn/:subject` → topics
- `/learn/:subject/:topic` → subtopics
- `/learn/:subject/:topic/:subtopic` → mode selection

Session URLs need the learn context for back navigation:
- `/learn/:subject/:topic/:subtopic/exam/:sessionId` → exam session
- `/learn/:subject/:topic/:subtopic/teach/:sessionId` → teach me session
- `/learn/:subject/:topic/:subtopic/clarify/:sessionId` → clarify doubts session

This way the Back button can navigate to `/learn/:subject/:topic/:subtopic` using URL params alone, no `location.state` needed.

### R4: Past Exams on Mode Selection Screen
- Add a "Past Exams" section/button on the mode selection screen
- Shows list of completed exam sessions for this subtopic (guideline_id) with: date, score (e.g., "4.6/7"), percentage
- Clicking a past exam navigates to a read-only exam review screen showing the detailed question cards (question text, student answer, expected answer, marks rationale, score per question) — reusing the exam completion UI we already built
- Backend: New endpoint `GET /sessions/guideline/{guideline_id}/exams` returning completed exam summaries

### R5: Multiple Exams Allowed
- Students can take unlimited exams per topic
- Only ONE incomplete exam can exist at a time per guideline (enforced at session creation)
- If an incomplete exam exists and student clicks "Exam", they resume it instead of creating a new one

---

## Technical Design

### Backend Changes

#### 1. New endpoint: Get sessions by guideline
**`GET /sessions/guideline/{guideline_id}`**
- Query params: `mode` (optional filter), `finished_only` (bool, default false)
- Returns list of session summaries for this user + guideline
- Used by frontend to: find resumable sessions (any mode), list past exams

Response:
```json
{
  "sessions": [
    {
      "session_id": "sess_abc",
      "mode": "exam",
      "created_at": "2026-02-27T...",
      "exam_finished": true,
      "exam_score": 4.6,
      "exam_total": 7,
      "coverage": null
    }
  ]
}
```

#### 2. New endpoint: Get exam review
**`GET /sessions/{session_id}/exam-review`**
- Returns full exam question details for a completed exam session
- Response: exam_feedback + exam_results array (question_text, student_answer, expected_answer, score, marks_rationale)
- Auth check: must be session owner

#### 3. New repository method
- `SessionRepository.list_by_guideline(user_id, guideline_id, mode=None, finished_only=False)`
- Add DB index on `(user_id, guideline_id, mode)` for performance

#### 4. Update session creation
- Before creating an exam session, check for existing incomplete exam (`exam_finished=False`) for same user + guideline
- If found, return the existing session instead of creating a new one (or return 409 with session_id)

#### 5. Remove pause dependency
- The "Back" button won't call any backend endpoint — it just navigates away
- Session state is already persisted after every turn, so nothing is lost
- Remove or deprecate the pause endpoint (keep for backward compat but stop using it from frontend)

### Frontend Changes

#### 6. New route structure
Update `App.tsx` routes:
```
/learn/:subject/:topic/:subtopic/exam/:sessionId → ChatSession (exam)
/learn/:subject/:topic/:subtopic/teach/:sessionId → ChatSession (teach_me)
/learn/:subject/:topic/:subtopic/clarify/:sessionId → ChatSession (clarify)
/learn/:subject/:topic/:subtopic/exam-review/:sessionId → ExamReviewPage (read-only)
```

ChatSession extracts `subject`, `topic`, `subtopic` from URL params for back navigation.

#### 7. Update ModeSelection component
- Fetch guideline sessions on mount (`GET /sessions/guideline/{guidelineId}`)
- If incomplete exam exists → show "Resume Exam" button with progress
- If incomplete teach_me exists → show "Resume Lesson" button with coverage
- Add "Past Exams" section showing completed exams with scores
- Each past exam links to `/learn/.../exam-review/:sessionId`

#### 8. Update ChatSession
- Replace "End Exam Early" / "Pause Session" with "← Back" button
- Back navigates to `/learn/:subject/:topic/:subtopic` (derived from URL params)
- No API call on back — just navigate
- Remove pause-related state and UI (pause summary, etc.)
- Session completion UI only shows when `isComplete` is genuinely true

#### 9. New ExamReviewPage
- Read-only page showing completed exam results
- Fetches data from `GET /sessions/{id}/exam-review`
- Reuses the exam result card UI from ChatSession's summary
- Has a Back button to mode selection

### Files to Modify

**Backend:**
1. `llm-backend/tutor/api/sessions.py` — new endpoints
2. `llm-backend/tutor/repositories/session_repository.py` — new query method
3. `llm-backend/shared/models/schemas.py` — new response models
4. `llm-backend/tutor/services/session_service.py` — exam creation guard, exam review method
5. `llm-backend/shared/models/entities.py` — add index on guideline_id

**Frontend:**
6. `llm-frontend/src/App.tsx` — new routes
7. `llm-frontend/src/pages/ChatSession.tsx` — back button, remove pause/end-exam
8. `llm-frontend/src/pages/ModeSelectPage.tsx` — resumable logic for all modes
9. `llm-frontend/src/components/ModeSelection.tsx` — resume buttons, past exams section
10. `llm-frontend/src/pages/ExamReviewPage.tsx` — new page (read-only exam results)
11. `llm-frontend/src/api.ts` — new API functions and types

---

## Verification
- Navigate subject → topic → subtopic → mode selection: each has correct URL
- Start an exam, answer 3/7 questions, click Back → goes to mode selection
- Mode selection now shows "Resume Exam (3/7 answered)" instead of fresh Exam button
- Click Resume Exam → continues from question 4
- Complete the exam → see detailed results with scores
- Click Back → mode selection shows "Past Exams" with this exam listed
- Click the past exam → see read-only review with all question cards
- Start a new exam → creates fresh session (old completed one stays in history)
- Start teach_me, answer a few questions, click Back → mode selection shows "Resume Lesson"
- Refresh any page → URL-based routing reconstructs everything correctly
