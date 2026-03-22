# Implementation Plan: Per-Card Simplification

## Implementation Order

### Step 1: Backend Models
**Files:** `tutor/models/session_state.py`, `tutor/models/messages.py`
- Add `RemedialCard` and `ConfusionEvent` Pydantic models to `session_state.py`
- Add `remedial_cards` and `confusion_events` fields to `CardPhaseState`
- Add `SimplifyCardRequest` model to `messages.py`
- Update `ExplanationCard` to accept `card_type: "simplification"` in addition to existing types

### Step 2: Backend Prompts
**Files:** `tutor/prompts/master_tutor_prompts.py`
- Add `SIMPLIFY_CARD_PROMPT` template for generating simplified cards
- Add `card_stuck` handling to bridge prompt builder

### Step 3: Backend Agent
**Files:** `tutor/agents/master_tutor.py`
- Add `generate_simplified_card()` method that builds a simplification prompt and calls the LLM
- Add `SimplifiedCardOutput` Pydantic model for structured LLM output
- Update `_build_bridge_prompt()` to handle `bridge_type="card_stuck"`

### Step 4: Backend Orchestrator
**Files:** `tutor/orchestration/orchestrator.py`
- Add `generate_simplified_card()` method that calls master tutor agent
- Return the generated card content

### Step 5: Backend Service
**Files:** `tutor/services/session_service.py`
- Add `simplify_card()` method: load session, determine depth, call orchestrator or escalate
- Update `_build_precomputed_summary()` to include confusion events
- Update `_switch_variant_internal()` to clear remedial_cards on variant switch
- Add confusion event logging

### Step 6: Backend API
**Files:** `tutor/api/sessions.py`
- Add `POST /{session_id}/simplify-card` endpoint
- Update replay endpoint to merge remedial cards into card deck

### Step 7: Frontend API
**Files:** `llm-frontend/src/api.ts`
- Add `simplifyCard()` function

### Step 8: Frontend UI
**Files:** `llm-frontend/src/pages/ChatSession.tsx`
- Add stable card IDs to carousel slide construction
- Add "I didn't understand" button on each explanation card
- Add `handleSimplifyCard()` handler with loading state
- Card insertion logic after API response
- End-of-deck button relabeling
- Handle escalation response (transition to interactive)
