# LLM Prompts

All paths relative to `llm-backend/`.

## Tutoring Session

| Prompt | File | Role |
|--------|------|------|
| `MASTER_TUTOR_SYSTEM_PROMPT` | `tutor/prompts/master_tutor_prompts.py` | Core tutor agent: 15 rules (radical simplicity, false-OK detection, scaffolding, emotional attunement). Used every teaching turn. |
| `MASTER_TUTOR_TURN_PROMPT` | `tutor/prompts/master_tutor_prompts.py` | Per-turn context injection: session state, mastery estimates, misconceptions, student message. |
| `MASTER_TUTOR_WELCOME_PROMPT` | `tutor/prompts/master_tutor_prompts.py` | Session opening greeting with curiosity hook. Different framing based on whether explanation cards exist. |
| `MASTER_TUTOR_BRIDGE_PROMPT` | `tutor/prompts/master_tutor_prompts.py` | Card-to-interactive transition. 3 variants: understood, card_stuck, all_variants_failed. |
| `SIMPLIFY_CARD_PROMPT` | `tutor/prompts/master_tutor_prompts.py` | Re-explain when student clicks "I didn't understand". Supports 4 reasons + depth tracking. |
| `WELCOME_MESSAGE_PROMPT` | `tutor/prompts/orchestrator_prompts.py` | Orchestrator-level greeting (simpler alternative, used directly by orchestrator). |
| `CLARIFY_DOUBTS_SYSTEM_PROMPT` | `tutor/prompts/clarify_doubts_prompts.py` | Student-led Q&A mode system prompt (direct explanations, no Socratic method). |
| `CLARIFY_DOUBTS_TURN_PROMPT` | `tutor/prompts/clarify_doubts_prompts.py` | Per-turn directive in clarify_doubts mode. |
| Practice grading prompts | `tutor/prompts/practice_grading.py` | `FreeFormGradingOutput` (score + rationale) for free-form answers; `PickRationaleOutput` (rationale) for wrong structured picks. Invoked from `PracticeGradingService` via `ThreadPoolExecutor` — one call per wrong answer. |

## Safety, Language & Translation

| Prompt | File | Role |
|--------|------|------|
| `SAFETY_TEMPLATE` | `tutor/prompts/templates.py` | Content moderation gate on every student message (abuse, PII, prompt injection). Has allow-list pre-filter to bypass LLM for safe messages. |
| `get_response_language_instruction()` | `tutor/prompts/language_utils.py` | Language rules for response field (English, Hindi, Hinglish). |
| `get_audio_language_instruction()` | `tutor/prompts/language_utils.py` | Language rules for TTS audio_text field. Includes `_AUDIO_CORE_RULES` (no symbols, natural speech). |
| `translation.txt` | `tutor/prompts/translation.txt` | Translate Hinglish/Hindi student input to English. Used by orchestrator before processing. |

## Onboarding

| Prompt | File | Role |
|--------|------|------|
| `PERSONALITY_DERIVATION_PROMPT` | `auth/prompts/personality_prompts.py` | Extract student personality profile (11 JSON fields) from parent-provided enrichment data. Called once during onboarding, result injected into tutor system prompt as `tutor_brief`. |

## Book Ingestion Pipeline

All under `book_ingestion_v2/prompts/`:

| Prompt File | Role |
|-------------|------|
| `chapter_topic_planning.txt` | Plan 5-7 topic skeleton for a chapter (8 planning principles). |
| `chunk_topic_extraction.txt` | Extract topics from 3-page chunks with curriculum scope guidelines. |
| `chapter_consolidation.txt` | Finalize topic structure: merge overlapping, track plan deviations. |
| `curriculum_context_generation.txt` | Generate "what you learned before" context for each topic. |
| `topic_guidelines_merge.txt` | Merge per-chunk curriculum guidelines into one document. |
| `explanation_generation.txt` | Generate 5-10 explanation cards per topic (radical simplicity, ASCII diagrams). |
| `explanation_critique.txt` | Critique explanation cards against 12 pedagogy principles. |
| `explanation_refinement.txt` | Refine cards based on critique feedback (issues + suggestions). Part of generate-critique-refine pipeline. |
| `visual_decision_and_spec.txt` | Decide which cards need static/animated visuals + write specs. |
| `visual_code_generation.txt` | Generate Pixi.js v8 code for educational animations from specs. |
| `toc_extraction.txt` | Extract table of contents from OCR'd textbook pages. |
| `ocr_page_extraction.txt` | Vision-based textbook page OCR (educational content only, ignore decorative elements). |
| `practice_bank_generation.txt` | Generate the initial 30–40 question bank per topic (12 formats, 3 difficulty levels, 0–3 free-form). |
| `practice_bank_review_refine.txt` | Correctness review + refine pass over the generated bank. Drops invalid questions and tops up if count drops below 30. |

## OCR

| Prompt File | Role |
|-------------|------|
| `shared/prompts/ocr_default.txt` | Default fallback OCR prompt for OpenAI Vision API (full page interpretation). |

## Curriculum Planning

All under `shared/prompts/templates/`:

| Prompt File | Role |
|-------------|------|
| `study_plan_generator.txt` | Generate 3-5 step study plans with gamification and success criteria. |
| `study_plan_reviewer.txt` | Review plans against 5 criteria (engagement, clarity, coverage, etc.). |
| `study_plan_improve.txt` | Refine plans based on reviewer feedback. |
| `session_plan_generator.txt` | Design interactive post-card session steps (check, practice, extend). |

## Autoresearch Evaluators

All prompt files under `autoresearch/<module>/evaluation/prompts/`:

| Prompt File | Module | Role |
|-------------|--------|------|
| `evaluator.txt` | `tutor_teaching_quality` | Score tutoring conversations on 7 dimensions (responsiveness, explanation quality, emotional attunement, pacing, authenticity, card-to-session coherence, transition quality). |
| `card_phase_dimensions.txt` | `tutor_teaching_quality` | Additional scoring rubric for card-to-session coherence and transition quality (injected when cards present). |
| `evaluator.txt` | `simplification_quality` | Score "I didn't understand" re-explanations on 5 dimensions (reason adherence, content differentiation, simplicity, concept accuracy, presentation quality). |
| `simplicity_evaluator.txt` | `simplicity_quality` | ELI5 radical simplicity judge with message-level flags. |
| `evaluator.txt` | `explanation_quality` | Score pre-computed explanation cards on 5 dimensions (simplicity, concept clarity, examples, structure, effectiveness). |
| `experience_evaluator.txt` | `session_experience` | Judge session naturalness across 12 issue categories (forced transition, overwhelming, robotic structure, etc.). |
| `prompt_analyzer.txt` | `session_experience` | Root-cause analysis: trace naturalness issues back to specific prompt rules. Runs only when issues found. |
| `judge.txt` | `book_ingestion_quality` | Score ingestion quality on 3 dimensions (topic granularity, coverage depth, copyright safety). |

Note: `_build_system_prompt()` in `tutor_teaching_quality/evaluation/student_simulator.py` generates student persona prompts dynamically from persona data — not a static template.