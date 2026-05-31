# Prompt-Review House Style

How every prompt in this repo should read. This is the taste the skill enforces, on top of the general best practices in `knowledge-base.md`.

> **North star:** simple language, straight to the point, no noise. Plain words, no buzzwords, no fancy phrasing. No repetition unless it earns its place. If a part brings value, keep it. If it's just noise, cut it. **But clarity always wins over shortness** — never trade away meaning to save words.

---

## The rules

1. **Plain words.** Common word over fancy word, always. (See the flag-and-replace list below.)
2. **Short sentences.** ~15 words average. Split anything over ~25.
3. **One idea per line.** One rule per line, too — so each can be read, checked, and edited on its own.
4. **Active voice.** "Summarize the report", not "the report should be summarized."
5. **Concrete over vague.** Replace "handle appropriately" / "make it engaging" with the exact behavior wanted.
6. **No emphasis theater.** No ALL-CAPS, no `!!!`, no "VERY IMPORTANT", no stacked "CRITICAL: YOU MUST". State the rule once, plainly. (On Claude 4.x, shouting backfires.)
7. **Each rule stated once.** Delete accidental restatements. Keep a second mention only for a deliberate end-of-prompt task restatement, or a constraint the model provably keeps breaking.
8. **Keep what carries information.** Examples, format specs, edge cases, scope words, and the "because…" behind a rule stay — even when they add words. See the protect list.

---

## Noise to cut (before → after)

| Noise | Before | After |
|---|---|---|
| Throat-clearing | "In this task, what I'd like you to do is go ahead and summarize the text below." | "Summarize the text below." |
| Politeness padding | "Could you please kindly help write a short summary?" | "Write a short summary." |
| Hedging a hard rule | "Try to maybe keep it under 100 words if you can." | "Keep it under 100 words." |
| Redundant restatement | "Be concise. Keep it brief and don't be verbose." | "Be concise." |
| Emphasis theater | "It is ABSOLUTELY CRITICAL!!! that you NEVER use jargon!!!" | "Do not use jargon." |
| Vague abstraction | "Make it engaging and high-quality." | "Use one concrete example per paragraph; end with a question." |
| Meta-narration | "The reason I'm asking this is because I think…" | (delete — unless the *why* changes behavior) |
| Over-explaining | "Remember a haiku is a Japanese poem. A poem is writing. Writing uses words…" | "Write a haiku (5-7-5 syllables)." |
| Filler connective | "It is important to note that the output should be JSON." | "Output JSON." |

**The cure for vagueness is specificity, which is sometimes more words.** "A few sentences, not too much more" → "Use 3 to 5 sentences." That's not bloat — that's signal.

---

## Buzzword / filler flag-and-replace

Flag these, propose the replacement, let Manish confirm. **Do not auto-replace** — a flagged word is occasionally load-bearing (e.g. "implement" vs "suggest" is a real distinction in an agent prompt).

| Flag | Replace with |
|---|---|
| utilize / leverage (verb) | use |
| facilitate | help, let, make possible |
| in order to | to |
| prior to | before |
| subsequent to / following | after |
| in the event that | if |
| due to the fact that | because |
| at this point in time | now |
| a number of | some, many |
| the majority of | most |
| approximately | about |
| commence / initiate | start |
| terminate | end, stop |
| endeavor | try |
| demonstrate | show |
| ascertain / determine | find out |
| with regard to / in respect of | about |
| robust | strong, reliable |
| streamline | simplify |
| foster | encourage, support |
| deep dive | analyze |
| it is important to note that / please be aware that / needless to say | (delete) |

---

## Protect — never auto-cut (drop-in checklist)

- [ ] Concrete examples, especially edge cases (target 3–5; keep them diverse)
- [ ] Output-format / length / schema / delimiter specs
- [ ] Distinct rules, branches, exceptions ("if X… otherwise Y") — never merge two into one
- [ ] Negative constraints (keep the info; reframe as positive where it reads better)
- [ ] WHY / rationale clauses the model can act on or generalize from
- [ ] Scope qualifiers — every / all / only / for each / not just the first
- [ ] Self-check instructions
- [ ] Anything that encodes a `docs/principles/` rule → flag, never silently cut

---

## From our own prompts

Grounding the style in real baatcheet prompts.

**Tighten-able (noise / wordiness):**
- `baatcheet_lesson_plan_generation_system.txt` — "Most topics have 2-3; some have only 1; a few have none" → "Most topics have 1–3 misconceptions."
- `baatcheet_dialogue_generation_system.txt` — "The student is Indian, English-as-second-language. Think in Hindi, read English second. No idioms, no phrasal verbs, no passive voice, no nested clauses." → drop the rhetorical "Think in Hindi, read English second"; keep the actionable list. *(But confirm — that line may encode an `easy-english` principle, in which case flag it instead of cutting.)*
- Interjection lists that print the full set *and* say "use ≥3 different ones" — keep the rule + 3–4 examples, not the entire menu twice.

**Load-bearing (do NOT cut — these define the pedagogy):**
- "A question and its answer NEVER go in the same card… the answer comes in the next `fall`/`observe`/`articulate` card." — structural rule; removing it collapses the teaching architecture.
- "Each misconception must have a complete trap-resolve cycle: trap-set → fall → (student-act OR funnel) → articulate." — the core minimum pedagogy.
- "Only frame the misconception as 'your way vs their way' if the guideline EXPLICITLY teaches the comparison. Otherwise frame it as the student getting the rule itself wrong." — an anti-pattern boundary; verbatim-protect.
- "Never use `{student_name}` on peer turns or inside `check_in.*`." — prevents audio-render errors; a precise constraint.

These are exactly the lines a careless shortener would "clean up." They are the product.

---

## How the skill uses this

**Flag → propose → confirm.** Never auto-edit. For every candidate change show: the current text, the proposed text, why, and the cosmetic/substantive tag. Cosmetic = plain-language/dedup that can't change model output. Substantive = anything that *could* change the output (touches a rule, example, spec, scope, or rationale). Substantive changes must clear the empirical eval before they ship.
