# Evaluation

Evaluation is an automated quality assurance system that tests how well the AI tutor teaches. It simulates tutoring sessions with AI-powered student personas and scores the tutor's performance.

---

## What Is Evaluation

Think of it as a teaching exam for the tutor. Instead of real students, the system creates simulated students with different personalities and learning styles. These simulated students have conversations with the tutor, and then an AI judge evaluates how well the tutor handled each one.

This lets admins measure and improve tutor quality without needing real students for testing.

---

## How It Works

1. **Choose a topic** -- Select which topic the simulated student will study
2. **Choose a student persona** -- Pick one (or all) of the available student types
3. **Run the simulation** -- The simulated student has a full tutoring conversation with the tutor
4. **Judge the session** -- An AI judge evaluates the tutor's teaching quality
5. **Review results** -- View detailed scores, analysis, and identified problems

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

Each persona has a defined probability of answering correctly, ranging from 30% (Priya) to 90% (Arjun). The persona also influences how the simulated student responds -- Meera gives minimal 1-5 word answers, Kabir writes longer tangential responses, and Dev confidently states wrong answers.

---

## What Gets Measured

The tutor is scored across 5 teaching dimensions, each rated 1-10:

1. **Responsiveness** -- Does the tutor adapt to the student's signals? (e.g., noticing boredom, confusion, or mastery)
2. **Explanation Quality** -- Does the tutor explain well and try different approaches when needed?
3. **Emotional Attunement** -- Does the tutor read the room emotionally?
4. **Pacing** -- Is the tutor moving at the right speed for this student?
5. **Authenticity** -- Does it feel like a real teacher or a chatbot?

Scores are persona-aware -- the same tutor behavior is judged differently based on the student type. For example, moving quickly is good for Arjun (ace) but bad for Priya (struggler).

The judge also identifies the top 5 problems with severity levels (critical, major, minor) and root causes.

---

## Two Evaluation Modes

### Evaluate an Existing Session

Pick any real tutoring session from the database. The system takes the existing conversation and runs it through the AI judge for scoring. This is useful for evaluating how the tutor performed with an actual student.

When selecting a session, you see the topic name, message count, and date for each available session.

### Run a New Simulation

Create a fresh simulated session. Choose an approved guideline from the dropdown, set the maximum number of conversation turns (5-40), and start. The system creates a simulated student, runs a full conversation with the tutor, then judges the result.

The persona used for simulated sessions defaults to the average student (Riya). To test with other personas or run all personas at once, use the command line.

---

## Viewing Results

### Evaluation Dashboard

The admin evaluation page shows:

**List view:**
- All evaluation runs with timestamps, topic, and message count
- Each run tagged as "Simulated" or "Session" to indicate its source
- Color-coded score badge (green for 7+, yellow for 4-6, red for below 4)
- Mini score bars showing all dimensions at a glance

**Detail view (click any run):**
- Full conversation transcript in chat bubble format (tutor messages left, student messages right)
- Model badges showing which tutor and evaluator models were used
- Score bars for each dimension with expandable detailed analysis
- Overall assessment summary
- Problems list with severity badges, root cause labels, turn numbers, and quoted evidence
- When no evaluation results exist yet, a placeholder message is shown

**Live status:**
- While an evaluation is running, a status banner shows real-time progress (current turn, total turns)
- The banner color-codes: blue for in-progress, green for complete, red for failed
- Failed evaluations show the error message in the banner
- Results auto-refresh when complete; the banner can be dismissed

### Re-evaluating a Run

An existing conversation can be re-evaluated without re-running the simulation. This is useful when the evaluator model is changed -- re-run the judge on the same conversation to compare scoring across different models.

---

## Key Details

- Running an evaluation with all 8 personas provides the most comprehensive quality picture
- Multiple runs per persona can be used to reduce scoring variance
- Each evaluation generates detailed reports including conversation transcripts, score breakdowns, and actionable problem descriptions
- The evaluator uses a different AI model than the tutor to ensure unbiased scoring
- Evaluator and simulator models can be configured independently through the LLM configuration page
