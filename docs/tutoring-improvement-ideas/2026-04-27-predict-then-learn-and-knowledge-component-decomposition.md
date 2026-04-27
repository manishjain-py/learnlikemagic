# Tutoring Improvement Ideas — 2026-04-27

## Idea 1: Predict-Then-Learn (Epistemic Emotion Triggering)

### What
Before explaining a concept, the tutor asks the student to **predict** what will happen. Only after the student commits does the tutor reveal the explanation. When the prediction is wrong, the resulting *surprise* triggers significantly deeper cognitive processing.

**Example (Baatcheet):**
> **Mr. Verma:** If you pour hot water into a cup of cold water, what do you think happens to the temperature? Pick one: (A) It stays the same (B) Hot water wins (C) Something in between  
> **Student:** B  
> **Mr. Verma:** Good guess! But here's the surprising part — the answer is C...  
> *(Explanation now lands on a brain that's actively processing WHY its prediction was wrong)*

### Why This Is Impactful

**Directly combats passive learning.** Indian board-exam culture trains students to absorb and reproduce — not to think before receiving. Prediction prompts force *active generation* before consumption.

**Strong evidence base:**
- Epistemic emotions (surprise, curiosity) robustly promote knowledge exploration (Frontiers in Psychology, PMC6861443)
- Refutation texts (information that contradicts expectations) activate deeper processing and suppress boredom (Nature, 2025 — s41539-025-00324-3)
- Harvard AI Tutor RCT (N=194, June 2025): AI tutoring that required students to generate responses first outperformed active learning classrooms by **0.73–1.3 standard deviations** (Nature Scientific Reports, s41598-025-97652-6)
- Students who passively receive AI-generated answers perform worse than those forced to generate first (arXiv 2510.16019)

**ESL-friendly.** Predictions can be simple A/B/C choices — no fluent English production required. This bypasses the language barrier while maintaining full cognitive engagement.

**Low implementation cost.** Fits naturally into existing Baatcheet dialogue flow and Explain card pipeline.

### How to Implement

1. **Ingestion-time:** During stages 5b/5c (Baatcheet dialogue generation), add a `prediction_prompt` to each topic's opening. The LLM generates a scenario + 2-3 prediction options grounded in common misconceptions.

2. **Card phase:** Insert a prediction card before the first explanation card. Student taps their prediction; the system records it.

3. **Interactive phase:** Mr. Verma references the student's prediction ("You thought B, right? Let's see why..."). When wrong, explicitly surface the *surprise gap* — "Most students think that too! Here's what actually happens."

4. **Tutor prompt addition:** New teaching rule: "When a prediction_prompt exists, always begin by referencing the student's prediction. If wrong, frame the explanation as resolving the surprise. If correct, acknowledge and deepen."

5. **Tracking:** Store prediction accuracy per topic. Patterns reveal which misconceptions are most common, feeding back into question bank and misconception library refinement.

### Differentiation from Previous Ideas
- **Not misconception-first teaching (#20):** That detects misconceptions reactively from errors. This *proactively creates* a prediction moment before any teaching begins.
- **Not cognitive offloading prevention (#6):** That prevents over-reliance on AI. This uses prediction to activate the brain's error-correction circuitry via surprise.
- **Not worked examples (#16):** That scaffolds solution steps. This scaffolds the *mental state* before learning even begins.

---

## Idea 2: Knowledge Component Decomposition with Granular Mastery Tracking

### What
During book ingestion, use the LLM to decompose each topic into **atomic knowledge components (KCs)** — the smallest teachable/testable skills. Track mastery per KC (not per topic) in the scorecard and tutor state, enabling the system to pinpoint exactly *which sub-skill* a student struggles with.

**Example — Topic: "Adding Fractions"**

Current system tracks: `adding_fractions → mastery: 0.45`

Proposed KC decomposition:
| KC | Mastery |
|----|---------|
| Identify numerator and denominator | 0.90 |
| Find LCM of two numbers | 0.30 |
| Convert to equivalent fractions | 0.35 |
| Add numerators after converting | 0.70 |
| Simplify the result | 0.55 |

Now the tutor knows: this student's bottleneck is LCM, not fractions conceptually. It can target remediation precisely.

### Why This Is Impactful

**Eliminates wasted teaching time.** Current topic-level mastery forces the tutor to re-teach entire topics when only one sub-skill is weak. KC-level tracking enables surgical remediation — 3 minutes on LCM instead of 15 minutes re-doing all of fractions.

**Strong evidence base:**
- KCGen-KT (Feb 2025, arXiv 2502.18632): LLM-generated knowledge components **outperform human-written KCs** on predicting student responses. Course instructors confirmed accuracy of problem-KC mappings.
- KC-level Correctness Labeling (Feb 2026, arXiv 2602.17542): LLMs can label correctness at the KC level for individual submissions, enabling granular mastery tracking.
- SkillX (2026, arXiv 2604.04804): Three-tiered skill hierarchies (strategic → functional → atomic) with iterative refinement show robust knowledge structuring.
- Systematic review of K-12 ITS (Nature 2025, s41539-025-00320-7): Step-based and sub-step-based tutoring systems achieve **effect sizes of 0.75–0.80**, significantly higher than topic-level systems.

**Transforms prerequisite detection.** Instead of detecting that a student "struggles with fractions," the system can identify that the specific blocker is LCM — and check whether LCM was mastered in its original chapter. This makes the prerequisite system (#19 in principles) dramatically more precise.

**Improves practice question targeting.** Practice mode can select questions that specifically test weak KCs rather than randomly sampling from the whole topic.

### How to Implement

1. **Ingestion-time (Stage 5a extension):** After extracting concepts per topic, add a KC decomposition step. Prompt: "Break this concept into the 3-7 atomic skills a student must master. Each KC should be independently testable with a single question."

2. **Schema addition:** Add a `knowledge_components` table linking to topics. Each KC has: `id`, `topic_id`, `name`, `description`, `prerequisite_kcs` (for dependency graph).

3. **Tutor state update:** Extend `mastery_updates` in `TutorTurnOutput` to include KC-level signals. When a student answers a question, the tutor identifies which KCs were exercised and updates each independently.

4. **Scorecard enhancement:** Display KC-level mastery within each topic (collapsible detail). Parent dashboard shows which specific sub-skills need attention.

5. **Practice targeting:** When generating practice sets, weight question selection toward weak KCs. A student strong on "identify numerator/denominator" but weak on "find LCM" gets more LCM questions.

6. **Tutor prompt integration:** Add KC mastery data to the turn prompt's mastery section. New rule: "When a student struggles, identify which specific KC is the bottleneck and focus remediation there, not on the whole topic."

### Differentiation from Previous Ideas
- **Not spaced repetition (#1):** That schedules review timing. This determines *what* to review at granular level.
- **Not misconception-first teaching (#20):** That identifies wrong mental models. KCs identify missing procedural sub-skills — complementary, not overlapping.
- **Not smart revision planner (#15):** That generates exam schedules. This provides the granular skill data that makes any revision plan dramatically more effective.

---

## Impact Comparison

| Dimension | Predict-Then-Learn | KC Decomposition |
|-----------|-------------------|------------------|
| Learning gain evidence | 0.73–1.3 SD (Harvard RCT) | 0.75–0.80 effect size (ITS meta-analysis) |
| Implementation effort | Low (prompt + card changes) | Medium (schema + ingestion + tutor state) |
| Time to first value | Days (add to Baatcheet dialogues) | Weeks (ingestion pipeline + DB + UI) |
| ESL benefit | High (bypasses language with choices) | Medium (indirect — less wasted teaching time) |
| Compounds with existing features | Baatcheet, Explain cards | Scorecard, Practice, Prerequisites |

**Recommendation:** Ship Predict-Then-Learn first (quick win, immediate learning impact). Build KC Decomposition as infrastructure investment (high long-term leverage across every feature).
