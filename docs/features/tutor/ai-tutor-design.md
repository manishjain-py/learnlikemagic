# AI Tutor Component - Complete Design & Workflow Analysis

**Last Updated:** November 10, 2025
**Status:** Production
**System:** Adaptive Tutoring Platform (Frontend: React/TypeScript, Backend: FastAPI/Python)

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Guidelines System (Subject-Topic-Subtopic)](#guidelines-system)
4. [Teaching Workflow - The Core Loop](#teaching-workflow)
5. [Student Assessment](#student-assessment)
6. [AI Integration Points](#ai-integration-points)
7. [Complete End-to-End Workflow](#complete-end-to-end-workflow)
8. [Data Models & Database Schema](#data-models--database-schema)
9. [Key Configuration & Constants](#key-configuration--constants)
10. [Critical Files Reference](#critical-files-reference)
11. [Performance & Error Handling](#performance--error-handling)
12. [Testing & Debugging](#testing--debugging)
13. [Future Enhancements](#future-enhancements)

---

## System Overview

### Purpose
The AI Tutor is an adaptive learning system that provides personalized, one-on-one tutoring to students. It uses pedagogically-grounded teaching guidelines combined with AI to:
- Present age-appropriate questions
- Grade student responses
- Provide scaffolding when students struggle
- Track mastery progression
- Adapt teaching strategy based on student performance

### Key Technologies
- **Frontend:** React 18, TypeScript, Vite
- **Backend:** FastAPI, SQLAlchemy, PostgreSQL
- **AI Service:** OpenAI API (gpt-4o-mini model)
- **Orchestration:** LangGraph (node-based state machine)
- **Architecture Pattern:** Repository + Service + Graph patterns

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Subject    │→ │    Topic     │→ │   Subtopic   │→ Chat    │
│  │  Selection   │  │  Selection   │  │  Selection   │  Interface│
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                          ↓ API Calls                             │
└─────────────────────────┼──────────────────────────────────────┘
                          ↓
┌─────────────────────────┼──────────────────────────────────────┐
│                    BACKEND (FastAPI)                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              SessionService (Orchestration)              │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                            ↓                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │         GraphService (LangGraph Workflow Engine)         │  │
│  │  ┌─────────┐  ┌─────────┐  ┌────────────┐  ┌──────────┐ │  │
│  │  │ Present │→ │  Check  │→ │ Remediate  │  │ Diagnose │ │  │
│  │  │  Node   │  │  Node   │  │    Node    │  │   Node   │ │  │
│  │  └─────────┘  └─────────┘  └────────────┘  └──────────┘ │  │
│  │  ┌─────────┐  ┌──────────────────────────────────────┐  │  │
│  │  │ Advance │  │       Routing Functions              │  │  │
│  │  │  Node   │  │  (route_after_check/advance)         │  │  │
│  │  └─────────┘  └──────────────────────────────────────┘  │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                            ↓                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │            Repository Layer (Data Access)                │  │
│  │  - TeachingGuidelineRepository                           │  │
│  │  - SessionRepository                                     │  │
│  │  - EventRepository                                       │  │
│  └────────────────────────┬─────────────────────────────────┘  │
└───────────────────────────┼──────────────────────────────────┘
                            ↓
┌───────────────────────────┼──────────────────────────────────┐
│                    PostgreSQL DATABASE                         │
│  - teaching_guidelines (pedagogy)                              │
│  - sessions (state management)                                 │
│  - events (audit log)                                          │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│                    EXTERNAL AI SERVICE                          │
│              OpenAI API (gpt-4o-mini)                          │
│  - Teaching (Present Node)                                     │
│  - Grading (Check Node)                                        │
│  - Remediation (Remediate Node)                                │
└────────────────────────────────────────────────────────────────┘
```

---

## Architecture

### Design Patterns

#### 1. **Repository Pattern**
- Abstraction layer over database access
- Decouples data access from business logic
- Files: `guideline_repository.py`, `repositories/*.py`

#### 2. **Service Pattern**
- Business logic orchestration
- Coordinates repositories and graph execution
- Files: `services/session_service.py`, `services/graph_service.py`

#### 3. **State Machine Pattern (LangGraph)**
- Node-based workflow orchestration
- Pure functions for each node
- Conditional routing between nodes
- Files: `graph/nodes.py`, `graph/state.py`

#### 4. **Provider Pattern**
- Abstraction for LLM services
- Easy to swap OpenAI with other providers
- Files: `llm.py`

---

## Guidelines System

### Purpose
Guidelines are the **pedagogical foundation** of the tutoring system. They contain detailed teaching instructions that guide AI behavior throughout a learning session.

### Database Model

**Table:** `teaching_guidelines`

```python
class TeachingGuideline(Base):
    __tablename__ = "teaching_guidelines"

    id = Column(String, primary_key=True)           # UUID
    country = Column(String)                         # e.g., "India"
    board = Column(String)                           # e.g., "CBSE"
    grade = Column(Integer)                          # e.g., 3
    subject = Column(String)                         # e.g., "Mathematics"
    topic = Column(String)                           # e.g., "Fractions"
    subtopic = Column(String)                        # e.g., "Comparing Like Denominators"
    guideline = Column(Text)                         # 500-2000 word teaching manual
    metadata_json = Column(Text)                     # Optional JSON metadata
    created_at = Column(DateTime)

    # Index for fast curriculum lookups
    Index("idx_curriculum", "country", "board", "grade", "subject", "topic")
```

### Hierarchy Structure

```
Country (e.g., India)
  └── Board (e.g., CBSE)
      └── Grade (e.g., 3)
          └── Subject (e.g., Mathematics)
              └── Topic (e.g., Fractions)
                  ├── Subtopic 1: Comparing Like Denominators
                  ├── Subtopic 2: Adding Like Denominators
                  └── Subtopic 3: Subtracting Like Denominators
```

### Guideline Content Structure

Each guideline is a comprehensive document (~500-2000 words) containing:

1. **Learning Objectives**
   - What students should understand by end of lesson
   - Measurable outcomes

2. **Prerequisites**
   - Concepts students should already know
   - Prior knowledge required

3. **Teaching Approach**
   - Concrete examples (pizza slices, toys, real objects)
   - Step-by-step progression
   - Visual descriptions for young learners

4. **Common Misconceptions**
   - Typical errors students make
   - How to identify and address them
   - Example incorrect reasoning patterns

5. **Scaffolding Strategies**
   - How to provide support progressively
   - When to reduce hints
   - Building independence

6. **Assessment Criteria**
   - How to evaluate understanding
   - What constitutes mastery
   - Red flags for confusion

7. **Real-World Applications**
   - Why this concept matters
   - Real-life scenarios
   - Connections to other topics

### Guideline Fetching Flow

#### API Endpoint: `GET /curriculum`

**1. Get Subjects**
```
Request: GET /curriculum?country=India&board=CBSE&grade=3

Backend:
  - TeachingGuidelineRepository.get_subjects(country, board, grade)
  - SQL: SELECT DISTINCT subject FROM teaching_guidelines
         WHERE country='India' AND board='CBSE' AND grade=3

Response: { subjects: ["Mathematics", "English", "Science", ...] }
```

**2. Get Topics**
```
Request: GET /curriculum?country=India&board=CBSE&grade=3&subject=Mathematics

Backend:
  - TeachingGuidelineRepository.get_topics(country, board, grade, subject)
  - SQL: SELECT DISTINCT topic FROM teaching_guidelines
         WHERE country='India' AND board='CBSE' AND grade=3
         AND subject='Mathematics'

Response: { topics: ["Fractions", "Multiplication", "Division", ...] }
```

**3. Get Subtopics (with guideline IDs)**
```
Request: GET /curriculum?country=India&board=CBSE&grade=3
             &subject=Mathematics&topic=Fractions

Backend:
  - TeachingGuidelineRepository.get_subtopics(...)
  - SQL: SELECT id, subtopic FROM teaching_guidelines
         WHERE country='India' AND board='CBSE' AND grade=3
         AND subject='Mathematics' AND topic='Fractions'

Response: {
  subtopics: [
    { subtopic: "Comparing Like Denominators", guideline_id: "uuid-1" },
    { subtopic: "Adding Like Denominators", guideline_id: "uuid-2" },
    { subtopic: "Subtracting Like Denominators", guideline_id: "uuid-3" }
  ]
}
```

### How Guidelines Guide AI

When a session is created with a `guideline_id`:

1. **Backend loads full guideline text** from database (500-2000 words)
2. **Text is injected into every AI prompt** during the session
3. **Present Node:** AI reads guideline to generate age-appropriate questions
4. **Check Node:** AI uses learning objectives to grade responses
5. **Remediate Node:** AI uses misconception patterns to provide targeted help

**Key Insight:** The guideline acts as a comprehensive "teaching manual" that the AI consultant throughout the entire learning session.

---

## Teaching Workflow

### The Core Loop - State Machine

```
┌────────────────────────────────────────────────────────────────┐
│                        START SESSION                            │
│                 (Load guideline from database)                  │
└────────────────────────┬───────────────────────────────────────┘
                         ↓
                  ┌──────────────┐
                  │ PRESENT Node │ ← Generate question using guideline + AI
                  │  (AI Call)   │
                  └──────┬───────┘
                         ↓
                  User types answer
                         ↓
                  ┌──────────────┐
                  │  CHECK Node  │ ← Grade response using AI
                  │  (AI Call)   │
                  └──────┬───────┘
                         ↓
        Score >= 0.8 AND Confidence >= 0.6?
                         │
         ┌───────────────┴───────────────┐
         │ YES (Good)                    │ NO (Needs Help)
         ↓                               ↓
  ┌──────────────┐              ┌────────────────┐
  │ ADVANCE Node │              │ REMEDIATE Node │ ← Provide help (AI Call)
  │ (No AI)      │              │   (AI Call)    │
  └──────┬───────┘              └────────┬───────┘
         ↓                               ↓
  Increment step_idx              ┌──────────────┐
         ↓                        │ DIAGNOSE Node│ ← Update mastery (No AI)
  ┌──────────────┐                │   (No AI)    │
  │ DIAGNOSE Node│                └────────┬─────┘
  │   (No AI)    │                         ↓
  └──────┬───────┘                Back to user input
         ↓                        (No Present - retry same Q)
  Update mastery
         ↓
  step >= 10 OR mastery >= 0.85?
         │
         ├─ YES → END SESSION
         │
         └─ NO → Back to PRESENT Node
```

### Node Implementations

#### 1. PRESENT Node

**File:** `llm-backend/graph/nodes.py:present_node`

**Purpose:** Generate teaching messages or pose questions to student

**Inputs:**
- `teaching_guideline` (full text, pre-loaded by service layer)
- `conversation_history` (all previous messages)
- `student.grade` and `student.prefs`
- `step_idx` (current step 0-9)

**Process:**
```python
def present_node(state: GraphState) -> GraphState:
    # 1. Format conversation history
    history_text = format_conversation_history(state["history"])

    # 2. Load system prompt template
    system_prompt = get_teaching_prompt(
        grade=state["student"]["grade"],
        topic=state["goal"]["topic"],
        prefs=prefs_json,
        step_idx=state["step_idx"]
    )

    # 3. Build user prompt with full guideline
    user_prompt = {
        "topic": state["goal"]["topic"],
        "grade": state["student"]["grade"],
        "teaching_guideline": teaching_guideline,  # ← KEY: 500+ words
        "conversation_history": history_text,
        "step_idx": state["step_idx"]
    }

    # 4. Call OpenAI API
    response = llm_provider.generate(system_prompt, user_prompt)
    # Returns: {message: "...", hints: [...], expected_answer_form: "..."}

    # 5. Add to conversation history
    state["history"].append({
        "role": "teacher",
        "msg": response["message"],
        "meta": {"hints": response.get("hints", [])}
    })

    return state
```

**AI Output Format:**
```json
{
  "message": "Imagine a pizza cut into 4 slices. You eat 3 slices. Your friend eats 1. Who ate more?",
  "hints": [
    "Count the slices each person ate",
    "Compare the numbers at the top (numerators)"
  ],
  "expected_answer_form": "short_text"
}
```

**System Prompt Key Instructions:**
- Make learning feel like magic! Use simple words, real examples
- Use REAL EXAMPLES: Pizza slices, toys, candies, sports
- Make it VISUAL: "Imagine 3 apples..."
- Keep it SIMPLE: Short sentences, simple words
- Progression by step:
  - Steps 0-2: Easy, concrete examples
  - Steps 3-5: Build on basics
  - Steps 6-7: "Why" questions (deeper understanding)
  - Steps 8-9: Real-life scenarios
- Maximum 80 words per message

**File:** `llm-backend/prompts/templates/teaching_prompt.txt`

---

#### 2. CHECK Node

**File:** `llm-backend/graph/nodes.py:check_node`

**Purpose:** Grade student's response using AI evaluation

**Inputs:**
- `current_student_reply` (student's answer)
- `conversation_history` (for context)
- `goal.learning_objectives` (what to assess against)
- `goal.topic`

**Process:**
```python
def check_node(state: GraphState) -> GraphState:
    # 1. Get student's reply
    student_reply = state.get("current_student_reply", "")

    # 2. Format history for context
    history_text = format_conversation_history(state["history"])

    # 3. Load grading prompt
    system_prompt = get_grading_prompt(
        grade=state["student"]["grade"],
        topic=state["goal"]["topic"],
        reply=student_reply
    )

    # 4. Call OpenAI API for grading
    grading = llm_provider.generate(system_prompt, {
        "topic": state["goal"]["topic"],
        "reply": student_reply,
        "expected_concepts": state["goal"]["learning_objectives"],
        "conversation_history": history_text
    })

    # 5. Store grading result
    state["last_grading"] = grading
    # Structure: {score, rationale, labels, confidence}

    return state
```

**AI Output Format:**
```json
{
  "score": 0.95,
  "rationale": "Student correctly identified that 3/4 is more than 1/4 and provided correct reasoning",
  "labels": [],
  "confidence": 0.98
}
```

**Grading Bands (from prompt):**
```
Be GENEROUS for Grade 3 students:
- 0.9-1.0:  Excellent understanding (answer is correct)
- 0.7-0.89: Good understanding with minor gaps
- 0.5-0.69: Partial understanding (on right track)
- 0.3-0.49: Significant misconceptions
- 0.0-0.29: Minimal understanding (off-topic)
```

**Misconception Labels (Examples):**
- `"confusing_denominators_with_numerators"`
- `"not_comparing_properly"`
- `"thinking_larger_number_always_bigger"`
- `"off_topic_response"`
- `"partially_understanding_comparison"`

**File:** `llm-backend/prompts/templates/grading_prompt.txt`

---

#### 3. ROUTING (After Check)

**File:** `llm-backend/graph/nodes.py:route_after_check`

**Purpose:** Decide whether to advance or remediate based on grading

**Logic:**
```python
def route_after_check(state: GraphState) -> str:
    """Returns 'advance' or 'remediate'"""
    score = state["last_grading"]["score"]
    confidence = state["last_grading"]["confidence"]

    # Advance only if BOTH conditions met
    if score >= 0.8 and confidence >= 0.6:
        return "advance"
    else:
        return "remediate"
```

**Constants:**
- `MASTERY_ADVANCE_THRESHOLD = 0.8` (need 80% score)
- `MIN_CONFIDENCE_FOR_ADVANCE = 0.6` (AI must be 60% confident)

**Why confidence matters:** Prevents advancing when AI is uncertain about grading

---

#### 4. REMEDIATE Node

**File:** `llm-backend/graph/nodes.py:remediate_node`

**Purpose:** Provide scaffolding and support when student struggles

**Inputs:**
- `last_grading.labels` (misconceptions identified)
- `last_grading.score`
- `goal.topic`
- `student.grade`

**Process:**
```python
def remediate_node(state: GraphState) -> GraphState:
    # 1. Get misconceptions identified
    labels = state.get("last_grading", {}).get("labels", [])

    # 2. Load remediation prompt
    system_prompt = get_remediation_prompt(
        grade=state["student"]["grade"],
        labels=json.dumps(labels)
    )

    # 3. Call OpenAI API
    response = llm_provider.generate(system_prompt, {
        "labels": labels,
        "last_score": state["last_grading"]["score"],
        "topic": state["goal"]["topic"]
    })
    # Returns: {message: "explanation...", followup: "question..."}

    # 4. Add help message to history
    full_message = response["message"] + " " + response.get("followup", "")
    state["history"].append({
        "role": "teacher",
        "msg": full_message,
        "meta": {"type": "remediation"}
    })

    return state
```

**AI Output Format:**
```json
{
  "message": "No worries! Let me help! Imagine pizza slices again. If you have 1 slice and your friend has 2 slices, who has more? Right - your friend! So 2 is bigger than 1.",
  "followup": "Now, if one pizza is 1/4 and another is 2/4, which is bigger?"
}
```

**System Prompt Key Instructions:**
- Start with "No worries!" or "Let me help!" - make them feel safe
- Use a SIMPLE EXAMPLE they can picture (same concrete objects)
- Break it into tiny steps
- Make it feel like a fun puzzle, not a mistake
- End with encouragement
- Maximum 60 words

**File:** `llm-backend/prompts/templates/remediation_prompt.txt`

**Important:** After remediation, student retries the SAME question (no Present Node called)

---

#### 5. DIAGNOSE Node

**File:** `llm-backend/graph/nodes.py:diagnose_node`

**Purpose:** Update mastery score and track misconceptions

**Inputs:**
- `last_grading.score`
- `last_grading.labels`
- `mastery_score` (current)
- `evidence` (list of misconceptions)

**Process:**
```python
def diagnose_node(state: GraphState) -> GraphState:
    # 1. Extract and track misconception labels
    labels = state["last_grading"].get("labels", [])
    state["evidence"].extend(labels)
    state["evidence"] = state["evidence"][-10:]  # Keep last 10 only

    # 2. Update mastery score using Exponential Moving Average (EMA)
    score = state["last_grading"]["score"]
    state["mastery_score"] = (
        (1 - MASTERY_EMA_ALPHA) * state["mastery_score"] +
        MASTERY_EMA_ALPHA * score
    )
    # MASTERY_EMA_ALPHA = 0.4
    # Formula: new_mastery = 0.6 * old + 0.4 * current_score

    return state
```

**Mastery Score Calculation (EMA):**

```
Formula: new_mastery = 0.6 * old_mastery + 0.4 * current_score

Example Progression:
  Step 0: Initial = 0.5
    Score: 0.95 → new = 0.6(0.5) + 0.4(0.95) = 0.30 + 0.38 = 0.68

  Step 1: Current = 0.68
    Score: 0.85 → new = 0.6(0.68) + 0.4(0.85) = 0.408 + 0.34 = 0.748

  Step 2: Current = 0.748
    Score: 0.35 → new = 0.6(0.748) + 0.4(0.35) = 0.449 + 0.14 = 0.589
    (Note: Drops smoothly, not drastically)

  Step 3: Current = 0.589
    Score: 0.90 → new = 0.6(0.589) + 0.4(0.90) = 0.353 + 0.36 = 0.713
    (Note: Recovers but considers history)
```

**Why EMA?**
- **Smooth progression:** No wild swings from single answers
- **Recent emphasis:** 40% weight to new score (responsive to current performance)
- **Historical context:** 60% weight to history (considers learning trajectory)
- **Prevents gaming:** Single correct answer doesn't inflate score
- **Realistic assessment:** Reflects overall understanding trend

**No AI used** - Pure mathematical calculation

---

#### 6. ADVANCE Node

**File:** `llm-backend/graph/nodes.py:advance_node`

**Purpose:** Increment step counter to move to next question

**Process:**
```python
def advance_node(state: GraphState) -> GraphState:
    state["step_idx"] += 1
    return state
```

**Simple but critical:** Tracks progression through session

**No AI used** - Simple increment

---

#### 7. ROUTING (After Advance)

**File:** `llm-backend/graph/nodes.py:route_after_advance`

**Purpose:** Decide whether to continue or end session

**Logic:**
```python
def route_after_advance(state: GraphState) -> str:
    """Returns 'present' to continue, 'end' to finish"""
    if state["step_idx"] >= MAX_STEPS or state["mastery_score"] >= MASTERY_COMPLETION_THRESHOLD:
        return "end"
    else:
        return "present"
```

**Constants:**
- `MAX_STEPS = 10` (maximum 10 questions)
- `MASTERY_COMPLETION_THRESHOLD = 0.85` (85% mastery)

**Session ends when EITHER condition is met:**
1. Completed 10 steps, OR
2. Achieved 85% mastery

**Whichever comes first**

---

## Student Assessment

### Assessment Components

#### 1. Response Grading (AI-Powered)
- **Location:** Check Node
- **Model:** OpenAI gpt-4o-mini
- **Input:** Student response + learning objectives + conversation context
- **Output:** `GradingResult`

```python
class GradingResult(BaseModel):
    score: float              # 0.0-1.0 (overall correctness)
    rationale: str            # Explanation of score
    labels: List[str]         # Misconceptions/confusion identified
    confidence: float         # 0.0-1.0 (AI's confidence in grading)
```

#### 2. Scoring Bands

```
┌─────────────┬──────────────────────────────────────────────────┐
│ Score Range │ Interpretation                                   │
├─────────────┼──────────────────────────────────────────────────┤
│ 0.9 - 1.0   │ Excellent: Answer is correct, good understanding │
│ 0.7 - 0.89  │ Good: Mostly correct, minor gaps                 │
│ 0.5 - 0.69  │ Partial: On right track, missing key concepts    │
│ 0.3 - 0.49  │ Significant: Wrong concept, misconceptions       │
│ 0.0 - 0.29  │ Minimal: Off-topic, no grasp of concept          │
└─────────────┴──────────────────────────────────────────────────┘
```

**Grading Philosophy:** Be GENEROUS for young learners (Grade 3)

#### 3. Misconception Tracking

**Labels Generated by AI:**
- `"confusing_numerator_with_denominator"`
- `"not_comparing_denominators"`
- `"thinking_larger_number_always_bigger"`
- `"off_topic_response"`
- `"partially_understanding_comparison"`

**Tracked in:**
- `evidence` list (max 10 most recent)
- Event logs (all historical)
- Session summary (deduplicated)

#### 4. Mastery Calculation

**Exponential Moving Average (EMA):**
```python
MASTERY_EMA_ALPHA = 0.4  # 40% weight to new, 60% to history

new_mastery = (1 - ALPHA) * old_mastery + ALPHA * current_score
new_mastery = 0.6 * old_mastery + 0.4 * current_score
```

**Initial Value:** 0.5 (50% - neutral starting point)

**Range:** 0.0 to 1.0 (displayed as 0-100% in UI)

#### 5. Session Completion Criteria

Session ends when **EITHER:**
1. `step_idx >= 10` (completed 10 questions), OR
2. `mastery_score >= 0.85` (85% mastery achieved)

**Design Rationale:**
- 10 steps: Prevents indefinitely long sessions
- 85% mastery: Allows early completion for fast learners
- Whichever comes first: Balances time and mastery

#### 6. Progress Indicators

**Visible to Student (Frontend):**
```typescript
// Header breadcrumb
"Grade 3 • Mathematics • Fractions • Comparing Like Denominators"

// Progress indicators
"Step 3/10"                    // Current step
"Mastery: 68%"                 // Mastery bar (0-100%)

// After each response
"Routing: Advance"             // or "Remediate"
"Score: 0.95"                  // (optional, if shown)
```

**Tracked in Backend (Database):**
- `sessions.step_idx` (current step)
- `sessions.mastery` (current mastery score)
- `sessions.state_json` (full TutorState)
- `events` table (each node execution)

---

## AI Integration Points

### LLM Provider Architecture

**File:** `llm-backend/llm.py`

```python
class OpenAIProvider(LLMProvider):
    """OpenAI API provider wrapper"""

    def __init__(self, api_key: Optional[str] = None,
                 model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.client = OpenAI(api_key=self.api_key)

    def generate(self, system_prompt: str, user_prompt: str,
                 response_format: str = "json") -> Dict[str, Any]:
        """
        Generate JSON response using OpenAI API

        Args:
            system_prompt: System instructions (role definition)
            user_prompt: User context/query (can be JSON string)
            response_format: "json" (enforces JSON output)

        Returns:
            Parsed JSON response as dictionary
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},  # Force JSON
                temperature=0.7,      # Some creativity but stable
                max_tokens=500        # Reasonable limit
            )

            content = response.choices[0].message.content
            return json.loads(content)

        except Exception as e:
            print(f"OpenAI API error: {e}")
            return self._fallback_response()

    def _fallback_response(self) -> Dict[str, Any]:
        """Return deterministic response when API fails"""
        return {
            "message": "Let's work on comparing fractions!",
            "hints": ["Think about which numerator is bigger"],
            "expected_answer_form": "short_text"
        }
```

### Configuration

**File:** `llm-backend/config.py`

```python
# Environment Variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")      # Required
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini") # Default: gpt-4o-mini
```

### AI Call Specifications

#### Present Node (Teaching)
```
Request:
  System: Teaching methodology + role definition
  User: {
    "topic": "Fractions",
    "grade": 3,
    "teaching_guideline": "[FULL 500+ WORD TEXT]",
    "conversation_history": "Teacher: ...\nStudent: ...",
    "step_idx": 1,
    "prefs": {...}
  }

Config:
  Model: gpt-4o-mini
  Temperature: 0.7
  Max Tokens: 500
  Response Format: JSON

Response:
  {
    "message": "Teaching message (≤80 words)",
    "hints": ["Hint 1", "Hint 2"],
    "expected_answer_form": "short_text|number|mcq"
  }
```

#### Check Node (Grading)
```
Request:
  System: Grading instructions + assessment criteria
  User: {
    "topic": "Fractions",
    "reply": "Student's response",
    "expected_concepts": ["Compare fractions", ...],
    "conversation_history": "Full conversation..."
  }

Config:
  Model: gpt-4o-mini
  Temperature: 0.7
  Max Tokens: 500
  Response Format: JSON

Response:
  {
    "score": 0.95,
    "rationale": "Why this score",
    "labels": ["misconception_A", ...],
    "confidence": 0.98
  }
```

#### Remediate Node (Scaffolding)
```
Request:
  System: Scaffolding instructions + empathy guidelines
  User: {
    "labels": ["confusing_comparison", ...],
    "last_score": 0.65,
    "topic": "Fractions"
  }

Config:
  Model: gpt-4o-mini
  Temperature: 0.7
  Max Tokens: 500
  Response Format: JSON

Response:
  {
    "message": "Friendly explanation (≤60 words)",
    "followup": "Easy follow-up question"
  }
```

### Prompt Management

**File:** `llm-backend/prompts/loader.py`

```python
class PromptLoader:
    """Load and cache prompt templates"""

    _cache: Dict[str, str] = {}

    @classmethod
    def load(cls, template_name: str) -> str:
        """Load template from file"""
        if template_name in cls._cache:
            return cls._cache[template_name]

        file_path = Path(__file__).parent / "templates" / f"{template_name}.txt"
        with open(file_path, "r") as f:
            content = f.read()

        cls._cache[template_name] = content
        return content

    @classmethod
    def format(cls, template_name: str, **kwargs) -> str:
        """Load and format template with variables"""
        template = cls.load(template_name)
        return template.format(**kwargs)

# Convenience functions
def get_teaching_prompt(grade, topic, prefs, step_idx) -> str:
    return PromptLoader.format("teaching_prompt",
                               grade=grade, topic=topic,
                               prefs=prefs, step_idx=step_idx)

def get_grading_prompt(grade, topic, reply) -> str:
    return PromptLoader.format("grading_prompt",
                               grade=grade, topic=topic, reply=reply)

def get_remediation_prompt(grade, labels) -> str:
    return PromptLoader.format("remediation_prompt",
                               grade=grade, labels=labels)
```

**Template Files:**
- `llm-backend/prompts/templates/teaching_prompt.txt`
- `llm-backend/prompts/templates/grading_prompt.txt`
- `llm-backend/prompts/templates/remediation_prompt.txt`

### Error Handling & Fallbacks

```python
def generate(self, system_prompt, user_prompt):
    try:
        response = self.client.chat.completions.create(...)
        return json.loads(response.choices[0].message.content)

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return self._fallback_response()

def _fallback_response(self) -> Dict[str, Any]:
    """Deterministic response when API fails"""
    # Different fallbacks per node type
    return {
        "message": "Let's work on this concept!",
        "hints": ["Think step by step"],
        "expected_answer_form": "short_text"
    }
```

**Why fallbacks matter:**
- API outages don't crash sessions
- User experience degrades gracefully
- Session can continue with reduced functionality

---

## Complete End-to-End Workflow

### Scenario: Student Learning "Comparing Fractions"

#### Phase 1: Topic Selection

**Step 1.1: Load Subject Selection**
```
Frontend: Component mounts
Action: Call getCurriculum({ country: 'India', board: 'CBSE', grade: 3 })

Backend:
  - TeachingGuidelineRepository.get_subjects('India', 'CBSE', 3)
  - SQL: SELECT DISTINCT subject FROM teaching_guidelines
         WHERE country='India' AND board='CBSE' AND grade=3

Response: { subjects: ["Mathematics", "English", "Science"] }

Frontend: Displays subject cards
```

**Step 1.2: Select Subject "Mathematics"**
```
Frontend: User clicks "Mathematics"
Action: Call getCurriculum({ country: 'India', board: 'CBSE', grade: 3, subject: 'Mathematics' })

Backend:
  - TeachingGuidelineRepository.get_topics('India', 'CBSE', 3, 'Mathematics')
  - SQL: SELECT DISTINCT topic FROM teaching_guidelines
         WHERE country='India' AND board='CBSE' AND grade=3
         AND subject='Mathematics'

Response: { topics: ["Fractions", "Multiplication", "Division", "Geometry"] }

Frontend: Displays topic cards with back button
```

**Step 1.3: Select Topic "Fractions"**
```
Frontend: User clicks "Fractions"
Action: Call getCurriculum({ country: 'India', board: 'CBSE', grade: 3,
                             subject: 'Mathematics', topic: 'Fractions' })

Backend:
  - TeachingGuidelineRepository.get_subtopics(...)
  - SQL: SELECT id, subtopic FROM teaching_guidelines
         WHERE country='India' AND board='CBSE' AND grade=3
         AND subject='Mathematics' AND topic='Fractions'

Response: {
  subtopics: [
    { subtopic: "Comparing Like Denominators", guideline_id: "guid-uuid-123" },
    { subtopic: "Adding Like Denominators", guideline_id: "guid-uuid-456" },
    { subtopic: "Subtracting Like Denominators", guideline_id: "guid-uuid-789" }
  ]
}

Frontend: Displays subtopic cards with back button
```

**Step 1.4: Select Subtopic "Comparing Like Denominators"**
```
Frontend: User clicks "Comparing Like Denominators"
State: guideline_id = "guid-uuid-123"
Action: Proceed to session creation
```

---

#### Phase 2: Session Creation

```
Frontend: POST /sessions
Request Body:
{
  "student": {
    "id": "s1",
    "grade": 3,
    "prefs": { "style": "standard", "lang": "en" }
  },
  "goal": {
    "topic": "Fractions",
    "syllabus": "CBSE-G3",
    "learning_objectives": ["Learn Comparing Like Denominators"],
    "guideline_id": "guid-uuid-123"  ← KEY: Links to teaching guideline
  }
}

═══════════════════════════════════════════════════════════════

Backend Processing (SessionService.create_session):

1. Load Guideline from Database
   ─────────────────────────────
   guideline = guideline_repo.get_guideline_by_id("guid-uuid-123")

   Result:
   "To teach comparing fractions with like denominators to Grade 3 students,
    begin with concrete visual examples using familiar objects like pizza slices,
    toys, or candies. Start by ensuring students understand that fractions represent
    equal parts of a whole...

    Common misconceptions: Students often confuse larger denominators with larger
    fractions, or compare numerators without checking denominators...

    Scaffolding: Begin with identical denominators (e.g., 1/4 vs 3/4), then progress
    to different numerators but same denominator...

    Assessment criteria: Student should correctly identify which fraction is larger
    and provide reasoning based on numerators when denominators are equal..."

    [... continues for 500-2000 words]

2. Initialize TutorState
   ──────────────────────
   tutor_state = TutorState(
       session_id="sess-uuid-456",
       student=request.student,
       goal=request.goal,
       step_idx=0,
       history=[],
       mastery_score=0.5,        # Start at 50%
       last_grading=None,
       evidence=[],
       next_action="present"
   )

3. Execute Present Node (First Question)
   ─────────────────────────────────────
   graph_state = tutor_state_to_graph_state(tutor_state)
   graph_state["teaching_guideline"] = guideline.guideline  # Inject full text

   graph_state = present_node(graph_state)

   Inside present_node:
   ↓
   System Prompt (from teaching_prompt.txt):
   "You are a magical tutor for Grade 3 students learning Fractions.
    Make learning feel like an adventure! Use simple words and real examples.

    Teaching style:
    - Use REAL objects: pizza, toys, candies
    - Make it VISUAL: 'Imagine 3 red apples...'
    - Keep sentences SHORT and SIMPLE
    - Maximum 80 words per message

    Progression rules:
    - Steps 0-2: Very easy, concrete examples
    - Steps 3-5: Build on basics, slight complexity
    - Steps 6-7: Ask 'why' questions
    - Steps 8-9: Real-life application scenarios

    Current context:
    - This is step 0 (first question)
    - No prior history"

   User Prompt (JSON):
   {
     "topic": "Fractions",
     "grade": 3,
     "teaching_guideline": "[FULL 500-2000 WORD GUIDELINE TEXT]",
     "conversation_history": "",
     "step_idx": 0,
     "prefs": {"style": "standard", "lang": "en"}
   }

   ↓ Call OpenAI API ↓

   OpenAI Response:
   {
     "message": "🍕 Imagine a pizza cut into 4 equal slices! You take 3 slices
                 and I take 1 slice. Who has more pizza?",
     "hints": [
       "Count the slices each of us has",
       "The bigger number means more slices!"
     ],
     "expected_answer_form": "short_text"
   }

   Add to history:
   history.append({
     "role": "teacher",
     "msg": "🍕 Imagine a pizza cut into 4 equal slices!...",
     "meta": {"hints": [...]}
   })

4. Persist Session in Database
   ───────────────────────────
   session_repo.create(Session(
       id="sess-uuid-456",
       student_json=json.dumps(tutor_state.student.model_dump()),
       goal_json=json.dumps(tutor_state.goal.model_dump()),
       state_json=json.dumps(tutor_state.model_dump()),
       mastery=0.5,
       step_idx=0,
       created_at=datetime.now(),
       updated_at=datetime.now()
   ))

5. Return Response to Frontend
   ───────────────────────────
   return CreateSessionResponse(
       session_id="sess-uuid-456",
       first_turn={
           "message": "🍕 Imagine a pizza cut into 4 equal slices!...",
           "hints": ["Count the slices...", "The bigger number..."],
           "step_idx": 0,
           "mastery_score": 0.5
       }
   )

═══════════════════════════════════════════════════════════════

Frontend Displays Chat Interface:
  Header: "Grade 3 • Mathematics • Fractions • Comparing Like Denominators"
  Progress: "Step 0/10" | "Mastery: 50%"
  Chat:
    [Teacher] 🍕 Imagine a pizza cut into 4 equal slices!...
    [Hints] (expandable)
  Input: Text area for student response
```

---

#### Phase 3: Student Responds (Correct Answer)

```
Frontend: User types answer and submits
Input: "I have 3 slices and you have 1, so I have more!"
Action: POST /sessions/sess-uuid-456/step
Request: { "student_reply": "I have 3 slices and you have 1, so I have more!" }

═══════════════════════════════════════════════════════════════

Backend Processing (SessionService.process_step):

1. Load Session
   ────────────
   session = session_repo.get_by_id("sess-uuid-456")
   tutor_state = json.loads(session.state_json)  # Deserialize

2. Add Student Reply to History
   ─────────────────────────────
   history.append({
       "role": "student",
       "msg": "I have 3 slices and you have 1, so I have more!"
   })

3. Execute Graph Workflow
   ──────────────────────

   3a) CHECK NODE (Grade Response)
       ───────────────────────────
       graph_state["current_student_reply"] = "I have 3 slices..."
       graph_state = check_node(graph_state)

       Inside check_node:
       ↓
       System Prompt (from grading_prompt.txt):
       "You are a grading assistant for a Grade 3 tutor teaching Fractions.
        Evaluate the student's response for understanding.

        Be GENEROUS - this is Grade 3!

        Scoring bands:
        - 0.9-1.0: Excellent (correct answer)
        - 0.7-0.89: Good (mostly correct, minor gaps)
        - 0.5-0.69: Partial (on right track)
        - 0.3-0.49: Significant misconceptions
        - 0.0-0.29: Minimal understanding

        Also identify misconception labels if any:
        - confusing_denominators_with_numerators
        - not_comparing_properly
        - thinking_larger_number_always_bigger
        - off_topic_response"

       User Prompt (JSON):
       {
         "topic": "Fractions",
         "reply": "I have 3 slices and you have 1, so I have more!",
         "expected_concepts": ["Compare fractions with like denominators"],
         "conversation_history": "Teacher: 🍕 Imagine a pizza cut into 4...\n
                                  Student: I have 3 slices and you have 1..."
       }

       ↓ Call OpenAI API ↓

       OpenAI Response:
       {
         "score": 0.95,
         "rationale": "Student correctly identified that 3 slices is more than
                      1 slice and provided clear reasoning using the pizza analogy.",
         "labels": [],  ← No misconceptions detected
         "confidence": 0.98
       }

       Store in state:
       state["last_grading"] = {score: 0.95, rationale: "...", labels: [], confidence: 0.98}

   3b) ROUTE AFTER CHECK
       ─────────────────
       route = route_after_check(graph_state)

       Logic:
       - score = 0.95 >= 0.8? YES ✅
       - confidence = 0.98 >= 0.6? YES ✅
       - Decision: "advance"

   3c) ADVANCE NODE (Increment Step)
       ─────────────────────────────
       graph_state = advance_node(graph_state)

       Logic:
       state["step_idx"] = 0 + 1 = 1

   3d) DIAGNOSE NODE (Update Mastery)
       ──────────────────────────────
       graph_state = diagnose_node(graph_state)

       Logic:
       new_mastery = 0.6 * 0.5 + 0.4 * 0.95
                   = 0.30 + 0.38
                   = 0.68

       state["mastery_score"] = 0.68
       state["evidence"].extend([])  # No misconceptions to add

   3e) ROUTE AFTER ADVANCE
       ───────────────────
       route = route_after_advance(graph_state)

       Logic:
       - step_idx = 1 >= 10? NO
       - mastery_score = 0.68 >= 0.85? NO
       - Decision: "present" (continue with next question)

   3f) PRESENT NODE (Generate Next Question)
       ─────────────────────────────────────
       graph_state = present_node(graph_state)

       Inside present_node:
       ↓
       System Prompt: (same as before, but now step_idx=1)

       User Prompt (JSON):
       {
         "topic": "Fractions",
         "grade": 3,
         "teaching_guideline": "[FULL GUIDELINE TEXT]",  ← Same guideline
         "conversation_history": "Teacher: 🍕 Imagine a pizza cut into 4...\n
                                  Student: I have 3 slices and you have 1...\n",
         "step_idx": 1,
         "prefs": {"style": "standard", "lang": "en"}
       }

       ↓ Call OpenAI API ↓

       OpenAI Response:
       {
         "message": "🌟 Awesome! You got it! Now let's try this:
                     Maria has 2/4 of a chocolate bar and her friend has 1/4.
                     Who has more chocolate?",
         "hints": [
           "Both chocolate bars are cut into 4 equal pieces",
           "Compare the numbers: 2 and 1"
         ],
         "expected_answer_form": "short_text"
       }

       Add to history:
       history.append({
         "role": "teacher",
         "msg": "🌟 Awesome! You got it!...",
         "meta": {"hints": [...]}
       })

4. Update Database
   ───────────────
   session_repo.update(session.id, {
       "state_json": json.dumps(tutor_state.model_dump()),
       "mastery": 0.68,
       "step_idx": 1,
       "updated_at": datetime.now()
   })

   event_repo.create(Event(
       session_id=session.id,
       node="check",
       step_idx=1,
       payload_json=json.dumps({"grading": graph_state["last_grading"]}),
       created_at=datetime.now()
   ))

5. Return Response
   ───────────────
   return StepResponse(
       next_turn={
           "message": "🌟 Awesome! You got it!...",
           "hints": ["Both chocolate bars...", "Compare the numbers..."],
           "step_idx": 1,
           "mastery_score": 0.68,
           "is_complete": False
       },
       routing="Advance",
       last_grading={
           "score": 0.95,
           "rationale": "Student correctly identified...",
           "labels": [],
           "confidence": 0.98
       }
   )

═══════════════════════════════════════════════════════════════

Frontend Updates:
  Progress: "Step 1/10" | "Mastery: 68%"
  Chat:
    [Teacher] 🍕 Imagine a pizza cut into 4 equal slices!...
    [Student] I have 3 slices and you have 1, so I have more!
    [Teacher] 🌟 Awesome! You got it! Now let's try this...
    [Hints] (expandable)
  Routing badge: "Advance" (green)
  Score: 0.95 (optional display)
```

---

#### Phase 4: Student Struggles (Remediation Path)

```
Assume at Step 2, student responds incorrectly:
Input: "1/4 is bigger because 4 is bigger than 2"

Frontend: POST /sessions/sess-uuid-456/step
Request: { "student_reply": "1/4 is bigger because 4 is bigger than 2" }

═══════════════════════════════════════════════════════════════

Backend Processing:

1. Load Session + Add Reply to History
   ────────────────────────────────────
   (Same as before)

2. Execute Graph Workflow
   ──────────────────────

   2a) CHECK NODE
       ──────────
       System Prompt: (same grading instructions)

       User Prompt:
       {
         "topic": "Fractions",
         "reply": "1/4 is bigger because 4 is bigger than 2",
         "expected_concepts": ["Compare fractions with like denominators"],
         "conversation_history": "[full conversation]"
       }

       ↓ Call OpenAI API ↓

       OpenAI Response:
       {
         "score": 0.35,  ← Low score
         "rationale": "Student is confusing the size of the denominator with
                      the value of the fraction. They think a larger denominator
                      means a larger fraction, which is incorrect.",
         "labels": ["confusing_denominator_size_with_fraction_value"],
         "confidence": 0.92
       }

   2b) ROUTE AFTER CHECK
       ─────────────────
       Logic:
       - score = 0.35 < 0.8? YES (failed threshold)
       - Decision: "remediate" ⚠️

   2c) REMEDIATE NODE (Provide Help)
       ─────────────────────────────
       graph_state = remediate_node(graph_state)

       Inside remediate_node:
       ↓
       System Prompt (from remediation_prompt.txt):
       "You're a super patient and fun tutor helping a Grade 3 student
        who is confused. Your job is to HELP, not judge!

        Guidelines:
        - Start with 'No worries!' or 'Let me help!'
        - Use a SIMPLE example they can picture
        - Break into tiny steps
        - Make it feel like a fun puzzle
        - End with encouragement
        - Maximum 60 words

        Misconceptions detected:
        - confusing_denominator_size_with_fraction_value"

       User Prompt (JSON):
       {
         "labels": ["confusing_denominator_size_with_fraction_value"],
         "last_score": 0.35,
         "topic": "Fractions"
       }

       ↓ Call OpenAI API ↓

       OpenAI Response:
       {
         "message": "No worries! Let me help! 🤔 Think about pizza again.
                     If you cut a pizza into 4 slices and take 1, that's 1/4.
                     If you cut another pizza into 4 slices and take 2, that's 2/4.
                     You have MORE pizza when you take 2 slices, not 1!",
         "followup": "So which is bigger: 1/4 or 2/4?"
       }

       Add to history:
       history.append({
         "role": "teacher",
         "msg": "No worries! Let me help! 🤔 Think about pizza again...",
         "meta": {"type": "remediation"}
       })

   2d) DIAGNOSE NODE (Update Mastery)
       ──────────────────────────────
       graph_state = diagnose_node(graph_state)

       Logic:
       new_mastery = 0.6 * 0.68 + 0.4 * 0.35
                   = 0.408 + 0.14
                   = 0.548

       state["mastery_score"] = 0.548
       state["evidence"].append("confusing_denominator_size_with_fraction_value")

   ⚠️ IMPORTANT: NO PRESENT NODE CALLED!
      Student stays on same step (step_idx still 1)
      Student will retry same concept

3. Update Database
   ───────────────
   (Update session with new state, mastery = 0.548)

4. Return Response
   ───────────────
   return StepResponse(
       next_turn={
           "message": "No worries! Let me help! 🤔 Think about pizza again...",
           "hints": [],
           "step_idx": 1,  ← SAME STEP (not advanced)
           "mastery_score": 0.548,
           "is_complete": False
       },
       routing="Remediate",  ← Key indicator
       last_grading={
           "score": 0.35,
           "rationale": "Student is confusing the size of the denominator...",
           "labels": ["confusing_denominator_size_with_fraction_value"],
           "confidence": 0.92
       }
   )

═══════════════════════════════════════════════════════════════

Frontend Updates:
  Progress: "Step 1/10" | "Mastery: 55%" ← Dropped
  Chat:
    [Student] 1/4 is bigger because 4 is bigger than 2
    [Teacher] No worries! Let me help! 🤔 Think about pizza again...
  Routing badge: "Remediate" (orange/yellow)

  User can now retry the same question with help
```

---

#### Phase 5: Session Completion

```
After multiple interactions, assume:
  - step_idx reaches 10, OR
  - mastery_score reaches 0.85

Final StepResponse includes:
  "is_complete": True

═══════════════════════════════════════════════════════════════

Frontend Detects Completion:
  if (response.next_turn.is_complete) {
    fetchSummary();
  }

Action: GET /sessions/sess-uuid-456/summary

═══════════════════════════════════════════════════════════════

Backend Processing (SessionService.get_summary):

1. Load Session
   ────────────
   session = session_repo.get_by_id("sess-uuid-456")

2. Analyze Events to Extract Misconceptions
   ─────────────────────────────────────────
   events = event_repo.get_by_session(session.id)

   misconceptions = set()
   for event in events:
       if event.node == "check":
           payload = json.loads(event.payload_json)
           labels = payload.get("grading", {}).get("labels", [])
           misconceptions.update(labels)

   misconceptions = list(misconceptions)

3. Generate Personalized Suggestions
   ──────────────────────────────────
   suggestions = []

   if session.mastery >= 0.85:
       suggestions.append("🎉 Excellent work on Comparing Fractions!")
       suggestions.append("You're ready to move to more advanced topics.")

   elif session.mastery >= 0.7:
       suggestions.append("👍 Good progress! You're on the right track.")
       suggestions.append("Try 3-5 more practice problems to solidify understanding.")

   else:
       suggestions.append("Keep practicing! Review the examples we worked through.")

   if misconceptions:
       suggestions.append(f"💡 Focus on understanding: {', '.join(misconceptions)}")

4. Return Summary
   ──────────────
   return SummaryResponse(
       steps_completed=10,
       mastery_score=0.87,
       misconceptions_seen=[
           "confusing_denominator_size_with_fraction_value",
           "thinking_larger_number_always_bigger"
       ],
       suggestions=[
           "🎉 Excellent work on Comparing Fractions!",
           "You're ready to move to more advanced topics.",
           "💡 Focus on understanding: confusing_denominator_size_with_fraction_value"
       ]
   )

═══════════════════════════════════════════════════════════════

Frontend Displays Summary Card:

  ┌─────────────────────────────────────────────────────┐
  │               🎊 Session Complete! 🎊               │
  ├─────────────────────────────────────────────────────┤
  │  Steps Completed: 10/10                             │
  │  Final Mastery: 87%                                 │
  │                                                     │
  │  📋 Areas to Review:                                │
  │    • confusing_denominator_size_with_fraction_value │
  │    • thinking_larger_number_always_bigger           │
  │                                                     │
  │  💡 Next Steps:                                     │
  │    • Excellent work on Comparing Fractions!         │
  │    • You're ready to move to more advanced topics.  │
  │    • Focus on understanding: confusing_denominator_ │
  │      size_with_fraction_value                       │
  │                                                     │
  │  [ Start New Session ]                              │
  └─────────────────────────────────────────────────────┘
```

---

## Data Models & Database Schema

### Database Tables

#### teaching_guidelines
```sql
CREATE TABLE teaching_guidelines (
    id VARCHAR PRIMARY KEY,              -- UUID
    country VARCHAR NOT NULL,             -- e.g., "India"
    board VARCHAR NOT NULL,               -- e.g., "CBSE"
    grade INTEGER NOT NULL,               -- e.g., 3
    subject VARCHAR NOT NULL,             -- e.g., "Mathematics"
    topic VARCHAR NOT NULL,               -- e.g., "Fractions"
    subtopic VARCHAR NOT NULL,            -- e.g., "Comparing Like Denominators"
    guideline TEXT NOT NULL,              -- 500-2000 word teaching manual
    metadata_json TEXT,                   -- Optional JSON metadata
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_curriculum
ON teaching_guidelines(country, board, grade, subject, topic);
```

#### sessions
```sql
CREATE TABLE sessions (
    id VARCHAR PRIMARY KEY,               -- UUID
    student_json TEXT NOT NULL,           -- Serialized Student object
    goal_json TEXT NOT NULL,              -- Serialized Goal object
    state_json TEXT NOT NULL,             -- Serialized TutorState (full state)
    mastery FLOAT NOT NULL,               -- 0.0-1.0 (current mastery score)
    step_idx INTEGER NOT NULL,            -- 0-10 (current step)
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### events
```sql
CREATE TABLE events (
    id VARCHAR PRIMARY KEY,               -- UUID
    session_id VARCHAR NOT NULL,          -- Foreign key to sessions
    node VARCHAR NOT NULL,                -- "present", "check", "remediate", etc.
    step_idx INTEGER NOT NULL,            -- Step when event occurred
    payload_json TEXT NOT NULL,           -- Event-specific data (grading, etc.)
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_session_events
ON events(session_id, step_idx);
```

### Python Data Models

#### TutorState (Persisted in sessions.state_json)

```python
class Student(BaseModel):
    id: str
    grade: int
    prefs: Optional[Dict[str, Any]] = None  # {style: "standard", lang: "en"}

class Goal(BaseModel):
    topic: str                               # "Fractions"
    syllabus: str                            # "CBSE-G3"
    learning_objectives: List[str]           # ["Learn Comparing Like Denominators"]
    guideline_id: str                        # UUID linking to teaching_guidelines

class HistoryEntry(BaseModel):
    role: str                                # "teacher" or "student"
    msg: str                                 # Message content
    meta: Optional[Dict[str, Any]] = None    # {hints: [...], type: "remediation"}

class GradingResult(BaseModel):
    score: float                             # 0.0-1.0
    rationale: str                           # Explanation
    labels: List[str]                        # Misconception labels
    confidence: float                        # 0.0-1.0

class TutorState(BaseModel):
    session_id: str
    student: Student
    goal: Goal
    step_idx: int                            # 0-10
    history: List[HistoryEntry]              # All conversation messages
    evidence: List[str]                      # Misconception labels (max 10)
    mastery_score: float                     # 0.0-1.0
    last_grading: Optional[GradingResult]    # Most recent grading
    next_action: Optional[str]               # "present", "check", etc.
```

#### GraphState (Transient - used by LangGraph)

```python
class GraphState(TypedDict):
    session_id: str
    student: Dict[str, Any]                  # {id, grade, prefs}
    goal: Dict[str, Any]                     # {topic, syllabus, objectives, guideline_id}
    step_idx: int
    history: List[Dict[str, Any]]            # [{role, msg, meta}, ...]
    evidence: List[str]
    mastery_score: float
    last_grading: Optional[Dict[str, Any]]
    next_action: Optional[str]
    current_student_reply: Optional[str]     # For check node
    teaching_guideline: Optional[str]        # Full guideline text (loaded by service)
```

#### API Response Models

```python
class CreateSessionResponse(BaseModel):
    session_id: str
    first_turn: Dict[str, Any]               # {message, hints, step_idx, mastery_score}

class StepResponse(BaseModel):
    next_turn: Dict[str, Any]                # {message, hints, step_idx, mastery_score, is_complete}
    routing: str                             # "Advance" or "Remediate"
    last_grading: Optional[GradingResult]

class SummaryResponse(BaseModel):
    steps_completed: int
    mastery_score: float
    misconceptions_seen: List[str]
    suggestions: List[str]

class CurriculumResponse(BaseModel):
    subjects: Optional[List[str]]
    topics: Optional[List[str]]
    subtopics: Optional[List[SubtopicInfo]]  # [{subtopic, guideline_id}, ...]
```

### Service Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Endpoints                        │
│  POST /sessions, POST /sessions/{id}/step, GET /curriculum  │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│                    SessionService                            │
│  - create_session()                                          │
│  - process_step()                                            │
│  - get_summary()                                             │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│                    GraphService                              │
│  - execute_present_node()                                    │
│  - execute_step_workflow()                                   │
│      ├─ check_node()                                         │
│      ├─ route_after_check()                                  │
│      ├─ remediate_node()                                     │
│      ├─ diagnose_node()                                      │
│      ├─ advance_node()                                       │
│      ├─ route_after_advance()                                │
│      └─ present_node()                                       │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│                  Repository Layer                            │
│  - TeachingGuidelineRepository (read-only)                   │
│  - SessionRepository (CRUD)                                  │
│  - EventRepository (logging)                                 │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│                PostgreSQL Database                           │
│  teaching_guidelines, sessions, events                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Configuration & Constants

### Critical Constants (llm-backend/utils/constants.py)

**These 5 numbers control the entire adaptive tutoring behavior:**

```python
# Mastery Scoring
MASTERY_EMA_ALPHA = 0.4
# Weight for new score in EMA calculation
# Formula: new_mastery = (1 - 0.4) * old + 0.4 * current_score
#                       = 0.6 * old + 0.4 * current_score
# Higher alpha = more weight to recent performance
# Lower alpha = more weight to history

MASTERY_COMPLETION_THRESHOLD = 0.85
# 85% mastery required to end session early
# Allows fast learners to complete before 10 steps

MASTERY_ADVANCE_THRESHOLD = 0.8
# 80% score required to advance to next question
# Below this triggers remediation

# Grading Thresholds
MIN_CONFIDENCE_FOR_ADVANCE = 0.6
# AI must be 60% confident in grading to allow advance
# Prevents advancing when AI is uncertain

# Session Progression
MAX_STEPS = 10
# Maximum 10 questions per session
# Prevents indefinitely long sessions

# Step Progression Stages (for teaching prompt)
STEP_PROGRESSION_STAGES = {
    "easy": (0, 2),          # Steps 0-2: Very easy, concrete
    "build": (3, 5),         # Steps 3-5: Build complexity
    "why": (6, 7),           # Steps 6-7: Conceptual "why" questions
    "real_life": (8, 9)      # Steps 8-9: Real-world application
}

# Scoring Bands (for reference)
SCORE_EXCELLENT = 0.9
SCORE_GOOD = 0.7
SCORE_PARTIAL = 0.5
SCORE_SIGNIFICANT_GAPS = 0.3

# Message Length Limits
MAX_MESSAGE_LENGTH = 80       # words (teaching messages)
MAX_REMEDIATION_LENGTH = 60   # words (remediation messages)
```

### Environment Variables

**File:** `.env` or system environment

```bash
# Required
OPENAI_API_KEY=sk-...

# Optional (with defaults)
LLM_MODEL=gpt-4o-mini
DATABASE_URL=postgresql://llmuser:password@localhost:5432/tutor
API_HOST=0.0.0.0
API_PORT=8000
```

### Frontend Configuration (Hardcoded)

**File:** `llm-frontend/src/TutorApp.tsx`

```typescript
const COUNTRY = 'India';       // Currently hardcoded
const BOARD = 'CBSE';          // Currently hardcoded
const GRADE = 3;               // Currently hardcoded

// Future: Make these configurable via props or user profile
```

---

## Critical Files Reference

### Frontend

| File | Purpose | Key Components |
|------|---------|----------------|
| `src/TutorApp.tsx` | Main component | 4 screens (subject/topic/subtopic/chat), session state management |
| `src/api.ts` | API client | getCurriculum, createSession, submitStep, getSummary |
| `src/App.css` | Styling | All UI styles |

### Backend

| File | Purpose | Key Components |
|------|---------|----------------|
| **API Layer** | | |
| `main.py` | FastAPI app entry | App initialization, CORS, routes |
| `routers/` | Endpoint definitions | /curriculum, /sessions, /sessions/{id}/step |
| **Service Layer** | | |
| `services/session_service.py` | Session orchestration | create_session, process_step, get_summary |
| `services/graph_service.py` | Graph workflow execution | execute_present_node, execute_step_workflow |
| **Graph Layer** | | |
| `graph/nodes.py` | Node implementations | present_node, check_node, remediate_node, diagnose_node, advance_node, routing |
| `graph/state.py` | State management | GraphState, state conversions, prompt helpers |
| **Data Layer** | | |
| `models.py` | SQLAlchemy models | TeachingGuideline, Session, Event |
| `database.py` | DB connection | Engine, SessionLocal |
| `guideline_repository.py` | Guideline access | get_guideline_by_id, get_subjects/topics/subtopics |
| `repositories/session_repository.py` | Session CRUD | create, get_by_id, update |
| `repositories/event_repository.py` | Event logging | create, get_by_session |
| **AI Layer** | | |
| `llm.py` | LLM provider | OpenAIProvider, generate, fallback_response |
| `prompts/loader.py` | Prompt management | PromptLoader, get_teaching/grading/remediation_prompt |
| `prompts/templates/teaching_prompt.txt` | Teaching system prompt | AI teaching instructions |
| `prompts/templates/grading_prompt.txt` | Grading system prompt | AI grading instructions |
| `prompts/templates/remediation_prompt.txt` | Remediation system prompt | AI scaffolding instructions |
| **Utilities** | | |
| `utils/constants.py` | Configuration | All magic numbers (thresholds, alpha values) |
| `utils/formatting.py` | Helpers | format_conversation_history |

---

## Performance & Error Handling

### Performance Characteristics

**API Response Times:**
- `/curriculum` endpoints: **< 100ms** (DB query only)
- `POST /sessions`: **2-5 seconds** (includes LLM call for first question)
- `POST /sessions/{id}/step`: **2-5 seconds** (includes 1-2 LLM calls)
- `GET /sessions/{id}/summary`: **< 100ms** (DB query + simple analysis)

**Session State Size:**
- Initial state: ~500 bytes
- Each turn adds: ~100-300 bytes (message + metadata)
- After 10 steps: ~2-3 KB
- Stored as JSON in `sessions.state_json`

**Database Queries:**
- Guidelines indexed by `(country, board, grade, subject, topic)` - very fast
- Sessions indexed by `id` (primary key)
- Events indexed by `(session_id, step_idx)`

**LLM Call Patterns:**
- Present Node: 1 call per new question
- Check Node: 1 call per student response
- Remediate Node: 1 call when student struggles
- Average per step: 1-2 calls (depending on routing)

### Error Handling

#### LLM API Failures

```python
class OpenAIProvider:
    def generate(self, system_prompt, user_prompt):
        try:
            response = self.client.chat.completions.create(...)
            return json.loads(response.choices[0].message.content)

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return self._fallback_response()

    def _fallback_response(self) -> Dict[str, Any]:
        """Deterministic response when API fails"""
        # Different fallbacks per node type
        return {
            "message": "Let's work on this concept together!",
            "hints": ["Think step by step"],
            "expected_answer_form": "short_text"
        }
```

**Why this matters:**
- API outages don't crash sessions
- User experience degrades gracefully
- Session can continue with reduced functionality

#### Session Not Found

```python
@router.post("/sessions/{session_id}/step")
async def submit_step(session_id: str, request: StepRequest):
    try:
        response = session_service.process_step(session_id, request.student_reply)
        return response

    except SessionNotFoundException as e:
        raise HTTPException(status_code=404, detail="Session not found")
```

#### Guideline Not Found

```python
def create_session(request: CreateSessionRequest):
    try:
        guideline = guideline_repo.get_guideline_by_id(request.goal.guideline_id)

    except GuidelineNotFoundException:
        raise HTTPException(status_code=400, detail="Invalid guideline_id")

    # Fallback: Use default guideline
    guideline = DEFAULT_GUIDELINE
```

#### JSON Parsing Errors

```python
def generate(self, system_prompt, user_prompt):
    try:
        content = response.choices[0].message.content
        return json.loads(content)

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}, content: {content}")
        return self._fallback_response()
```

---

## Testing & Debugging

### Manual Testing Flow

**1. Start Services**
```bash
# Backend
cd llm-backend
uvicorn main:app --reload --port 8000

# Frontend
cd llm-frontend
npm run dev
```

**2. Test Curriculum Loading**
```bash
curl 'http://localhost:8000/curriculum?country=India&board=CBSE&grade=3'
curl 'http://localhost:8000/curriculum?country=India&board=CBSE&grade=3&subject=Mathematics'
curl 'http://localhost:8000/curriculum?country=India&board=CBSE&grade=3&subject=Mathematics&topic=Fractions'
```

**3. Test Session Creation**
```bash
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "student": {"id": "s1", "grade": 3, "prefs": {"style": "standard", "lang": "en"}},
    "goal": {
      "topic": "Fractions",
      "syllabus": "CBSE-G3",
      "learning_objectives": ["Learn Comparing Like Denominators"],
      "guideline_id": "[ACTUAL_GUIDELINE_ID]"
    }
  }'
```

**4. Test Step Submission**
```bash
curl -X POST http://localhost:8000/sessions/{session_id}/step \
  -H "Content-Type: application/json" \
  -d '{"student_reply": "3 is bigger than 1"}'
```

**5. Test Summary**
```bash
curl http://localhost:8000/sessions/{session_id}/summary
```

### Debugging Helpers

**Check Session State:**
```bash
curl http://localhost:8000/sessions/{session_id}
# Returns full TutorState as JSON
```

**Test LLM Integration:**
```python
from llm import get_llm_provider

provider = get_llm_provider()
result = provider.generate(
    "You are a helpful tutor",
    "Ask a simple math question for Grade 3"
)
print(result)
```

**Verify Guidelines Loaded:**
```bash
psql -U llmuser -d tutor -c "SELECT COUNT(*) FROM teaching_guidelines;"
psql -U llmuser -d tutor -c "SELECT id, topic, subtopic FROM teaching_guidelines WHERE grade=3 LIMIT 5;"
```

**Check Event Logs:**
```bash
psql -U llmuser -d tutor -c "SELECT node, step_idx, created_at FROM events WHERE session_id='[SESSION_ID]' ORDER BY created_at;"
```

### Expected Behavior

**Progressive Difficulty:**
- Step 0: "Imagine 4 pizza slices..."
- Step 3: "If Maria has 2/4 and John has 3/4..."
- Step 6: "Why is 3/4 more than 1/4?"
- Step 9: "You have $3 and your friend has $1. Who can buy more candy?"

**Remediation Path:**
```
Student: "4 is bigger so 1/4 is bigger"
  ↓ Score: 0.35
  ↓ Route: Remediate
Teacher: "No worries! Think about pizza again..."
  ↓ Student retries same question
Student: "Oh, 2/4 is bigger!"
  ↓ Score: 0.85
  ↓ Route: Advance
Teacher: "Great! Now let's try..."
```

---

## Future Enhancements

### Planned Features

**Immediate (Next Sprint):**
- [ ] Make curriculum selection configurable (not hardcoded)
- [ ] Add session recovery (localStorage persistence)
- [ ] Add loading states and better error messages in UI
- [ ] Add voice input/output option

**Short-Term (Next Quarter):**
- [ ] Multiple student profiles with progress tracking
- [ ] Admin dashboard for viewing/editing guidelines
- [ ] Analytics: Track learning patterns across students
- [ ] A/B testing framework for teaching strategies
- [ ] Gamification: Badges, streaks, leaderboards

**Long-Term (Future):**
- [ ] Multi-language support (Hindi, Spanish, etc.)
- [ ] Adaptive difficulty based on student history
- [ ] Parent/teacher dashboard with insights
- [ ] Integration with school LMS systems
- [ ] Video explanations alongside text
- [ ] Peer learning features (study groups)

### Extensibility Points

**1. LLM Provider Swap:**
```python
# Current: OpenAI
from llm import OpenAIProvider
provider = OpenAIProvider()

# Future: Anthropic
from llm import AnthropicProvider
provider = AnthropicProvider()

# Future: Self-hosted
from llm import LocalLLMProvider
provider = LocalLLMProvider(model_path="/path/to/model")
```

**2. Add New Graph Nodes:**
```python
# Example: Personalization node
def personalize_node(state: GraphState) -> GraphState:
    """Adjust teaching style based on student history"""
    # Analyze past performance
    # Modify presentation style
    # Return updated state
    pass

# Add to graph workflow
graph.add_node("personalize", personalize_node)
graph.add_edge("check", "personalize")
graph.add_edge("personalize", "route_after_check")
```

**3. Customize Prompts:**
```python
# Modify prompts in:
# llm-backend/prompts/templates/teaching_prompt.txt
# llm-backend/prompts/templates/grading_prompt.txt
# llm-backend/prompts/templates/remediation_prompt.txt

# Prompts support template variables:
# {grade}, {topic}, {prefs}, {step_idx}, etc.
```

**4. Switch Database:**
```python
# Current: PostgreSQL
DATABASE_URL = "postgresql://llmuser:password@localhost:5432/tutor"

# Future: MySQL
DATABASE_URL = "mysql://llmuser:password@localhost:3306/tutor"

# Future: SQLite (development)
DATABASE_URL = "sqlite:///tutor.db"
```

---

## Summary

### The Big Picture

**This AI tutor system combines:**
1. **Pedagogical guidelines** (500-2000 word teaching manuals in database)
2. **AI intelligence** (OpenAI gpt-4o-mini for teaching, grading, remediation)
3. **Adaptive workflow** (LangGraph state machine with conditional routing)
4. **Mastery tracking** (EMA formula for smooth progress assessment)
5. **Scaffolding support** (Automatic remediation when students struggle)

### Key Design Principles

**1. Pedagogy-First:**
- Guidelines embedded in database, not hardcoded
- AI reads pedagogical instructions for every decision
- Teaching approach grounded in educational research

**2. Adaptive Intelligence:**
- Conditional routing based on performance
- EMA mastery calculation prevents wild swings
- Different paths for success vs. struggle

**3. Clean Architecture:**
- Repository pattern for data access
- Service layer for business logic
- Graph nodes as pure functions
- Provider pattern for AI services

**4. Graceful Degradation:**
- Fallback responses when AI fails
- Error handling at every layer
- Sessions never crash, always recoverable

### The Magic Numbers

**Remember these 5 constants that control everything:**

```python
MASTERY_EMA_ALPHA = 0.4              # How much recent score matters (40%)
MASTERY_COMPLETION_THRESHOLD = 0.85  # When to end session (85% mastery)
MASTERY_ADVANCE_THRESHOLD = 0.8      # Score to advance (80%)
MIN_CONFIDENCE_FOR_ADVANCE = 0.6     # AI confidence needed (60%)
MAX_STEPS = 10                       # Max questions (10)
```

**Adjust these to change the entire tutoring behavior!**

---

## Quick Reference

### Data Flow (One Sentence Per Step)

1. Student selects subject → topic → subtopic (frontend navigates through curriculum hierarchy)
2. Frontend sends `guideline_id` to backend to create session
3. Backend loads 500-2000 word guideline text from database
4. Present Node uses guideline + AI to generate first question
5. Student answers, frontend sends reply to backend
6. Check Node uses AI to grade response (score + misconception labels)
7. Route decides: score >= 0.8 → advance, else → remediate
8. If advance: increment step, update mastery, generate next question
9. If remediate: provide help, update mastery, retry same question
10. Session ends at 10 steps or 85% mastery, whichever comes first
11. Summary analyzes misconceptions and provides recommendations

### AI Usage (3 Nodes)

| Node | Purpose | Input to AI | Output from AI |
|------|---------|-------------|----------------|
| **Present** | Generate teaching question | Guideline text (500+ words) + history + step | Message + hints |
| **Check** | Grade student response | Student reply + learning objectives + history | Score + rationale + labels + confidence |
| **Remediate** | Provide scaffolding | Misconception labels + score + topic | Explanation + followup question |

---

**End of Documentation**
