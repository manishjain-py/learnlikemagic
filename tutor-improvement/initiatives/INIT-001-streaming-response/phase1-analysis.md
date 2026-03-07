# Phase 1: Analysis — INIT-001-streaming-response

**Date:** 2026-03-07
**Feedback:** No streaming — long wait times (3-8s) kill engagement for young kids

---

## Feedback Summary

> The tutor makes a single massive LLM call per turn with no streaming. System + turn context can exceed 3000 tokens, meaning 3-8 second waits. For young kids, this is an eternity. Kids lose interest during waits. Feels like texting a slow friend, not having a tutor in the room. The WebSocket endpoint exists but isn't used by the frontend.

## Current Behavior

The entire turn pipeline is synchronous and non-streaming:

1. **Frontend uses REST, not WebSocket.** The frontend (`llm-frontend/src/api.ts:254`) calls `POST /sessions/{id}/step` — a blocking HTTP request. The WebSocket endpoint exists at `llm-backend/tutor/api/sessions.py:588` (`/ws/{session_id}`) and is fully functional, but the frontend never connects to it.

2. **BaseAgent.execute() waits for full completion.** (`llm-backend/tutor/agents/base_agent.py:74-125`) The master tutor call goes through `BaseAgent.execute()`, which calls `self.llm.call()` via `run_in_executor()`. This is a blocking call that waits for the entire structured JSON response before returning.

3. **LLMService.call() has no streaming support.** (`llm-backend/shared/services/llm_service.py:67-97`) The `call()` method uses `self.client.responses.create()` (OpenAI) or `self.anthropic_adapter.call_sync()` — both are non-streaming. The service has zero streaming infrastructure.

4. **Orchestrator waits for full TutorTurnOutput.** (`llm-backend/tutor/orchestration/orchestrator.py:217-218`) `process_turn()` calls `await self.master_tutor.execute(context)` and only proceeds to state updates after the entire response (all ~20 structured fields) is returned.

5. **WebSocket endpoint also waits for full response.** Even the existing WebSocket path (`sessions.py:700-723`) calls `orchestrator.process_turn()` and only sends the response after full completion — no incremental delivery.

**The bottleneck chain:**
```
Student sends message
  -> REST POST (frontend)
  -> orchestrator.process_turn() (backend)
    -> translate_to_english() [LLM call #1, ~500ms]
    -> safety_agent.execute() [LLM call #2, ~500ms]
    -> master_tutor.execute() [LLM call #3, ~2-6s — the big one]
    -> _apply_state_updates() [instant]
  -> JSON response back to frontend
Total: 3-8 seconds of dead silence
```

## Root Cause Hypothesis

Three independent causes converge:

1. **No streaming API at the LLM layer.** `LLMService` only has `call()` which returns the complete response. There is no `call_stream()` or equivalent that yields tokens incrementally. This is the foundational blocker.

2. **Structured output is all-or-nothing.** The master tutor returns `TutorTurnOutput` — a Pydantic model with ~20 fields including `response` (student-facing text) AND `mastery_updates`, `answer_correct`, `advance_to_step`, etc. The current architecture requires the *entire* JSON to be valid before any field can be read. You can't extract the `response` field until the JSON is complete.

3. **Frontend chose REST over WebSocket.** The WebSocket endpoint was built (and the evaluation pipeline uses it) but the main frontend chat uses REST. REST inherently can't stream partial responses without SSE or chunked transfer encoding.

## Proposed Change Strategy

A two-phase streaming architecture:

### Phase A: Backend streaming infrastructure

1. **Add `call_stream()` to LLMService** — yields raw text tokens as they arrive. For OpenAI: use `responses.create(stream=True)`. For Anthropic: use `messages.stream()`.

2. **Split the master tutor output into two stages:**
   - **Stage 1 (streamable):** Generate the `response` and `audio_text` fields as free text, streamed token-by-token to the client.
   - **Stage 2 (post-stream):** After the full response is generated, parse the complete JSON to extract structured fields (`mastery_updates`, `answer_correct`, `advance_to_step`, etc.) and apply state updates.

   Two approaches for the split:
   - **Option A — Two-call approach:** First call generates just the student-facing `response` (streamed). Second fast call (with the response as context) generates the structured metadata. Adds ~300-500ms but enables true streaming.
   - **Option B — Stream-then-parse:** Keep single call with structured output but use partial JSON parsing to extract the `response` field as it streams, buffering the rest. This is fragile (depends on field ordering in JSON output) but avoids a second LLM call.
   - **Option C (recommended) — Prompt restructure:** Instruct the LLM to output `response` first as plain text, followed by a `---METADATA---` delimiter, followed by JSON metadata. Stream everything before the delimiter, parse everything after.

3. **Add streaming to the WebSocket path.** Modify the WS handler to send incremental `token` messages as they arrive, followed by a final `assistant` message with the complete response + state update.

### Phase B: Frontend WebSocket migration

4. **Switch frontend from REST to WebSocket** for the chat session. The WebSocket endpoint already handles auth, state management, and exam/clarify modes. The frontend needs a WebSocket hook that:
   - Connects on session load
   - Sends `chat` messages
   - Handles `token` (incremental), `assistant` (final), `state_update`, and `error` message types
   - Renders tokens as they arrive in the chat bubble

5. **Add a typing/streaming indicator.** Show the teacher avatar with a "speaking" animation as tokens arrive, replacing the current loading spinner.

### Files to modify

| File | Change |
|------|--------|
| `shared/services/llm_service.py` | Add `call_stream()` method for OpenAI + Anthropic |
| `tutor/agents/base_agent.py` | Add `execute_stream()` method that yields tokens |
| `tutor/agents/master_tutor.py` | Support split response/metadata generation |
| `tutor/orchestration/orchestrator.py` | Add `process_turn_stream()` that yields tokens then applies state |
| `tutor/api/sessions.py` | Update WS handler to send incremental token messages |
| `llm-frontend/src/api.ts` | Add WebSocket connection manager |
| `llm-frontend/src/pages/ChatSession.tsx` | Replace REST call with WS, render streaming tokens |

## Impact Prediction

**Expected improvement:** High

- **Perceived latency drops from 3-8s to ~200-400ms** (time to first token). The student sees text appearing almost immediately.
- **Engagement dramatically improves** for young kids who have short attention spans. The real-time text appearance creates a "tutor is talking to me right now" feeling.
- **TTS can start sooner** — the audio_text can begin synthesis as soon as the response is complete, rather than waiting for all metadata.
- **Aligns with industry standard** — ChatGPT, Gemini, and all modern LLM UIs stream responses. Users expect this.

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Structured output parsing breaks with streaming** | High | Option C (delimiter approach) avoids partial JSON parsing. Option A (two-call) is safest but adds latency. |
| **State updates delayed** | Medium | State updates already happen after the full response today. Streaming doesn't change when state is applied — it just shows the response sooner. |
| **WebSocket connection management complexity** | Medium | The WS endpoint already handles reconnection, auth, and CAS. Frontend needs reconnect logic. |
| **Two-call approach doubles LLM costs** | Low | The metadata-only call can use a fast/cheap model (gpt-4o-mini) since it's just extracting structured fields from an already-generated response. |
| **Race conditions with concurrent REST endpoints** | Low | Already handled by the `state_version` CAS mechanism in the WS path. |
| **Evaluation pipeline regression** | Low | Evaluation already uses WebSocket. Streaming additions are backward-compatible (non-streaming callers still work). |

## Recommendation

**PROCEED**

This is the single highest-impact UX improvement available. The wait time is the most viscerally noticeable problem — every single turn exposes the student to it. The technical foundation exists (WebSocket endpoint is built, LLM providers support streaming natively), and the change is architecturally clean.

Recommended implementation order:
1. Add `call_stream()` to LLMService (backend infra, no user-facing change)
2. Add streaming to the WebSocket handler with Option C (delimiter approach)
3. Migrate frontend to WebSocket with streaming token rendering
4. Measure: compare time-to-first-token before/after

The two-call approach (Option A) is the safest starting point since it doesn't require prompt restructuring and keeps structured output validation intact. Option C is more elegant but requires careful prompt engineering to ensure the delimiter is respected.
