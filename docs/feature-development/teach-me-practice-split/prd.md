# PRD: Teach Me / Let's Practice Split

**Date:** 2026-04-06
**Status:** Draft (v2 — revised after review)
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

Students can learn and practice independently — Teach Me for absorbing concepts, Let's Practice for reinforcing them through questions — with a seamless handoff between the two and standalone access to each.

---

## 3. Design Philosophy

**The full learning experience is the combination of modes.** Teach Me and Let's Practice are two halves of one learning journey. Neither mode is designed to be self-sufficient. Teach Me handles concept absorption (explanation cards + check-ins). Let's Practice handles concept reinforcement (questions + adaptive re-explanation). Together they form the complete learn-then-practice loop.

This is an intentional separation. Check-in cards during Teach Me test recognition — can the student identify and match concepts? Practice tests application — can the student solve problems using those concepts? Both are necessary; they don't need to live in the same session.

The seamless transition (Teach Me ends with a prominent Practice CTA) ensures most students naturally flow from one into the other while giving them the freedom to pause between the two.

---

## 4. User Stories

- As a student, I want to go through explanation cards and stop when I've read them, so I don't feel locked into a long session.
- As a student, I want to practice a topic I just learned by answering questions, so I can check if I actually understood it.
- As a student, I want to practice a topic I already know (from school, previous sessions, etc.) without sitting through explanations first.
- As a student, I want the tutor to explain things when I get stuck during practice, so I don't feel lost.
- As a student, I want to re-practice the same topic multiple times over a week to reinforce my learning.
- As a student, I want to pause a practice session and come back later without losing my progress.
- As a parent, I want to see whether my child has both learned and practiced a topic, so I know they're not just reading without testing themselves.

---

## 5. Functional Requirements

### 5.1 Teach Me Mode (Explanation-Only)

- **FR-1:** Teach Me MUST show pre-computed explanation cards (with embedded check-ins) as it does today. No change to card phase behavior.
- **FR-2:** After the last explanation card, Teach Me MUST show a summary card that recaps the key concepts covered.
- **FR-3:** After the summary, Teach Me MUST show a "Let's Practice" CTA that starts a practice session for the same topic. This is the primary action.
- **FR-4:** A secondary "I'm done for now" option MUST be available alongside the CTA, ending the session without starting practice.
- **FR-5:** Teach Me MUST NOT proceed to any interactive question phase (no bridge turn, no v2 plan generation, no check_understanding/guided_practice/independent_practice/extend steps).
- **FR-6:** Teach Me MUST still support per-card simplification ("I didn't understand" flow) and variant switching ("Explain differently") as today.
- **FR-7:** Teach Me MUST still support pause/resume. A paused Teach Me session resumes at the card the student left off on.
- **FR-8:** This PRD assumes all topics have pre-computed explanation cards. Topics without cards are out of scope (see Section 10).

### 5.2 Let's Practice Mode

- **FR-9:** Let's Practice MUST be available as a 4th mode on the mode selection screen, alongside Teach Me, Clarify Doubts, and Exam.
- **FR-10:** Let's Practice MUST also be launchable directly from the Teach Me completion screen via the CTA (FR-3). When launched this way, the practice session MUST receive context about which explanation cards were shown and which check-in struggles occurred.
- **FR-11:** Let's Practice MUST work standalone (cold start) — no prior Teach Me required. When entered cold, the tutor dives straight into questions and explains when the student struggles.
- **FR-12:** The tutor's role in Let's Practice is **assessor-who-explains-when-needed**. The default behavior is asking questions (~80% of turns). The tutor shifts to explanation only when the student demonstrates clear misunderstanding (not on a single wrong answer).
- **FR-13:** The tutor MUST use scaffolded correction during practice: 1st wrong answer = guiding question, 2nd wrong = targeted hint, 3rd+ = explain the concept directly. Same escalation as current interactive teaching (principles/interactive-teaching.md, Section 3).
- **FR-14:** When a student shows a pattern of errors on a concept (3+ errors revealing the same gap), the tutor MUST pause questioning and explain that concept before resuming questions. Same prerequisite gap detection as today.
- **FR-15:** Let's Practice MUST support pause/resume. A paused practice session resumes where the student left off, with full conversation history and mastery state restored.
- **FR-16:** The student MUST be able to end a practice session early at any time via an "End Practice" button.
- **FR-17:** Let's Practice MUST be repeatable — students can start multiple practice sessions for the same topic. Each session is independent.
- **FR-18:** When launched from Teach Me (FR-10), the tutor MUST reference explanation card analogies/examples as shared vocabulary (e.g., "Remember the pizza slices?"). When launched cold, the tutor MUST NOT reference cards the student hasn't seen.

### 5.3 Context Handoff (Teach Me -> Practice)

- **FR-19:** When a student transitions from Teach Me to Let's Practice via the CTA, the system MUST pass to the practice session: (a) which explanation variant was shown, (b) the explanation summary, (c) check-in struggle data (wrong_count, confused_pairs per check-in), (d) any remedial cards generated.
- **FR-20:** The practice session's tutor system prompt MUST include the explanation summary so it can reference card content as shared vocabulary and focus on concepts where check-ins revealed struggles.
- **FR-21:** When a student starts Let's Practice from the mode selection screen on a topic they've previously completed Teach Me for, the system MUST auto-attach context from the most recent completed Teach Me session. This is not a cold start — the student has seen the explanations before.
- **FR-22:** A practice session is only truly cold (no explanation context) when there is no completed Teach Me session for that topic+user.

### 5.4 Practice Session Flow

- **FR-23:** Each Let's Practice session MUST generate a practice-focused study plan. When context is available from Teach Me, the plan SHOULD weight questions toward concepts where check-ins showed struggles.
- **FR-24:** The practice study plan MUST primarily consist of question steps (check_understanding, guided_practice, independent_practice) with no upfront explain steps. Explanation happens reactively, not proactively.
- **FR-25:** Question difficulty MUST progress adaptively. For cold-start sessions, start with a medium-difficulty question and adjust up or down based on the student's response. For post-Teach-Me sessions, start at easy/medium and advance as the student demonstrates understanding.
- **FR-26:** The practice study plan SHOULD use structured question formats (single_select, fill_in_the_blank, multi_select) for most questions, with open-ended questions for reasoning checks. Same format rules as current interactive teaching.

### 5.5 Practice Completion

- **FR-27:** A practice session ends when the tutor determines sufficient mastery. Specific criteria:
  - **Minimum:** At least 5 questions answered before the session can end on mastery
  - **Threshold:** 70% mastery across all tested concepts, with at least 2 questions per key concept
  - **Uneven mastery:** If some concepts are mastered but others aren't, the tutor continues on the weak concepts. Session ends when all concepts hit threshold or student ends early
  - **Maximum:** Session wraps up after ~15-20 questions to prevent fatigue (attention-aware)
- **FR-28:** The practice welcome message MUST be dynamically generated by the tutor (not pre-generated). It should be warm and set expectations: "Let's see what stuck!" / "Ready to put what you learned into practice?"

### 5.6 Progress Tracking

- **FR-29:** Coverage MUST be computed from both Teach Me and Let's Practice sessions combined. Cards completed in Teach Me and concepts practiced in Let's Practice both contribute to the coverage numerator.
- **FR-30:** The report card MUST show a "Last practiced" date for each topic where the student has completed at least one practice session (minimum 3 questions answered).
- **FR-31:** The mode selection screen SHOULD show a practice indicator (e.g., "Practiced 2 days ago") when the student has prior practice sessions for that topic.

### 5.7 Session Summaries

- **FR-32:** When Teach Me ends (cards complete + student chooses "I'm done"), the session summary MUST show: concepts covered, coverage achieved, and a nudge to practice.
- **FR-33:** When Let's Practice ends (mastery achieved or student ends early), the session summary MUST show: concepts tested, how the student performed (qualitative — e.g., "You nailed fractions! Struggled a bit with unlike denominators"), and a suggestion for what to do next.
- **FR-34:** The Teach Me completion nudge MUST be warm and action-oriented: e.g., "You've got the concepts! Ready to put them to work?" — not just a generic "Let's Practice" button.
- **FR-35:** After a successful practice session (mastery achieved), the summary SHOULD nudge the student to take a formal Exam: "You did great! Want to make it official with an exam?"

---

## 6. UX Requirements

- The mode selection screen MUST show 4 modes with clear, distinct descriptions:
  - **Teach Me** — "Learn this topic step by step"
  - **Let's Practice** — "Practice what you learned"
  - **Clarify Doubts** — "Ask me anything about this topic"
  - **Exam** — "Formal test with a score"
- The "Let's Practice" CTA at the end of Teach Me MUST be the primary action (large, prominent button). "I'm done for now" MUST be secondary (smaller, less prominent).
- Practice mode MUST feel lighter than Exam — no question counter ("3/10"), no formal score display. The tutor just asks questions conversationally and wraps up when mastery is sufficient.
- Practice mode MUST use warm, encouraging language: "Let's see what stuck!" not "Assessment beginning."
- All screens MUST work on mobile (min 44px tap targets, single-column layout).
- Language MUST follow easy-english principles for all student-facing text.

---

## 7. Technical Considerations

### Integration Points

- **Backend modules affected:**
  - `session_service.py` — New `practice` mode creation, context handoff logic (both CTA and auto-attach from prior Teach Me), modified Teach Me completion (no bridge turn / v2 plan)
  - `orchestrator.py` — New `_process_practice_turn()` path in mode router, practice-specific system and turn prompts
  - `study_plan_generator_service.py` — New practice-focused plan generation (question-heavy, no explain steps)
  - `report_card_service.py` — Coverage computation updated to include practice sessions; "Last practiced" date tracking
  - `session_repository.py` — Query practice sessions per guideline; find most recent completed Teach Me for auto-context

- **Database changes:**
  - `sessions.mode` — New value: `practice` (alongside `teach_me`, `clarify_doubts`, `exam`)
  - No new tables needed. Practice sessions use the existing `sessions` table with `mode='practice'`
  - `state_json` for practice sessions stores: `practice_source` (`teach_me` or `cold`), `source_session_id` (when context from Teach Me), mastery tracking per concept

- **API endpoints:**
  - `POST /sessions` — Accept `mode='practice'` with optional `source_session_id` for explicit CTA handoff. When no `source_session_id` is provided, the service auto-queries for the most recent completed Teach Me session on that topic
  - `POST /sessions/{id}/step` — Works as today; orchestrator routes to practice path
  - No new endpoints needed

- **Frontend screens:**
  - `ModeSelection.tsx` — Add 4th mode card; show "Last practiced" indicator
  - `ChatSession.tsx` — Handle new practice session phase (no card carousel, straight to interactive); support pause/resume for practice
  - Teach Me card phase completion — Replace bridge turn with summary + CTA screen
  - New: Practice completion summary component

### Architecture Notes

Practice mode fits naturally into the existing mode-routing pattern in the orchestrator. Like `clarify_doubts` and `exam`, it gets its own `_process_practice_turn()` method with practice-specific system and turn prompts. The master tutor agent handles practice just like other modes — single LLM call per turn with structured output.

**State machine changes (significant):** The `complete_card_phase()` method in `session_service.py` currently triggers v2 plan generation and bridge turn. This needs to be rewritten — card phase completion now ends the Teach Me session (with summary + CTA) instead of transitioning to interactive. The v2 plan generation logic moves to practice session creation. The `is_complete` property for `teach_me` mode changes from `current_step > total_steps` to "all cards shown + summary displayed." Bridge turn generation (`generate_bridge_turn`) becomes dead code in Teach Me.

**Context auto-attach:** When creating a practice session without an explicit `source_session_id`, the service queries `sessions` for the most recent completed `teach_me` session matching the user+guideline. If found, it reads the Teach Me session's `CardPhaseState` and `precomputed_explanation_summary` and injects them into the new practice session's state.

---

## 8. Impact on Existing Features

| Feature | Impact | Details |
|---------|--------|---------|
| Teach Me (card phase) | Minor | No change to card behavior. Session ends after cards + summary instead of transitioning to interactive phase |
| Teach Me (interactive phase) | Major | Post-card interactive phase (bridge turn, v2 plan, check/guided/independent/extend) is removed from Teach Me. `complete_card_phase()` rewritten. `is_complete` redefined. Bridge turn and v2 plan generation become dead code in Teach Me context |
| Clarify Doubts | None | Unchanged |
| Exam | None | Unchanged |
| Report Card | Moderate | Coverage computation updated to include practice sessions. Add "Last practiced" date display |
| Mode Selection | Minor | Add 4th mode card + practice indicator |
| Evaluation System | Minor | Evaluation simulations need a new practice mode test path (can be deferred) |
| Session History | Minor | Practice sessions appear with "Let's Practice" label |
| Pause/Resume | Minor | Practice sessions support pause/resume same as Teach Me |

---

## 9. Edge Cases & Error Handling

| Scenario | Expected Behavior |
|----------|-------------------|
| Student clicks "Let's Practice" from Teach Me but the practice session fails to create | Show error toast, keep Teach Me completion screen visible so student can retry or tap "I'm done" |
| Student starts practice cold on a topic with no teaching guideline | Practice mode unavailable — same gating as current modes (guideline required) |
| Student starts practice cold, gets everything right immediately | Tutor acknowledges mastery quickly but enforces minimum 5 questions before ending |
| Student starts practice cold, struggles heavily on every question | After sustained struggle (5+ consecutive wrong across multiple concepts), tutor suggests: "Looks like this topic is new — want to try Teach Me first?" with an actionable link |
| Student ends practice early after 1 question | Session saved. No coverage contribution and no "Last practiced" indicator (require minimum 3 questions answered for meaningful data) |
| Student starts practice from mode selection on a topic with prior Teach Me | System auto-attaches context from most recent completed Teach Me session. Not a cold start |
| Student has done Teach Me twice (different variants) | Auto-attach uses the most recent completed Teach Me session's context |
| Student pauses practice and resumes later | Full conversation history and mastery state restored, session continues from where they left off |
| Multiple practice sessions same day | Allowed. Each is independent. "Last practiced" updates to most recent |

---

## 10. Out of Scope

- Topics without pre-computed explanation cards — v1 Teach Me fallback behavior will be addressed in a separate spec
- Spaced repetition scheduling (automated "time to practice again" push notifications)
- Evaluation system updates for practice mode testing
- Gamification of practice (streaks, points, leaderboards)
- Group/peer practice
- Practice across multiple topics in one session

---

## 11. Open Questions

None — all previously open questions resolved in v2:
- Mastery threshold: 70% across all concepts, minimum 5 questions, max ~15-20 (FR-27)
- Welcome message: dynamic, generated by tutor (FR-28)
- Practice → Exam nudge: yes, after successful practice (FR-35)
- Cold-start: start at medium difficulty, adapt from first response (FR-25)

---

## 12. Success Metrics

- **Practice adoption**: >50% of students who complete Teach Me click the "Let's Practice" CTA (measures nudge effectiveness)
- **Standalone practice usage**: >20% of practice sessions are cold-start (measures value of standalone entry point)
- **Session fatigue reduction**: Average Teach Me session duration decreases (shorter, focused explanation sessions)
- **Re-practice rate**: >30% of students who practice a topic return to practice it again within 7 days (measures spaced repetition value)
- **Practice completion rate**: >70% of practice sessions reach mastery-based completion (vs. early exit)
- **Learning efficacy**: Students who do Teach Me + Practice score higher on subsequent Exams than students who only do Teach Me (current flow)
