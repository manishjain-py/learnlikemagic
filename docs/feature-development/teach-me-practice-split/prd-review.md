# PRD Review: Teach Me / Let's Practice Split

PR #92 | Reviewed 2026-04-06

---

## Overall Assessment

The PRD identifies real problems (session fatigue, no standalone practice, no re-practice). The standalone practice mode is a genuinely valuable addition. But the proposed solution — stripping the interactive phase from Teach Me — creates a pedagogical gap that the PRD doesn't adequately address. The core question is whether the problems can be solved without breaking the learning loop.

---

## The Fundamental Design Question

The PRD bundles two changes into one:

1. **Add a new practice mode** — universally good, solves problems #2 and #3
2. **Remove the interactive phase from Teach Me** — solves problem #1 (session length) but creates new problems

These are independent decisions. You can do #1 without #2. The PRD treats them as inseparable, but they're not.

### What Teach Me loses under this proposal

Current Teach Me: Cards → Bridge Turn → Check Understanding → Guided Practice → Independent Practice → Extend

Proposed Teach Me: Cards → Summary → CTA → END

What's removed:
- **Bridge turn** — the moment where the tutor checks what stuck from cards and identifies gaps. This is described in `learning-session.md` as: *"The tutor generates a personalized interactive plan based on what you just read, then asks you a question referencing specific analogies or examples from the cards to check what stuck."*
- **Check Understanding** — recall and comprehension questions about card content
- **Guided Practice** — working through problems together with tutor help
- **Independent Practice** — solving problems on your own
- **Extend** — applying concepts to new contexts

Under the proposal, all of this moves to Let's Practice. But Let's Practice is optional — the student can tap "I'm done for now" (FR-4) and walk away having only read cards and done match-the-pairs check-ins. They haven't solved a single problem, applied a single concept, or demonstrated understanding beyond recognition.

### The principle conflict

`interactive-teaching.md` Section 1: *"Never jump from explanation to drill. Check understanding with a concrete task first. Student must show WHY something works, not just HOW to do it."*

Check-in cards test recognition (match term A to definition B). They don't test application (solve this problem using the concept). The current interactive phases fill this gap. Removing them from Teach Me means a student can "complete" Teach Me without ever demonstrating they can apply what they read.

The PRD's implicit argument is: check-in cards are sufficient verification during explanation, and deeper verification happens in Let's Practice. This may be defensible, but the PRD should state it explicitly and acknowledge the trade-off.

### Alternative: keep the learning loop, add a natural exit point

Instead of stripping Teach Me, consider:

1. **Keep Teach Me as-is** (cards → bridge → interactive phases)
2. **Add a pause point after the card phase**: "Ready to practice? Or save it for later?"
   - "Practice now" → continues with current bridge + interactive flow (within the same session)
   - "Practice later" → ends Teach Me, marks cards as complete, student can return via Let's Practice
3. **Add Let's Practice as a standalone mode** — exactly as the PRD describes for cold-start

This solves all three problems:
- **Session fatigue**: Students can exit after cards. Session is shorter if they choose.
- **Standalone practice**: Let's Practice exists as a 4th mode.
- **Re-practice**: Students can start new practice sessions anytime.

And it preserves the learning loop for students who choose to continue. No pedagogical regression.

The key insight: the PRD's "Let's Practice" CTA at the end of Teach Me (FR-3) is essentially this pause point already — it just currently requires creating a new session instead of continuing the current one. Making practice continuation seamless (same session, no mode switch) would be a better UX than forcing a session boundary.

---

## Coverage Metric Problem

The PRD says:
- FR-26: Teach Me continues contributing to coverage (based on explanation cards completed)
- FR-27: Practice does NOT contribute to coverage

Currently, coverage is defined as `len(concepts_covered_set) / len(all_concepts) * 100`. `concepts_covered_set` is updated when the tutor advances through study plan steps — including check_understanding, guided_practice, independent_practice, and extend steps.

If Teach Me removes these steps, `concepts_covered_set` can only be populated from card-phase data (`card_covered_concepts`). Coverage becomes "cards read" — a much weaker signal than "concepts applied."

**Scorecard principle #2**: *"Coverage = Teach Me Only. Coverage = how much of the study plan was worked through."*

If the study plan no longer has interactive steps (because they moved to practice), what does "worked through" mean? Reading cards? That contradicts the spirit of the metric, which was designed to track active engagement.

**Options:**
1. Coverage includes practice sessions (contradicts FR-27 and scorecard principle #2)
2. Coverage means "cards completed" (semantically weaker, potentially misleading to parents)
3. Coverage requires both Teach Me + Practice (adds complexity, but most accurate)

The PRD should pick one and justify it.

---

## Context Handoff: Good but Incomplete

FR-19 specifies what gets passed from Teach Me to Practice: variant shown, explanation summary, check-in struggles, remedial cards. This is well-thought-out for the immediate handoff case.

Missing scenarios:

**Delayed practice**: Student does Teach Me on Monday, starts Practice on Thursday. FR-10 says practice launched from the CTA gets context. But what if the student closes the app after Teach Me, returns Thursday, and starts Practice from the mode selection screen (cold start)? Does the system detect the prior Teach Me session and offer to pull context?

The PRD should specify: when a student starts Practice cold on a topic they've previously done Teach Me for, does the system automatically attach context from the most recent Teach Me session? Or is it truly cold (no context, per FR-21)? The former is better pedagogically; the latter is simpler to build.

**Multiple Teach Me sessions**: Student does Teach Me twice (different variants). Which session's context does Practice use? The PRD says `source_session_id` is passed, which handles the CTA case. But for cold-start practice, the system needs a policy for selecting which Teach Me session (if any) to use as context.

---

## Practice Mode Design: Mostly Strong, Some Gaps

### What works well

- **FR-12**: "Assessor who explains when needed" — 80% questions, explains on clear misunderstanding. Good balance.
- **FR-13**: Scaffolded correction reusing the same 3-stage escalation as current interactive teaching. Consistent.
- **FR-14**: Prerequisite gap detection (3+ errors → pause and explain). Important safety net.
- **FR-17**: Repeatable sessions. Essential for spaced practice.
- **FR-18**: Context-aware references when launched from Teach Me, no phantom references when cold. Correct.
- **Edge case**: Sustained struggle → suggest Teach Me first. Smart fallback.

### What needs work

**FR-15: "Tutor decides when to wrap up based on mastery signals"** — This is too vague for implementation. The tutor needs specific criteria:
- Minimum questions before session can end? (The PRD suggests 3-4 for the "rapid mastery" edge case, but no general minimum)
- What mastery level across what % of concepts?
- What if the student masters 3/5 concepts but struggles on 2? Does the session end?

Open Question #1 asks this but frames it as optional. It's not — it's a core design parameter.

**FR-24: "Question difficulty MUST progress: start easy/medium, advance to harder questions"** — Good, but what about the cold-start case? If a student starts Practice cold on a topic they're strong at, starting with easy questions wastes time. The PRD's Open Question #4 asks about cold-start diagnostics. A single calibration question at the start would solve this — ask a medium question, then adjust up or down based on the response.

**Practice sessions are not pausable** — The PRD says practice sessions are "meant to be completed in one sitting." But for Grade 3-8 students, interruptions are constant (dinner, school bus, siblings, parent's phone call). An abandoned session that forces restarting is frustrating, especially if the student was doing well. Consider making practice sessions pausable with a simple "pick up where you left off" — the state is already tracked.

---

## Mode Selection UX: Cognitive Overhead

The mode selection screen grows from 3 choices to 4:
- Teach Me — "Learn this topic step by step"
- Let's Practice — "Test yourself with questions"
- Clarify Doubts — "I have specific questions"
- Exam — "Take a scored test"

For a 9-year-old, the distinction between "Test yourself with questions" (Practice) and "Take a scored test" (Exam) is unclear. Both involve answering questions. The difference is tone and consequences (casual vs formal, unscored vs scored). But the descriptions don't make this obvious.

Worse: "Test yourself with questions" (Practice) vs "I have specific questions" (Clarify Doubts) — both mention "questions." One means "the tutor asks you questions" and the other means "you ask the tutor questions." This directional difference is lost on young students.

**Suggestion:** Make the descriptions more distinct:
- Let's Practice — "Practice what you learned" (no "questions" in description)
- Clarify Doubts — "Ask me anything about this topic"
- Exam — "Formal test with a score"

Or: consider not showing Let's Practice on the mode selection at all for topics the student hasn't done Teach Me on. The primary entry point would be the CTA at the end of Teach Me. Cold-start practice would be accessible but de-emphasized (e.g., only shown for topics with prior Teach Me sessions).

---

## Impact Table: "Teach Me (interactive phase) — Major"

The PRD correctly identifies this as a major impact. But it understates what's involved:

- The entire v2 study plan generation (`_generate_v2_session_plan`) becomes dead code in Teach Me
- The bridge turn generation (`generate_bridge_turn`) becomes dead code in Teach Me
- All step advancement logic, mastery tracking, and explanation phase tracking in the orchestrator is no longer exercised by Teach Me
- The `is_complete` property for teach_me mode (currently: `current_step > study_plan.total_steps`) needs a new definition (cards completed?)
- The `complete_card_phase()` method in session_service.py (currently triggers v2 plan generation and bridge turn) needs to be completely rewritten for the new flow

This is not "removing the interactive phase" — it's rearchitecting how Teach Me sessions work at the state machine level. The technical section should call this out more explicitly.

---

## What the PRD Gets Right

- **Problem statement is accurate** — session fatigue, no standalone practice, and no re-practice are real user pain points
- **Practice mode design is solid** — the 80/20 question/explanation ratio, scaffolded correction, prerequisite detection, and context-aware references are well-designed
- **Context handoff** — FR-19/20 specify exactly what data flows from Teach Me to Practice. Clean.
- **Edge cases are thorough** — abandoned sessions, rapid mastery, sustained struggle, minimum question thresholds. Well thought out.
- **"Last practiced" date** — simple, deterministic metric that fits the scorecard principles
- **Success metrics** — specific, measurable, time-bound. The 50% CTA click rate and 70% completion rate targets are ambitious but reasonable.
- **Technical integration points** — realistic. Practice mode fits the existing mode-routing pattern in the orchestrator.
- **Warm tone requirements** — "Let's see what stuck!" not "Assessment beginning." Consistent with UX principles.

---

## Open Questions That Are Actually Critical Decisions

The PRD's Open Questions section frames these as deferrable. They're not — each one fundamentally shapes the feature:

1. **Mastery threshold** — Without this, you can't implement FR-15 (tutor decides when to wrap up). This isn't an open question; it's a missing spec.
2. **Practice welcome message** — Dynamic is correct (no cards to pre-generate from). But latency for the first message matters for UX — confirm the LLM can generate a welcome in <2s.
3. **Practice → Exam nudge** — This affects the user journey. If the answer is yes, the session completion screen (FR-31) needs a CTA. Decide now, not during implementation.
4. **Cold-start diagnostic** — The PRD's answer to this affects every cold-start practice session's first-question experience. "Start at medium and adapt" is the simplest correct answer.

---

## Summary of Recommendations

| # | Type | Recommendation |
|---|------|---------------|
| 1 | **Rethink** | Consider keeping Teach Me's interactive phase as optional (pause point after cards) rather than removing it entirely. Add Let's Practice as a standalone mode regardless. |
| 2 | **Fix** | Define what "coverage" means when Teach Me no longer has interactive steps. Pick a policy and justify it. |
| 3 | **Fix** | Resolve Open Question #1 (mastery threshold) — it's a prerequisite for implementation, not deferrable. |
| 4 | **Add** | Specify what happens when a student starts Practice cold on a topic they've previously done Teach Me for. Auto-attach context or truly cold? |
| 5 | **Add** | Make mode descriptions more distinct for young students. "Test yourself with questions" vs "Take a scored test" is confusing. |
| 6 | **Add** | Acknowledge the "Explain Before Testing" principle trade-off. Check-in cards test recognition, not application. The PRD should state why this is acceptable. |
| 7 | **Add** | Reconsider practice pause/resume. "Not pausable" is hostile to the target audience's reality (constant interruptions). |
| 8 | **Add** | Specify the practice study plan structure more concretely — what step types, how many, in what order? FR-23 says "primarily question steps" but doesn't define the plan shape. |
| 9 | **Resolve** | Open Questions #2-4 are not deferrable. Decide them in the PRD. |

---

## Reviewer 2

### Executive Summary

The PRD is solving a real problem: the current Teach Me flow is doing too many jobs at once, and the product already hints at that split because the end-of-cards CTA is effectively a practice handoff. A separate Practice mode is directionally strong.

The issue is that this draft swings too far. It makes Teach Me mostly passive, makes Practice’s mastery logic too fuzzy, and treats the implementation as lighter than it really is. I would revise the PRD before building.

### Strengths of the Idea and Approach

- The core diagnosis is right: one mode currently mixes explanation, retrieval, guided practice, and light assessment. That is too much cognitive and product responsibility for one session.
- The distinction between Practice and Exam is good. “Casual, adaptive, teaches when stuck” versus “formal, scored, no teaching” is a meaningful product separation.
- Standalone practice is valuable. Students often need “just quiz me” more than “teach me again.”
- The Teach Me -> Practice handoff is one of the best parts of the draft. Current state already captures card confusion and check-in struggle data, so there is real substrate for this.
- The mobile-first emphasis and structured question formats fit LearnLikeMagic’s audience well.

### Weaknesses / Risks / Missing Edge Cases

#### 1. Teach Me becomes too passive

The PRD effectively turns Teach Me into cards -> summary -> CTA -> end. That means a student can “finish” Teach Me after passive exposure plus recognition-level checks, without ever demonstrating meaningful application or transfer.

Check-in cards help, but they are not enough to make completion mean real learning. If Teach Me completion remains a product milestone, the PRD should either preserve a minimal active retrieval moment or explicitly redefine Teach Me completion as “explained” rather than “understood.”

#### 2. The PRD bundles two separate decisions

The draft currently couples:
- adding a standalone Practice mode
- removing the interactive phase from Teach Me

Those are not inherently the same decision. Adding Practice is broadly strong. Removing the rest of Teach Me’s active learning loop is much more debatable. The PRD should separate these choices more explicitly.

#### 3. Coverage / progress semantics become muddy

If Teach Me becomes mostly explanation/cards, then current coverage semantics become much weaker. Coverage risks meaning “cards completed” rather than “concepts actively worked through.”

That has downstream implications for:
- scorecard semantics
- parent interpretation
- completion messaging
- product trust

The PRD should define what coverage means after the split and whether Practice contributes anything complementary.

#### 4. Practice completion is too fuzzy

The tutor “decides when to wrap up” is not enough for implementation. Practice needs explicit product rules around:
- minimum question count
- mastery thresholds
- concept coverage requirements
- stopping conditions
- behavior when mastery is uneven across concepts

Without these, Practice completion becomes too prompt-dependent and inconsistent.

#### 5. Cold-start Practice is underdefined

Practice-after-Teach-Me and cold-start Practice are not the same pedagogical state. If the student enters Practice without recent card context, the tutor needs a different contract and probably a short calibration behavior before it decides difficulty and support level.

#### 6. Lifecycle / resume behavior is inconsistent

The PRD appears to preserve pause/resume expectations for Teach Me while making Practice effectively non-pausable. For kids on phones, that is a weak assumption. Interruptions are common. Practice likely needs at least some accidental-exit recovery, even if it does not expose an explicit pause button.

#### 7. Availability / dependency rules are inconsistent

The PRD needs to resolve whether Practice:
- depends on cards / prior Teach Me
- can work cold without cards
- is available for all topics or only card-backed ones

Right now the availability logic feels under-specified.

#### 8. Mode selection UX could blur for younger users

For younger students, “Let’s Practice,” “Clarify Doubts,” and “Exam” can blur together. The current conceptual separation may be obvious to adults, but not necessarily to children. The PRD should sharpen copy or entry logic so the differences are clearer.

### Pedagogical and UX Feedback

- Keep the mode split, but do not let Teach Me end as a purely passive reading experience.
- Treat Practice as a coach mode, not a hidden exam.
- Use soft progress framing in Practice rather than rigid counters where possible.
- Consider allowing Practice to offer a lightweight “review explanation again” escape hatch when the student is clearly lost.
- Make sure repeated Practice sessions do not become overfit to the same card analogies; scaffold fading and transfer matter.

### Final Verdict / Recommendations

The direction is good, but the PRD should be revised substantially before implementation begins.

Recommended changes:
1. Clarify Teach Me’s learning contract so completion does not imply passive exposure only.
2. Define deterministic Practice stop conditions and mastery semantics.
3. Resolve no-card / cold-start / resume / accidental-exit behavior.
4. Rewrite the technical section to reflect the real scope: new mode touches prompts, schemas, state models, routing, reporting, analytics, and tests.
5. Resolve the currently open questions in the PRD before engineering starts.

Overall: strong product direction, but not yet implementation-ready as written.
