# Tutor Workflow Pipeline - Documentation Changes Justification

**Date:** 2026-02-13
**Document Updated:** `docs/TUTOR_WORKFLOW_PIPELINE.md`

---

## Summary of Changes

| # | Change | Evidence |
|---|--------|----------|
| 1 | Architecture diagram: added SANITIZATION CHECK step | `orchestrator.py:180-181`, `_LEAK_PATTERNS` regex at line 241 |
| 2 | Agent table: model column → "GPT-5.2 / Claude" | `llm_service.py` dispatches to either provider |
| 3 | Provider support: listed all 3 values with Claude model names | `config.py` `tutor_model_label` property |
| 4 | Orchestrator flow: added step 0 (post-completion LLM) and step 4b (sanitization) | `orchestrator.py:105-115` and `180-181` |
| 5 | Teaching rules: 8 → 11 with accurate descriptions | `master_tutor_prompts.py` MASTER_TUTOR_SYSTEM_PROMPT |
| 6 | TutorTurnOutput mastery_signal: "low/medium/high" → "strong/adequate/needs_remediation" | `master_tutor.py:44-46` |
| 7 | API endpoints: added GET /, GET /config/models, GET /sessions, POST /evaluate-session | Multiple API files |
| 8 | Eval dimensions: 10 generic → 5 persona-aware | `evaluator.py:13-19` |
| 9 | Personas: 1 → 6 documented with table | `evaluation/personas/` directory |
| 10 | CLI args: documented all args including --runs-per-persona, --provider | `run_evaluation.py:257-265` |
| 11 | Key Design Decisions: added sanitization, dynamic post-completion, multi-run eval | New code patterns |
| 12 | LLM Calls: added POST-COMPLETION row, Claude model IDs | `orchestrator.py` `_generate_post_completion_response()` |

---

## Detailed Justification

### 1. Architecture diagram: Added SANITIZATION CHECK step
**Evidence:** `orchestrator.py` lines 240-245 define `_LEAK_PATTERNS` regex. Lines 274-281 define `_check_response_sanitization()`. Called at line 181 between master tutor output and state updates.
**Why:** The doc's architecture flow omitted this safety-net step.

### 2. Agent system table: Updated model column to "GPT-5.2 / Claude"
**Evidence:** Agents call `llm_service.call_gpt_5_2()` which routes to OpenAI or Anthropic based on `APP_LLM_PROVIDER`.
**Why:** Doc implied agents only use GPT-5.2. Both providers are equally supported.

### 3. Provider support: Listed all 3 provider values with model names
**Evidence:** `config.py` `tutor_model_label` maps: openai→"GPT-5.2", anthropic→"Claude Opus 4.6", anthropic-haiku→"Claude Haiku 4.5". Model IDs: `claude-opus-4-6`, `claude-haiku-4-5-20251001`.
**Why:** Doc vaguely said "OpenAI and Anthropic (Claude)" without specifying variants.

### 4. Orchestrator flow: Added post-completion and sanitization steps
**Evidence:**
- Post-completion: `orchestrator.py` lines 105-115 call `_generate_post_completion_response()` (lines 247-272) which makes an LLM call instead of returning a canned string.
- Sanitization: `_check_response_sanitization()` at lines 274-281, called at line 181.
**Why:** Two significant new flow steps missing from doc.

### 5. Teaching rules: Updated from 8 to 11
**Evidence:** `master_tutor_prompts.py` MASTER_TUTOR_SYSTEM_PROMPT:
- Rule 2 (lines 34-44): Enhanced with 4 adaptive pacing sub-bullets (escalate on 3+ correct, honor harder-material requests, simplify on 2+ wrong, match response length)
- Rule 4 (lines 50-57): Enhanced with CRITICAL verification guard (check specific values before praising)
- Rule 9 (lines 77-87): Rewritten — must acknowledge last message, reflect on specific learnings, personalized sign-off, never canned
- Rule 10 (lines 89-93): NEW — never leak internal/diagnostic language into student-facing response
- Rule 11 (lines 95-99): NEW — check for misconceptions before ending session
**Why:** Doc listed 8 vague rule titles. Actual prompt has 11 detailed rules, critical for understanding tutor behavior.

### 6. TutorTurnOutput mastery_signal: Corrected values
**Evidence:** `master_tutor.py` line 44-46: `mastery_signal: Optional[str] = Field(description="Mastery signal: strong, adequate, or needs_remediation")`
**Why:** Doc incorrectly listed "low/medium/high".

### 7. API endpoints: Added 4 missing endpoints
**Evidence:**
- `GET /` — root health check in main app
- `GET /config/models` — returns tutor/ingestion provider labels, referenced by frontend `api.ts` `getModelConfig()`
- `GET /sessions` — list all sessions in `tutor/api/sessions.py`
- `POST /api/evaluation/evaluate-session` — evaluate existing DB session in `evaluation/api.py`
**Why:** Endpoints existed in code but were undocumented.

### 8. Evaluation dimensions: 10 → 5 persona-aware
**Evidence:** `evaluator.py` lines 13-19 defines exactly 5: responsiveness, explanation_quality, emotional_attunement, pacing, authenticity. Evaluator prompt includes persona context for persona-aware judging.
**Why:** Evaluator was rewritten. Old 10 dimensions (coherence, non-repetition, etc.) no longer exist in code.

### 9. Student personas: 1 → 6
**Evidence:** `ls evaluation/personas/` shows 6 files: ace.json, average_student.json, confused_confident.json, distractor.json, quiet_one.json, struggler.json. `EvalConfig.all_personas()` classmethod loads all.
**Why:** Doc only mentioned `average_student.json`.

### 10. CLI args: Documented all including new ones
**Evidence:** `run_evaluation.py` argparse (lines 257-265):
- `--runs-per-persona` (int, default 1) — multi-run noise reduction
- `--provider` (str) — override eval LLM provider
- `--persona` supports 'all' for multi-persona runs
**Why:** New capabilities undocumented.

### 11. Key Design Decisions: Added 3 new entries
**Evidence:**
- Response sanitization: `_LEAK_PATTERNS` regex + `_check_response_sanitization()` in orchestrator.py
- Dynamic post-completion: `_generate_post_completion_response()` replaces hardcoded string
- Multi-run eval: `--runs-per-persona` loop + comparison report aggregation in run_evaluation.py
**Why:** These are meaningful architectural decisions.

### 12. LLM Calls Summary: Added POST-COMPLETION, Claude model IDs
**Evidence:** `orchestrator.py` `_generate_post_completion_response()` calls `self.llm.call_gpt_5_2(prompt=..., reasoning_effort="none", json_mode=False)`. Claude models: `claude-opus-4-6`, `claude-haiku-4-5-20251001`.
**Why:** New LLM call pattern + model specifics were undocumented.

---

## Previous Changes (preserved from earlier updates)
- 2025-12-30: Backend path corrections after folder reorganization
- 2025-12-28: Pre-Built Study Plans section, Phase 2 flow with plan loading
