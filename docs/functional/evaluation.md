# Evaluation

Evaluation is an automated quality assurance system that tests how well the AI tutor teaches. It simulates tutoring sessions with AI-powered student personas and scores the tutor's performance.

---

## What Is Evaluation

Think of it as a teaching exam for the tutor. Instead of real students, the system creates simulated students with different personalities and learning styles. These simulated students have conversations with the tutor, and then an AI judge evaluates how well the tutor handled each one.

This lets admins measure and improve tutor quality without needing real students for testing.

---

## How It Works

1. **Choose a topic** — Select which topic the simulated student will study
2. **Choose a student persona** — Pick one (or all) of the available student types
3. **Run the simulation** — The simulated student has a full tutoring conversation with the tutor
4. **Judge the session** — An AI judge evaluates the tutor's teaching quality
5. **Review results** — View detailed scores, analysis, and identified problems

---

## Student Personas

Eight simulated student types test the tutor from different angles:

| Persona | Personality | Key Challenge for the Tutor |
|---------|------------|----------------------------|
| **Arjun** (Ace) | Quick learner, gets bored easily | Keep them challenged, skip ahead when appropriate |
| **Riya** (Average) | Attentive but sometimes confused | Balance explanation depth with pacing |
| **Dev** (Confused but Confident) | Gives wrong answers confidently | Probe confident mistakes, uncover misconceptions |
| **Kabir** (Distractor) | Bright but scattered, goes off-topic | Handle tangents gracefully, redirect gently |
| **Meera** (Quiet One) | Shy, minimal responses | Draw them out, don't overwhelm with questions |
| **Vikram** (Repetition Detector) | Notices repetitive patterns | Vary question formats, don't repeat approaches |
| **Aanya** (Simplicity Seeker) | Easily overwhelmed | Keep explanations simple and concrete |
| **Priya** (Struggler) | Hardworking but confused | Be patient, try different approaches |

---

## What Gets Measured

The tutor is scored across 5 teaching dimensions, each rated 1-10:

1. **Responsiveness** — Does the tutor adapt to the student's signals? (e.g., noticing boredom, confusion, or mastery)
2. **Explanation Quality** — Does the tutor explain well and try different approaches when needed?
3. **Emotional Attunement** — Does the tutor read the room emotionally?
4. **Pacing** — Is the tutor moving at the right speed for this student?
5. **Authenticity** — Does it feel like a real teacher or a chatbot?

Scores are persona-aware — the same tutor behavior is judged differently based on the student type. For example, moving quickly is good for Arjun (ace) but bad for Priya (struggler).

The judge also identifies the top 5 problems with severity levels (critical, major, minor) and root causes.

---

## Viewing Results

### Evaluation Dashboard

The admin evaluation page shows:

**List view:**
- All evaluation runs with timestamps and topic
- Color-coded score badge (green for 7+, yellow for 4-6, red for below 4)
- Mini score bars showing all 5 dimensions at a glance

**Detail view (click any run):**
- Full conversation transcript in chat bubble format
- Score bars for each dimension with detailed analysis
- Overall assessment summary
- Problems list with severity badges and root causes
- Configuration details (which models were used)

**Live status:**
- While an evaluation is running, a status banner shows real-time progress (current turn, total turns)
- Results auto-refresh when complete

### Running an Evaluation

From the admin evaluation page:
1. **Evaluate an existing session** — Pick a real student session from the database
2. **Run a new simulation** — Choose a guideline, persona, and max turns

Evaluations can also be run from the command line for batch testing across all personas.

---

## Key Details

- Running an evaluation with all 8 personas provides the most comprehensive quality picture
- Multiple runs per persona can be used to reduce scoring variance
- Each evaluation generates detailed reports including conversation transcripts, score breakdowns, and actionable problem descriptions
- The evaluator uses a different AI model than the tutor to ensure unbiased scoring
