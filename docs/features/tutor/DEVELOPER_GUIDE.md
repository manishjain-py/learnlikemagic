# AI Tutor System - Developer Guide
**Quick reference for running, testing, and debugging the AI Tutor**

---

## 🏗️ High-Level Architecture

### System Overview
```
┌─────────────────────────────────────────────────────────────┐
│                    AI Tutor Workflow                         │
│                   (LangGraph StateGraph)                     │
└─────────────────────────────────────────────────────────────┘
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
         START SESSION              SUBMIT RESPONSE
                 │                         │
                 │                         │
         ┌───────▼───────┐         ┌──────▼──────┐
         │   PLANNER     │         │  Add Student│
         │   (GPT-5.1)   │         │   Message   │
         └───────┬───────┘         └──────┬──────┘
                 │                        │
                 ▼                        │
         ┌───────────────┐                │
         │ Study Plan    │                │
         │ - 3-5 Steps   │                │
         │ - Approach    │                │
         │ - Success     │                │
         └───────┬───────┘                │
                 │                        │
                 ▼                        │
         ┌───────────────┐                │
         │   EXECUTOR    │◄───────────────┘
         │   (GPT-4o)    │
         └───────┬───────┘
                 │
                 ▼
         ┌───────────────┐
         │ Check Last    │
         │ Message Role  │
         └───────┬───────┘
                 │
         ┌───────┴───────┐
         │               │
    Student msg?      No │
         │               │
         ▼               ▼
    ┌─────────┐      ┌─────┐
    │EVALUATOR│      │ END │ ← Wait for student
    │(GPT-4o) │      └─────┘
    └────┬────┘
         │
         ▼
    ┌─────────────┐
    │  Evaluate   │
    │  Response   │
    │  & Route    │
    └──────┬──────┘
           │
    ┌──────┴──────┬──────────┐
    │             │          │
Replan?      Complete?   Continue?
    │             │          │
    ▼             ▼          ▼
┌─────────┐   ┌─────┐   ┌─────────┐
│ PLANNER │   │ END │   │EXECUTOR │
└─────────┘   └─────┘   └─────────┘
```

---

## 🧩 Components

### 1. **TutorWorkflow** (`workflows/tutor_workflow.py`)
Main orchestrator - manages session lifecycle

**Methods:**
- `start_session()` → Returns first teaching message
- `submit_response(student_reply)` → Returns feedback + next message
- `get_session_state()` → Returns full session state

### 2. **Three Agents**

| Agent | Model | Role | Input | Output |
|-------|-------|------|-------|--------|
| **PLANNER** | GPT-5.1 | Create/revise study plan | Topic, student profile, guidelines | Study plan (3-5 steps) |
| **EXECUTOR** | GPT-4o | Generate teaching messages | Current step, conversation | Teaching message |
| **EVALUATOR** | GPT-4o | Evaluate responses & route | Student reply, step criteria | Feedback + routing decision |

### 3. **State Management** (`workflows/state.py`)
- **SimplifiedState** - TypedDict with all session data
- **Checkpointing** - SQLite persistence for resumability
- **Conversation** - Append-only message list
- **Study Plan** - Source of truth with step statuses

### 4. **Services**

| Service | Purpose | Location |
|---------|---------|----------|
| **LLMService** | OpenAI API wrapper (GPT-5.1 + GPT-4o) | `services/llm_service.py` |
| **AgentLoggingService** | Dual-format logs (JSONL + TXT) | `services/agent_logging_service.py` |

---

## 🚀 Quick Start

### Setup (One-time)

```bash
# 1. Navigate to backend
cd llm-backend

# 2. Ensure OpenAI API key is set
export OPENAI_API_KEY='sk-...'

# 3. Install dependencies (if not already done)
venv/bin/pip install -r requirements.txt

# 4. Verify setup
venv/bin/python -c "import openai; print('✓ OpenAI installed')"
```

### Run a Test Session

```bash
# Quick test (no API calls) - validates logic
venv/bin/python test-scripts/03_test_helpers.py

# Full integration test (with API calls)
venv/bin/python test-scripts/05_test_agents_full.py
```

---

## 🔧 Developer Workflow

### 1. Start a Session Programmatically

```python
from workflows.tutor_workflow import TutorWorkflow
from services.llm_service import LLMService
from services.agent_logging_service import AgentLoggingService
from workflows.helpers import generate_session_id
import os

# Initialize services
llm = LLMService(api_key=os.getenv("OPENAI_API_KEY"))
logger = AgentLoggingService()
workflow = TutorWorkflow(llm, logger)

# Start session
session_id = generate_session_id()
result = workflow.start_session(
    session_id=session_id,
    guidelines="Be patient and encouraging. Use visual examples.",
    student_profile={
        "interests": ["dinosaurs", "video games"],
        "learning_style": "visual",
        "grade": 4
    },
    topic_info={
        "topic": "Fractions",
        "subtopic": "Comparing Fractions",
        "grade": 4
    },
    session_context={"estimated_duration_minutes": 20}
)

print(f"📝 First message: {result['first_message']}")
print(f"📋 Study plan: {len(result['study_plan']['todo_list'])} steps")
```

### 2. Submit Student Responses

```python
# Student responds
response = workflow.submit_response(
    session_id=session_id,
    student_reply="The numerator is the top number"
)

print(f"💬 Feedback: {response['feedback']}")
if response.get('next_message'):
    print(f"❓ Next question: {response['next_message']}")
```

### 3. Check Session State

```python
state = workflow.get_session_state(session_id)

print(f"Session: {state['session_id']}")
print(f"Messages: {len(state['conversation'])}")
print(f"Current step: {state['study_plan']['todo_list'][0]['title']}")
```

---

## 🐛 Debugging & Logs

### View Logs

**1. Human-Readable Logs (TXT)**
```bash
# View session logs
cat logs/sessions/{session-id}/agent_steps.txt

# Tail logs in real-time
tail -f logs/sessions/{session-id}/agent_steps.txt
```

**2. Machine-Readable Logs (JSONL)**
```bash
# Parse structured logs
cat logs/sessions/{session-id}/agent_steps.jsonl | jq '.'

# Filter by agent
cat logs/sessions/{session-id}/agent_steps.jsonl | jq 'select(.agent == "planner")'
```

### Log Structure

**TXT Format:**
```
================================================================================
AGENT: PLANNER
TIMESTAMP: 2025-11-20T08:01:03.332312Z
DURATION: 39178ms
--------------------------------------------------------------------------------

INPUT SUMMARY:
Initial planning for Fractions - Comparing Fractions

OUTPUT:
{
  "todo_list": [...],
  "metadata": {...}
}

REASONING:
The student needs to start with...
```

**JSONL Format:**
```json
{
  "agent": "planner",
  "timestamp": "2025-11-20T08:01:03.332312Z",
  "duration_ms": 39178,
  "input_summary": "Initial planning for Fractions",
  "output": {...},
  "reasoning": "..."
}
```

### Check Checkpoint Database

```bash
# View checkpoint data
sqlite3 checkpoints/tutor_sessions.db

# List all sessions
sqlite> SELECT DISTINCT thread_id FROM checkpoint;

# View latest checkpoint for a session
sqlite> SELECT * FROM checkpoint WHERE thread_id = '{session-id}' ORDER BY checkpoint_id DESC LIMIT 1;
```

### Common Debugging Commands

```bash
# Find all sessions
ls -la logs/sessions/

# Check last session created
ls -lt logs/sessions/ | head -5

# Count messages in a session
cat logs/sessions/{session-id}/agent_steps.jsonl | wc -l

# View study plan from logs
cat logs/sessions/{session-id}/agent_steps.jsonl | jq 'select(.agent == "planner") | .output.todo_list'
```

---

## 🧪 Testing

### Run All Tests

```bash
# Sequential execution
for script in test-scripts/0*.py; do
    echo "Running $script..."
    venv/bin/python "$script" || exit 1
done
```

### Run Individual Tests

```bash
# 1. Helper functions (instant, no API)
venv/bin/python test-scripts/03_test_helpers.py

# 2. Prompt loader (instant, no API)
venv/bin/python test-scripts/04_test_prompt_loader.py

# 3. Logging service (instant, no API)
venv/bin/python test-scripts/02_test_logging_service.py

# 4. LLM service (~10s, ~$0.01)
venv/bin/python test-scripts/01_test_llm_service.py

# 5. Full integration (~45s, ~$0.05)
venv/bin/python test-scripts/05_test_agents_full.py
```

### Test with Custom Scenarios

Create a test script:

```python
# test_custom_session.py
from workflows.tutor_workflow import TutorWorkflow
from services.llm_service import LLMService
from services.agent_logging_service import AgentLoggingService
import os

llm = LLMService(api_key=os.getenv("OPENAI_API_KEY"))
logger = AgentLoggingService()
workflow = TutorWorkflow(llm, logger)

# Test different topics
topics = [
    {"topic": "Multiplication", "subtopic": "Times Tables", "grade": 3},
    {"topic": "Geometry", "subtopic": "Shapes", "grade": 2},
    {"topic": "Algebra", "subtopic": "Variables", "grade": 6}
]

for topic_info in topics:
    session_id = f"test_{topic_info['topic'].lower()}"
    result = workflow.start_session(
        session_id=session_id,
        guidelines="Be clear and concise",
        student_profile={"interests": ["sports"], "grade": topic_info["grade"]},
        topic_info=topic_info,
        session_context={"estimated_duration_minutes": 15}
    )
    print(f"\n✓ {topic_info['topic']}: {result['first_message'][:100]}...")
```

---

## 📊 Monitoring

### Check System Health

```bash
# Count active sessions
ls logs/sessions/ | wc -l

# Check average session duration
sqlite3 checkpoints/tutor_sessions.db "SELECT AVG(duration) FROM checkpoint;"

# Find failed sessions (check for errors in logs)
grep -r "ERROR" logs/sessions/*/agent_steps.txt
```

### Performance Metrics

Monitor in logs:
- **PLANNER duration:** Typically 10-40s (GPT-5.1 deep reasoning)
- **EXECUTOR duration:** Typically 1-3s (GPT-4o fast generation)
- **EVALUATOR duration:** Typically 2-4s (GPT-4o evaluation)

---

## 🔍 Troubleshooting

### Issue: "Session not found"
```bash
# Check if session exists in checkpoint
sqlite3 checkpoints/tutor_sessions.db "SELECT * FROM checkpoint WHERE thread_id = '{session-id}';"

# Check if logs exist
ls logs/sessions/{session-id}/
```

### Issue: "GPT-5.1 timeout"
- **Normal:** First call may take 30-40s for deep reasoning
- **Solution:** Wait for retry (automatic with exponential backoff)
- **Check:** Look for "Retrying" in stderr

### Issue: Agent execution failed
```bash
# Find the error
grep -A 10 "failed" logs/sessions/{session-id}/agent_steps.txt

# Check agent-specific logs
cat logs/sessions/{session-id}/agent_steps.jsonl | jq 'select(.agent == "evaluator")'
```

### Issue: Conversation loop
- **Check:** Routing decisions in EVALUATOR logs
- **Look for:** Repeated messages in conversation
- **Fix:** Review `route_after_executor` and `route_after_evaluation` logic

---

## 📁 Project Structure

```
llm-backend/
├── agents/
│   ├── base.py                 # BaseAgent template
│   ├── planner_agent.py        # GPT-5.1 strategic planning
│   ├── executor_agent.py       # GPT-4o message generation
│   ├── evaluator_agent.py      # GPT-4o evaluation & routing
│   └── prompts/
│       ├── planner_initial.txt
│       ├── planner_replan.txt
│       ├── executor.txt
│       └── evaluator.txt
│
├── workflows/
│   ├── state.py                # SimplifiedState TypedDict
│   ├── schemas.py              # Pydantic validation models
│   ├── tutor_workflow.py       # LangGraph workflow + service
│   └── helpers.py              # Utility functions
│
├── services/
│   ├── llm_service.py          # OpenAI API wrapper
│   └── agent_logging_service.py # Dual-format logging
│
├── test-scripts/
│   ├── 01_test_llm_service.py
│   ├── 02_test_logging_service.py
│   ├── 03_test_helpers.py
│   ├── 04_test_prompt_loader.py
│   └── 05_test_agents_full.py
│
├── logs/
│   └── sessions/{session-id}/
│       ├── agent_steps.jsonl   # Machine-readable
│       └── agent_steps.txt     # Human-readable
│
└── checkpoints/
    └── tutor_sessions.db       # SQLite persistence
```

---

## 🎯 Key Concepts

### Status-Based Navigation
The system uses step statuses to determine current position:
- `pending` → Not started
- `in_progress` → Currently active (only ONE step can be in_progress)
- `completed` → Finished

**No manual step tracking!** Current step = first `in_progress` or first `pending`

### Conditional Routing
Two routing points:

**1. After EXECUTOR:**
- If last message from student → EVALUATOR
- Else → END (wait for response)

**2. After EVALUATOR:**
- If `replan_needed` → PLANNER
- Else if all steps completed → END
- Else → EXECUTOR (continue)

### Session Resumability
Sessions are automatically checkpointed after each node execution.
Resume by calling `submit_response()` with the session_id.

---

## 💡 Best Practices

### 1. Always Check Logs
```bash
# Before debugging, check logs
cat logs/sessions/{session-id}/agent_steps.txt | tail -100
```

### 2. Use Meaningful Session IDs
```python
# Good: Descriptive IDs for debugging
session_id = f"fractions_grade4_{timestamp}"

# Avoid: Random UUIDs in manual testing
session_id = generate_session_id()  # Use only in production
```

### 3. Monitor API Costs
```bash
# Check PLANNER usage (most expensive)
cat logs/sessions/*/agent_steps.jsonl | jq 'select(.agent == "planner") | .duration_ms'
```

### 4. Clean Test Data
```bash
# Remove test sessions
rm -rf logs/test_*
rm -f checkpoints/test_*.db
```

---

## 🚀 Quick Reference

| Task | Command |
|------|---------|
| **Run all tests** | `for s in test-scripts/0*.py; do venv/bin/python "$s"; done` |
| **View session logs** | `cat logs/sessions/{id}/agent_steps.txt` |
| **Check session state** | `workflow.get_session_state(session_id)` |
| **List all sessions** | `ls logs/sessions/` |
| **Clean test data** | `rm -rf logs/test_* checkpoints/test_*.db` |
| **Parse JSONL logs** | `cat logs/.../agent_steps.jsonl \| jq '.'` |
| **View checkpoint** | `sqlite3 checkpoints/tutor_sessions.db` |

---

**Need Help?** Check `docs/features/tutor/IMPLEMENTATION_PROGRESS.md` for full technical details.
