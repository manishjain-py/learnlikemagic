# PRD: Learning Session Modes

**Status:** Draft
**Date:** 2026-02-21

---

## 1. Problem Statement

Today, LearnLikeMagic offers a single learning experience: guided tutoring where the tutor follows a study plan (explain, check, practice). This works well for structured learning but does not cover two important student needs:

1. **Targeted doubt clearing** — A student knows the topic but has specific questions or confusion on certain concepts. They don't want to sit through a full lesson; they want quick, precise answers.
2. **Self-assessment** — A student wants to test their own knowledge before an exam or after studying. They want a score that tells them where they stand.

These are fundamentally different interactions, and forcing them all through a guided lesson creates friction and poor learning outcomes.

---

## 2. Solution Overview

Introduce three distinct **session modes** that students choose after selecting a subtopic:

| Mode | Student Need | Who Leads | Produces |
|------|-------------|-----------|----------|
| **Teach Me** | "Explain this topic to me" | Tutor leads | Mastery score per concept |
| **Clarify Doubts** | "I have specific questions" | Student leads | Understanding assessment per concept |
| **Exam** | "Test my knowledge" | Tutor leads | Numeric exam score + per-question results |

All three modes produce data that feeds into a renamed **Report Card** (currently Scorecard).

---

## 3. User Flow

### 3.1 Mode Selection (New Screen)

After selecting Subject > Topic > Subtopic, instead of immediately starting a session, the student sees a mode selection screen:

```
┌─────────────────────────────────┐
│     What would you like to do?  │
│                                 │
│  ┌───────────┐                  │
│  │  Teach Me  │  "Learn this    │
│  │   (book)   │   topic from    │
│  │            │   scratch"      │
│  └───────────┘                  │
│                                 │
│  ┌───────────┐                  │
│  │  Clarify   │  "I have       │
│  │  Doubts    │   questions"    │
│  │   (chat)   │                 │
│  └───────────┘                  │
│                                 │
│  ┌───────────┐                  │
│  │   Exam     │  "Test my      │
│  │  (check)   │   knowledge"   │
│  └───────────┘                  │
│                                 │
└─────────────────────────────────┘
```

Each card shows a short description so students understand what to expect. The UI follows the existing design language — big tap targets, minimal text, mobile-first.

---

### 3.2 Teach Me (Existing Behavior)

No changes to the core teaching flow. The tutor follows the study plan, explains concepts, asks questions, tracks mastery. All existing behavior is preserved.

**Progress indicator:** Step X/Y + Mastery bar (unchanged).

---

### 3.3 Clarify Doubts (New)

**What it is:** A student-led Q&A session. The student comes with questions; the tutor answers them clearly using the curriculum as context.

**Entry:** Tutor sends a warm welcome inviting questions: *"Hi! I'm here to help with [subtopic]. What's on your mind?"*

**Conversation dynamics:**
- Student asks a question about the subtopic
- Tutor answers clearly using curriculum-appropriate language and the teaching guidelines as context
- After answering, the tutor asks a brief follow-up to check understanding (e.g., "Does that make sense?" or a quick check question)
- Based on the student's response, the tutor assesses understanding of that concept
- Student asks more questions or says they're done

**Tutor behavior:**
- Uses teaching guidelines for accurate, curriculum-aligned answers
- Keeps answers concise — this mode values directness over scaffolded teaching
- If a question reveals a deep misunderstanding, the tutor addresses it directly rather than doing Socratic exploration (unlike Teach Me mode)
- Tracks which concepts/areas from the guidelines are being discussed
- Gently offers related areas if the student seems stuck on what to ask
- If a question falls outside the subtopic scope, the tutor answers briefly and redirects

**Session end:** Student explicitly says they're done, or taps an "End Session" button. No study plan completion trigger — the student controls when they're finished.

**Progress indicator:** No step counter, no mastery bar. Instead, show a list of concepts discussed as chips/tags that accumulate during the session.

**Session summary (shown at end):**
- Concepts discussed with understanding levels (strong / adequate / needs work)
- Misconceptions that were addressed
- Suggestions for what to study next or ask about next time

---

### 3.4 Exam Mode (New)

**What it is:** A timed-feeling, no-teaching assessment. The tutor asks questions, the student answers, and at the end they get a score.

**Entry:** Tutor welcomes and sets expectations: *"Let's test your knowledge of [subtopic]! I'll ask you [N] questions. Ready?"*

**Exam structure:**
- 5-10 questions per exam (default 7)
- Questions cover key concepts from the subtopic's learning objectives
- Mix of difficulty levels: ~30% easy, ~50% medium, ~20% hard
- Question types: conceptual, procedural, application

**Conversation dynamics:**
- Tutor asks one question at a time
- Student answers
- Tutor evaluates: correct, partially correct, or incorrect
- Brief feedback after each answer (1-2 sentences max — this is an exam, not a teaching session)
  - Correct: "Right!" + move to next question
  - Partially correct: Acknowledge what's right, note what's missing, move on
  - Incorrect: State the correct answer briefly, move on
- Tutor does NOT teach or remediate during the exam — it just assesses
- After all questions, tutor provides a score summary

**Key distinction from Teach Me:** In Teach Me, wrong answers trigger remediation (probe → hint → explain). In Exam mode, wrong answers get brief feedback and the exam moves on. The goal is assessment, not teaching.

**Session end:** All questions answered, or student taps "End Early" (partial scores are still recorded).

**Progress indicator:** "Question X of Y" + running score (e.g., "3/5 correct").

**Session summary (shown at end):**
- Score prominently displayed: "7/10 — 70%"
- Per-question breakdown: question text, student's answer, correct answer, and a correct/partial/incorrect indicator
- Weak areas highlighted: concepts where questions were answered incorrectly
- "Practice these topics" suggestions linking back to Teach Me mode

---

## 4. Report Card (Renamed from Scorecard)

### 4.1 Renaming

"Scorecard" → "Report Card" throughout the app (navigation, headers, all UI labels).

### 4.2 How Modes Feed Into the Report Card

Each mode produces a 0-1 score for the subtopic:

| Mode | What Gets Scored |
|------|-----------------|
| **Teach Me** | Overall mastery (existing behavior) |
| **Clarify Doubts** | Average understanding of discussed concepts |
| **Exam** | Exam percentage (correct answers / total questions) |

The **latest session** per subtopic still determines the subtopic score, regardless of which mode was used. A student who scores 90% on an exam after a 60% Teach Me session should see 90%.

### 4.3 What the Report Card Shows

**Per subtopic (updated):**
- Mastery score (unchanged)
- Mastery label and badge (unchanged)
- Concepts and their scores (unchanged)
- Misconceptions (unchanged)
- Session count (unchanged)
- **NEW:** Latest session mode label (Teach Me / Clarify Doubts / Exam)
- **NEW:** If any exam sessions exist:
  - Latest exam score
  - Number of exams taken

**Per subject overview:** Unchanged. Subject score, topic scores, trend — all computed from subtopic scores the same way as today.

### 4.4 Action Buttons

Currently there's a "Practice Again" button. Updated:

- **"Practice Again"** → Starts a **Teach Me** session (unchanged behavior)
- **"Take Exam"** → Starts an **Exam** session (new button)

Both buttons appear on the subtopic detail view in the Report Card.

---

## 5. Session History

The session history list now shows a mode label per session (Teach Me / Clarify Doubts / Exam) alongside the existing topic name, mastery, and date.

---

## 6. What Does NOT Change

| Area | Impact |
|------|--------|
| **Book ingestion pipeline** | No changes. Guidelines and study plans are generated the same way. |
| **Teaching guidelines** | No changes to the data model or admin workflow. |
| **Study plan generation** | No changes. Study plans are used only in Teach Me mode. |
| **Admin evaluation system** | No changes for V1. Can be extended later to test Clarify/Exam modes. |
| **Authentication & onboarding** | No changes. |
| **User profile** | No changes. |
| **Safety agent** | Works the same across all modes. |

---

## 7. Key Design Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| **Mode is per-session, not per-subtopic** | A student might want Teach Me on Monday and Exam on Friday for the same subtopic. Modes are about *what you want to do right now*, not a property of the content. |
| **Latest session score wins (regardless of mode)** | Keeps scoring simple. Modes are different ways to arrive at a score, not different score types. |
| **Clarify Doubts still tracks understanding** | Even in a Q&A format, the tutor can assess understanding. Without it, Clarify Doubts sessions would create "holes" in the Report Card. |
| **Exam feedback is brief, not remedial** | An exam that teaches defeats the purpose of assessment. Students who want to learn should use Teach Me or Clarify Doubts. Clear separation of concerns. |
| **Report Card, not separate exam results page** | One place for all progress data. Avoids fragmenting the student experience. Exam data lives within the Report Card, not a separate destination. |
| **Exam questions generated dynamically** | Questions come from the existing teaching guidelines. No separate question bank or generation pipeline needed. |
| **Default to Teach Me** | Existing "Practice Again" buttons and any entry points that don't specify a mode continue to work as before. |
