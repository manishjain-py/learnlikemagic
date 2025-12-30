"""
Pydantic Schemas for Tutor Workflow

This module defines Pydantic models for validation of all data structures
used in the tutor workflow. These provide:
- Runtime validation
- Type safety
- Clear documentation
- Serialization/deserialization
"""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime


# === Step Status Enum ===
StepStatus = Literal["pending", "in_progress", "completed", "blocked"]
MessageType = Literal["question", "explanation", "encouragement", "hint"]
Difficulty = Literal["easy", "medium", "hard"]


# === Student Profile ===
class StudentProfile(BaseModel):
    """Student information for personalized teaching"""

    interests: List[str] = Field(
        description="Student's interests (e.g., ['dinosaurs', 'video games'])"
    )
    learning_style: str = Field(
        description="Preferred learning style (e.g., 'visual', 'auditory', 'kinesthetic')"
    )
    grade: int = Field(description="Grade level", ge=1, le=12)
    strengths: Optional[List[str]] = Field(
        default=None, description="Known strengths"
    )
    challenges: Optional[List[str]] = Field(
        default=None, description="Known challenges"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "interests": ["dinosaurs", "video games"],
                "learning_style": "visual",
                "grade": 4,
                "strengths": ["quick learner", "creative thinking"],
                "challenges": ["attention span", "complex word problems"],
            }
        }


# === Topic Info ===
class TopicInfo(BaseModel):
    """Information about the learning topic"""

    topic: str = Field(description="Main topic (e.g., 'Fractions')")
    subtopic: str = Field(description="Specific subtopic (e.g., 'Comparing Fractions')")
    grade: int = Field(description="Grade level for content", ge=1, le=12)

    class Config:
        json_schema_extra = {
            "example": {"topic": "Fractions", "subtopic": "Comparing Fractions", "grade": 4}
        }


# === Session Context ===
class SessionContext(BaseModel):
    """Context for the tutoring session"""

    estimated_duration_minutes: int = Field(
        description="Expected session duration in minutes", ge=5, le=120
    )

    class Config:
        json_schema_extra = {"example": {"estimated_duration_minutes": 20}}


# === Step Status Info ===
class StepStatusInfo(BaseModel):
    """Status information for a step"""

    questions_asked: int = Field(default=0, ge=0)
    questions_correct: int = Field(default=0, ge=0)
    attempts: int = Field(default=0, ge=0)
    started_at: Optional[str] = Field(default=None, description="ISO timestamp")
    completed_at: Optional[str] = Field(default=None, description="ISO timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "questions_asked": 3,
                "questions_correct": 2,
                "attempts": 4,
                "started_at": "2024-11-19T14:20:00Z",
                "completed_at": "2024-11-19T14:25:00Z",
            }
        }


# === Step ===
class Step(BaseModel):
    """Individual step in the study plan"""

    step_id: str = Field(description="Unique identifier (UUID)")
    title: str = Field(description="Step title")
    description: str = Field(description="Detailed description of what to teach")
    teaching_approach: str = Field(
        description="How to teach this step (e.g., 'Use pizza slices as visual metaphor')"
    )
    success_criteria: str = Field(
        description="How to determine if step is complete"
    )
    status: StepStatus = Field(
        default="pending", description="Current status of the step"
    )
    status_info: StepStatusInfo = Field(
        default_factory=StepStatusInfo, description="Tracking information"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "step_id": "step_uuid_1",
                "title": "Understanding Numerators and Denominators",
                "description": "Explain what top/bottom numbers mean in fractions",
                "teaching_approach": "Use pizza slices as visual metaphor",
                "success_criteria": "Student can identify numerator vs denominator in 3 examples",
                "status": "completed",
                "status_info": {
                    "questions_asked": 4,
                    "questions_correct": 3,
                    "attempts": 5,
                    "started_at": "2024-11-19T14:20:00Z",
                    "completed_at": "2024-11-19T14:25:00Z",
                },
            }
        }


# === Study Plan Metadata ===
class StudyPlanMetadata(BaseModel):
    """Metadata for the study plan"""

    plan_version: int = Field(default=1, ge=1, description="Increments on replanning")
    estimated_total_questions: int = Field(
        description="Estimated total questions in session", ge=1
    )
    estimated_duration_minutes: int = Field(
        description="Estimated session duration", ge=5
    )
    replan_count: int = Field(default=0, ge=0, description="Number of replans")
    max_replans: int = Field(default=3, ge=1, description="Maximum allowed replans")
    created_at: str = Field(description="ISO timestamp of plan creation")
    last_updated_at: str = Field(description="ISO timestamp of last update")

    class Config:
        json_schema_extra = {
            "example": {
                "plan_version": 1,
                "estimated_total_questions": 10,
                "estimated_duration_minutes": 20,
                "replan_count": 0,
                "max_replans": 3,
                "created_at": "2024-11-19T14:15:00Z",
                "last_updated_at": "2024-11-19T14:25:00Z",
            }
        }


# === Study Plan ===
class StudyPlan(BaseModel):
    """Complete study plan with steps and metadata"""

    todo_list: List[Step] = Field(description="List of learning steps")
    reasoning: str = Field(description="Why this plan was created (deep thinking)")
    metadata: StudyPlanMetadata = Field(description="Plan metadata")
    changes_made: Optional[str] = Field(
        default=None, description="Summary of changes (for replanning)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "todo_list": [
                    {
                        "step_id": "step_uuid_1",
                        "title": "Understanding Numerators",
                        "description": "...",
                        "teaching_approach": "...",
                        "success_criteria": "...",
                        "status": "completed",
                        "status_info": {},
                    }
                ],
                "reasoning": "I designed this plan to start with fundamentals...",
                "metadata": {
                    "plan_version": 1,
                    "estimated_total_questions": 10,
                    "estimated_duration_minutes": 20,
                    "replan_count": 0,
                    "max_replans": 3,
                    "created_at": "2024-11-19T14:15:00Z",
                    "last_updated_at": "2024-11-19T14:15:00Z",
                },
            }
        }


# === Conversation Message ===
class ConversationMessage(BaseModel):
    """A message in the conversation"""

    role: Literal["tutor", "student", "system"] = Field(description="Message sender")
    content: str = Field(description="Message content")
    step_id: Optional[str] = Field(default=None, description="Associated step ID")
    timestamp: str = Field(description="ISO timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "role": "tutor",
                "content": "Which is bigger, 3/8 or 5/8?",
                "step_id": "step_uuid_2",
                "timestamp": "2024-11-19T14:25:00Z",
            }
        }


# === Agent Log Entry ===
class AgentLogEntry(BaseModel):
    """Log entry for an agent execution"""

    agent: Literal["planner", "executor", "evaluator"] = Field(
        description="Which agent executed"
    )
    timestamp: str = Field(description="ISO timestamp")
    input_summary: str = Field(description="Brief summary of input")
    output: Dict[str, Any] = Field(description="Full output JSON")
    reasoning: str = Field(description="Agent's internal reasoning")
    duration_ms: Optional[int] = Field(default=None, description="Execution duration")

    class Config:
        json_schema_extra = {
            "example": {
                "agent": "planner",
                "timestamp": "2024-11-19T14:15:00Z",
                "input_summary": "Initial planning for Fractions session",
                "output": {"todo_list": []},
                "reasoning": "I created this plan because...",
                "duration_ms": 3500,
            }
        }


# === Agent Outputs ===
class PlannerOutput(BaseModel):
    """Output from PLANNER agent"""

    todo_list: List[Step]
    reasoning: str
    metadata: StudyPlanMetadata
    changes_made: Optional[str] = None


class ExecutorOutput(BaseModel):
    """Output from EXECUTOR agent"""

    message: str = Field(description="Message to send to student")
    reasoning: str = Field(description="Why this message")
    step_id: str = Field(description="Which step this addresses")
    question_number: int = Field(description="Question number within step", ge=1)
    meta: Dict[str, str] = Field(
        description="Metadata (message_type, difficulty)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Which is bigger, 3/8 or 5/8?",
                "reasoning": "Student understands numerators, ready for comparison",
                "step_id": "step_uuid_2",
                "question_number": 1,
                "meta": {"message_type": "question", "difficulty": "medium"},
            }
        }


class EvaluatorOutput(BaseModel):
    """Output from EVALUATOR agent"""

    # Evaluation
    score: float = Field(ge=0.0, le=1.0, description="Response score")
    feedback: str = Field(description="Feedback to student")
    reasoning: str = Field(description="Why this score")

    # Step status updates
    updated_step_statuses: Dict[str, StepStatus] = Field(
        description="step_id -> new_status"
    )
    updated_status_info: Dict[str, Dict[str, Any]] = Field(
        description="step_id -> status_info updates"
    )

    # Assessment tracking
    assessment_note: str = Field(description="Timestamped observation to append")

    # Off-topic handling
    was_off_topic: bool = Field(description="Was response off-topic?")
    off_topic_response: Optional[str] = Field(
        default=None, description="Redirect message if off-topic"
    )

    # Replanning decision
    replan_needed: bool = Field(description="Should we replan?")
    replan_reason: Optional[str] = Field(
        default=None, description="Why replanning is needed"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "score": 1.0,
                "feedback": "Excellent! You're absolutely right...",
                "reasoning": "Student correctly identified that 5/8 > 3/8",
                "updated_step_statuses": {"step_uuid_2": "completed"},
                "updated_status_info": {
                    "step_uuid_2": {
                        "questions_asked": 3,
                        "questions_correct": 3,
                        "attempts": 3,
                        "completed_at": "2024-11-19T14:30:00Z",
                    }
                },
                "assessment_note": "2024-11-19 14:30 - Student correctly compared fractions",
                "was_off_topic": False,
                "off_topic_response": None,
                "replan_needed": False,
                "replan_reason": None,
            }
        }


# === API Request/Response Models ===
class CreateSessionRequest(BaseModel):
    """Request to create a new tutoring session"""

    topic: str
    subtopic: str
    grade: int = Field(ge=1, le=12)
    student_profile: StudentProfile
    session_context: SessionContext


class CreateSessionResponse(BaseModel):
    """Response after creating a session"""

    session_id: str
    study_plan: StudyPlan
    first_message: str
    status: Literal["active", "completed", "needs_intervention"]


class SubmitResponseRequest(BaseModel):
    """Request to submit student response"""

    student_reply: str


class SubmitResponseResponse(BaseModel):
    """Response after submitting student response"""

    feedback: str
    score: float
    next_message: Optional[str]
    session_status: Literal["active", "completed", "needs_intervention"]
    plan_updated: bool
    replan_reason: Optional[str] = None
    current_progress: Dict[str, int]


class SessionStatusResponse(BaseModel):
    """Response for session status query"""

    session_id: str
    status: Literal["active", "completed", "needs_intervention"]
    study_plan: StudyPlan
    progress: Dict[str, Any]
    assessment_notes: str
    current_step: Optional[Step]
    agent_logs: List[AgentLogEntry]
