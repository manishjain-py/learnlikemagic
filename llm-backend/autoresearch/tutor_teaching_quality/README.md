# Tutor Teaching Quality

Optimizes the **interactive tutoring experience** — how the master tutor teaches during live sessions.

## What It Improves

Prompts and logic in: `master_tutor_prompts.py`, `master_tutor.py`, `session_service.py`

## How It Works

1. Student simulator (LLM as "Riya", Grade 5, ~45% correct answers) chats with tutor via REST+WebSocket (20 turns max)
2. LLM judge scores the session across 7 dimensions
3. Agent tweaks prompts, re-runs, keeps improvements

## Evaluation Dimensions (1-10 each, averaged)

| Dimension | What It Measures |
|-----------|-----------------|
| Responsiveness | Adapts to vague "ok"s, random guesses, confidence drops |
| Explanation Quality | Simple language, concrete examples, tries different approaches |
| Emotional Attunement | Calibrated encouragement, patience, genuine reactions |
| Pacing | Slows for struggling students, doesn't rush |
| Authenticity | Feels like a real teacher, not a script |
| Card-to-Session Coherence | Builds on pre-computed explanation cards |
| Transition Quality | Smooth handoff from reading cards to interactive teaching |

## Key Details

- **Primary persona:** average_student (Riya) — also has ace, struggler, quiet_one, distractor, confused_confident, simplicity_seeker, repetition_detector
- **Throughput:** ~8-10 experiments/hour (~5-8 min per evaluation)
- **Results:** `results.tsv`
