# Prompt-Review Knowledge Base — Best Practices

The expert reference the `/prompt-review` skill reads before judging any prompt. It answers one question for every line: **does this earn its place, or is it noise?**

> **Refresh:** this file is built from research, not frozen. To update it, re-run the web research on current prompt-engineering best practices (Anthropic docs first, since these prompts run through Claude) and rewrite this file. Sources are listed at the bottom.

---

## The one rule

**Aim for the smallest set of high-signal tokens that get the desired output.** Not the shortest prompt — the *densest*. Anthropic's own framing: include enough detail to ensure adherence while eliminating redundancy. Cutting redundancy is good. Cutting information is not.

**Clarity beats brevity.** A shorter prompt that's more ambiguous is a worse prompt. The cure for vague writing is often *more* words (a precise spec), not fewer.

**The golden test (run it on every proposed cut):** *"If a colleague with no context read the prompt without this line, would they produce a different result?"* If yes → the line stays. If no → it's a candidate to cut.

**Why noise actually hurts (the case FOR cutting):** a model has a finite attention budget; every token spends it. As context grows, recall degrades ("context rot"). Genuine redundancy competes with real instructions. So tightening is real work — but only when it removes low-signal tokens, never high-signal ones.

---

## Part A — What a strong prompt does (Claude 4.x)

These prompts run through Claude. The latest Claude models (Opus 4.8 / 4.7 / 4.6, Sonnet 4.6, Haiku 4.5) follow instructions **literally** and are highly steerable. That changes what's good and what's noise.

### A1. Structure
- **Separate content types** — instructions, context, examples, input data — with XML tags (`<instructions>`, `<context>`, `<example>`, `<input>`) or Markdown headers. Tags help the model tell an instruction from the data it operates on. *Stripping structure to "tidy up" is a real regression.*
- **No magic tag names** — any descriptive name works; just be **consistent** and refer back to tags by name. Don't rename or collapse tags inconsistently mid-prompt.
- **Role in the system prompt.** One sentence ("You are a strict JSON formatter") focuses tone and behavior. Role lines are short and high-leverage — keep them.
- **Ordering:** context/instructions as the spine; examples after instructions; output-format spec near the end.
- **Long context (~20k+ tokens):** put the big document/data at the **top**, query and instructions at the **bottom**. Queries at the end can lift quality up to ~30% on multi-doc inputs. This is about position, not length.

### A2. Clarity & specificity
- **Be explicit.** Treat Claude as a brilliant new hire with zero context on your norms. The more precisely you say what you want, the better the result.
- **Positive over negative.** "Write in flowing prose paragraphs" beats "Don't use markdown." Convert load-bearing "don'ts" into "do this instead" — keep the information, improve the framing.
- **State the WHY.** A rule with its reason generalizes to cases you didn't list. *"Never use ellipses — the text is read aloud by a TTS engine that can't pronounce them"* outperforms a bare *"Never use ellipses."* **A naive shortener deletes the "because…" clause as filler. That clause is load-bearing — protect it.**
- **Specify output format** — length, structure, schema, delimiters. Vague prompts get baseline output; explicit "modifier" sentences ("go beyond the basics", "include as many relevant features as possible") lift quality and are not redundant.
- **Set scope.** Literal models don't silently generalize. If a rule applies broadly, say so: *"apply to every section, not just the first."* Cutting `every / all / for each / only / not just X` changes behavior.

### A3. Examples (the highest-leverage part — protect it)
- A few well-crafted examples steer format, tone, and structure more reliably than prose instructions. They are often the single most valuable component of a prompt.
- **Target 3–5.** Fewer under-specifies the pattern.
- Good examples are **Relevant** (mirror the real use case), **Diverse** (cover edge cases; vary enough that the model doesn't latch onto an incidental shared trait), and **Structured** (each wrapped in `<example>`).
- Examples must agree with the instructions — the model follows the *examples* when they conflict with prose.
- **Cutting examples to save tokens is the #1 way a "shorten this" pass silently degrades quality. Examples are the LAST thing to cut, not the first.**

### A4. Reasoning
- Latest models use **adaptive thinking** (the `effort` parameter), not hand-written step plans. *"Think thoroughly"* usually beats a prescriptive CoT script — over-specifying the reasoning path can cap the model below its own ability. An over-engineered step list is safe to simplify.
- **Self-check earns its tokens.** *"Before you finish, verify your answer against [criteria]"* reliably catches errors. Keep it.
- **Word gotcha:** with thinking off, Opus 4.5 is sensitive to the literal word "think" — prefer "consider", "evaluate", "reason through".

### A5. Claude 4.x behavior
- **Literal following.** It does what you say and doesn't infer what you didn't. Vague/partial-scope instructions older models "figured out" may now be taken narrowly.
- **Don't shout.** `CRITICAL: You MUST…`, ALL-CAPS, `!!!`, and stacked emphasis cause *over*-triggering on current models. Plain `Use this tool when…` is better. **This is a case where removing emphasis genuinely helps — flag caps-lock imperatives for softening.**
- **Imperatives drive action.** "Change this function…" acts; "Can you suggest…" only suggests. Match the verb to the intent.
- **Prefill is deprecated on 4.6+** (a prefilled final assistant turn 400s). Use structured outputs / tool enums / a direct "respond without preamble" instruction instead. Flag any prompt still relying on it.
- **Defaults to know:** latest models default to LaTeX for math and calibrate verbosity to perceived complexity. If you need plain text or a fixed verbosity, say so explicitly.

---

## Part B — Cutting noise (concision + plain language)

See `house-style.md` for the full noise→fix table and the buzzword flag-and-replace list. In short:

- **Noise to cut:** throat-clearing, politeness padding, hedging on hard rules, redundant restatement, emphasis theater (CAPS/!!!), vague abstractions with no operational meaning, meta-narration, over-explaining the obvious, filler connectives ("it is important to note that").
- **Plain language:** common word over fancy word; short sentences (~15 words avg); one idea per line; active voice; concrete over abstract.
- **Match the prompt's register to the output you want** — heavy markdown/bullets in the prompt nudge heavy markdown in the output. Don't bullet-point a prose-output prompt while "tidying."

---

## Part C — What must NOT be cut (load-bearing)

Every item here is something an aggressive shortener wrongly deletes. **Never auto-cut:**

1. **Concrete examples** — especially edge-case ones (keep 3–5; preserve diversity).
2. **Distinct rules, branches, exceptions** ("if X… otherwise Y"). Never collapse two rules into one — on literal models, a sloppy merge creates a contradiction the model follows to the letter.
3. **Output-format / length / schema / delimiter specs.**
4. **Negative constraints** — keep the information; convert to positive framing where it reads better.
5. **WHY / rationale clauses** the model can act on or generalize from.
6. **Scope qualifiers** — `every / all / only / for each / not just the first`.
7. **Disambiguating modifiers** — "go beyond the basics", "fully-featured" — the longer version is often the better one.
8. **Self-verification instructions.**
9. **Anything that encodes an app principle** (see `docs/principles/`). Even if it reads like filler, it's a founder decision — flag, never silently cut.

**Borderline → simplify, don't delete.** If a line carries real information in a wordy/fancy/negative way, rewrite it (plain word, active voice, positive framing). Deletion is for pure noise only.

---

## Part D — Repetition: help vs noise

**Repetition that helps (keep):**
- End-of-prompt restatement of the core task in a long-context prompt (positional reinforcement, ~30% quality lever).
- A constraint the model *empirically keeps violating* — restating it is a tested fix. (Should be marked as such, not guessed.)

**Repetition that hurts (flag):**
- The same rule stated 2–3 times in nearby lines with no positional reason.
- Stacked emphasis for "safety."

Default: **each rule appears once, stated precisely.** Allow a second occurrence only for the two "helps" cases above.

---

## Part E — Anti-patterns (lint list)

Treat each as a check:

1. Vague instruction, no format/scope spec.
2. Negative-only framing (a wall of "don't / NEVER").
3. Bare rule with no rationale where the rationale would generalize it.
4. ALL-CAPS / "CRITICAL: YOU MUST" stacking → soften.
5. Blanket tool defaults ("if in doubt, use X") → make conditional.
6. Under-varied few-shot examples (model learns a spurious shared trait).
7. Fewer than 3 examples where a pattern needs teaching.
8. Cutting examples to save tokens.
9. Long document buried below the query in a long-context prompt.
10. Relying on assistant prefill on the final turn (4.6+).
11. Mixed content with no XML/section structure.
12. Over-prescriptive CoT script that caps the model.
13. Prompt formatting mismatched to desired output register.
14. Inconsistent tag names within one prompt.
15. Silently assuming defaults (LaTeX, verbosity) without overriding when you need otherwise.

---

## Part F — Pitfalls of shortening (why this skill measures)

- **Information loss & broken structure.** Token-removal compression drops grammar and breaks phrases, raising ungrounded/hallucinated output.
- **Non-linear cliff.** *Moderate* trimming can even help; *excessive* trimming spikes failure. Don't optimize for token count.
- **Silent rule-merging → contradictions** that literal models obey to the letter.
- **Position sensitivity ("lost in the middle").** Moving an instruction during a rewrite can bury it where the model attends least. Preserve task-at-top / instruction-at-end in long prompts.
- **You can't eyeball quality.** Every provider says prompt work is empirical. **A shortened prompt is a hypothesis, not an improvement, until it's tested on real inputs.** That's why this skill proves changes before keeping them.

---

## The line test (apply to every line)

**Keep — load-bearing — if it does any of these:**
1. Changes the output if deleted (format, length, content, scope, behavior).
2. Disambiguates — closes a door the model could otherwise walk through wrongly.
3. Is an example, or a format/schema spec.
4. Is a distinct rule, branch, or exception not stated elsewhere.
5. Explains a WHY the model can act on or generalize from.
6. Sets scope.
7. Encodes an app principle.

**Cut or simplify — noise — only if ALL of these hold:**
1. Deleting it changes no output (mental A/B: same result with and without).
2. It restates something already said (and isn't the deliberate end-of-prompt restatement).
3. It's politeness, hedging, emphasis theater, throat-clearing, meta-narration, or a vague adjective with no operational meaning.
4. It teaches the model something it plainly already knows.

Mantra: **if a no-context colleague would behave differently without the line, it stays.**

---

## Sources

- Anthropic — [Prompting best practices (unified Claude 4.x reference)](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices), [Be clear, direct, and detailed](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/be-clear-and-direct), [Use examples](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/multishot-prompting), [Long-context tips](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/long-context-tips), [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- OpenAI — [Best practices for prompt engineering](https://help.openai.com/en/articles/6654000-best-practices-for-prompt-engineering-with-the-openai-api)
- Google — [Gemini prompting strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies)
- Plain language — [plainlanguage.gov](https://www.plainlanguage.gov/guidelines/words/use-simple-words-phrases/), [GOV.UK content design](https://www.gov.uk/guidance/content-design/writing-for-gov-uk)
- Compression risk — [arXiv 2503.19114](https://arxiv.org/pdf/2503.19114), [arXiv 2504.11004](https://arxiv.org/pdf/2504.11004)
