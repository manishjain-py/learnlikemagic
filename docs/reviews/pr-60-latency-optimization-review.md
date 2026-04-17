# PR #60 Review: Reduce Tutor Response Latency from ~30-40s to ~10-15s

**Branch:** `claude/reduce-tutor-latency-aaIpk` → `main`
**Reviewed:** 2026-03-11
**Reviewer:** Claude Code

---

## Summary

The PR implements 7 latency optimizations across the tutor pipeline: parallel translation+safety, ASCII-based English detection, rule-based safety pre-filter, gpt-4o-mini for lightweight tasks, Anthropic prompt caching, streaming fix, and system prompt compression. The optimizations are well-motivated and target real bottlenecks.

---

## Functional Correctness Issues

### 1. CRITICAL — Safety pre-filter bypasses LLM for dangerous content outside the regex list

**File:** `llm-backend/tutor/agents/safety.py` — `_is_obviously_safe()`

The function returns `True` for any message that doesn't match `_UNSAFE_PATTERNS`. This is a **whitelist-by-absence** approach: if harmful content uses words not in the regex (e.g., sophisticated manipulation, self-harm language in Hindi transliterated to Roman, or novel slang), it passes through with zero LLM scrutiny.

The function's logic:
```python
if _UNSAFE_PATTERNS.search(stripped):
    return False
# No unsafe patterns found — safe for a tutoring context
return True  # <-- Everything not matched is assumed safe
```

This means only ~5% of messages (those matching regexes) ever reach the LLM safety check. The pre-filter is a **deny-list**, not a true fast-pass — any false negative is a complete safety bypass, not a degraded check.

**Recommendation:** Invert the logic to an **allow-list** approach: only short-circuit for messages that are *provably* safe (pure math expressions, very short messages, single-word common answers like "yes"/"no"/"ok"). All other messages should still go through the LLM.

---

### 2. HIGH — `call_fast` bypasses JSON schema validation

**File:** `llm-backend/shared/services/llm_service.py` — `call_fast()`

`call_fast` calls `_call_chat_completions` with `json_mode=True` but does **not** pass `json_schema` or `schema_name`. In `base_agent.py`, when `use_fast_model=True`, the execute path calls:

```python
self.llm.call_fast(prompt=prompt, json_mode=True)
```

But the regular path calls:
```python
self.llm.call(prompt=prompt, json_schema=schema, schema_name=output_model.__name__)
```

The fast path loses **structured output enforcement**. The LLM is asked for JSON but has no schema constraint, so `SafetyOutput` parsing relies entirely on the LLM producing the right field names with the right types. With `gpt-4o-mini`, this is a reliability regression — malformed JSON or missing fields will cause `validate_agent_output()` to throw `AgentOutputError`, which propagates as a turn-level error.

**Recommendation:** Pass the schema to `call_fast` or at minimum add a fallback default for `SafetyOutput` when parsing fails in the fast path.

---

### 3. HIGH — Post-completion paths skip safety check entirely

**File:** `llm-backend/tutor/orchestration/orchestrator.py` — `process_turn()`

In the new flow, the post-completion short-circuits are moved **above** the parallel safety+translation block:

```python
if session.is_complete and session.mode == "clarify_doubts":
    student_message = await self._translate_to_english(student_message)
    return await self._process_post_completion(session, student_message)
```

This means students in completed sessions can send **unsafe messages that are never checked**. In the original code, safety ran on every message regardless of session state. This is a behavioral regression — a student could send harmful content after session completion and it would pass through unchecked to `_process_post_completion`.

**Recommendation:** Run safety before or in parallel with translation for the post-completion paths too, or move the short-circuits back below the safety gate.

---

### 4. MEDIUM — `_is_likely_english` fails on Hinglish (Roman-script Hindi)

**File:** `llm-backend/tutor/orchestration/orchestrator.py` — `_is_likely_english()`

The heuristic:
```python
return ascii_letters / total_letters > 0.85
```

Hinglish (Hindi written in Roman/ASCII script, e.g., "mujhe samajh nahi aaya") is 100% ASCII but needs translation. This heuristic will skip translation for all Hinglish input, sending untranslated Hindi-English mix to the master tutor. Given this is an Indian education platform where Hinglish is a primary input mode, this is a significant functional regression.

**Recommendation:** Either remove this optimization or use a more robust language detection method (e.g., a lightweight language-id model or checking against a Hindi word list).

---

### 5. MEDIUM — Safety runs on original (untranslated) message, tutor gets translated message

**File:** `llm-backend/tutor/orchestration/orchestrator.py` — `process_turn()`

The PR deliberately passes the original message to safety and the translated message to the tutor:

```python
safety_context = AgentContext(..., student_message=student_message)  # original
translated_msg, safety_result = await asyncio.gather(
    self._translate_to_english(student_message),
    self.safety_agent.execute(safety_context),
)
```

The safety prompt template (`SAFETY_TEMPLATE`) was presumably designed and tested against English input since it previously always received translated text. Now it receives raw Hinglish/Hindi, which may reduce the LLM safety model's accuracy — especially with the downgrade to `gpt-4o-mini`. Additionally, the regex pre-filter `_UNSAFE_PATTERNS` is entirely English, so Hindi-script unsafe content bypasses both the regex AND may get weaker LLM classification.

---

## Regression Risks

### 6. MEDIUM — Anthropic `stream_sync` doesn't handle `tool_use` responses for structured output

**File:** `llm-backend/shared/services/anthropic_adapter.py` — `stream_sync()`

`stream_sync` yields raw `delta.text` or `delta.partial_json` chunks. But when `json_schema` is provided, `_build_kwargs` configures tool use. The streaming response for tool-use calls uses `input_json_delta` events — the code checks `delta.partial_json` which should match, but there's no final assembly of the complete tool response into the `{"output_text": ..., "parsed": ...}` format that `_parse_response` provides for non-streaming calls.

The caller (`base_agent.execute_stream`) concatenates all chunks and parses the result, which should work for the JSON content. But if the response includes both thinking blocks and tool-use blocks, the streaming code has no logic to separate them — it will interleave thinking text with JSON, breaking the parse.

**Recommendation:** Test streaming with `reasoning_effort != "none"` + `json_schema` to verify thinking blocks are properly filtered out.

---

### 7. MEDIUM — State mutated before safety check completes

**File:** `llm-backend/tutor/orchestration/orchestrator.py` — `process_turn()`

In the new flow:

```python
translated_msg, safety_result = await asyncio.gather(...)
student_message = translated_msg
session.increment_turn()          # <-- state mutation
session.add_message(...)          # <-- state mutation
# ... later ...
if not safety_result.is_safe:     # <-- check happens after mutations
```

In the original code, `increment_turn()` and `add_message()` happened inside the `try` block but before safety. So this is actually the same ordering. However, the PR description says safety and translation are parallelized for speed — if safety fails, the turn counter and message history have already been mutated. This was true before too, but worth noting: an unsafe message is now permanently in the conversation history with an incremented turn count.

---

### 8. LOW — System prompt compression may alter tutor behavior

**File:** `llm-backend/tutor/prompts/master_tutor_prompts.py`

The master tutor prompt was reduced from ~160 to ~60 lines. While the compressed version covers the same rules, important nuances have been removed:

- Detailed wrong-answer escalation strategy (3-step probing → hint → explain)
- Prerequisite gap detection protocol
- Explicit "never repeat yourself" guidance with concrete variation examples
- Formatting rules (bullet points, bold, short paragraphs)
- Visual explanation criteria details

These details guided the LLM's behavior in edge cases. The compressed prompt may produce subtly different tutoring quality, particularly for struggling students where the detailed scaffolding instructions mattered most. This should be validated with evaluation runs.

---

### 9. LOW — Prompt caching separator `---` could appear in user content

**File:** `llm-backend/shared/services/anthropic_adapter.py` — `_build_kwargs()`

The code splits on `"\n\n---\n\n"`:

```python
if separator in prompt:
    system_text, user_text = prompt.split(separator, 1)
```

If any prompt naturally contains `\n\n---\n\n` (e.g., a student message with markdown horizontal rules), it will be incorrectly split. The system prompt portion would contain user text, and the user message would be truncated. Using `split(separator, 1)` limits damage but the system prompt would still be wrong.

---

## Summary Table

| # | Severity | Issue | Type |
|---|----------|-------|------|
| 1 | CRITICAL | Safety pre-filter allows all unknown content through | Functional |
| 2 | HIGH | `call_fast` loses JSON schema validation | Functional |
| 3 | HIGH | Post-completion paths skip safety entirely | Functional |
| 4 | MEDIUM | ASCII heuristic misclassifies Hinglish as English | Functional |
| 5 | MEDIUM | Safety checks untranslated text with English-only regex | Functional |
| 6 | MEDIUM | Streaming may break with reasoning + tool_use | Regression |
| 7 | MEDIUM | State mutated before safety decision | Regression |
| 8 | LOW | Prompt compression may degrade tutoring quality | Regression |
| 9 | LOW | `---` separator collision risk | Regression |

---

## Verdict

The latency goals are sound but the PR introduces safety regressions (#1, #3, #5) that should be addressed before merging. Issues #2 and #4 are also likely to cause production errors. Recommend fixing #1–5 and running evaluation suites to validate #8 before merging.
