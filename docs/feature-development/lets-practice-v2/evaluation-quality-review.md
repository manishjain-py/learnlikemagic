# Let's Practice — Evaluation Quality Review

**Date:** 2026-04-23
**Status:** Analysis / recommendations (no code changes)
**Scope:** Review how practice answers are graded and how corrections are explained to students, benchmarked against the explanation-cards gold standard.

---

## Problem statement

"Let's Practice" is a drill feature: students answer a bank of questions without hints, then see a graded review with explanations for each wrong answer. This is the single largest surface where the app tells a student "you were wrong, here's why" — so correction quality directly drives learning.

Two questions to answer:

1. **Is grading accurate?** Do students get the right score for what they actually know?
2. **Are the correction explanations good teaching?** When a student gets something wrong, does the explanation teach the concept — or just announce the correct answer?

Benchmark: our pre-computed **explanation cards** represent the app's highest-quality teaching output (per `docs/principles/how-to-explain.md`, reviewed, refined, scored across 5 dimensions). Practice corrections are a teaching opportunity of at least equal importance — the student has engaged and failed, so their misconception is now *exposed* and ready to be addressed.

---

## Headline finding

**The moment of highest learning leverage gets the lowest-quality teaching.** Initial exposition (explanation cards) gets `claude-opus-4-6`, a 9-point review-refine checklist, visuals, per-line audio, and a 5-dimension quality score. Corrections — delivered when the student has just demonstrated a specific misconception — get a ~20-word `gpt-4o-mini` single-shot rationale with no quality gate. The gap is structural, not accidental.

---

## How grading works today

**Structured formats (11 types) — deterministic, binary.** `pick_one`, `true_false`, `match_pairs`, `sort_buckets`, `swipe_classify`, `sequence`, `spot_the_error`, `odd_one_out`, `fill_blank`, `tap_to_eliminate`, `predict_then_reveal` all use exact comparison (`llm-backend/tutor/services/practice_grading_service.py:162-226`). No LLM variance, fast, reproducible. Score is 1.0 or 0.0 — no partial credit path.

**Free-form — rubric-based LLM grading, fractional.** `_grade_free_form()` calls the `FREE_FORM_GRADING_PROMPT` (`llm-backend/tutor/prompts/practice_grading.py:17-42`). LLM returns a score in {0.0, 0.5, 1.0} against the question's `grading_rubric`. A free-form answer is marked `correct` at `score >= 0.75` (`practice_grading_service.py:47`). Raw totals are half-point rounded at write time (`:141-145`).

**Per-pick rationales — LLM, single-shot, no quality gate.** `_explain_wrong_pick()` (`:339-357`) runs the `PER_PICK_RATIONALE_PROMPT` (`practice_grading.py:45-66`). The prompt is fed: the question, the correct answer summary, the student's pick, and the bank's pre-generated `explanation_why` field. Output is a single sentence ≤20 words. No review pass. No validation. No scoring.

**Models.** Bank generation uses `claude_code/claude-opus-4-6` (offline, medium reasoning). Runtime grading and rationale generation use `openai/gpt-4o-mini` (latency-optimized, no reasoning).

---

## How the explanation-cards gold standard works

For contrast, the explanation-cards pipeline (`llm-backend/book_ingestion_v2/services/explanation_generator_service.py:128-284`):

1. **Generate** — LLM produces 3–15 cards with title, lines[], visuals, audio.
2. **Review-and-refine** — a second LLM pass reads the cards as a struggling student, applies a 9-point checklist, fixes weaknesses in-place. Default 1 round (configurable). Measured impact: overall score 7.30 → 7.52, concept-clarity +0.40.
3. **Validate** — card count, structure, line length (≤15 words).
4. **Scored** across 5 dimensions: Simplicity, Concept Clarity, Examples & Analogies, Structure & Flow, Overall Effectiveness (`llm-backend/autoresearch/explanation_quality/README.md`).

The 9-point reviewer checklist (`llm-backend/book_ingestion_v2/prompts/explanation_review_refine_system.txt:17-26`): factual accuracy, vocabulary clarity, one idea per card, concrete visuals, natural flow, misconception prevention, warm tone, confidence ending, Indian-context check ("teach their form as THE form").

---

## The gap — side by side

| Quality dimension | Explanation cards | Practice corrections |
|---|---|---|
| Model | `claude-opus-4-6` | `gpt-4o-mini` |
| Review/refine quality gate | 1 default round | None |
| Multi-dimension quality scoring | 5 dimensions | None |
| Visuals | ASCII diagrams + optional code | None (`visual_explanation_code: None` placeholder at `:383`) |
| Structure | Multiple cards, progressive | Single ≤20-word sentence |
| Misconception-targeted | Principle #10, enforced | Only implicitly — fed generic `explanation_why` and asked to infer |
| Scaffolding | Explicit in card sequence | None |
| Confidence ending | Last card aims to build it | Not attempted |
| Warm tone | Enforced and checked in review | Asked for, not validated |
| Grounded in topic teaching | Uses full guideline | Uses only the bank-time `explanation_why` sentence |
| Indian-context validation | Checked in review | Asked for, not validated |

---

## Specific findings

### 1. Evaluation accuracy

**What works**

- Structured-format correctness is deterministic and reproducible.
- Free-form grading has a sensible threshold (0.75) and half-point granularity.
- Prompts embed easy-english rules.

**What's wrong or missing**

- **No partial credit on structured formats.** `match_pairs` with 2/3 correct pairs, `sort_buckets` with 8/10 correctly sorted items, `sequence` with one swap — all score 0.0. Principle #6 of `docs/principles/practice-mode.md` permits half-point granularity; the 11 checkers don't use it. This under-rewards real understanding.
- **No accommodation for ESL input noise.** A child writing "one lakh" vs "1,00,000", "biggger" vs "bigger", or reordering words in free-form — exact comparison only, no fuzzy match or lightweight LLM-repair layer.
- **No post-generation validation that grader output follows easy-english rules.** Prompt asks for it; nothing checks. An occasional "Western system uses commas" slip ships straight to a student.
- **Grader tests mock the LLM.** `test_practice_grading_service.py` covers deterministic logic thoroughly but never asserts on real rationale quality. Regressions in tone, misconception accuracy, or easy-english compliance are invisible.
- **Blank answers on structured formats get no rationale at all** — just a red ✗. For a student who gave up, that is the exact moment a warm one-liner would help most.
- **Model split is latency-first, not learning-first.** No published benchmark justifies `gpt-4o-mini` at runtime. Latency budget is generous (grading is async, polled).

### 2. Correction explanation quality

The single most important gap: **the rationale prompt does not diagnose the specific misconception the wrong pick reveals.**

A student who picks `5,067 > 5,076` is showing a specific error (comparing left-aligned digits at the wrong place). The current pipeline feeds the LLM a generic `explanation_why` about place value, and asks it to infer. What we get is a plausible-sounding, generic sentence. What the student needs is:

> "You compared the **7** in 5,067 with the **7** in 5,076 — but the **tens** digit is what's different. 6 tens < 7 tens, so 5,067 is smaller."

That is teaching. What we produce is a correction receipt.

Other quality issues visible from the code:

- **`JSON.stringify` for complex `correct_answer_summary`** (`llm-frontend/src/pages/PracticeResultsPage.tsx:291-293`). For `match_pairs` or `sort_buckets`, students see `[{"left":"dog","right":"animal"},...]`. That's the UX of a stack trace.
- **No per-question `common_misconceptions` field at bank time.** We already have `claude-opus-4-6` generating each question offline — it could generate 2–3 likely-wrong-pick explanations too, which runtime grading would use.
- **No easy-english lint.** Regex-level checks for phrasal verbs, sentence length, "Western"/"In India" framings would catch slips from both bank generation and runtime rationales.

### 3. Operational gap (separate from quality)

- **Silent grading-thread death is a known, unmitigated v1 risk** (`docs/technical/practice-mode.md:184`, `llm-backend/tutor/services/practice_service.py:17-18`). Frontend caps polling at ~5 minutes. A crashed worker leaves the attempt stuck in `status='grading'` forever. Post-v1 mitigation — `grading_started_at` timestamp + sweeper — is documented but not built.

---

## Recommendations in priority order

**P0 — Add a review-refine pass to correction rationales.** Mirror the explanation-cards pattern. After the first rationale, run a second LLM pass with a checklist: misconception-named? one idea? Indian-context clean? ≤20 words? warm tone? confidence-building close? Reject and regenerate if it fails. Probably 15–30 ms extra per wrong answer. Biggest leverage, smallest code change.

**P1 — Feed the rationale LLM richer context.** At bank generation time, have Claude emit a `common_misconceptions` array per question (2–3 likely wrong-pick diagnoses). At runtime, pass: question, student pick, correct answer, the matched misconception entry, and the topic's `summary_json` teaching notes (already generated by the explanation-cards pipeline). The rationale becomes pick-specific and grounded in the topic's teaching, not pick-agnostic.

**P2 — Add partial credit for structured formats with per-item scoring.** `match_pairs`, `sort_buckets`, `swipe_classify`, `sequence` all have natural per-item partial credit. Score as `correct_items / total_items`, half-point round. Already permitted by principle #6.

**P3 — Upgrade the grader model, or explicitly justify not.** Run an A/B: `gpt-4o-mini` vs `claude-sonnet-4-6` on ~200 real wrong answers, score rationales across the 5 explanation-quality dimensions. Either switch, or document why latency wins and what quality we're trading off.

**P4 — Validate easy-english post-generation.** Cheap lint: regex for phrasal verbs, sentence length >12 words, comparison framings like "Western", "In India". Flag in dev, block in prod. Same lint runs on bank-gen `explanation_why` fields and runtime rationales.

**P5 — Replace `JSON.stringify` on `correct_answer_summary`** for complex formats. Per-format renderer on the frontend: "dog → animal, cat → pet" instead of raw JSON. Small change, big perceived-quality improvement.

**P6 — Always produce a rationale, including for blanks on structured formats.** A blank is a teachable moment, not a no-op.

**P7 (infra) — Implement the grading sweeper.** `grading_started_at` + 5-min sweeper that flips stuck attempts to `grading_failed`. Already documented as post-v1 (`docs/technical/practice-mode.md:184`).

---

## The core insight

The practice-mode evaluation was built as a **grading** system. The principles (`docs/principles/practice-mode.md:#4 — Evaluation as Learning`) say it is a **learning** system. The code follows the first framing: fast, deterministic, binary, terse. To make it follow the second framing, the correction explanation needs the same production-value treatment the initial exposition already gets. **P0–P2 close ~80% of that gap.**

---

## Key file references

**Grading service and prompts**

- `llm-backend/tutor/services/practice_grading_service.py:47` — `FF_CORRECT_THRESHOLD = 0.75`
- `llm-backend/tutor/services/practice_grading_service.py:106-115` — Deterministic pass enqueues LLM tasks only for wrong/blank structured answers
- `llm-backend/tutor/services/practice_grading_service.py:141-145` — Half-point rounding at persistence
- `llm-backend/tutor/services/practice_grading_service.py:162-226` — `_check_structured()` for all 11 formats
- `llm-backend/tutor/services/practice_grading_service.py:228-273` — `_summarize_correct()` (produces the object later `JSON.stringify`d on frontend)
- `llm-backend/tutor/services/practice_grading_service.py:318-357` — `_grade_free_form()` and `_explain_wrong_pick()`
- `llm-backend/tutor/services/practice_grading_service.py:383` — `"visual_explanation_code": None` (FR-43 placeholder)
- `llm-backend/tutor/prompts/practice_grading.py:17-42` — `FREE_FORM_GRADING_PROMPT`
- `llm-backend/tutor/prompts/practice_grading.py:45-66` — `PER_PICK_RATIONALE_PROMPT`

**Bank generation**

- `llm-backend/book_ingestion_v2/prompts/practice_bank_generation.txt:1-140` — Full prompt (language rules, format spec, `explanation_why` requirement)

**Frontend display**

- `llm-frontend/src/pages/PracticeResultsPage.tsx:9-14` — Polling config (5-min cap)
- `llm-frontend/src/pages/PracticeResultsPage.tsx:251-296` — `ReviewRow` component
- `llm-frontend/src/pages/PracticeResultsPage.tsx:291-293` — `JSON.stringify(correct_answer_summary)` rendering

**Explanation-cards benchmark**

- `llm-backend/book_ingestion_v2/services/explanation_generator_service.py:128-284` — Generate → review-refine → validate pipeline
- `llm-backend/book_ingestion_v2/prompts/explanation_generation_system.txt` — 9 principles + card type examples
- `llm-backend/book_ingestion_v2/prompts/explanation_review_refine_system.txt:17-26` — 9-point reviewer checklist
- `llm-backend/autoresearch/explanation_quality/README.md` — 5 evaluation dimensions

**Principles**

- `docs/principles/practice-mode.md` — Practice mode vision; principles #4 (eval as learning) and #6 (half-point granularity) referenced above
- `docs/principles/how-to-explain.md` — 13-principle teaching philosophy
- `docs/principles/easy-english.md` — Indian ESL language rules

**Known gaps**

- `docs/technical/practice-mode.md:184` — Silent thread death documented, sweeper deferred
- `llm-backend/tutor/services/practice_service.py:17-18` — Same, in code comment
