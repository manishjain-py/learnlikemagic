# Feedback — INIT-001-streaming-response

**Date:** 2026-03-07

## Raw Feedback

> Gap 1: No Streaming — Long Wait Times Kill Engagement. The tutor makes a single massive LLM call per turn with no streaming. System + turn context can exceed 3000 tokens, meaning 3-8 second waits. For young kids, this is an eternity. Impact: Kids lose interest during waits. Feels like texting a slow friend, not having a tutor in the room. Fix: Stream the `response` field token-by-token while structured metadata (mastery updates, etc.) is processed after stream completes. WebSocket endpoint exists but isn't used by frontend.
