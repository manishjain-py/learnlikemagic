# Phase 2: Implementation — INIT-001-streaming-response

**Date:** 2026-03-07
**Branch:** `tutor-improve/INIT-001-streaming-response`

---

## Files Changed

| File | Change Summary |
|------|---------------|
| `shared/services/llm_service.py` | Added `call_stream()` entry point + `_stream_responses_api()` and `_stream_chat_completions()` streaming generators |
| `tutor/agents/base_agent.py` | Added `ResponseFieldExtractor` utility class + `execute_stream()` async generator on BaseAgent |
| `tutor/orchestration/orchestrator.py` | Added `process_turn_stream()` async generator + `_process_post_completion()` helper |
| `tutor/models/messages.py` | Added `"token"` to ServerMessage type literal + `create_token_message()` factory |
| `tutor/api/sessions.py` | Updated WebSocket chat handler to use `process_turn_stream()` and send `token` messages |
| `llm-frontend/src/api.ts` | Added `TutorWebSocket` class with connection management, message routing, and pending message queue |
| `llm-frontend/src/pages/ChatSession.tsx` | Added WebSocket connection, `streamingText` state, streaming token rendering, REST fallback |

## Diffs Summary

### Backend streaming infrastructure (`llm_service.py`)
- `call_stream()` routes to provider-specific streaming methods (OpenAI) or falls back to non-streaming for Anthropic/Gemini (yields full response as single chunk)
- `_stream_responses_api()` uses OpenAI Responses API with `stream=True`, yields `response.output_text.delta` events
- `_stream_chat_completions()` uses Chat Completions API with `stream=True`, yields `delta.content` chunks
- Includes logging for stream start/complete with timing

### Response field extraction (`base_agent.py`)
- `ResponseFieldExtractor` — a streaming JSON parser that detects the `"response"` key in structured JSON output and extracts its string value character-by-character
- Handles JSON escape sequences (`\n`, `\t`, `\"`, `\\`, etc.)
- State machine: `scanning` -> `found_key` -> `in_value` -> `done`
- Only processes the first `"response"` key, ignoring subsequent occurrences in nested values

### Streaming agent execution (`base_agent.py`)
- `execute_stream()` — async generator on BaseAgent that:
  1. Runs `call_stream()` in a background thread via `run_in_executor`
  2. Feeds chunks through `ResponseFieldExtractor` to extract student-facing text
  3. Yields `("token", text)` tuples via `asyncio.Queue` bridge
  4. After stream completes, parses full JSON and validates against Pydantic schema
  5. Yields `("result", validated_output)` as final message

### Streaming orchestrator (`orchestrator.py`)
- `process_turn_stream()` — async generator that mirrors `process_turn()` but uses streaming for the master tutor call
- Non-streamable paths (exam mode, clarify_doubts, post-completion, unsafe messages) fall back to non-streaming and yield a single `("result", TurnResult)`
- Extracted `_process_post_completion()` helper to avoid duplication

### WebSocket protocol (`messages.py` + `sessions.py`)
- Added `"token"` to the `ServerMessage.type` literal union
- Added `create_token_message(text)` factory
- WS handler now iterates `process_turn_stream()`, sending `token` messages incrementally before the final `assistant` message

### Frontend WebSocket integration (`api.ts` + `ChatSession.tsx`)
- `TutorWebSocket` class manages WebSocket lifecycle with callbacks for `token`, `assistant`, `state_update`, `typing`, `error`, and `close` events
- Handles pending messages queued before connection is established
- ChatSession connects WebSocket on mount for non-exam modes
- New `streamingText` state accumulates token chunks and displays them in a teacher message bubble
- When `assistant` message arrives, streaming text is cleared and finalized as a real message
- Falls back to REST `submitStep` if WebSocket is not connected (exam mode, WS failure)

## Code Review Findings

1. **No prompt changes** — The master tutor prompt is untouched. Streaming is implemented purely at the transport layer.
2. **Backward compatible** — REST endpoints and `process_turn()` are unchanged. The evaluation pipeline continues to work.
3. **Anthropic/Gemini fallback** — Non-OpenAI providers yield the full response as a single chunk (no real streaming but no breakage).
4. **Thread safety** — Background thread communicates with async event loop via `asyncio.Queue` and `call_soon_threadsafe`, avoiding race conditions.
5. **State updates unchanged** — State updates are applied after the full JSON is parsed, same as before. Streaming only affects when the student sees text, not when state is modified.

## Test Results

```
Unit tests: 166 passed (all pre-existing failures unchanged)
Pre-existing failures (not caused by this change):
  - test_base_agent.py: Mock uses call_gpt_5_2 but code uses call()
  - test_orchestrator.py: Missing required field in test mock
  - test_event_repository.py: SQLite JSONB incompatibility
```

## Deviations from Phase 1 Plan

| Phase 1 Proposal | Actual Implementation | Reason |
|---|---|---|
| Option A (two-call) or Option C (delimiter) | Single-call with JSON field extraction | Simpler, no prompt changes needed, no extra LLM cost. `ResponseFieldExtractor` reliably extracts the `response` field from streaming structured JSON. |
| Separate `execute_stream()` on MasterTutorAgent | `execute_stream()` on BaseAgent | More reusable — any agent can now stream. |
| Full Anthropic streaming support | Anthropic falls back to non-streaming | Anthropic uses tool_use for structured output, making streaming complex. Deferred to a follow-up. |
| Streaming for all modes | Streaming only for teach_me mode | Clarify_doubts and exam use different orchestration paths. Added as future enhancement. |
