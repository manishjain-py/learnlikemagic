# PRD: Teach Me / Let's Practice Split

**Date:** 2026-04-06
**Status:** Draft
**Author:** PRD Generator + Manish

---

## 1. Problem Statement

The current Teach Me flow bundles explanation and practice into one continuous session: explanation cards, then bridge turn, then check-understanding, guided practice, independent practice, and extension. This creates three problems:

1. **Long sessions** — Students must sit through both explanation and practice in one go. A 20-minute session with no natural exit point causes fatigue, especially for younger students with shorter attention spans.
2. **No standalone practice** — A student who learned fractions in school today has no way to just practice. They must either sit through Teach Me explanations they don't need, or take a formal Exam.
3. **No re-practice without re-learning** — A student who wants to drill the same topic again next week must restart the full Teach Me flow. There's no lightweight "just quiz me" option.

The gap is a casual, adaptive practice mode that lives between Teach Me (structured learning) and Exam (formal assessment).

---

## 2. Goal

Students can learn and practice independently — Teach Me for absorbing concepts, Let's Practice for reinforcing them through questions — with a smooth handoff between the two and standalone access to each.

---

## 3. User Stories

- As a student, I want to go through explanation cards and stop when I've read them, so I don't feel locked into a long session.
- As a student, I want to practice a topic I just learned by answering questions, so I can check if I actually understood it.
- As a student, I want to practice a topic I already know (from school, previous sessions, etc.) without sitting through explanations first.
- As a student, I want the tutor to explain things when I get stuck during practice, so I don't feel lost.
- As a student, I want to re-practice the same topic multiple times over a week to reinforce my learning.
- As a parent, I want to see whether my child has both learned and practiced a topic, so I know they're not just reading without testing themselves.

---

## 4. Functional Requirements

### 4.1 Teach Me Mode (Explanation-Only)

- **FR-1:** Teach Me MUST show pre-computed explanation cards (with embedded check-ins) as it does today. No change to card phase behavior.
- **FR-2:** After the last explanation card, Teach Me MUST show a summary card that recaps the key concepts covered.
- **FR-3:** After the summary, Teach Me MUST show a "Let's Practice" CTA that starts a practice session for the same topic. This is the primary action.
- **FR-4:** A secondary "I'm done for now" option MUST be available alongside the CTA, ending the session without starting practice.
- **FR-5:** Teach Me MUST NOT proceed to any interactive question phase (no bridge turn, no v2 plan generation, no check_understanding/guided_practice/independent_practice/extend steps).
- **FR-6:** Teach Me MUST still support per-card simplification ("I didn't understand" flow) and variant switching ("Explain differently") as today.
- **FR-7:** Teach Me MUST still support pause/resume. A paused Teach Me session resumes at the card the student left off on.
- **FR-8:** This PRD assumes all topics have pre-computed explanation cards. Topics without cards are out of scope (see Section 9).

### 4.2 Let's Practice Mode

- **FR-9:** Let's Practice MUST be available as a 4th mode on the mode selection screen, alongside Teach Me, Clarify Doubts, and Exam.
- **FR-10:** Let's Practice MUST also be launchable directly from the Teach Me completion screen via the CTA (FR-3). When launched this way, the practice session MUST receive context about which explanation cards were shown and which check-in struggles occurred.
- **FR-11:** Let's Practice MUST work standalone (cold start) — no prior Teach Me required. When entered cold, the tutor dives straight into questions and explains when the student struggles.
- **FR-12:** The tutor's role in Let's Practice is **assessor-who-explains-when-needed**. The default behavior is asking questions (~80% of turns). The tutor shifts to explanation only when the student demonstrates clear misunderstanding (not on a single wrong answer).
- **FR-13:** The tutor MUST use scaffolded correction during practice: 1st wrong answer = guiding question, 2nd wrong = targeted hint, 3rd+ = explain the concept directly. Same escalation as current interactive teaching (principles/interactive-teaching.md, Section 3).
- **FR-14:** When a student shows a pattern of errors on a concept (3+ errors revealing the same gap), the tutor MUST pause questioning and explain that concept before resuming questions. Same prerequisite gap detection as today.
- **FR-15:** Let's Practice sessions MUST end when the tutor determines the student has demonstrated sufficient mastery across the topic's key concepts. The tutor decides when to wrap up based on mastery signals.
- **FR-16:** The student MUST also be able to end a practice session early at any time via an "End Practice" button.
- **FR-17:** Let's Practice MUST be repeatable — students can start multiple practice sessions for the same topic. Each session is independent.
- **FR-18:** When launched from Teach Me (FR-10), the tutor MUST reference explanation card analogies/examples as shared vocabulary (e.g., "Remember the pizza slices?"). When launched cold, the tutor MUST NOT reference cards the student hasn't seen.

### 4.3 Context Handoff (Teach Me -> Practice)

- **FR-19:** When a student transitions from Teach Me to Let's Practice, the system MUST pass to the practice session: (a) which explanation variant was shown, (b) the explanation summary, (c) check-in struggle data (wrong_count, confused_pairs per check-in), (d) any remedial cards generated.
- **FR-20:** The practice session's tutor system prompt MUST include the explanation summary so it can reference card content as shared vocabulary and focus on concepts where check-ins revealed struggles.
- **FR-21:** When entered cold, the practice session MUST NOT include any explanation summary in the tutor prompt.

### 4.4 Practice Study Plan

- **FR-22:** Each Let's Practice session MUST generate a practice-focused study plan. When context is available from Teach Me, the plan SHOULD weight questions toward concepts where check-ins showed struggles.
- **FR-23:** The practice study plan MUST primarily consist of question steps (check_understanding, guided_practice, independent_practice) with no upfront explain steps. Explanation happens reactively, not proactively.
- **FR-24:** Question difficulty MUST progress: start easy/medium, advance to harder questions as the student demonstrates understanding. Strong students should reach challenging problems quickly.
- **FR-25:** The practice study plan SHOULD use structured question formats (single_select, fill_in_the_blank, multi_select) for most questions, with open-ended questions for reasoning checks. Same format rules as current interactive teaching.

### 4.5 Progress Tracking

- **FR-26:** Teach Me sessions MUST continue contributing to the coverage metric as today (based on explanation cards completed).
- **FR-27:** Let's Practice sessions MUST NOT contribute to coverage. Coverage remains explanation-only.
- **FR-28:** The report card MUST show a "Last practiced" date for each topic where the student has completed at least one practice session.
- **FR-29:** The mode selection screen SHOULD show a practice indicator (e.g., "Practiced 2 days ago") when the student has prior practice sessions for that topic.

### 4.6 Session Completion

- **FR-30:** When Teach Me ends (cards complete + student chooses "I'm done"), the session summary MUST show: concepts covered, coverage achieved, and a nudge to practice.
- **FR-31:** When Let's Practice ends (mastery achieved or student ends early), the session summary MUST show: concepts tested, how the student performed (qualitative — e.g., "You nailed fractions! Struggled a bit with unlike denominators"), and a suggestion for what to do next.
- **FR-32:** The Teach Me completion nudge MUST be warm and action-oriented: e.g., "You've got the concepts! Ready to put them to work?" — not just a generic "Let's Practice" button.

---

## 5. UX Requirements

- The mode selection screen MUST show 4 modes with clear, distinct descriptions so students understand the difference. Suggested labels:
  - **Teach Me** — "Learn this topic step by step"
  - **Let's Practice** — "Test yourself with questions"
  - **Clarify Doubts** — "I have specific questions"
  - **Exam** — "Take a scored test"
- The "Let's Practice" CTA at the end of Teach Me MUST be the primary action (large, prominent button). "I'm done for now" MUST be secondary (smaller, less prominent).
- Practice mode MUST feel lighter than Exam — no question counter ("3/10"), no formal score display. The tutor just asks questions conversationally and wraps up when mastery is sufficient.
- Practice mode MUST use warm, encouraging language: "Let's see what stuck!" not "Assessment beginning."
- All screens MUST work on mobile (min 44px tap targets, single-column layout).
- Language MUST follow easy-english principles for all student-facing text.

---

## 6. Technical Considerations

### Integration Points

- **Backend modules affected:**
  - `session_service.py` — New `practice` mode creation, context handoff logic, modified Teach Me completion (no bridge turn / v2 plan)
  - `orchestrator.py` — New `_process_practice_turn()` path in mode router, practice-specific prompts
  - `study_plan_generator_service.py` — New practice-focused plan generation
  - `report_card_service.py` — "Last practiced" date tracking
  - `session_repository.py` — Query practice sessions per guideline

- **Database changes:**
  - `sessions.mode` — New value: `practice` (alongside `teach_me`, `clarify_doubts`, `exam`)
  - No new tables needed. Practice sessions use the existing `sessions` table with `mode='practice'`
  - `state_json` for practice sessions stores: `practice_source` (`teach_me` or `cold`), `source_session_id` (when from Teach Me), mastery tracking per concept

- **API endpoints:**
  - `POST /sessions` — Accept `mode='practice'` with optional `source_session_id` for context handoff
  - `POST /sessions/{id}/step` — Works as today; orchestrator routes to practice path
  - No new endpoints needed

- **Frontend screens:**
  - `ModeSelection.tsx` — Add 4th mode card; show "Last practiced" indicator
  - `ChatSession.tsx` — Handle new practice session phase (no card carousel, straight to interactive)
  - Teach Me card phase completion — Replace bridge turn with summary + CTA screen
  - New: Practice completion summary component

### Architecture Notes

Practice mode fits naturally into the existing mode-routing pattern in the orchestrator. Like `clarify_doubts` and `exam`, it gets its own `_process_practice_turn()` method with practice-specific system and turn prompts. The master tutor agent handles practice just like other modes — single LLM call per turn with structured output.

The context handoff (Teach Me -> Practice) uses the existing `precomputed_explanation_summary` mechanism. When creating a practice session from a Teach Me session, the service reads the completed Teach Me session's card phase state and explanation summary, then injects it into the new practice session's state.

---

## 7. Impact on Existing Features

| Feature | Impact | Details |
|---------|--------|---------|
| Teach Me (card phase) | Minor | No change to card behavior. Only change: session ends after cards + summary instead of transitioning to interactive phase |
| Teach Me (interactive phase) | Major | Post-card interactive phase (bridge turn, v2 plan, check/guided/independent/extend) is removed from Teach Me. This logic moves to Let's Practice |
| Clarify Doubts | None | Unchanged |
| Exam | None | Unchanged |
| Report Card | Minor | Add "Last practiced" date display. Coverage computation unchanged |
| Mode Selection | Minor | Add 4th mode card + practice indicator |
| Evaluation System | Minor | Evaluation simulations need a new practice mode test path (can be deferred) |
| Session History | Minor | Practice sessions appear with "Let's Practice" label |
| Pause/Resume | Minor | Practice sessions are NOT pausable (they're meant to be completed in one sitting). Teach Me pause/resume unchanged |

---

## 8. Edge Cases & Error Handling

| Scenario | Expected Behavior |
|----------|-------------------|
| Student clicks "Let's Practice" from Teach Me but the practice session fails to create | Show error toast, keep Teach Me completion screen visible so student can retry or tap "I'm done" |
| Student starts practice cold on a topic with no teaching guideline | Practice mode unavailable — same gating as current modes (guideline required) |
| Student starts practice cold, gets everything right immediately | Tutor acknowledges mastery quickly and ends session after a minimum of 3-4 questions (don't end after 1 correct answer) |
| Student starts practice cold, struggles heavily on every question | After sustained struggle (5+ consecutive wrong across multiple concepts), tutor suggests: "Looks like this topic is new — want to try Teach Me first?" with an actionable link |
| Student ends practice early after 1 question | Session saved with minimal data. No practice indicator shown in report card (too little data to be meaningful — require minimum 3 questions answered) |
| Student has an in-progress practice session | Practice sessions are NOT pausable. If student leaves mid-session and returns, the session is marked as abandoned. They can start a new one |
| Multiple practice sessions same day | Allowed. Each is independent. "Last practiced" updates to most recent |

---

## 9. Out of Scope

- Topics without pre-computed explanation cards — v1 Teach Me fallback behavior will be addressed in a separate spec
- Spaced repetition scheduling (automated "time to practice again" push notifications)
- Practice session pause/resume
- Evaluation system updates for practice mode testing
- Gamification of practice (streaks, points, leaderboards)
- Group/peer practice
- Practice across multiple topics in one session

---

## 10. Open Questions

1. **Minimum mastery threshold** — What mastery level should the tutor target before ending a practice session? 70%? 80%? Should it vary by topic difficulty?
2. **Practice welcome message** — Should the welcome be pre-generated (like Teach Me) or dynamic? Dynamic seems right since there's no card phase, but worth confirming.
3. **Practice + Exam nudge** — After a good practice session, should the app nudge the student to take a formal Exam? ("You did great! Want to make it official with an exam?")
4. **Cold-start diagnostic depth** — When entering practice cold, should the tutor start with a quick diagnostic question to gauge level, or just start at medium difficulty and adapt?

---

## 11. Success Metrics

- **Practice adoption**: >50% of students who complete Teach Me click the "Let's Practice" CTA (measures nudge effectiveness)
- **Standalone practice usage**: >20% of practice sessions are cold-start (measures value of standalone entry point)
- **Session fatigue reduction**: Average Teach Me session duration decreases (shorter, focused explanation sessions)
- **Re-practice rate**: >30% of students who practice a topic return to practice it again within 7 days (measures spaced repetition value)
- **Practice completion rate**: >70% of practice sessions reach mastery-based completion (vs. early exit)
- **Learning efficacy**: Students who do Teach Me + Practice score higher on subsequent Exams than students who only do Teach Me (current flow)
