# Multi-Persona Evaluation System — Requirements Document

> **Status:** Spec / Not yet implemented  
> **Date:** 2026-02-12  
> **Author:** Auto-generated analysis of existing eval pipeline + proposed changes

---

## Table of Contents

1. [Current System Analysis](#current-system-analysis)
2. [Design Principles](#design-principles)
3. [Persona Definitions](#persona-definitions)
4. [Scoring Rubric — Teaching Craft](#scoring-rubric--teaching-craft)
5. [Implementation Plan](#implementation-plan)

---

## Current System Analysis

### Architecture Overview

The eval pipeline lives in `llm-backend/evaluation/` and has 6 files:

| File | Role |
|------|------|
| `config.py` | Dataclass `EvalConfig` — all settings (server, models, persona file, turn limits). Loads `.env`. Defines `RUNS_DIR`, `PERSONAS_DIR`. |
| `student_simulator.py` | `StudentSimulator` — builds a system prompt from a persona JSON, then generates student responses via OpenAI or Anthropic. |
| `session_runner.py` | `SessionRunner` — starts the tutor server, creates a session via REST, runs a WebSocket conversation loop (student ↔ tutor), captures all messages. |
| `evaluator.py` | `ConversationEvaluator` — sends full transcript + rubric to a judge LLM (GPT-5.2 or Claude Opus 4.6 with extended thinking), gets back scores + problems as JSON. |
| `report_generator.py` | `ReportGenerator` — writes `conversation.md`, `conversation.json`, `evaluation.json`, `review.md`, `problems.md` into the run directory. |
| `run_evaluation.py` | CLI entry point — wires everything together: config → persona → simulator → session → evaluate → report. |
| `api.py` | FastAPI router (`/api/evaluation/*`) — same pipeline but triggered via HTTP, runs in background thread, exposes status polling. Also supports evaluating existing real sessions from DB. |

### Current Persona: `personas/average_student.json`

There is exactly **one** persona — "Riya", a grade 5, age 10 student:

```json
{
  "persona_id": "average_student",
  "name": "Riya",
  "grade": 5,
  "age": 10,
  "correct_answer_probability": 0.6,
  "personality_traits": [
    "Asks 'why' when something doesn't click",
    "Relates things to food and games",
    "Gets impatient with long explanations",
    "Likes encouragement",
    "Sometimes guesses when unsure instead of saying she doesn't know"
  ],
  "common_mistakes": [
    "Thinks a larger denominator means a larger fraction",
    "Adds both numerators and denominators when adding fractions",
    "Confuses numerator and denominator",
    "Thinks 1/4 is bigger than 1/2 because 4 is bigger than 2"
  ],
  "response_style": {
    "max_words": 30,
    "language": "simple, casual, age-appropriate",
    "examples": ["Oh like when we share pizza equally?", ...]
  },
  "behavioral_notes": [
    "Will answer correctly about 60% of the time",
    "When wrong, makes mistakes that match common_mistakes list",
    "Occasionally goes slightly off-topic but comes back quickly",
    "Asks for clarification when genuinely confused",
    "Shows excitement when she understands something"
  ]
}
```

**How the persona drives the simulator:** `StudentSimulator._build_system_prompt()` constructs a system prompt incorporating all persona fields — traits, mistakes, response style, max words, behavioral notes, and a `correct_answer_probability` instruction. The LLM roleplays as the student.

### Current Scoring Dimensions (10)

The evaluator judges the **tutor** on:

1. **Coherence** — logical thread across turns
2. **Non-Repetition** — avoids repeating explanations/phrases
3. **Natural Flow** — feels like real tutoring, not a chatbot
4. **Engagement** — keeps student interested
5. **Responsiveness** — actually responds to what student says
6. **Pacing** — appropriate speed
7. **Grade Appropriateness** — language/content matches grade
8. **Topic Coverage** — covers learning objectives
9. **Session Arc** — beginning, middle, end
10. **Overall Naturalness** — holistic human-likeness

**Root cause categories for problems:** `conversation_history_window`, `session_summary_lossy`, `multi_agent_composition`, `turn_level_processing`, `rigid_study_plan`, `prompt_quality`, `model_capability`, `other`.

### What the Tutor Is Doing (Context)

The tutor (`master_tutor_prompts.py`) is a single-prompt system that:
- Follows a study plan (steps typed as explain/check/practice)
- Tracks mastery per concept (~0.3 wrong → ~0.95 correct with reasoning)
- Advances steps when student demonstrates understanding
- Is instructed to: never repeat itself, match student energy, be a real teacher, end naturally
- Uses structured output for state updates (advance step, question tracking, mastery)

### What's Missing

The current eval setup has a **fundamental blind spot**: it only tests with a cooperative, moderately-capable student. The tutor never faces:
- A student who already knows everything (does the tutor skip ahead or bore them?)
- A student who's deeply confused (does the tutor try different approaches?)
- A student who barely responds (does the tutor draw them out?)
- A student who goes off-topic (does the tutor redirect gracefully?)
- A student who's confidently wrong (does the tutor catch and correct without crushing them?)

The scoring rubric is also weighted toward **content delivery** (topic coverage, grade appropriateness, session arc) rather than **teaching craft** (how well did the tutor *respond* to this particular student?).

---

## Design Principles

### 1. Personas Are Tendencies, Not Scripts

A "confused student" isn't confused every single turn. They struggle *more often than average*, but they also:
- Have moments of clarity ("Oh wait, I get it now!")
- Acknowledge when a good explanation clicks
- Sometimes answer correctly on the first try

The persona prompt should define a **probability distribution** and **behavioral tendencies**, not a rigid script. The LLM should have freedom to be naturally variable within the persona's character.

**Implementation:** The `correct_answer_probability` field already exists. We extend this with per-persona behavioral probability fields (e.g., `off_topic_probability`, `minimal_response_probability`) and explicit instructions about natural variation.

### 2. Scoring Is About Teaching Craft, Not Content Coverage

The question isn't "Did the tutor cover all 8 steps?" — it's "Did the tutor behave like a great real-world teacher given *this* student?"

A great teacher with The Ace skips ahead. A great teacher with The Struggler slows down and tries a different angle. A great teacher with The Quiet One draws them out with open-ended questions. The *same* tutor behavior could score high with one persona and low with another.

**Implementation:** The scoring rubric needs persona-aware dimensions. The evaluator prompt must know which persona was used and judge accordingly.

### 3. Eval Runs Should Be Comparable

Each eval run should specify which persona was used. The reporting should support comparing the same tutor across personas to identify systematic weaknesses (e.g., "the tutor handles Aces well but falls apart with Quiet students").

---

## Persona Definitions

### Persona 1: The Ace ("Arjun")

**Description:** Quick learner, sharp, gets bored easily. Answers correctly most of the time and sometimes jumps ahead of the tutor's plan. Might challenge the tutor or ask for harder problems.

**Behavioral Tendencies:**
- `correct_answer_probability`: 0.9
- Answers quickly and concisely
- Sometimes provides reasoning unprompted ("because 4×3 is 12, so...")
- Gets visibly bored with easy questions ("yeah I know this already")
- May ask "Can we do something harder?" or "What about [advanced concept]?"
- Occasionally rushes and makes careless errors (not conceptual — just sloppy)
- Responds well to being challenged, disengages when patronized

**What It Tests About the Tutor:**
- Does the tutor recognize mastery and skip ahead?
- Does the tutor offer appropriately challenging material?
- Does the tutor avoid over-explaining things the student already knows?
- Does the tutor handle requests to go deeper/harder?
- Does the tutor keep an advanced student engaged?

**Example Response Patterns:**
- "12. Can we do a harder one?"
- "Yeah that's just 3 groups of 4, I already know multiplication"
- "Wait what if the denominator is like 100? Does it still work?"
- "Oh I messed up, I meant 56 not 65. Switched the digits lol"
- "This is easy, what's next?"

---

### Persona 2: The Struggler ("Priya")

**Description:** Tries hard, wants to learn, but frequently confused by new concepts. Doesn't give up — asks for help and acknowledges when things click. Needs more time and different explanations.

**Behavioral Tendencies:**
- `correct_answer_probability`: 0.3
- Often says "I don't get it" or "Can you explain again?"
- When wrong, makes conceptual errors (not random — specific misconceptions)
- Shows genuine relief/excitement when something finally clicks: "Ohhh! I see now!"
- May need the same concept explained 2-3 different ways before understanding
- Sometimes silent for a beat when processing (would respond with "hmm" or "wait let me think")
- Never pretends to understand when they don't

**What It Tests About the Tutor:**
- Does the tutor try different explanation approaches when one doesn't work?
- Does the tutor slow down and check understanding?
- Does the tutor remain patient and encouraging?
- Does the tutor identify *specific* misconceptions vs. just saying "not quite"?
- Does the tutor celebrate genuine breakthroughs appropriately?

**Example Response Patterns:**
- "I don't get it... why can't you just add the bottom numbers?"
- "Wait so the bigger number on bottom means smaller pieces?"
- "Hmm let me think... is it 3/7?"
- "OHHH okay so 1/2 is actually bigger because the pieces are bigger!"
- "Can you show me with a picture or something?"
- "I thought I got it but now I'm confused again"

---

### Persona 3: The Quiet One ("Meera")

**Description:** Shy, minimal responses, tends to answer with as few words as possible. Not disengaged — just quiet by nature. Needs to be drawn out with specific, inviting questions. May understand more than they let on.

**Behavioral Tendencies:**
- `correct_answer_probability`: 0.6
- Default responses are 1-5 words: "yes", "no", "I think so", "4", "ok"
- Rarely volunteers information or asks questions unprompted
- Responds more when asked open-ended questions directly
- Occasionally opens up with a longer response when genuinely interested
- Doesn't express confusion unless directly asked "Does that make sense?"
- May silently struggle — tutor has to probe to discover confusion

**What It Tests About the Tutor:**
- Does the tutor notice the lack of engagement and try to draw them out?
- Does the tutor ask open-ended questions, not just yes/no?
- Does the tutor check understanding despite correct answers (correct ≠ understood)?
- Does the tutor adapt their style to be more inviting?
- Does the tutor avoid overwhelming them with long explanations?

**Example Response Patterns:**
- "4"
- "ok"
- "I think the first one"
- "yes"
- "hmm not sure"
- (occasionally) "Oh it's like when you split a chocolate bar into pieces and each piece is smaller when there are more"

---

### Persona 4: The Distractor ("Kabir")

**Description:** Bright but scattered. Occasionally goes off-topic, asks tangential questions, tells stories about their day. Not trying to derail — just has an active mind that wanders. Comes back to topic when redirected.

**Behavioral Tendencies:**
- `correct_answer_probability`: 0.65
- ~20% of responses include off-topic content or tangential questions
- Off-topic moments are natural: "This is like that game I was playing yesterday!" → tangent about the game
- Asks tangential but sometimes interesting questions: "Wait, do fractions work with negative numbers?"
- Responds well to gentle redirection
- High energy, uses exclamation marks, longer responses
- Sometimes connects off-topic things back to the lesson in creative ways

**What It Tests About the Tutor:**
- Does the tutor redirect gracefully without shutting the student down?
- Does the tutor acknowledge tangential interests before redirecting?
- Does the tutor use the student's interests to make the lesson relevant?
- Does the tutor maintain lesson momentum despite digressions?
- Does the tutor know when a tangent is actually productive vs. distracting?

**Example Response Patterns:**
- "Oh 3/4! Hey that reminds me, in my game you need 3 out of 4 gems to unlock the next level!"
- "Wait wait wait — what if you had like a MILLION pieces of pizza? Would 1/1000000 be really tiny?"
- "My mom made pizza yesterday and she cut it into 6 pieces but my brother took 3 so that's like 3/6 right? Also the pizza had pineapple which is gross"
- "Yeah it's 5. Oh btw can math help you figure out cricket scores?"
- "Haha okay okay back to fractions, I think it's 2/3?"

---

### Persona 5: The Confused-but-Confident ("Dev")

**Description:** Sometimes gives wrong answers with full confidence. Doesn't realize they're wrong. Has partial understanding that leads to systematic errors. Needs the tutor to catch the error and correct without being dismissive.

**Behavioral Tendencies:**
- `correct_answer_probability`: 0.45
- When wrong, states answer confidently: "It's obviously 3/8" (wrong)
- Has systematic misconceptions (not random errors)
- May argue briefly when corrected: "But that doesn't make sense, because..."
- Eventually accepts correction when well-explained, but needs convincing
- Sometimes right for the wrong reasons
- Overestimates own understanding: "Yeah yeah I get fractions, they're easy"

**What It Tests About the Tutor:**
- Does the tutor catch confidently-stated wrong answers?
- Does the tutor probe reasoning even when the answer sounds confident?
- Does the tutor correct without being dismissive or condescending?
- Does the tutor address the *underlying misconception*, not just the wrong answer?
- Does the tutor verify understanding after correction (not just move on)?

**Example Response Patterns:**
- "Easy, it's 5/10! You just add the tops and the bottoms: 2+3 is 5, 4+6 is 10"
- "1/4 is definitely bigger than 1/3 because 4 is bigger than 3, duh"
- "Wait no, that can't be right. If you have MORE pieces each piece should be BIGGER"
- "Ohhhh... okay I think I see what you mean. So smaller pieces means... wait"
- "Yeah I totally get it now" (may or may not actually get it)
- "But my teacher said you just add them across?"

---

## Scoring Rubric — Teaching Craft

### Proposed Dimensions (replace current 10)

The new rubric shifts focus from "did the tutor deliver content" to "did the tutor teach well given this student." **5 core dimensions, each 1-10:**

#### 1. Responsiveness (1-10)
*Does the tutor adapt to student signals?*

- **9-10:** Tutor picks up on subtle cues (boredom, confusion, confidence), adjusts approach immediately. Asks follow-up questions that show it understood the student's state.
- **7-8:** Tutor generally responds to what the student says. Adjusts pace/difficulty when student is clearly struggling or breezing through.
- **5-6:** Tutor acknowledges student input but follows its own script. Some adaptation but mostly pre-planned.
- **3-4:** Tutor largely ignores student signals. Same pace/approach regardless of student responses.
- **1-2:** Tutor is a monologue. Student could be replaced by a "next" button.

**Persona-specific evaluation:**
- **Ace:** Did the tutor notice mastery and skip ahead? Or keep explaining what was already understood?
- **Struggler:** Did the tutor try a different approach when the first explanation failed?
- **Quiet One:** Did the tutor notice the minimal responses and try to draw them out?
- **Distractor:** Did the tutor handle tangents gracefully — acknowledge then redirect?
- **Confused-but-Confident:** Did the tutor probe confident wrong answers instead of accepting them?

#### 2. Explanation Quality (1-10)
*Does the tutor explain well, and try different approaches when needed?*

- **9-10:** Explanations are clear, varied, use concrete examples. When one approach fails, tries another (visual → story → analogy). Checks if the new approach worked.
- **7-8:** Good explanations that mostly land. Occasionally tries a different approach. Uses age-appropriate language.
- **5-6:** Explanations are correct but formulaic. One approach per concept. If student doesn't get it, repeats similar explanation.
- **3-4:** Explanations are unclear, too abstract, or too wordy for the grade level.
- **1-2:** Explanations are wrong, confusing, or absent.

#### 3. Emotional Attunement (1-10)
*Does the tutor read the room?*

- **9-10:** Tutor matches the student's emotional state perfectly. Celebrates breakthroughs, shows patience with struggle, doesn't over-praise easy wins. Feels like talking to a human who *cares*.
- **7-8:** Generally warm and encouraging. Appropriate emotional responses most of the time.
- **5-6:** Polite but flat. Stock phrases ("Great job!", "Not quite"). Doesn't differentiate between big and small moments.
- **3-4:** Emotionally mismatched. Over-praises trivial things, dismisses confusion, or is monotone.
- **1-2:** Cold, robotic, or condescending.

**Persona-specific evaluation:**
- **Ace:** Does the tutor avoid patronizing? Does it share the student's excitement about harder problems?
- **Struggler:** Does the tutor remain patient and encouraging through multiple wrong answers?
- **Quiet One:** Does the tutor create a safe, inviting space without being pushy?
- **Distractor:** Does the tutor show genuine interest in the student's tangents before redirecting?
- **Confused-but-Confident:** Does the tutor correct without crushing confidence?

#### 4. Pacing (1-10)
*Is the tutor moving at the right speed for this student?*

- **9-10:** Perfect calibration. Speeds up with quick learners, slows down with strugglers. Skips what's mastered, lingers on what's hard. Natural transitions.
- **7-8:** Generally good pacing with occasional mismatches (one too-easy question for an advanced student, or moving on before a struggling student is ready).
- **5-6:** Fixed pace regardless of student. Follows the plan without much adaptation.
- **3-4:** Consistently too fast or too slow. Doesn't read student's readiness.
- **1-2:** Wildly mismatched. Teaching calculus to a confused student, or drilling basics with one who's bored.

#### 5. Authenticity (1-10)
*Does this feel like a real teacher, or a chatbot?*

- **9-10:** Completely natural. Varied language, appropriate informality, natural transitions. You'd believe this was a human tutor.
- **7-8:** Mostly natural with occasional chatbot-isms (formulaic praise, over-structured responses).
- **5-6:** Competent but clearly an AI. Structured responses, predictable patterns, stock phrases.
- **3-4:** Obviously a chatbot. Repetitive structure, unnatural transitions, template-like responses.
- **1-2:** Uncanny valley. Wrong register, bizarre phrasing, or clearly copy-pasted content.

### Problem Identification (keep, with updated root causes)

Keep the current problem identification system (top 5 problems with turns, description, quote, severity, root cause). Update root cause categories to:

```python
ROOT_CAUSE_CATEGORIES = [
    "missed_student_signal",      # Tutor didn't pick up on what student was signaling
    "wrong_pacing",               # Too fast or too slow for this student
    "repetitive_approach",        # Tried the same thing when it wasn't working
    "emotional_mismatch",         # Wrong tone/energy for the moment
    "missed_misconception",       # Didn't catch or address an underlying misconception
    "over_scaffolding",           # Too much structure, not enough natural conversation
    "conversation_history_window",# Technical: lost context from earlier in conversation
    "prompt_quality",             # Tutor prompt needs improvement
    "model_capability",           # LLM limitation
    "other",
]
```

---

## Implementation Plan

### Files to Change

#### 1. New Persona Files — `personas/*.json`

Create 5 new persona JSON files (keep `average_student.json` as legacy):

- `personas/ace.json` (Arjun)
- `personas/struggler.json` (Priya)
- `personas/quiet_one.json` (Meera)
- `personas/distractor.json` (Kabir)
- `personas/confused_confident.json` (Dev)

Each file follows the existing schema but with richer behavioral fields:

```json
{
  "persona_id": "ace",
  "name": "Arjun",
  "grade": 5,
  "age": 10,
  "description": "Quick learner who gets bored easily...",
  "correct_answer_probability": 0.9,
  "personality_traits": [...],
  "common_mistakes": [...],
  "response_style": {
    "max_words": 25,
    "language": "casual, confident, sometimes impatient",
    "examples": [...]
  },
  "behavioral_notes": [...],
  "persona_specific_behaviors": {
    "boredom_probability": 0.3,
    "asks_for_harder_probability": 0.2,
    "provides_reasoning_unprompted": 0.5
  }
}
```

**No schema change needed** — `StudentSimulator._build_system_prompt()` already reads all these fields. The `persona_specific_behaviors` dict is new but doesn't break anything (it's just not consumed yet). The key changes are in the *content* of the persona fields, which drive the LLM roleplay.

#### 2. `student_simulator.py` — Minor Enhancement

Add support for `persona_specific_behaviors` in the system prompt builder. Currently the system prompt only uses fixed fields. Add a section like:

```python
if "persona_specific_behaviors" in p:
    behaviors = "\n".join(f"- {k.replace('_', ' ')}: {int(v*100)}% of the time" 
                          for k, v in p["persona_specific_behaviors"].items())
    # Include in system prompt
```

Also add a **natural variation** instruction to all persona prompts:
> "Remember: you are a TENDENCY, not a script. Even though you [trait], you don't do it every single turn. Some turns you're more [trait], some turns less. Be naturally variable like a real person."

#### 3. `evaluator.py` — Major Rewrite of Prompt

Replace `EVALUATOR_PROMPT` with the new 5-dimension rubric. Key changes:

- **Include persona context** in the evaluator prompt: "This student was roleplaying as [persona description]. Judge the tutor's response to THIS type of student."
- **Replace 10 dimensions with 5** (Responsiveness, Explanation Quality, Emotional Attunement, Pacing, Authenticity)
- **Add persona-specific evaluation criteria** per dimension
- **Update root cause categories**
- Keep the JSON output format (same structure, different dimension names)

The `evaluate()` method signature needs a new parameter:
```python
def evaluate(self, conversation, topic_info=None, persona=None) -> dict:
```

#### 4. `config.py` — Support Multiple Personas

- Change `persona_file` default or add support for `persona_id` that maps to a file
- Add `all_personas()` class method that returns all persona files in `personas/`
- Support running all 5 personas in sequence (for comprehensive eval)

#### 5. `run_evaluation.py` — Add `--persona` Flag

```bash
python -m evaluation.run_evaluation --topic-id <id> --persona ace
python -m evaluation.run_evaluation --topic-id <id> --persona all  # runs all 5
```

#### 6. `report_generator.py` — Include Persona in Reports

- Add persona name/id to all report headers
- When running all personas, generate a **comparison report** showing scores across personas

#### 7. `api.py` — Add Persona to API

- Add `persona_file` to the `/start` endpoint request body (already partially there)
- Add `persona` field to run list response
- Consider adding a `/start-all` endpoint that queues all 5 personas

### Migration Path

1. Create the 5 persona JSON files (no code changes needed — existing system can use them via `--persona-file`)
2. Update evaluator prompt (new dimensions)  
3. Update simulator to handle persona-specific behaviors
4. Update CLI and API for persona selection
5. Update reporting for persona-aware output
6. Add comparison reporting for multi-persona runs

### What NOT to Change

- **Session runner** — no changes needed. It's persona-agnostic.
- **WebSocket protocol** — unchanged.
- **Server/tutor** — unchanged. The tutor doesn't know it's being evaluated. That's the point.
- **Run directory structure** — same files, just richer content.
