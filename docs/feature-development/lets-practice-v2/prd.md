# PRD: Let's Practice (v2 — Batch Drill Redesign)

**Date:** 2026-04-16
**Status:** Draft
**Supersedes:** `docs/feature-development/teach-me-practice-split/prd.md` (v1 Practice design — tutor-in-the-loop), and the existing Exam mode entirely.

---

## 1. Problem Statement

Teach Me is in good shape (~70–80% of where we want it). The other learning modes are not:

1. **Exam mode** is functional but generates 7 questions per session on the fly, with no offline question bank and no reusable practice loop. It also carries high-stakes "test" framing that conflicts with the warm-tutor tone.
2. **The earlier "Let's Practice" design** (tutor-in-the-loop, scaffolded correction, adaptive difficulty) was specified but never implemented. The prompts exist dormant in `practice_prompts.py`. That design overlaps heavily with Teach Me and blurs the modes.
3. **Students have no low-stakes, repeatable way to check mastery** after Teach Me — no batch drill, no per-question review, no visible history of prior attempts.

---

## 2. Goal

Replace the existing Exam mode with a single, simple, repeatable **Let's Practice** mode that gives students a batch-drill experience: silent answering, one-tap submit, background evaluation, per-question review, and a persistent history of attempts per topic.

---

## 3. Design Philosophy

- **Practice ≠ teaching.** No hints, no scaffolding, no tutor-in-the-loop during the set. If a student is struggling on a concept, the learning loop sends them back to Teach Me via the Reteach button — not into a hybrid teacher-during-drill mode.
- **Low stakes by default.** Name ("Let's Practice"), no timer, repeats allowed, history kept forever. The mode is built for reps, not for grading.
- **Offline-first question bank.** Quality and consistency come from pre-generating and reviewing questions at ingestion time, not from runtime generation.
- **Evaluation as learning.** Every wrong answer earns a per-question explanation at review time. The post-submit experience is where students learn from their mistakes.
- **Deterministic where possible, LLM where necessary.** Structured formats grade deterministically. Only free-form text grading and per-pick "why you were wrong" feedback use the LLM.

---

## 4. User Stories

- As a student, I want to test myself on a topic after Teach Me without any hints or scaffolding, so I can honestly see what I know.
- As a student, I want to review each question after I submit and understand why I got things wrong.
- As a student, I want to see my past practice attempts on a topic so I can track improvement.
- As a student, I want to pause mid-practice and resume later without losing my answers.
- As a student, I want to retake practice easily on topics I did poorly on, with fresh questions each time.
- As a student, I want to jump back to Teach Me for the whole topic if I realize I don't remember it well.
- As an admin, I want to see the offline question bank for each topic so I can verify quality.

---

## 5. Functional Requirements

### 5.1 Positioning & Availability

- **FR-1:** Let's Practice MUST replace the Exam mode entirely. The existing Exam backend code (`exam_service.py`, exam-specific prompts, exam tables/state) MUST be deleted — clean slate, no historical exam data preserved.
- **FR-2:** The existing `practice_prompts.py` (scaffolded 80/20 teacher-in-the-loop prompts) MUST be deleted.
- **FR-3:** Let's Practice MUST be available on all non-refresher topics with no prerequisite. Students can enter practice without having completed Teach Me.
- **FR-4:** Let's Practice MUST be hidden on refresher topics (consistent with refreshers being card-only warm-up content).
- **FR-5:** If a topic has no question bank yet, the practice tile MUST be greyed out with a "not available yet" message. No on-demand generation.

### 5.2 Offline Question Bank

- **FR-6:** Question bank generation MUST run as a new last stage in the book ingestion pipeline, after topic decomposition.
- **FR-7:** Each topic's bank MUST contain 30–40 questions total.
- **FR-8:** The bank MUST use all 11 existing interactive formats (pick_one, true_false, fill_blank, match_pairs, sort_buckets, sequence, spot_the_error, odd_one_out, predict_then_reveal, swipe_classify, tap_to_eliminate) plus free-form text.
- **FR-9:** Each bank MUST contain 1–3 free-form (FF) text questions. The LLM decides the exact count per topic based on the nature of the topic (explanation-heavy topics get more FFs; purely procedural topics get fewer).
- **FR-10:** Each question MUST store: `concept_tag`, `difficulty` (easy/medium/hard), `format`, `correct_answer`, `explanation_why` (short "why" shown on eval cards).
- **FR-11:** Free-form questions MUST additionally store: `expected_answer` (model answer) and `grading_rubric` (key points for partial credit).
- **FR-12:** Generation MUST include a refine/review step (pattern borrowed from explanation card generation). The review step focuses on **correctness**: the marked-correct answer is actually correct; distractors are actually wrong. The review step MUST also top up the bank if the count drops below 30 after filtering out invalid questions.
- **FR-13:** Questions MUST be English-only, following easy-english principles (per `docs/principles/easy-english.md`). No multi-language generation.
- **FR-14:** Questions MUST be static — no runtime personalization (no name/interest substitution).

### 5.3 Runtime Set Selection

- **FR-15:** Each practice set MUST contain exactly 10 questions.
- **FR-16:** Difficulty mix MUST be **3 easy / 5 medium / 2 hard**. The topic's free-form questions count toward this mix (they are absorbed, not additive — set size stays 10).
- **FR-17:** ALL of the topic's free-form questions MUST be included in every set. The remaining slots are filled with structured questions to hit the difficulty mix.
- **FR-18:** Structured-question selection MUST be pure random per attempt. Repeats across attempts are allowed (no tracking of seen-question-ids).
- **FR-19:** Format variety: No more than two consecutive questions of the same format within a set. Each set MUST use at least 4 different formats.
- **FR-20:** Once a set is generated at session start, the 10 selected questions MUST be locked for that attempt. Resuming a paused set MUST show the same questions in the same order.

### 5.4 Entry & Landing Screen

- **FR-21:** Tapping the "Let's Practice" tile on ModeSelection MUST route to a landing screen with three actions: **Start practice**, **See past evaluations**, and **Resume** (only shown when an in-progress set exists).
- **FR-22:** The ModeSelection tile itself MUST show only the label "Let's Practice" — no score badges, no in-progress badges, no new-results badges.

### 5.5 During the Set

- **FR-23:** The set MUST start immediately when the student taps Start practice — no intro card, no welcome message.
- **FR-24:** Questions MUST render one per card with a progress indicator ("5 of 10").
- **FR-25:** Students MUST be able to navigate backwards and change answers at any point before submit.
- **FR-26:** The set MUST show no correctness signals during answering (no green/red, no scoring, no hints).
- **FR-27:** There MUST be no timer. Session duration is untracked and unpressured.
- **FR-28:** No audio (TTS) on practice questions.
- **FR-29:** No Pixi.js visuals on practice questions (prevents answer-leaking for numeric or visual problems).
- **FR-30:** After the last question, a Review screen MUST display all 10 answers with their current selections, allowing edits before submit.
- **FR-31:** The Submit button on the Review screen MUST be one-tap (no confirmation dialog).
- **FR-32:** Students MUST be able to submit with any number of blank answers. Blanks are counted as wrong at grading time.
- **FR-33:** If the student closes/leaves mid-set, their progress (selected questions + answers so far) MUST be auto-saved and resumable from the landing screen.

### 5.6 Grading (Background)

- **FR-34:** After Submit, the student MUST be routed back to the topic list and be free to start any other activity (Teach Me, Clarify Doubts, or Practice on a different topic).
- **FR-35:** Grading MUST run in the background. An in-app banner appears at the top of the app when the grading completes ("Your Practice results are ready →").
- **FR-36:** Multiple practice attempts MUST be allowed to grade in parallel across different topics.
- **FR-37:** Structured-format grading MUST be deterministic (no LLM call). Compares student's selection against the stored `correct_answer`.
- **FR-38:** Free-form grading MUST use the admin-configured default LLM provider to produce a fractional score (0.0–1.0) plus a short rationale, graded against the stored `expected_answer` and `grading_rubric`.
- **FR-39:** Per-question "what was wrong about your specific pick" feedback MUST be generated by the LLM at submit time for every incorrect or blank answer, using the question, the student's pick, and the correct answer as context.
- **FR-40:** If LLM grading fails (API error, timeout), the system MUST retry 3 times with exponential backoff. After 3 failures, the attempt MUST be flagged as "grading failed" and the banner MUST expose a manual "Retry grading" button.

### 5.7 Results

- **FR-41:** Tapping the results banner MUST open a score-first summary screen containing:
  - Fractional score with half-point granularity (e.g., "7.5 / 10").
  - A **Reteach** button that routes the student to Teach Me for the whole topic.
  - A **Practice again** button that immediately starts a new practice set (one-tap retake).
  - An option to drill into the card-by-card review.
- **FR-42:** The card-by-card review MUST show one evaluation card per question. Each card MUST display:
  - The original question.
  - The student's answer (or "not answered" for blanks).
  - The correct answer.
  - A short "why" explaining the correct answer.
  - For wrong/blank answers: a targeted "what was wrong about your pick" explanation (LLM-generated at submit time per FR-39).
- **FR-43:** Pixi.js visuals MAY be included on evaluation cards when they help explain the "why" (unlike question cards, where visuals are disallowed).

### 5.8 History

- **FR-44:** Every submitted practice attempt MUST be stored forever (no retention limit).
- **FR-45:** "See past evaluations" from the landing screen MUST show a list of all attempts for the current topic (date + score), newest first.
- **FR-46:** Tapping a past attempt MUST open the full card-by-card review for that attempt (same UI as FR-42).
- **FR-47:** The student MUST store only the final submitted answer per question (no edit history, no per-question timestamps).

### 5.9 Scorecard Integration

- **FR-48:** The scorecard's existing "Exam scores" section MUST be renamed to "Practice scores".
- **FR-49:** The scorecard MUST display, per topic where practice has been attempted: latest score + attempt count (e.g., "Topic X — 7/10 (3 attempts)").

### 5.10 Admin Tools

- **FR-50:** The admin dashboard MUST provide a read-only question bank viewer per topic — list of all 30–40 questions with their metadata (format, difficulty, correct answer, explanation). No regenerate, no per-question delete, no analytics in v1.

### 5.11 Observability

- **FR-51:** Backend logging only: attempt created, submitted, grading completed, grading failed. No admin metrics dashboard, no autoresearch integration in v1.

---

## 6. UX Requirements

- ModeSelection tile reads simply **Let's Practice** — no badges, no metadata.
- Landing screen uses warm, minimal copy: "Start practice" / "See past evaluations" / "Resume" (conditional).
- During the set: mobile-first, minimum 44px tap targets, single-column layout. No audio, no visuals on questions.
- Submit is one-tap; grading confirmation is an in-app banner, not a modal.
- Results screen leads with the fractional score and two primary actions (Reteach, Practice again). Card-by-card review is secondary.
- All student-facing text follows `docs/principles/easy-english.md`.

---

## 7. Technical Considerations

### Backend
- **New table:** `practice_questions` — keyed by `topic_guideline_id`, stores all 30–40 questions per topic with full metadata (including FF `expected_answer` + `grading_rubric`).
- **New table / state:** `practice_attempts` — one row per submitted attempt. Stores the 10 question IDs, student answers (final only), grading results (per-question score + rationale + per-pick explanation), aggregate score, timestamps, grading status.
- **New service:** `practice_service.py` — handles set creation (question selection, locking), attempt state, submit, background grading orchestration.
- **New ingestion stage:** question bank generation + refine/review, triggered after topic decomposition.
- **Mode routing:** `orchestrator.py` gets a practice path — but since there is no tutor-in-the-loop, it's more of a card sequencer + submit handler than a typical agent path.
- **Cleanup:** delete `exam_service.py`, exam-specific prompts, exam session type code, `practice_prompts.py`, and any dead references in orchestrator/session_service.

### Frontend
- `ModeSelection.tsx` — rename Exam tile → Let's Practice. Remove exam-specific resume logic. No badges.
- New landing screen: Start / Past evaluations / Resume.
- New Practice session renderer: progress bar, question card, back-nav, review screen, submit button.
- Reuse existing 11 `InteractiveQuestion` components for structured formats; add a free-form text input component.
- New Results screen: score-first, drill into card-by-card review.
- New Past Evaluations list + drill-in.
- New Banner component for background-grading notifications.

### Data Migration
- No migration needed — exam history is discarded per FR-1.

---

## 8. Impact on Existing Features

| Feature | Impact | Details |
|---|---|---|
| Exam mode | **Deleted** | Backend + frontend code removed. Historical exam data discarded. |
| `practice_prompts.py` (old design) | **Deleted** | Never wired up; superseded by this PRD. |
| Teach Me | None | No changes. |
| Clarify Doubts | None | No changes. |
| Scorecard | Minor | Section renamed; per-topic display shows latest + attempt count. |
| ModeSelection | Minor | Tile rename + landing screen route. |
| Book ingestion pipeline | Moderate | New last stage for question bank generation + refine/review. |
| Docs (principles, functional, technical) | Moderate | Exam references updated/removed. New docs added (see §11). |

---

## 9. Edge Cases

| Scenario | Expected Behavior |
|---|---|
| Student opens Practice for a topic with no question bank | Tile greyed out with "not available yet" message. |
| Student leaves mid-set | Progress auto-saved; Resume button appears on landing screen; same questions on resume. |
| Student submits with all blanks | Submit allowed; all questions graded as wrong; review still shows correct answers and "why". |
| LLM grading fails after 3 retries | Attempt marked "grading failed"; banner exposes "Retry grading" button. |
| Bank review/refine removes too many questions (<30) | Review step tops up by regenerating more questions until threshold met. |
| Student submits Practice on Topic A, starts Practice on Topic B before A finishes grading | Allowed. Each attempt banners independently when done. |
| Student retakes practice immediately after results | One-tap "Practice again" starts a fresh random set on the same topic. May include repeated questions. |
| Student navigates back mid-set and changes an answer | New selection overwrites old. Only final submitted answer is stored. |
| Refresher topic | Practice tile hidden entirely. |

---

## 10. Out of Scope (v1)

- Adaptive difficulty based on past performance.
- Avoiding repeats across attempts.
- Timed test variant.
- Multi-topic (chapter-level) practice sets.
- Personalization of questions at runtime.
- Audio (TTS) on questions or evaluation cards.
- Pixi visuals on question cards.
- Multi-language question generation.
- Admin regenerate / per-question delete / analytics dashboard.
- Autoresearch integration for grading prompts.
- Browser push notifications (in-app banner only).
- Feature flag / phased rollout — shipping to all users at once.

---

## 11. Documentation Deliverables

- **New:** `docs/principles/practice-mode.md` — philosophy (no hints, offline bank, static questions, warm framing, evaluation-as-learning).
- **New:** `docs/functional/practice-mode.md` — student journey end-to-end.
- **New:** `docs/technical/practice-mode.md` — schema, ingestion stage, grading service, resume state, evaluation card generation.
- **Updated:** `docs/principles/scorecard.md` — rename Exam → Practice, describe latest+attempt-count display.
- **Updated:** `docs/technical/architecture-overview.md`, `docs/technical/database.md`, and any doc referencing Exam mode.
- **Deleted:** any stale docs describing the Exam mode or the previous Practice design that no longer apply.

---

## 12. Success Criteria

- Every non-refresher topic has a 30–40 question bank generated after ingestion, all passing correctness review.
- Students can complete a practice set, submit, leave the app, and return to find graded results via the banner.
- Per-question review cards consistently show correct answer + "why" + targeted feedback on the student's specific pick for every wrong or blank answer.
- LLM grading failures surface cleanly with a retry path; no attempts stuck in limbo.
- No remaining code, prompts, DB tables, docs, or UI elements reference the old Exam mode or the old in-the-loop Practice design.
