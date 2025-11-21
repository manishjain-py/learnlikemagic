# AI Tutor Planner - Adaptive 3-Agent System
## Requirements & Design Document
**Version:** 2.0 - Finalized Adaptive Design
**Last Updated:** 2024-11-19

---

## Executive Summary

### Problem
Current AI tutor generates questions one-by-one without a session-level plan, making learning disjointed. The complex 5-node LangGraph system is hard to debug and lacks adaptability.

### Solution
**Adaptive 3-agent system** with intelligent routing:
1. **PLANNER** - Creates/updates comprehensive study plan (GPT-5.1 deep reasoning)
2. **EXECUTOR** - Generates teaching messages based on current plan state (GPT-4o)
3. **EVALUATOR** - Evaluates responses, updates plan, controls flow, triggers replanning (GPT-4o)

### Key Benefits
- ✅ **Strategic Teaching**: Coherent session plan with adaptive replanning
- ✅ **Self-Correcting**: System adapts when students struggle or excel
- ✅ **Full Observability**: Every decision logged with reasoning
- ✅ **Status-Based Navigation**: Plan itself is source of truth (no manual tracking)
- ✅ **Production-Ready**: LangGraph foundation with checkpointing
- ✅ **Cost-Optimized**: Expensive model only for planning, cheap model for loops

---

## Core Philosophy

1. **Start Simple**: Build 3 agents with clear responsibilities
2. **Observability First**: Every agent answers: Input? Output? Why?
3. **Status as Truth**: Plan statuses determine flow (no manual state tracking)
4. **Iterate Based on Evidence**: Improve prompts from logs, not assumptions
5. **Adaptive by Design**: System can replan when needed

---

## System Architecture

### High-Level Flow with Conditional Routing

```
┌─────────────────────────────────────────────────┐
│              SESSION START                       │
│  guidelines + student_profile + topic_info       │
└────────────────────┬────────────────────────────┘
                     ↓
             ┌──────────────┐
             │   PLANNER    │ (GPT-5.1, reasoning: high)
             │              │
             │ Creates plan │ Input: context + optional(replan_reason)
             │ with steps   │ Output: todo_list, reasoning, metadata
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │  EXECUTOR    │ (GPT-4o, fast)
             │              │
             │ Gets current │ Input: full plan state + conversation
             │ step & makes │ Output: teaching message + reasoning
             │ next message │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │  [STUDENT    │
             │  RESPONDS]   │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │  EVALUATOR   │ (GPT-4o, complex)
             │              │
             │ • Evaluates  │ Input: response + full plan + notes
             │ • Updates    │ Output: score, feedback, status updates,
             │   plan       │         replan_needed, off_topic handling
             │ • Routes     │
             └──────┬───────┘
                    ↓
             ┌──────────────┐
             │   ROUTER     │ (Conditional logic)
             │              │
             │ Decides:     │
             │ • Replan?    │
             │ • Complete?  │
             │ • Continue?  │
             └──────┬───────┘
                    │
        ┌───────────┼────────────┐
        ↓           ↓            ↓
    REPLAN      CONTINUE       END
   (→PLANNER)  (→EXECUTOR)  (all steps
                              complete)
```

### Key Architecture Principles

1. **No Step Numbers**: Current step determined dynamically from statuses
2. **EVALUATOR Controls Flow**: Updates statuses, triggers replanning, handles off-topic
3. **Plan is Source of Truth**: Looking at plan tells you everything
4. **LangGraph with Checkpointing**: Session persistence and resumability

---

## State Schema

### SimplifiedState (Complete)

```python
from typing import TypedDict, Annotated, Sequence, Optional
import operator

class SimplifiedState(TypedDict):
    # Session metadata
    session_id: str
    created_at: str  # ISO timestamp
    last_updated_at: str

    # Inputs (immutable context)
    guidelines: str  # Teaching approach/philosophy
    student_profile: dict  # {interests, learning_style, grade, ...}
    topic_info: dict  # {topic, subtopic, grade}
    session_context: dict  # {estimated_duration_minutes}

    # Dynamic state (THE PLAN IS THE SOURCE OF TRUTH)
    study_plan: dict  # Contains todo_list with step statuses
    assessment_notes: str  # SIMPLIFIED: accumulated text observations
    conversation: Annotated[Sequence[dict], operator.add]  # Append-only

    # Control flags (set by EVALUATOR)
    replan_needed: bool
    replan_reason: Optional[str]

    # Observability (full audit trail)
    agent_logs: Annotated[Sequence[dict], operator.add]  # Append-only
```

### Study Plan Structure (Status-Based)

```python
{
    "todo_list": [
        {
            "step_id": "step_uuid_1",  # UUID, NOT sequential number!
            "title": "Understanding Numerators and Denominators",
            "description": "Explain what top/bottom numbers mean in fractions",
            "teaching_approach": "Use pizza slices as visual metaphor",
            "success_criteria": "Student can identify numerator vs denominator in 3 examples",

            # Status is source of truth for navigation
            "status": "completed",  # pending | in_progress | completed | blocked

            "status_info": {
                "questions_asked": 4,
                "questions_correct": 3,
                "attempts": 5,
                "started_at": "2024-11-19T14:20:00Z",
                "completed_at": "2024-11-19T14:25:00Z"
            }
        },
        {
            "step_id": "step_uuid_2",
            "title": "Comparing Fractions with Same Denominator",
            "description": "Teach comparison: 3/8 vs 5/8",
            "teaching_approach": "Visual comparison - larger numerator = more pieces",
            "success_criteria": "Student correctly compares 3 pairs with same denominator",
            "status": "in_progress",
            "status_info": {
                "questions_asked": 2,
                "questions_correct": 1,
                "attempts": 2
            }
        },
        {
            "step_id": "step_uuid_3",
            "title": "Practice Problems",
            "description": "Mixed practice with feedback",
            "teaching_approach": "Graduated difficulty with hints",
            "success_criteria": "Student solves 5/6 problems correctly",
            "status": "pending",
            "status_info": {}
        }
    ],
    "metadata": {
        "plan_version": 1,  # Increments on replanning
        "estimated_total_questions": 10,
        "estimated_duration_minutes": 20,
        "replan_count": 0,  # Tracks number of replans
        "max_replans": 3,  # Safety limit
        "created_at": "2024-11-19T14:15:00Z",
        "last_updated_at": "2024-11-19T14:25:00Z"
    }
}
```

**Critical Design Decision:** No `current_step_number` field!
Next step is calculated dynamically:
1. First check: any step with `status = "in_progress"`?
2. Else: first step with `status = "pending"`?
3. All `status = "completed"`? → Session done!

### Assessment Notes (Simplified Approach)

**Decision:** Use simple accumulated text notes instead of structured schema.

```python
# Example assessment_notes content:
"""
2024-11-19 14:23 - Student correctly identified numerator (top number) and denominator (bottom number). Strong conceptual start.

2024-11-19 14:25 - Struggled comparing 3/8 vs 5/8. Needed hint about same denominator rule. After hint, successfully solved problem.

2024-11-19 14:28 - Completed 3 consecutive problems correctly. Demonstrates good learning velocity and concept retention.

2024-11-19 14:30 - Attempted harder problem (3/8 vs 5/12). Made error but reasoning was partially correct. Need more practice with different denominators.
"""
```

**Benefits:**
- ✅ Flexible: Natural language, no rigid schema
- ✅ Readable: Teachers/parents can understand
- ✅ AI-friendly: Agents can parse and reason about patterns
- ✅ Simple: No structured fields to maintain

---

## The 3 Agents (Detailed Specifications)

### 1. PLANNER Agent

**Purpose:** Create or update comprehensive study plan
**Model:** GPT-5.1 (Deep Reasoning)
**Execution:** At session start + when triggered by EVALUATOR for replanning

#### Input Schema

```python
{
    # Always present
    "guidelines": str,
    "student_profile": dict,
    "topic_info": dict,
    "session_context": dict,

    # Present during replanning
    "is_replanning": bool,
    "original_plan": dict,  # Current plan state
    "assessment_notes": str,  # What we've learned
    "replan_reason": str,  # Why replanning is needed
    "conversation": List[dict]  # Recent context
}
```

#### Output Schema

```python
{
    "todo_list": [
        {
            "step_id": str,  # UUID
            "title": str,
            "description": str,
            "teaching_approach": str,
            "success_criteria": str,
            "status": "pending",  # All new steps start pending
            "status_info": {}
        }
        # ... more steps
    ],
    "reasoning": str,  # Deep thinking: WHY this plan/changes
    "metadata": {
        "plan_version": int,  # Increment on replan
        "estimated_total_questions": int,
        "estimated_duration_minutes": int,
        "replan_count": int,
        "max_replans": 3
    },

    # If replanning
    "changes_made": str  # Summary of modifications
}
```

#### GPT-5.1 API Pattern

```python
from openai import OpenAI

client = OpenAI()

result = client.responses.create(
    model="gpt-5.1",
    input=planner_prompt,
    reasoning={"effort": "high"}  # Triggers extended thinking
)

plan = parse_json(result.output_text)
reasoning = result.reasoning  # Access deep thinking process
```

#### Replanning Triggers

PLANNER is called again when EVALUATOR sets `replan_needed = True`:

**Common Replan Scenarios:**
- Student fails same concept 3+ times (add prerequisite step)
- Student shows knowledge gap (insert foundational step)
- Student excelling (skip ahead, increase difficulty)
- Student explicitly confused about approach (change teaching method)

**Replanning Strategy:**
- **Insert steps**: Add prerequisite before blocked step
- **Split steps**: Break complex step into smaller ones
- **Skip steps**: Student already knows this
- **Change approach**: Use different teaching method
- **Adjust difficulty**: Make questions easier/harder

---

### 2. EXECUTOR Agent

**Purpose:** Generate next teaching message based on current plan state
**Model:** GPT-4o (Fast)
**Execution:** In loop - every time system needs to send message to student

#### Input Schema

```python
{
    "study_plan": dict,  # Full plan with all steps
    "current_step": dict,  # Dynamically calculated current step
    "guidelines": str,
    "student_profile": dict,
    "conversation": List[dict],  # Recent messages (last 10-15)
    "assessment_notes": str  # What we know about student
}
```

#### Output Schema

```python
{
    "message": str,  # Message to send to student
    "reasoning": str,  # WHY this message (internal)
    "step_id": str,  # Which step this addresses
    "question_number": int,  # Within this step
    "meta": {
        "message_type": str,  # "question" | "explanation" | "encouragement" | "hint"
        "difficulty": str  # "easy" | "medium" | "hard"
    }
}
```

#### Responsibilities

1. **Read current step** from plan (dynamically determined)
2. **Check success_criteria** for that step
3. **Review recent conversation** and assessment notes
4. **Generate appropriate message**:
   - Question (if student needs practice)
   - Explanation (if introducing concept)
   - Encouragement (if student struggling)
   - Summary (if step completing)

**Key Constraint:** EXECUTOR must faithfully follow the plan. No going rogue!

---

### 3. EVALUATOR Agent (Most Complex)

**Purpose:** Evaluate student response, update plan status, control system flow
**Model:** GPT-4o (Fast but complex prompt)
**Execution:** After every student response

#### Input Schema

```python
{
    "student_response": str,  # What student just said
    "study_plan": dict,  # Full plan with all step statuses
    "current_step": dict,  # The step we're evaluating for
    "guidelines": str,
    "assessment_notes": str,  # Running observations
    "conversation": List[dict],  # Recent context (last 10)
    "question_context": dict  # The question asked
}
```

#### Output Schema (Comprehensive)

```python
{
    # 1. EVALUATION
    "score": float,  # 0.0 - 1.0 for this response
    "feedback": str,  # Direct feedback to student
    "reasoning": str,  # Internal reasoning for score

    # 2. STEP STATUS UPDATES
    "updated_step_statuses": {
        "step_uuid_2": "completed"  # step_id: new_status
    },
    "updated_status_info": {
        "step_uuid_2": {
            "questions_asked": 3,
            "questions_correct": 3,
            "attempts": 3,
            "completed_at": "2024-11-19T14:30:00Z"
        }
    },

    # 3. ASSESSMENT TRACKING
    "assessment_note": str,  # Timestamped note to append
    # Example: "2024-11-19 14:30 - Student correctly compared 3/8 vs 5/8. Shows understanding of same-denominator rule."

    # 4. OFF-TOPIC HANDLING
    "was_off_topic": bool,
    "off_topic_response": str | null,
    # If true, this response redirects student back to topic

    # 5. REPLANNING DECISION
    "replan_needed": bool,
    "replan_reason": str | null
    # Triggers PLANNER to modify plan
}
```

#### Responsibilities (Multi-faceted)

**1. Evaluate Response**
- Score accuracy (0.0 - 1.0)
- Generate constructive feedback
- Log reasoning

**2. Update Step Statuses**
- `pending` → `in_progress` (when first question asked in step)
- `in_progress` → `completed` (when success criteria met)
- `in_progress` → `blocked` (after multiple failures)
- Ensure only ONE step is `in_progress` at a time

**3. Track Assessment**
- Append timestamped observation to assessment_notes
- Note strengths, struggles, patterns

**4. Handle Off-Topic**
- Detect if response is off-topic
- Generate brief, friendly redirect that ties student interest to topic
- Don't update step statuses for off-topic responses

**5. Decide Replanning**
- Check for replan triggers:
  - Student failed 3+ times on same concept
  - Knowledge gap detected
  - Student excelling (can skip ahead)
  - Approach not working
- Provide clear replan_reason for PLANNER

#### Prompt Structure Recommendation

```
# EVALUATOR PROMPT STRUCTURE

## SECTION 1: EVALUATE RESPONSE
Analyze the student's response to the question.
Score from 0.0 (incorrect) to 1.0 (perfect).
Generate constructive feedback.

## SECTION 2: UPDATE STEP STATUS
Current step: {current_step}
Success criteria: {success_criteria}
Based on evaluation, should step status change?
- pending → in_progress (first question in step)
- in_progress → completed (success criteria met)
- in_progress → blocked (multiple failures, no progress)

## SECTION 3: ASSESSMENT NOTES
Add timestamped observation (strengths/struggles/patterns).

## SECTION 4: OFF-TOPIC DETECTION
Was response off-topic? If yes, provide friendly redirect.

## SECTION 5: REPLANNING DECISION
Should we replan? Consider:
- Failed 3+ times? (add prerequisite)
- Knowledge gap? (insert foundation step)
- Excelling? (skip ahead)
- Approach not working? (change method)

## OUTPUT FORMAT (JSON)
{...}
```

---

## Routing Logic (Conditional Flow)

### Router Function

```python
def route_after_evaluation(state: SimplifiedState) -> str:
    """Decide next action after evaluation"""

    # 1. Check replan flag (highest priority)
    if state.get("replan_needed", False):
        # Safety check: max replans reached?
        replan_count = state["study_plan"]["metadata"].get("replan_count", 0)
        max_replans = state["study_plan"]["metadata"].get("max_replans", 3)

        if replan_count >= max_replans:
            # Too many replans - flag for human intervention
            state["needs_intervention"] = True
            return "end"

        return "replan"

    # 2. Check session completion
    todo_list = state["study_plan"]["todo_list"]
    if all(step["status"] == "completed" for step in todo_list):
        return "end"

    # 3. Continue execution
    return "continue"
```

### Route Destinations

- **"replan"** → Go to PLANNER with feedback
- **"continue"** → Go to EXECUTOR for next message
- **"end"** → Session complete (END node)

---

## Helper Functions

### Get Current Step (Dynamic Calculation)

```python
def get_current_step(plan: dict) -> Optional[dict]:
    """
    Dynamically calculate current step from plan statuses.
    NO manual tracking needed!
    """
    todo_list = plan["todo_list"]

    # Priority 1: Any step in progress?
    for step in todo_list:
        if step["status"] == "in_progress":
            return step

    # Priority 2: First pending step?
    for step in todo_list:
        if step["status"] == "pending":
            return step

    # All steps completed
    return None
```

### Update Plan Statuses

```python
def update_plan_statuses(
    plan: dict,
    status_updates: dict,
    info_updates: dict
) -> dict:
    """Apply EVALUATOR's status updates to plan"""

    updated_list = []
    in_progress_count = 0

    for step in plan["todo_list"]:
        step_id = step["step_id"]

        # Apply status update if present
        if step_id in status_updates:
            step["status"] = status_updates[step_id]

        # Apply info update if present
        if step_id in info_updates:
            step["status_info"].update(info_updates[step_id])

        # Validate: only one in_progress
        if step["status"] == "in_progress":
            in_progress_count += 1

        updated_list.append(step)

    # Safety check
    if in_progress_count > 1:
        raise ValueError(f"Invalid state: {in_progress_count} steps in_progress!")

    plan["todo_list"] = updated_list
    plan["metadata"]["last_updated_at"] = get_timestamp()

    return plan
```

---

## LangGraph Implementation

### Complete Workflow Definition

```python
from typing import TypedDict, Annotated, Sequence, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
import operator

# === STATE DEFINITION ===

class SimplifiedState(TypedDict):
    # [Full state schema as defined above]
    pass

# === AGENT FUNCTIONS ===

def planner_agent(state: SimplifiedState) -> SimplifiedState:
    """Creates or updates study plan using GPT-5.1"""
    from openai import OpenAI
    client = OpenAI()

    is_replanning = state.get("replan_needed", False)

    if is_replanning:
        prompt = build_replan_prompt(state)
    else:
        prompt = build_initial_plan_prompt(state)

    # Call GPT-5.1 with deep reasoning
    result = client.responses.create(
        model="gpt-5.1",
        input=prompt,
        reasoning={"effort": "high"}
    )

    plan = parse_json_output(result.output_text)

    # Update state
    return {
        **state,
        "study_plan": plan,
        "replan_needed": False,
        "replan_reason": None,
        "agent_logs": state["agent_logs"] + [create_log_entry(
            agent="planner",
            input_summary="Replanning" if is_replanning else "Initial planning",
            output=plan,
            reasoning=result.output_text
        )]
    }


def executor_agent(state: SimplifiedState) -> SimplifiedState:
    """Generates next teaching message"""

    current_step = get_current_step(state["study_plan"])

    if not current_step:
        # Shouldn't happen, but safety
        return state

    prompt = build_executor_prompt(state, current_step)
    result = call_gpt4o(prompt)
    output = parse_json_output(result)

    # Add message to conversation
    return {
        **state,
        "conversation": state["conversation"] + [{
            "role": "tutor",
            "content": output["message"],
            "step_id": current_step["step_id"],
            "timestamp": get_timestamp()
        }],
        "agent_logs": state["agent_logs"] + [create_log_entry(
            agent="executor",
            input_summary=f"Generate message for {current_step['title']}",
            output=output,
            reasoning=output["reasoning"]
        )]
    }


def evaluator_agent(state: SimplifiedState) -> SimplifiedState:
    """Evaluates response, updates plan, routes flow"""

    student_response = state["conversation"][-1]["content"]
    current_step = get_current_step(state["study_plan"])

    prompt = build_evaluator_prompt(state, current_step, student_response)
    result = call_gpt4o(prompt)
    eval_output = parse_json_output(result)

    # Update plan statuses
    updated_plan = update_plan_statuses(
        state["study_plan"],
        eval_output["updated_step_statuses"],
        eval_output["updated_status_info"]
    )

    # Append assessment note
    updated_notes = state["assessment_notes"] + "\n" + eval_output["assessment_note"]

    # Choose feedback (handle off-topic)
    feedback = (
        eval_output["off_topic_response"]
        if eval_output["was_off_topic"]
        else eval_output["feedback"]
    )

    return {
        **state,
        "study_plan": updated_plan,
        "assessment_notes": updated_notes,
        "conversation": state["conversation"] + [{
            "role": "tutor",
            "content": feedback,
            "timestamp": get_timestamp()
        }],
        "replan_needed": eval_output["replan_needed"],
        "replan_reason": eval_output.get("replan_reason"),
        "agent_logs": state["agent_logs"] + [create_log_entry(
            agent="evaluator",
            input_summary=f"Evaluate response for {current_step['title']}",
            output=eval_output,
            reasoning=eval_output["reasoning"]
        )]
    }


def route_after_evaluation(state: SimplifiedState) -> str:
    """Conditional routing logic"""

    # Check replan flag
    if state.get("replan_needed", False):
        replan_count = state["study_plan"]["metadata"].get("replan_count", 0)
        max_replans = state["study_plan"]["metadata"].get("max_replans", 3)

        if replan_count >= max_replans:
            state["needs_intervention"] = True
            return "end"

        return "replan"

    # Check completion
    if all(s["status"] == "completed" for s in state["study_plan"]["todo_list"]):
        return "end"

    # Continue
    return "continue"


# === BUILD GRAPH ===

workflow = StateGraph(SimplifiedState)

# Add nodes
workflow.add_node("planner", planner_agent)
workflow.add_node("executor", executor_agent)
workflow.add_node("evaluator", evaluator_agent)

# Set entry point
workflow.set_entry_point("planner")

# Add edges
workflow.add_edge("planner", "executor")
workflow.add_edge("executor", "evaluator")  # Note: After student responds!

# Conditional routing from evaluator
workflow.add_conditional_edges(
    "evaluator",
    route_after_evaluation,
    {
        "replan": "planner",
        "continue": "executor",
        "end": END
    }
)

# Compile with checkpointing
checkpointer = SqliteSaver("session_checkpoints.db")
app = workflow.compile(checkpointer=checkpointer)
```

### Using the Workflow

```python
# Start new session
initial_state = {
    "session_id": generate_uuid(),
    "created_at": get_timestamp(),
    "guidelines": load_guidelines(),
    "student_profile": get_student_profile(),
    "topic_info": {"topic": "Fractions", "subtopic": "Comparing", "grade": 4},
    "session_context": {"estimated_duration_minutes": 20},
    "study_plan": {},
    "assessment_notes": "",
    "conversation": [],
    "replan_needed": False,
    "agent_logs": []
}

config = {"configurable": {"thread_id": initial_state["session_id"]}}

# Run initial planning + first message
for output in app.stream(initial_state, config):
    print(output)

# Student responds
student_input = {"conversation": [{"role": "student", "content": "5/8 is bigger!"}]}
for output in app.stream(student_input, config):
    print(output)

# Resume interrupted session
for output in app.stream(None, config):  # Auto-resumes from checkpoint!
    print(output)
```

---

## Edge Cases & Handling

### 1. Student Consistently Failing

**Scenario:** Student fails same concept 4+ times.

**EVALUATOR Action:**
```python
{
    "score": 0.2,
    "feedback": "I see this is tricky. Let's break it down differently...",
    "replan_needed": True,
    "replan_reason": "Student failed fraction comparison 4 times. Lacks prerequisite understanding of numerators. Recommend adding foundational step."
}
```

**PLANNER Action:**
- Inserts new step: "Understanding Numerators"
- Moves blocked step after new prerequisite
- Increments `plan_version`
- Logs changes in `changes_made` field

---

### 2. Off-Topic Response

**Student:** "Can we talk about dinosaurs instead?"

**EVALUATOR Response:**
```python
{
    "was_off_topic": True,
    "off_topic_response": "Dinosaurs are awesome! 🦕 How about this: If a T-Rex ate 3/8 of a pizza and a Triceratops ate 5/8, who ate more? Let's figure it out!",
    "replan_needed": False,
    # Don't update step statuses for off-topic
}
```

**Result:** System redirects gracefully, ties interest to topic.

---

### 3. Student Excelling

**Scenario:** Student solves all problems perfectly, quickly.

**EVALUATOR Response:**
```python
{
    "score": 1.0,
    "feedback": "Wow! You really understand this well!",
    "updated_step_statuses": {
        "step_2": "completed",
        "step_3": "completed"  # Skip ahead!
    },
    "assessment_note": "2024-11-19 14:30 - Student demonstrating advanced understanding. Completed steps 2 and 3 preemptively based on strong performance.",
    "replan_needed": False
}
```

**Result:** System intelligently skips steps.

---

### 4. Session Interruption

**Scenario:** Student closes browser mid-session.

**LangGraph Checkpointing:**
```python
# State auto-saved after each agent execution

# When student returns (minutes, hours, or days later):
config = {"configurable": {"thread_id": session_id}}
for output in app.stream(None, config):  # Resume from checkpoint!
    # Continues from exact last state
    pass
```

**Result:** Seamless resumption.

---

### 5. Maximum Replans Reached

**Scenario:** System replanned 3 times, student still struggling.

**Router Logic:**
```python
if replan_count >= max_replans:
    state["needs_intervention"] = True
    state["intervention_reason"] = "Multiple replans unsuccessful. Recommend human tutor."
    return "end"
```

**Result:** Graceful failure with teacher alert.

---

### 6. Context Window Management

**Problem:** Long sessions could overflow context.

**Solution:** Summarize older conversation in prompts
```python
def get_relevant_context(state: SimplifiedState, max_messages: int = 15) -> List[dict]:
    """Get recent conversation with summary of older messages"""
    conversation = state["conversation"]

    if len(conversation) <= max_messages:
        return conversation

    # Keep first 3 (intro) + last 12 (recent)
    summary_count = len(conversation) - 15
    summary_msg = {
        "role": "system",
        "content": f"[{summary_count} earlier messages summarized]"
    }

    return conversation[:3] + [summary_msg] + conversation[-12:]
```

---

## API Endpoints

### Start Session

```http
POST /sessions
Content-Type: application/json

{
    "topic": "Fractions",
    "subtopic": "Comparing Fractions",
    "grade": 4,
    "student_profile": {
        "interests": ["dinosaurs", "video games"],
        "learning_style": "visual",
        "grade": 4
    },
    "session_context": {
        "estimated_duration_minutes": 20
    }
}

Response 200:
{
    "session_id": "uuid",
    "study_plan": {...},
    "first_message": "Hi! Today we're going to learn about comparing fractions...",
    "status": "active"
}
```

### Submit Student Response

```http
POST /sessions/{session_id}/step
Content-Type: application/json

{
    "student_reply": "5/8 is bigger than 3/8"
}

Response 200:
{
    "feedback": "Excellent! You're absolutely right. 5/8 is bigger...",
    "score": 1.0,
    "next_message": "Now let's try a harder one: Which is bigger, 2/5 or 4/5?",
    "session_status": "active",
    "plan_updated": false,
    "current_progress": {
        "steps_completed": 1,
        "steps_total": 3
    }
}
```

### Replanning Scenario

```http
POST /sessions/{session_id}/step
Content-Type: application/json

{
    "student_reply": "I don't know, I'm really confused"
}

Response 200:
{
    "feedback": "That's okay! Let's take a step back and make sure we understand the basics first...",
    "score": 0.0,
    "next_message": "Let's start simple: In a fraction like 3/8, the top number is called the numerator. Can you identify the numerator in 5/8?",
    "session_status": "active",
    "plan_updated": true,
    "replan_reason": "Student showing confusion about basic fraction concepts. Added prerequisite step on numerator/denominator identification.",
    "current_progress": {
        "steps_completed": 0,
        "steps_total": 4  // Increased!
    }
}
```

### Get Session Status

```http
GET /sessions/{session_id}/status

Response 200:
{
    "session_id": "uuid",
    "status": "active",
    "study_plan": {...},
    "progress": {
        "steps_completed": 2,
        "steps_total": 4,
        "questions_asked": 8,
        "accuracy": 0.75
    },
    "assessment_notes": "...",
    "current_step": {...},
    "agent_logs": [...]
}
```

---

## Logging & Observability

### Principle
**Every agent execution must be logged with: Input, Output, Reasoning, Timestamp**

### Log Entry Structure

```python
{
    "agent": "planner" | "executor" | "evaluator",
    "timestamp": "2024-11-19T14:30:00Z",
    "input_summary": "Brief description of input",
    "output": {...},  # Full output JSON
    "reasoning": "Agent's internal reasoning",
    "duration_ms": 1234
}
```

### Storage

```
logs/sessions/{session_id}/
  ├── agent_steps.jsonl      # Machine-readable (one JSON per line)
  └── agent_steps.txt        # Human-readable formatted
```

### Dashboard Metrics

**Key Metrics to Track:**
- Session duration
- Steps completed vs total
- Questions asked per step
- Student accuracy rate
- Number of replans per session
- Average time per step
- Off-topic frequency
- Intervention rate (max replans reached)

---

## Implementation Roadmap

### Phase 1: Core System (Week 1)
- [ ] Define `SimplifiedState` and all TypedDict schemas
- [ ] Implement helper functions (`get_current_step`, `update_plan_statuses`)
- [ ] Build PLANNER agent with GPT-5.1 integration
  - [ ] Initial planning prompt
  - [ ] Replanning prompt
- [ ] Build EXECUTOR agent with GPT-4o
  - [ ] Message generation prompt
- [ ] Build EVALUATOR agent with GPT-4o
  - [ ] Structured prompt (5 sections)
  - [ ] All output fields
- [ ] Implement LangGraph workflow
  - [ ] Add nodes
  - [ ] Add conditional routing
  - [ ] Add checkpointing (SqliteSaver)
- [ ] Unit test each agent independently

### Phase 2: Integration & Testing (Week 2)
- [ ] End-to-end test: Session start → planning → execution → evaluation → completion
- [ ] Test replanning trigger and execution
  - [ ] Student failing scenario
  - [ ] Student excelling scenario
- [ ] Test off-topic handling
- [ ] Test edge cases:
  - [ ] Session interruption/resumption
  - [ ] Max replans reached
  - [ ] Context window overflow
  - [ ] Invalid status transitions
- [ ] Load test (concurrent sessions)
- [ ] Add structured logging (JSONL + TXT)
- [ ] Add timing/performance metrics

### Phase 3: API & Observability (Week 3)
- [ ] Update `POST /sessions` endpoint
- [ ] Update `POST /sessions/{id}/step` endpoint
- [ ] Add `GET /sessions/{id}/status` endpoint
- [ ] Add log retrieval API
- [ ] Build observability dashboard:
  - [ ] Plan visualization (progress bar)
  - [ ] Assessment notes display
  - [ ] Agent logs viewer
  - [ ] Session metrics
- [ ] Add monitoring/alerting
  - [ ] High replan rate
  - [ ] Intervention flags
  - [ ] Error rates

### Phase 4: Production Deployment & Iteration
- [ ] Deploy to staging environment
- [ ] Run pilot with real students (controlled group)
- [ ] Collect feedback and analyze logs
- [ ] Identify prompt improvement opportunities
- [ ] Refine agent prompts based on evidence
- [ ] Deploy to production
- [ ] Monitor metrics and iterate

---

## Success Criteria

### System-Level
- ✅ Session completion rate > 90%
- ✅ Replan rate < 20% of sessions
- ✅ Intervention rate < 5% of sessions
- ✅ Average session latency < 2s per message
- ✅ Zero state corruption bugs

### Educational Outcomes
- ✅ Student accuracy improves over session duration
- ✅ Students report positive experience (survey)
- ✅ Teachers can understand assessment notes
- ✅ Plans are pedagogically sound (teacher review)

### Technical Excellence
- ✅ All agent decisions logged with reasoning
- ✅ 100% session resumability (checkpointing works)
- ✅ Prompts can be improved iteratively from logs
- ✅ System is debuggable (can trace any session)

---

## Key Design Decisions Summary

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| **No step numbers** | Status-based navigation is self-documenting | Must ensure only one step "in_progress" |
| **Simple assessment (text notes)** | Flexible, readable, AI-friendly | No structured analytics |
| **EVALUATOR controls flow** | Centralized intelligence | Complex agent, single point of failure |
| **Dynamic replanning** | Adaptive, realistic for education | Complexity, additional cost |
| **LangGraph foundation** | Checkpointing, expandability | Learning curve for team |
| **GPT-5.1 for planning** | High-quality strategic plans | Cost, latency (but only once per session) |
| **GPT-4o for execution** | Fast, cheap for repeated calls | Less sophisticated than o1 |
| **Max replans limit** | Safety against infinite loops | May end session prematurely |

---

## Future Enhancements (Post-MVP)

### Priority 2 (After Launch)
- [ ] Hint system (graduated hints on demand)
- [ ] Multi-modal support (diagrams, images, videos)
- [ ] Cross-session memory (use previous sessions in planning)
- [ ] Real-time difficulty adjustment (within step)
- [ ] Parent/teacher dashboard with insights

### Priority 3 (Future)
- [ ] Multi-agent collaboration (add specialist agents)
- [ ] Student-initiated topic changes
- [ ] Gamification elements
- [ ] Voice interaction support
- [ ] Personalized learning path optimization

---

## References

- **LangGraph Documentation**: https://langchain-ai.github.io/langgraph/
- **GPT-5.1 API**: OpenAI `responses.create()` with reasoning parameter
- **Checkpointing**: SqliteSaver for session persistence

---

**Document Status:** ✅ Finalized
**Next Action:** Begin Phase 1 implementation
