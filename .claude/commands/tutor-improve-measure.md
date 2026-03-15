# Tutor Improve — Phase 3: Measurement & Report

You are orchestrating Phase 3 (Measurement) of the master tutor improvement initiative. You gather context and then delegate the heavy work to a subagent.

---

## Input

**Input arguments format:** `initiative_id: <INIT-XXX-name>`

---

## Process

### Step 1: Read context

Read these files:
- `tutor-improvement/initiatives/<initiative_id>/phase1-analysis.md`
- `tutor-improvement/initiatives/<initiative_id>/phase2-implementation.md`

Extract:
- The original feedback text
- What was changed and why
- What improvement looks like
- What could regress

### Step 2: Verify server is running

```bash
curl -s http://localhost:8000/health
```

If not running, start it in the background:
```bash
cd llm-backend && source venv/bin/activate && python -m uvicorn main:app --host 0.0.0.0 --port 8000 &
```

Wait for health check to pass.

### Step 3: Find a topic for evaluation

```bash
cd llm-backend && source venv/bin/activate
python -c "
from autoresearch.tutor_teaching_quality.evaluation.config import EvalConfig
config = EvalConfig.__new__(EvalConfig)
# List available guideline/topic IDs
"
```

Pick a topic relevant to the feedback.

### Step 4: Spawn the measurement subagent

Use the **Agent tool** to spawn a subagent with the following prompt. Replace all `{{PLACEHOLDERS}}` with real values from Steps 1-3.

```
You are executing Phase 3 measurement for tutor improvement initiative {{INITIATIVE_ID}}.

## Context

**Original Feedback:** {{FEEDBACK_TEXT}}
**Changes Made:** {{CHANGES_SUMMARY}}
**Expected Improvement:** {{EXPECTED_IMPROVEMENT}}
**Regression Risks:** {{REGRESSION_RISKS}}

## Your Job

Drive 3 full tutoring conversations via the REST API, capture them, evaluate them, and produce a report.

## API Contract

**Create session:**
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "student": {"id": "eval-student", "grade": 3},
    "goal": {
      "chapter": "Evaluation",
      "syllabus": "CBSE Grade 3",
      "learning_objectives": ["Evaluate tutoring quality"],
      "guideline_id": "{{TOPIC_ID}}"
    }
  }'

Response: {"session_id": "...", "first_turn": {"message": "..."}}

**Send student reply (each turn):**
curl -X POST http://localhost:8000/sessions/<SESSION_ID>/step \
  -H "Content-Type: application/json" \
  -d '{"student_reply": "<STUDENT_MESSAGE>"}'

Response: {"next_turn": {"message": "..."}, "routing": "Advance|Remediate", ...}

## Conversation 1: Struggler Persona (10-12 turns)

Create a new session. You ARE a struggling student:
- Frequently give wrong answers, make common arithmetic/conceptual mistakes
- Get confused, say "I don't understand", need things repeated
- Respond hesitantly — short answers, sometimes just "ok" or "huh?"
- Get wrong ~60% of the time
- Sound like a real 8-year-old who finds this hard

After each tutor response, craft your next student reply in character, then call the step API.

Save the full transcript to: tutor-improvement/initiatives/{{INITIATIVE_ID}}/conversations/struggler-conversation.md

Format each conversation file as:
# Struggler Conversation — {{INITIATIVE_ID}}
**Date:** <today>
**Topic:** {{TOPIC_ID}}
**Turns:** <final count>
---
**Turn 1 — Tutor:**
> <tutor message>
**Turn 1 — Student:**
> <student reply>
(etc.)

## Conversation 2: Average Student Persona (10-12 turns)

Create a NEW session. You ARE an average student:
- Mix of right and wrong answers (~50/50)
- Engage normally, ask occasional clarifying questions
- Show typical grade-level understanding
- Sometimes give lazy one-word answers

Save to: tutor-improvement/initiatives/{{INITIATIVE_ID}}/conversations/average-conversation.md

## Conversation 3: Ace Persona (10-12 turns)

Create a NEW session. You ARE a strong student:
- Get most answers right (~80%), answer quickly
- Show deeper understanding, ask "why does it work this way?"
- Get bored with easy questions, want to move faster
- Occasionally make a careless mistake

Save to: tutor-improvement/initiatives/{{INITIATIVE_ID}}/conversations/ace-conversation.md

## After All 3 Conversations: Evaluate

Re-read all 3 conversation transcripts. Score each across 5 dimensions (1-10):

1. **Responsiveness** — Does the tutor adapt to student signals (confusion, boredom, confidence)?
2. **Explanation Quality** — Are explanations clear, varied, age-appropriate? Different approaches when one fails?
3. **Emotional Attunement** — Does the tutor match emotional state? Appropriate praise calibration?
4. **Pacing** — Right speed for this student? Speeds up for ace, slows down for struggler?
5. **Authenticity** — Does it feel like a real teacher or a chatbot?

**Critical evaluation:** Does the original feedback issue ("{{FEEDBACK_TEXT}}") still appear in any conversation? Quote specific evidence.

## Produce the Report

Create tutor-improvement/initiatives/{{INITIATIVE_ID}}/phase3-report.md using the template at tutor-improvement/templates/phase3-report.md. Fill in ALL sections with real data from the conversations.

## Generate HTML Report

Save as tutor-improvement/initiatives/{{INITIATIVE_ID}}/phase3-report.html — well-structured HTML with proper styling.

## Email the Report

BRANCH=$(git branch --show-current)
REPORT_FILE="$(pwd)/tutor-improvement/initiatives/{{INITIATIVE_ID}}/phase3-report.html"

osascript -e '
tell application "Mail"
    set newMessage to make new outgoing message with properties {subject:"Tutor Improvement Report — {{INITIATIVE_ID}} — <VERDICT>", content:"See attached HTML report.", visible:false}
    tell newMessage
        make new to recipient at end of to recipients with properties {address:"manishjain.py@gmail.com"}
        make new attachment with properties {file name:POSIX file "'"$REPORT_FILE"'"} at after the last paragraph
    end tell
    send newMessage
end tell'

Replace <VERDICT> with the actual verdict.

## AUTOMATION RULES
- Do NOT use EnterPlanMode or AskUserQuestion
- Do NOT pause for confirmation
- Execute everything end-to-end
- If an API call fails, retry up to 3 times
```

### Step 5: Update index

After the subagent completes, read `tutor-improvement/initiatives/<initiative_id>/phase3-report.md` and extract the verdict.

Update `tutor-improvement/index.md` — set this initiative's status to the final verdict with the overall score.
