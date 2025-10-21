"""
LangGraph state definition and prompt templates.
"""
from typing import TypedDict, List, Dict, Any, Optional
from models import TutorState, GradingResult, HistoryEntry, RAGSnippet


# LangGraph compatible state (TypedDict for better compatibility)
class GraphState(TypedDict):
    """State object for LangGraph - compatible with TypedDict requirements."""
    session_id: str
    student: Dict[str, Any]  # {id, grade, prefs}
    goal: Dict[str, Any]     # {topic, syllabus, learning_objectives, guideline_id}
    step_idx: int
    history: List[Dict[str, Any]]
    evidence: List[str]
    mastery_score: float
    last_grading: Optional[Dict[str, Any]]
    next_action: Optional[str]
    # Additional fields for node communication
    current_student_reply: Optional[str]
    teaching_guideline: Optional[str]  # Full guideline text for teaching


# Prompt templates for each node

PRESENT_SYSTEM_PROMPT = """You are a Grade {grade} tutor specializing in {topic}.

Your task is to present a teaching step or pose a question to the student, following the pedagogical guidelines provided.

Input context:
- Topic: {topic}
- Grade: {grade}
- Student preferences: {prefs}
- Current step: {step_idx}/10
- Conversation history (what has been said so far)
- Teaching guideline (detailed pedagogical instructions - follow these carefully)

Output JSON format:
{{
  "message": "Your teaching message or question (≤80 words, clear, friendly, grade-appropriate)",
  "hints": ["Optional hint 1", "Optional hint 2"],
  "expected_answer_form": "short_text|number|mcq"
}}

Guidelines:
- FOLLOW THE TEACHING GUIDELINE PROVIDED: It contains specific instructions on how to teach this topic, common misconceptions to address, and scaffolding strategies
- IMPORTANT: Review the conversation history and build on what was already discussed
- Acknowledge student's previous answers when appropriate (e.g., "Great!", "Good job!", "Let's try again")
- CRITICAL: Vary your question types and increase complexity as step_idx increases:
  * Steps 0-2: Start with concrete examples and simple questions as per guideline
  * Steps 3-5: Move to intermediate complexity questions
  * Steps 6-7: Include reasoning and explanation questions
  * Steps 8-9: Apply concepts to real-world scenarios
- Avoid asking the same type of question repeatedly
- Be encouraging and conversational
- Use age-appropriate language for Grade {grade}
- Ask one focused question or teach one concept per turn
- Use the scaffolding strategies mentioned in the guideline when appropriate
- Address common misconceptions proactively as mentioned in the guideline
"""

CHECK_SYSTEM_PROMPT = """You are a grading assistant for a Grade {grade} tutor.

Your task is to evaluate the student's response for understanding of: {topic}

IMPORTANT: You will receive the conversation history showing what the teacher asked.
The student's reply should be evaluated IN CONTEXT of what was asked.

Consider:
- Correctness of the answer in context of the question asked
- Presence of misconceptions
- Partial understanding
- Be lenient with Grade {grade} students - if the answer is correct relative to the question, give high score

Student's reply: {reply}

Output JSON format:
{{
  "score": 0.0-1.0,
  "rationale": "Brief explanation of why this score was given",
  "labels": ["misconception_X", "confusion_Y", etc.],
  "confidence": 0.0-1.0
}}

Score bands (be GENEROUS for Grade {grade} students):
- 0.9-1.0: Excellent understanding (answer is correct for what was asked, even if terse)
- 0.7-0.89: Good understanding with minor gaps (mostly correct but missing details)
- 0.5-0.69: Partial understanding (on the right track)
- 0.3-0.49: Significant misconceptions (wrong concept)
- 0.0-0.29: Minimal understanding (completely off-topic)

IMPORTANT: If the student provides a correct answer to the question asked (even if brief), give 0.9-1.0. Don't penalize for brevity.

Labels should identify specific misconceptions or confusion patterns.
"""

REMEDIATE_SYSTEM_PROMPT = """You are a patient tutor helping a Grade {grade} student who is struggling.

The student showed these issues: {labels}

Your task is to provide:
1. A short, gentle explanation to clarify the misconception (≤60 words)
2. One focused follow-up question to check understanding

Output JSON format:
{{
  "message": "Your clarifying explanation",
  "followup": "Your follow-up question"
}}

Guidelines:
- Be encouraging and supportive
- Use concrete examples or analogies
- Avoid overwhelming with too much information
- Focus on one key concept at a time
- Use age-appropriate language
"""


# Helper functions for state conversion

def tutor_state_to_graph_state(tutor_state: TutorState) -> GraphState:
    """Convert TutorState Pydantic model to GraphState TypedDict."""
    return GraphState(
        session_id=tutor_state.session_id,
        student=tutor_state.student.model_dump(),
        goal=tutor_state.goal.model_dump(),
        step_idx=tutor_state.step_idx,
        history=[h.model_dump() for h in tutor_state.history],
        evidence=tutor_state.evidence,
        mastery_score=tutor_state.mastery_score,
        last_grading=tutor_state.last_grading.model_dump() if tutor_state.last_grading else None,
        next_action=tutor_state.next_action,
        current_student_reply=None,
        teaching_guideline=None
    )


def graph_state_to_tutor_state(graph_state: GraphState) -> TutorState:
    """Convert GraphState TypedDict back to TutorState Pydantic model."""
    from models import Student, Goal, HistoryEntry, GradingResult

    return TutorState(
        session_id=graph_state["session_id"],
        student=Student(**graph_state["student"]),
        goal=Goal(**graph_state["goal"]),
        step_idx=graph_state["step_idx"],
        history=[HistoryEntry(**h) for h in graph_state["history"]],
        evidence=graph_state["evidence"],
        mastery_score=graph_state["mastery_score"],
        last_grading=GradingResult(**graph_state["last_grading"]) if graph_state.get("last_grading") else None,
        next_action=graph_state.get("next_action")
    )


# Routing logic helpers

def should_remediate(state: GraphState) -> bool:
    """Determine if student needs remediation based on last grading."""
    if not state.get("last_grading"):
        return False

    score = state["last_grading"]["score"]
    confidence = state["last_grading"]["confidence"]

    # Remediate if score < 0.8 or low confidence
    return score < 0.8 or confidence < 0.6


def should_end(state: GraphState) -> bool:
    """Determine if session should end."""
    return state["step_idx"] >= 10 or state["mastery_score"] >= 0.85
