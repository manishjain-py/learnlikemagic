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
| **Teach Me** | "Explain this topic to me" | Tutor leads | Coverage % |
| **Clarify Doubts** | "I have specific questions" | Student leads | Coverage % |
| **Exam** | "Test my knowledge" | Tutor leads | Score (e.g., 7/10) + evaluation feedback |

**Teach Me** and **Clarify Doubts** are both learning activities — one tutor-driven, one student-driven. They track one metric: how much of the subtopic has been covered. Coverage is factual and trustworthy — you either went through the material or you didn't.

**Exam** is the assessment layer. It produces a concrete score and grounded evaluative feedback — because feedback tied to actual right/wrong answers is trustworthy in a way that subjective impressions during learning sessions are not.

All three modes feed into a renamed **Report Card** (currently Scorecard).

---

## 3. Evaluation Model

This is the core change in how we measure student progress. The current single "mastery score" is replaced by two things: factual coverage tracking during learning, and concrete scored assessment via exams.

**Design principle:** Every metric shown to students must be grounded in something factual. Coverage is factual — you either went through the material or you didn't. Exam scores are factual — you either got the answer right or you didn't. Subjective "understanding" impressions from an LLM during learning sessions are not — they risk feeling arbitrary and eroding trust, especially when they fluctuate between sessions for similar performance. So we don't show them.

### 3.1 Learning Evaluation (Teach Me + Clarify Doubts)

Both Teach Me and Clarify Doubts are learning activities. The difference is only who drives the conversation — the tutor or the student. Both track one metric:

**Coverage (percentage)**

How much of the subtopic has the student gone through? This is measured against the subtopic's study plan / learning objectives.

- If a subtopic has 10 concepts and the student has covered 3 through Teach Me sessions, coverage is 30%.
- If the student then asks questions about 2 more concepts in Clarify Doubts, coverage moves to 50%.
- Coverage accumulates across sessions and across both modes. It never goes down.

Coverage answers: *"How far along are you in this subtopic?"*

That's it for learning sessions. No qualitative understanding evaluation, no subjective impressions. The tutor teaches; coverage tracks how far along the student is. If the student (or parent) wants to know *how well* they know the material, that's what exams are for.

### 3.2 Exam Evaluation

Exams produce two things:

**1. Score:** A concrete number — **score out of total questions** (e.g., 7/10). How many did you get right?

**2. Evaluation feedback:** Because exam feedback is grounded in actual answers (right/wrong), it can offer trustworthy qualitative insight that learning sessions cannot. After an exam, the student sees:

- **Strengths:** Concepts/areas where they answered correctly (e.g., *"Strong on basic fraction comparison and equivalent fractions"*)
- **Weak areas:** Concepts where they got questions wrong, with brief explanations (e.g., *"Struggled with comparing fractions with unlike denominators — revisit LCM"*)
- **Pattern observations:** If the exam reveals a pattern, call it out (e.g., *"You got conceptual questions right but struggled with application problems"* or *"Accuracy was solid on easy questions but dropped on harder ones"*)
- **What to do next:** Actionable suggestions linking back to learning modes (e.g., *"Practice these topics in Teach Me"* or *"Try Clarify Doubts to work through your questions on LCM"*)

This feedback is trustworthy because it points at concrete evidence — specific questions the student got right or wrong — not an LLM's impression of how the conversation felt.

Multiple exams can be taken for the same subtopic. Each one is recorded. The Report Card shows the latest score and a graph of all past scores over time.

### 3.3 Last Studied & Revision Nudges

Coverage never goes down — it's a factual record of how much material the student has gone through. But coverage alone can create false confidence. A student who covered 80% three months ago may have forgotten much of it.

To address this, every subtopic tracks a **"Last studied"** timestamp — the date of the most recent session of any mode (Teach Me, Clarify Doubts, or Exam). Any engagement with the subtopic resets this timestamp.

**What the student sees:**
- "80% covered — last studied 3 weeks ago"
- If enough time has passed without engagement, a gentle revision nudge: *"It's been a while — consider revising"* or *"Time to revisit?"*
- The nudge can suggest a specific action: *"Take a quick exam to check how much you remember"* — tying the exam mode into a natural revision workflow

This keeps coverage motivating and honest while preventing students (or parents) from assuming that coverage = retained knowledge. The Report Card message becomes: *you've covered this much, here's when you last studied it, and here's how you did on the exam.*

### 3.4 How These All Relate

Coverage tells you: *"How much have you studied?"*

Last studied tells you: *"How fresh is it?"*

Exam score + feedback tells you: *"How well do you actually know it?"*

A student might have 80% coverage but score 60% on an exam — that gap is valuable information. Or they might score 90% on an exam with only 50% coverage — they already knew some of the material. And if the last session was months ago, even high coverage might need a refresh.

All three signals are factual and trustworthy. The Report Card shows all of them.

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
- Concepts covered in this session
- If paused: "You can pick up where you left off anytime"
- If completed: prompt to take an exam (e.g., *"Ready to test yourself? Take an exam to see how much you've learned"*)

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
- Suggestions for what to study next or ask about next time
- Prompt to take an exam if coverage is significant (e.g., *"You've covered a lot — take an exam to see where you stand"*)

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
- **Score** prominently displayed: "7/10 — 70%"
- **Per-question breakdown:** question text, student's answer, correct answer, and a correct/partial/incorrect indicator
- **Strengths:** concepts/areas where the student answered correctly (e.g., *"Strong on basic fraction comparison and equivalent fractions"*)
- **Weak areas:** concepts where questions were answered incorrectly, with brief explanations of what went wrong (e.g., *"Struggled with comparing fractions with unlike denominators — revisit LCM"*)
- **Pattern observations:** if the exam reveals a pattern, call it out (e.g., *"You got conceptual questions right but struggled with application problems"*)
- **What to do next:** actionable suggestions linking back to learning modes (e.g., *"Practice these topics in Teach Me"* or *"Use Clarify Doubts to work through your questions on LCM"*)

---

## 5. Report Card (Renamed from Scorecard)

### 5.1 Renaming

"Scorecard" → "Report Card" throughout the app (navigation, headers, all UI labels).

### 5.2 What the Report Card Shows Per Subtopic

The Report Card is the single place where a student sees all their progress. For each subtopic:

**Learning progress (from Teach Me + Clarify Doubts):**
- **Coverage:** percentage of subtopic covered (e.g., "60% covered")
- **Last studied:** when the student last engaged with this subtopic in any mode (e.g., "Last studied 3 days ago")
- **Revision nudge:** if significant time has passed since last engagement, show a gentle prompt (e.g., *"It's been a while — take a quick exam to check how much you remember"*)
- Coverage updates after every Teach Me or Clarify Doubts session

**Exam results (from Exam mode):**
- **Latest exam score** prominently displayed (e.g., "7/10"), clearly labeled as the latest
- **Strengths and weak areas** from the latest exam (e.g., *"Strong on comparisons, needs work on unlike denominators"*)
- **Score history graph** showing all past exam scores over time for this subtopic — so the student can see their trend (e.g., 50% → 65% → 80%)
- Number of exams taken

If a student hasn't taken any exams yet for a subtopic, the exam section shows a prompt to take one (e.g., *"Take an exam to test your knowledge"*).

### 5.3 Per Subject Overview

Subject-level and topic-level views aggregate from subtopic data. The exact aggregation approach (how coverage + exam scores roll up into a subject-level view) can be refined, but the principle is: one place, all progress, no fragmentation.

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
| **Coverage only during learning (no understanding evaluation)** | Subjective "understanding" impressions from an LLM risk feeling arbitrary — especially when they fluctuate between sessions for similar performance. This erodes trust with students and parents. Coverage is factual (you either covered the material or you didn't) and therefore trustworthy. Qualitative evaluation belongs in exams, where it's grounded in concrete right/wrong answers. |
| **Teach Me and Clarify Doubts share the same metric** | Both are learning activities — the only difference is who drives. A student who covers 3 concepts through teaching and 2 through questions has covered 5 concepts, period. Keeping separate metrics per mode would fragment the progress picture. |
| **Exam as the primary evaluation signal** | Exams produce a concrete score and grounded evaluative feedback (strengths, weak areas, patterns). Because feedback is tied to actual answers, it's trustworthy in a way that learning-session impressions are not. This makes the exam the natural place for "how well do you know this?" |
| **Rich exam feedback, not just a number** | A bare score (7/10) tells you the result but not what to do about it. Strengths, weak areas, and pattern observations give actionable insight — and because they're grounded in specific questions, they don't feel arbitrary. This also creates a natural loop: see weak areas → study in Teach Me / Clarify Doubts → retake exam. |
| **Pause and resume for Teach Me** | Without pause/resume, students who run out of time lose their progress and have to restart. With coverage as a metric, pause/resume is natural — you're just picking up where you left off. This respects the student's time. |
| **Fresh context for each Clarify Doubts session** | Carrying conversation context across sessions would make the tutor's responses depend on potentially stale context. A fresh session with the same curriculum guidelines is simpler and avoids confusion. Past history is shown to the student for their own reference. |
| **Multiple exams pile up with a trend graph** | A single exam is a snapshot. Multiple exams over time show progress. The graph makes improvement visible and motivating — take exam, study, retake, see the line go up. |
| **Exam feedback is evaluative, not remedial** | An exam that teaches defeats the purpose of assessment. The exam tells you *what* you got wrong and *where* to focus — but the actual learning happens in Teach Me or Clarify Doubts. Clear separation of concerns. |
| **Report Card, not separate exam results page** | One place for all progress data. Coverage and exam results all live in the Report Card. No fragmentation. |
| **Default to Teach Me** | Existing entry points that don't specify a mode continue to work as before. |
