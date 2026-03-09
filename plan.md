# Implementation Plan: Replace Visual Explanations with PixiJS

## Overview

Replace the current hardcoded SVG-based `VisualExplanation` system (5 math scene types) with an LLM-generated PixiJS illustration system that can produce **any** static or animated visual for **any** subject.

---

## Architecture: Two-LLM-Call Approach

The master tutor continues to decide **when** a visual helps and **what** to show (natural language description). A second, separate LLM call generates the **Pixi.js code** from that description.

**Flow:**
```
Student message
  → Master Tutor LLM (teaching response + visual_prompt + output_type)
  → [if visual_prompt present] Pixi Code Generator LLM (visual_prompt → JS code)
  → Frontend receives { text response, pixi_code, output_type, title, narration }
  → PixiJS renderer executes code inline in chat
```

The Pixi code generation runs **in parallel** with streaming the text response — minimal added latency. The frontend already uses a "Visualise" button, so code just needs to be ready by the time the user clicks.

---

## Step-by-Step Implementation

### Step 1: Update Master Tutor Output Schema

**File:** `llm-backend/tutor/agents/master_tutor.py`

Replace `VisualExplanation` and `VisualAnimationStep` models with:

```python
class VisualExplanation(BaseModel):
    """Visual prompt for PixiJS illustration generation."""
    visual_prompt: str = Field(
        description="Natural language description of the visual to generate. "
        "Be specific about objects, layout, colors, labels, and any animation. "
        "Example: 'Show 3 red apples on the left and 4 green apples on the right. "
        "Animate them merging into a single group of 7 with a label showing 3+4=7.'"
    )
    output_type: str = Field(
        default="image",
        description="'image' for static illustrations, 'animation' for animated visuals. "
        "Use animation for processes, merging/splitting, or sequences. "
        "Use image for diagrams, charts, labeled structures."
    )
    title: Optional[str] = Field(default=None, description="Short title like '3 + 4 = 7'")
    narration: Optional[str] = Field(default=None, description="Short narration text")
```

Keep `visual_explanation: Optional[VisualExplanation]` on `TutorTurnOutput` — same field name, new shape.

### Step 2: Update Master Tutor Prompt

**File:** `llm-backend/tutor/prompts/master_tutor_prompts.py`

Rewrite rule #13: Instead of listing 5 fixed scene types, tell the LLM to write a **natural language visual_prompt** describing any illustration — diagrams, animations, charts, structures, processes — and to choose `output_type` ('image' or 'animation') based on what serves the explanation best. Remove all references to `scene_type`, `group1_count`, `group2_count`, etc.

### Step 3: Create Pixi Code Generator Service

**New file:** `llm-backend/tutor/services/pixi_code_generator.py`

- Extract the LLM prompt from `api/pixi_poc.py` into a reusable service class `PixiCodeGenerator`.
- Method: `async def generate(self, visual_prompt: str, output_type: str) -> str` — returns Pixi.js v8 code.
- Same Pixi v8 system prompt rules as the POC, but with a smaller canvas (500x350 for inline chat).
- Uses `LLMService` with OpenAI/Codex.
- Strips markdown fences from output.

### Step 4: Integrate Pixi Generation into Orchestrator

**File:** `llm-backend/tutor/orchestration/orchestrator.py`

After the master tutor returns `TutorTurnOutput`:
- If `visual_explanation` is present, fire `PixiCodeGenerator.generate()` concurrently (`asyncio.create_task`) while the text response streams.
- Once pixi code is generated, attach `pixi_code` to the `TurnResult.visual_explanation` dict.
- Update `TurnResult.visual_explanation` shape to: `{ visual_prompt, pixi_code, output_type, title, narration }`.

### Step 5: Update API/WebSocket Layer

**File:** `llm-backend/tutor/api/sessions.py`

- For streaming sessions: send pixi code as a separate `visual_ready` WebSocket message once generation completes (text may still be streaming). This way the frontend knows the visual is ready without blocking text.
- For non-streaming (REST) responses: include pixi_code in the visual_explanation payload as before.

**File:** `llm-backend/tutor/services/session_service.py`

- Pass new visual shape (with `pixi_code`) through to the response.

### Step 6: Update Frontend Types

**File:** `llm-frontend/src/api.ts`

Update `VisualExplanation` interface:
```typescript
export interface VisualExplanation {
  pixi_code: string;
  output_type: 'image' | 'animation';
  title?: string;
  narration?: string;
}
```

Remove `VisualAnimationStep` interface. Add handler for `visual_ready` WebSocket message type.

### Step 7: Rewrite VisualExplanation Component

**File:** `llm-frontend/src/components/VisualExplanation.tsx`

Complete rewrite — replace all SVG rendering with PixiJS renderer:
- On "Visualise" click: create `PIXI.Application` (500x350), execute `pixi_code` via `new Function('app', 'PIXI', code)`.
- Title + narration text around the canvas.
- Replay button (destroys + recreates app).
- Cleanup on unmount.
- Error boundary: if code execution fails, show "Visual couldn't load" fallback.
- Reuse patterns from `PixiJsPocPage.tsx`.

### Step 8: Update CSS

**File:** `llm-frontend/src/App.css`

Update `.visual-explanation` styles:
- Canvas container sized for inline chat (max-width 500px).
- Dark background (#1a1a2e) matching POC.
- Rounded corners, overflow hidden.
- Keep existing button styles with minor size adjustments.

### Step 9: Update ChatSession Integration

**File:** `llm-frontend/src/pages/ChatSession.tsx`

- Handle `visual_ready` WebSocket message: attach `pixi_code` to the latest teacher message.
- The `VisualExplanationComponent` usage stays the same in all 3 render locations (focus subtitle, message thread, focus carousel) — just passes new data shape.

### Step 10: Handle First-Turn Visuals

- `session_service.py` already includes `visual_explanation` in first turn — ensure the new shape (with pixi code generation) flows through the same path.

---

## Files Modified Summary

| File | Change |
|------|--------|
| `llm-backend/tutor/agents/master_tutor.py` | Replace VisualExplanation model |
| `llm-backend/tutor/prompts/master_tutor_prompts.py` | Rewrite rule #13 |
| `llm-backend/tutor/services/pixi_code_generator.py` | **NEW** — Pixi code generation service |
| `llm-backend/tutor/orchestration/orchestrator.py` | Add parallel pixi generation call |
| `llm-backend/tutor/api/sessions.py` | Add `visual_ready` WS message type |
| `llm-backend/tutor/services/session_service.py` | Pass new visual shape |
| `llm-frontend/src/api.ts` | Update VisualExplanation type + WS handler |
| `llm-frontend/src/components/VisualExplanation.tsx` | Full rewrite → PixiJS renderer |
| `llm-frontend/src/pages/ChatSession.tsx` | Handle `visual_ready` WS message |
| `llm-frontend/src/App.css` | Update visual container styles |

---

## Key Design Decisions

1. **Two-call approach** — Master tutor describes, Codex generates code. Clean separation.
2. **Parallel generation** — Pixi code generates concurrently with text streaming. No added latency for the user.
3. **Lazy rendering** — Code executes only when user clicks "Visualise" (same UX as today).
4. **Same execution tech as POC** — `new Function('app', 'PIXI', code)` pattern, proven to work.
5. **Smaller canvas for chat** — 500x350 (vs POC's 800x600) to fit inline in messages.
6. **Fallback on error** — If pixi code fails to execute, show friendly fallback instead of crashing.
7. **`visual_ready` WS message** — Decouples visual generation from text streaming so neither blocks the other.

---

## Out of Scope (for now)

- Caching/reusing generated pixi code across sessions
- User ability to regenerate/modify visuals
- Removing the admin POC page (keep for testing)
- Updating evaluation/exam flows (only teach_me and clarify_doubts)
- Unit tests for the new pixi code generator service
