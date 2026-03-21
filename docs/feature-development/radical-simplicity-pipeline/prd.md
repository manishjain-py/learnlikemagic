# PRD: Radical Simplicity Auto-Research Pipeline

**Date:** 2026-03-21
**Status:** Draft
**Author:** PRD Generator + Manish

---

## 1. Problem Statement

The tutoring system's explanations and tutor messages are not simple enough. Current prompts list simplicity as one concern among 15 rules — it gets diluted when the LLM tries to satisfy all rules simultaneously. The master tutor prompt devotes one line to simplicity ("Use the simplest words the student would use") before moving on to 15 other rules about false-OK detection, scaffolding, visual explanations, question formats, etc.

The gold standard we want: **"Explain Like I'm 5."** Even a below-average IQ student should read any card or tutor message and instantly think "wow, that's so simple, I just get it." Currently, the tutor is pedagogically correct but not radically simple.

---

## 2. Goal

Make every explanation card and tutor message so simple that the weakest student understands instantly — then build an autonomous pipeline that continuously measures and improves this simplicity.

---

## 3. User Stories

- As a **struggling student**, I want every tutor message to use words I already know and say one thing at a time, so that I never feel overwhelmed or confused.
- As a **student reading explanation cards**, I want each card to feel obvious and bite-sized, so that I think "I can do this" — not "what does this mean?"
- As an **admin running auto-research**, I want an autonomous pipeline that scores simplicity, identifies exactly which messages are too complex, and iterates to improve them.
- As a **product owner**, I want simplicity measured as a first-class metric alongside teaching quality and naturalness, so that optimization never trades off simplicity for other goals.

---

## 4. Functional Requirements

### 4.1 Prompt Changes (Phase 1)

- **FR-1:** Master tutor system prompt MUST add "Rule 0: RADICAL SIMPLICITY" as the FIRST rule, positioned before all existing rules, containing:
  - "Explain like you're talking to a 5-year-old"
  - Every sentence under 15 words
  - Only words a child uses in daily life
  - One idea per message — if you need "and" to describe what you're saying, split it
  - "If you can say it simpler, you MUST say it simpler"
  - Simplicity beats thoroughness — say less, not more
  - Self-check before every response: "Would a struggling 10-year-old get this instantly?"
  - Anti-patterns to ban: "In other words," "Essentially," "This means that" — these signal the first explanation was too complex. Say it simply the first time.
- **FR-2:** Explanation generation prompt MUST elevate Principle 1 to ELI5 standard: "Write as if explaining to a 5-year-old. Every sentence must be instantly clear to even a below-average student."
- **FR-3:** Explanation generation prompt SHOULD add explicit constraints: sentences under 15 words, only daily vocabulary of a child, one concept per card.
- **FR-4:** Master tutor Rule 1's "WHY before HOW" MUST add a simplicity caveat: "Keep WHY explanations radically simple — one short sentence, not a paragraph."
- **FR-5:** Master tutor Rule 14 (visual explanations) SHOULD clarify that visual descriptions must not make the overall message longer or more complex.

### 4.2 Simplicity Evaluator

- **FR-6:** A new `SimplicityEvaluator` MUST score the entire session (explanation cards + tutor messages) on one primary dimension: **Simplicity Score** (1-10).
- **FR-7:** The evaluator MUST consider these sub-criteria when scoring:
  - **Word Choice** — Are all words from a child's daily vocabulary? Are technical terms introduced with plain-language explanation?
  - **Sentence Structure** — Are sentences short (under 15 words)? One idea per sentence? No complex or compound clauses?
  - **Concept Density** — One idea per card/message? No information overload? Student never holds multiple new concepts at once?
  - **Accessibility** — Would even a below-average IQ student understand immediately without re-reading?
  - **The "Wow" Factor** — Does the student feel "that's so simple, I just get it!"?
- **FR-8:** The evaluator MUST score two supporting dimensions (diagnostic, not primary optimization target):
  - **Relatability** (1-10) — Are examples from the student's world? Do analogies click immediately?
  - **Progressive Building** (1-10) — Is each step a tiny, natural leap from the previous?
- **FR-9:** The evaluator MUST flag individual cards/messages that fall short, providing for each:
  - Turn/card number
  - The specific word, phrase, or sentence that's too complex
  - Why it's not simple enough
  - How it could be simplified
  - Severity: critical (student would be lost), major (student would struggle), minor (student might pause)
- **FR-10:** The evaluator MUST produce a composite score: `simplicity_score` (the primary 1-10 score) and `weighted_issue_count` (critical x 3 + major x 2 + minor x 1).
- **FR-11:** The scoring rubric:
  - 9-10: Every message crystal clear. A 5-year-old could follow. Words everyday, sentences short, ideas bite-sized.
  - 7-8: Most messages simple. Occasional words/sentences could be simpler. Student pauses at 1-2 spots.
  - 5-6: Mix of simple and complex. Some big words, long sentences, packed ideas.
  - 3-4: Often too complex. Textbook-like language, long explanations, multiple concepts at once.
  - 1-2: Far too complex for a child. Academic language, dense paragraphs.

### 4.3 Pipeline Infrastructure

- **FR-12:** A new auto-research pipeline MUST be created at `autoresearch/simplicity_quality/` with this structure:
  ```
  simplicity_quality/
  ├── program.md              # Auto-research agent instructions
  ├── run_experiment.py       # Experiment runner
  ├── email_report.py         # HTML email report generation
  ├── results.tsv             # Experiment log
  └── evaluation/
      ├── config.py           # SimplicityConfig
      ├── simplicity_evaluator.py  # LLM judge for simplicity
      ├── session_runner.py   # Reuse session_experience runner
      └── report_generator.py # Save artifacts
  ```
- **FR-13:** The pipeline MUST reuse the session runner from `session_experience` (captures both cards + interactive conversation + master tutor prompts).
- **FR-14:** The pipeline MUST reuse personas from `tutor_teaching_quality/evaluation/personas/`.
- **FR-15:** Default personas MUST be `average_student.json` (Riya, 45% correct) and `struggler.json` (Priya, 30% correct) — the students who need simplicity most.
- **FR-16:** Topics MUST rotate from the session_experience TOPIC_POOL (6 Grade 3 Math topics with pre-computed explanations), 3 per iteration by default.

### 4.4 Experiment Execution

- **FR-17:** The pipeline MUST support the same CLI arguments as session_experience:
  - `--restart-server` / `--skip-server`
  - `--description` (experiment hypothesis)
  - `--iteration` (iteration number)
  - `--email` (recipient for report)
  - `--runs` (number of runs to average, default 2)
  - `--quick` (1 topic, 12 turns, 1 run)
  - `--personas` (comma-separated persona files)
- **FR-18:** Keep/discard threshold: Keep if simplicity score improves by >= 0.2 OR weighted issue count decreases by >= 1, without the other metric getting significantly worse.
- **FR-19:** Results MUST be logged to `results.tsv` with columns: commit, simplicity_score, weighted_issues, relatability, progressive_building, elapsed_min, status, description, scores_json.

### 4.5 Email Reports

- **FR-20:** Email reports MUST be generated via macOS Mail.app (same mechanism as existing pipelines).
- **FR-21:** The HTML report MUST include:
  - Iteration number, status (KEEP/DISCARD/CRASH), experiment description
  - Simplicity score vs baseline + delta
  - Weighted issue count vs baseline + delta
  - Supporting dimension scores (relatability, progressive building)
  - Top flagged messages (the most complex cards/messages with specific quotes and simplification suggestions)
  - Prompt diff (git diff of modified prompt files)
  - Full conversation transcript (collapsible)
- **FR-22:** Reports MUST be sent to manish@simplifyloop.com.

### 4.6 Modifiable Surface

- **FR-23:** The auto-research agent MUST only modify these files (same as session_experience):
  - TIER 1: `tutor/prompts/master_tutor_prompts.py`, `tutor/agents/master_tutor.py`, `tutor/services/session_service.py`
  - TIER 2: `tutor/prompts/orchestrator_prompts.py`, `tutor/prompts/clarify_doubts_prompts.py`
- **FR-24:** The auto-research agent MUST NEVER modify evaluation code, run_experiment.py, email_report.py, or any file outside the modifiable surface.

---

## 5. UX Requirements

This feature is an internal admin/research tool — no student-facing UX. The "UX" is the developer experience of running the pipeline and reading reports.

- Email reports MUST be scannable in under 30 seconds — lead with scores and deltas, details below.
- Flagged messages MUST show the exact problematic text and a concrete simplification suggestion — actionable, not vague.
- The pipeline MUST be runnable with a single command (no manual setup beyond `source venv/bin/activate`).

---

## 6. Technical Considerations

### Integration Points

- **Backend modules affected:**
  - `tutor/prompts/master_tutor_prompts.py` — Add Rule 0
  - `book_ingestion_v2/prompts/explanation_generation.txt` — Strengthen simplicity emphasis
  - New module: `autoresearch/simplicity_quality/` (entire pipeline)
- **Database changes:** None. Uses existing `llm_configs` table for evaluator/simulator model config.
- **API endpoints:** None new. Uses existing session and agent-logs APIs.
- **Frontend changes:** None.

### Architecture Notes

- Follows same pattern as existing auto-research pipelines (tutor_teaching_quality, session_experience).
- Reuses `session_experience` session runner for prompt capture (critical for prompt tracing).
- Reuses `tutor_teaching_quality` personas directory.
- New evaluator class (`SimplicityEvaluator`) with its own rubric, distinct from `ConversationEvaluator` and `ExperienceEvaluator`.
- No prompt analyzer stage (unlike session_experience) — the simplicity evaluator's message-level flags with simplification suggestions serve that purpose directly.

### Evaluator LLM Configuration

- Default: GPT-5.2 or Claude Opus 4.6 with high reasoning effort (same as other pipelines).
- Loaded from `llm_configs` DB table, fallback to env var `EVAL_LLM_PROVIDER`.

---

## 7. Impact on Existing Features

| Feature | Impact | Details |
|---------|--------|---------|
| Master Tutor (Teach Me) | **Major** | Rule 0 added to system prompt — changes tutor behavior across all sessions |
| Explanation Cards | **Minor** | Generation prompt strengthened — affects future card generation only, not existing cards |
| tutor_teaching_quality pipeline | **None** | Separate pipeline, independent evaluation |
| session_experience pipeline | **None** | Separate pipeline, shares session runner code |
| Clarify Doubts mode | **Minor** | If TIER 2 prompts modified by auto-research, clarify doubts tone may shift toward simpler language |
| Exam mode | **None** | Exam prompts not in modifiable surface |

### Risk: Simplicity vs Depth Trade-off

Adding Rule 0 ("simplicity overrides everything") may cause the tutor to under-explain concepts that genuinely need multi-step reasoning. Mitigation: Rule 0 should clarify that simplicity means "say it simply" not "say less" — a multi-step explanation is fine if each step is radically simple. The auto-research loop will surface this if it happens (low explanation_quality scores in the tutor_teaching_quality pipeline would flag it).

### Risk: Impact on Other Pipeline Scores

Prompt changes optimized for simplicity could lower scores on other pipelines (e.g., naturalness in session_experience, or explanation_quality in tutor_teaching_quality). Mitigation: Run all three pipelines periodically to check for regression. The simplicity pipeline optimizes for simplicity; other pipelines guard other dimensions.

---

## 8. Edge Cases & Error Handling

| Scenario | Expected Behavior |
|----------|-------------------|
| Topic has no pre-computed explanation cards | Evaluate only tutor messages; skip card-phase scoring. Simplicity score applies to interactive turns only. |
| Tutor response is very short (1-2 words like "Yes!" or "Exactly") | Do not flag as simplicity issue — brevity is simplicity. Only flag when content IS present and is too complex. |
| Technical term is unavoidable (e.g., "fraction", "regrouping") | Score based on whether the term is introduced with a plain-language explanation alongside it, not on the term's presence alone. |
| Evaluator gives perfect 10/10 | Valid. If genuinely simple, the pipeline should still run but may shift to optimizing supporting dimensions (relatability, progressive building). |
| Server crash during experiment | Log as "crash" in results.tsv. Do not keep or discard. Auto-research agent should debug and retry (same pattern as other pipelines). |
| Very long card phase (10+ cards) | Evaluate each card individually. Many cards is fine (12 short > 4 long). Flag individual cards that are too complex. |

---

## 9. Out of Scope

- **Card generation optimization**: This pipeline only modifies tutor prompts (master_tutor_prompts.py, etc.). The explanation_generation.txt changes in Phase 1 are one-time manual edits, not part of the auto-research loop. A separate pipeline for card generation quality already exists (book_ingestion_quality).
- **Multi-language simplicity**: Pipeline evaluates English sessions only. Hindi/Hinglish simplicity is a future extension.
- **Student-facing simplicity feedback**: No UI changes. This is an internal measurement + optimization tool.
- **Readability metrics**: No automated readability scores (Flesch-Kincaid, etc.). The LLM evaluator judges simplicity holistically, which is more appropriate for tutoring content than formula-based metrics.
- **A/B testing with real students**: This pipeline uses simulated students only. Real student impact is measured separately.

---

## 10. Open Questions

1. **Separate card vs tutor scoring?** Should the evaluator produce separate simplicity scores for explanation cards and tutor messages, or one combined score? Current plan: one combined score with message-level flags that distinguish cards from tutor turns.
2. **Explanation generation in the loop?** Should the auto-research agent eventually be able to modify `explanation_generation.txt` to optimize card simplicity too? Currently out of scope (card generation has its own pipeline).
3. **Cross-pipeline regression checks?** Should the simplicity pipeline automatically run the tutor_teaching_quality evaluator as a regression check? Would add ~10 min per iteration but catch depth trade-offs.

---

## 11. Success Metrics

- **Baseline simplicity score** established after Phase 1 prompt changes.
- **Simplicity score improves by >= 1.0** within 10 auto-research iterations.
- **Zero critical-severity simplicity flags** per session within 10 iterations.
- **No regression** on tutor_teaching_quality scores (explanation_quality, pacing, responsiveness remain within 0.5 of pre-change baseline).
- **Qualitative**: Reading a conversation transcript, every tutor message and card feels like something a warm older sibling would say to a 5-year-old.
