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
| **Teach Me** | "Explain this topic to me" | Tutor leads | Coverage % + Understanding evaluation |
| **Clarify Doubts** | "I have specific questions" | Student leads | Coverage % + Understanding evaluation |
| **Exam** | "Test my knowledge" | Tutor leads | Numeric score (e.g., 7/10) |

**Teach Me** and **Clarify Doubts** are both learning activities — one tutor-driven, one student-driven. They share the same two evaluation metrics: how much of the subtopic was covered, and how well the student seems to understand what was covered.

**Exam** is a pure assessment. It produces a concrete number — no interpretation, just a score.

All three modes feed into a renamed **Report Card** (currently Scorecard).

---

## 3. Evaluation Model

This is the core change in how we measure student progress. The current single "mastery score" is replaced by two distinct evaluation approaches depending on whether the student is learning or being tested.

### 3.1 Learning Evaluation (Teach Me + Clarify Doubts)

Both Teach Me and Clarify Doubts are learning activities. The difference is only who drives the conversation — the tutor or the student. Both produce the same two metrics:

**1. Coverage (percentage)**

How much of the subtopic has the student gone through? This is measured against the subtopic's study plan / learning objectives.

- If a subtopic has 10 concepts and the student has covered 3 through Teach Me sessions, coverage is 30%.
- If the student then asks questions about 2 more concepts in Clarify Doubts, coverage moves to 50%.
- Coverage accumulates across sessions and across both modes. It never goes down.

Coverage answers: *"How far along are you in this subtopic?"*

**2. Understanding Evaluation (qualitative)**

Based on the conversations that happened, what does the tutor think about the student's understanding? This is the teacher's impression — not a test score, but an informed read on how well the student is grasping the material.

Two parts:
- **At-a-glance signal:** Strong / Developing / Needs Work
- **Short feedback:** 2-3 lines of qualitative feedback (e.g., *"You have a solid grasp of basic fraction comparison. You struggled a bit when the denominators were different — revisiting LCM might help."*)

This is similar to how a teacher who's been teaching a student can tell whether the student is following along, even without giving them a formal test. It's based on how the student answers questions, what kinds of questions they ask, where they get confused, and how they respond to explanations.

Understanding evaluation is updated at the end of each learning session (Teach Me or Clarify Doubts) and reflects the tutor's latest impression.

### 3.2 Exam Evaluation

Exams produce a simple, concrete number: **score out of total questions** (e.g., 7/10).

No qualitative interpretation, no coverage tracking. Just: how many did you get right?

Multiple exams can be taken for the same subtopic. Each one is recorded. The Report Card shows the latest score and a graph of all past scores over time.

### 3.3 How These Relate

Coverage and understanding evaluation tell you: *"How much have you studied, and how's it going?"*

Exam score tells you: *"When tested, how much do you actually know?"*

A student might have 80% coverage with "Strong" understanding but score 60% on an exam — that gap is valuable information. Or they might score 90% on an exam with only 50% coverage — they already knew some of the material.

These are complementary, not competing metrics. The Report Card shows all of them.

---

## 4. User Flow

### 4.1 Mode Selection

After selecting Subject > Topic > Subtopic, the student sees a mode selection screen:

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

**If the student has an in-progress Teach Me session** for this subtopic, the screen should prominently show a "Resume" option (e.g., "Resume — 30% covered") alongside the ability to start fresh or choose other modes.

Each card shows a short description so students understand what to expect. The UI follows the existing design language — big tap targets, minimal text, mobile-first.

---

### 4.2 Teach Me

**What it is:** A tutor-led lesson where the tutor follows the study plan, explains concepts, asks questions, and guides the student through the material. This is the existing teaching flow.

**What's new: Pause and Resume.**

Students can pause a Teach Me session and come back later to continue from where they left off. This is important because:
- A student might only have 15 minutes right now
- Coverage is cumulative — pausing at step 3/10 means 30% coverage, and resuming picks up at step 4
- When resuming, the tutor does a brief recap of where they left off before continuing

**Restart option:** A student can also choose to restart a subtopic from scratch. This resets coverage to 0% and begins a new Teach Me session from step 1.

**Progress indicator:** Step X/Y + Coverage percentage.

**Session summary (shown when pausing or completing):**
- Coverage so far (e.g., "You've covered 60% of Comparing Fractions")
- Understanding evaluation: at-a-glance signal + short qualitative feedback
- If paused: "You can pick up where you left off anytime"

---

### 4.3 Clarify Doubts

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

**Past discussion history:** When a student opens Clarify Doubts for a subtopic they've discussed before, they can see a summary of what they asked in previous sessions (past questions and topics covered). This is purely for the student's reference — the tutor does NOT carry context from past Clarify Doubts sessions. Each session is fresh.

**Session end:** Student explicitly says they're done, or taps an "End Session" button. No study plan completion trigger — the student controls when they're finished.

**Progress indicator:** No step counter. Show a list of concepts discussed as chips/tags that accumulate during the session.

**Session summary (shown at end):**
- Concepts discussed in this session
- Updated coverage (reflecting anything new that was covered)
- Understanding evaluation: at-a-glance signal + short qualitative feedback
- Suggestions for what to study next or ask about next time

---

### 4.4 Exam Mode

**What it is:** A no-teaching assessment. The tutor asks questions, the student answers, and at the end they get a score.

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

**Multiple exams:** Students can take as many exams as they want for the same subtopic. Each exam is recorded separately. This creates a natural study loop: take exam → see weak areas → study in Teach Me / Clarify Doubts → retake exam → see improvement.

**Session end:** All questions answered, or student taps "End Early" (partial scores are still recorded).

**Progress indicator:** "Question X of Y" + running score (e.g., "3/5 correct").

**Session summary (shown at end):**
- Score prominently displayed: "7/10 — 70%"
- Per-question breakdown: question text, student's answer, correct answer, and a correct/partial/incorrect indicator
- Weak areas highlighted: concepts where questions were answered incorrectly
- "Practice these topics" suggestions linking back to Teach Me mode

---

## 5. Report Card (Renamed from Scorecard)

### 5.1 Renaming

"Scorecard" → "Report Card" throughout the app (navigation, headers, all UI labels).

### 5.2 What the Report Card Shows Per Subtopic

The Report Card is the single place where a student sees all their progress. For each subtopic:

**Learning progress (from Teach Me + Clarify Doubts):**
- **Coverage:** percentage of subtopic covered (e.g., "60% covered")
- **Understanding:** at-a-glance signal (Strong / Developing / Needs Work) + short feedback text
- These update after every Teach Me or Clarify Doubts session

**Exam results (from Exam mode):**
- **Latest exam score** prominently displayed (e.g., "7/10"), clearly labeled as the latest
- **Score history graph** showing all past exam scores over time for this subtopic — so the student can see their trend (e.g., 50% → 65% → 80%)
- Number of exams taken

If a student hasn't taken any exams yet for a subtopic, the exam section shows a prompt to take one (e.g., "Take an exam to test your knowledge").

### 5.3 Per Subject Overview

Subject-level and topic-level views aggregate from subtopic data. The exact aggregation approach (how coverage + understanding + exam scores roll up into a subject-level view) can be refined, but the principle is: one place, all progress, no fragmentation.

### 5.4 Action Buttons

From the subtopic detail in the Report Card:

- **"Continue Learning"** → Resumes Teach Me (or starts new if none in progress)
- **"Ask Questions"** → Starts a Clarify Doubts session
- **"Take Exam"** → Starts a new Exam session

---

## 6. Session History

The session history list shows:
- Mode label per session (Teach Me / Clarify Doubts / Exam)
- Topic and subtopic name
- Date
- For Teach Me: coverage achieved in that session
- For Clarify Doubts: concepts discussed
- For Exam: score

For Clarify Doubts specifically, past sessions serve as a reference for the student to review what they've discussed before.

---

## 7. What Does NOT Change

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

## 8. Key Design Decisions & Rationale

| Decision | Rationale |
|----------|-----------|
| **Coverage + Understanding instead of mastery score** | A single "mastery" number conflates how much you've studied with how well you know it. Separating coverage (how far along) from understanding (how well it's going) gives students a clearer picture. Coverage is objective and motivating; understanding evaluation is the teacher's informed read. |
| **Teach Me and Clarify Doubts share the same metrics** | Both are learning activities — the only difference is who drives. A student who covers 3 concepts through teaching and 2 through questions has covered 5 concepts, period. Keeping separate metrics per mode would fragment the progress picture. |
| **Understanding evaluation is qualitative, not a number** | A number (like "mastery 0.7") feels like a test score, which is misleading for a learning session. A teacher's impression ("Strong — you grasped comparison well but struggled with unlike denominators") is more honest and more actionable. The at-a-glance signal (Strong / Developing / Needs Work) gives a quick read without false precision. |
| **Exam score is just a number** | Exams are the one place where a concrete score is appropriate. No interpretation, no qualitative spin. You got 7/10 — that's the data point. |
| **Pause and resume for Teach Me** | Without pause/resume, students who run out of time lose their progress and have to restart. With coverage as a metric, pause/resume is natural — you're just picking up where you left off. This respects the student's time. |
| **Fresh context for each Clarify Doubts session** | Carrying conversation context across sessions would make the tutor's responses depend on potentially stale context. A fresh session with the same curriculum guidelines is simpler and avoids confusion. Past history is shown to the student for their own reference. |
| **Multiple exams pile up with a trend graph** | A single exam is a snapshot. Multiple exams over time show progress. The graph makes improvement visible and motivating — take exam, study, retake, see the line go up. |
| **Exam feedback is brief, not remedial** | An exam that teaches defeats the purpose of assessment. Students who want to learn should use Teach Me or Clarify Doubts. Clear separation of concerns. |
| **Report Card, not separate exam results page** | One place for all progress data. Coverage, understanding, and exam scores all live in the Report Card. No fragmentation. |
| **Default to Teach Me** | Existing entry points that don't specify a mode continue to work as before. |
