"""Session management business logic — new single-agent architecture."""

import json
import logging
from typing import Optional, List
from sqlalchemy.orm import Session as DBSession
from uuid import uuid4

from config import get_settings
from shared.models import (
    CreateSessionRequest,
    CreateSessionResponse,
    StepRequest,
    StepResponse,
    SummaryResponse,
    GradingResult,
)
from shared.models.entities import StudyPlan as StudyPlanRecord
from shared.repositories import SessionRepository, EventRepository, TeachingGuidelineRepository
from shared.services.llm_service import LLMService
from shared.utils.exceptions import SessionNotFoundException, GuidelineNotFoundException

from tutor.orchestration import TeacherOrchestrator
from tutor.models.session_state import SessionState, create_session
from tutor.models.messages import StudentContext, create_teacher_message
from tutor.services.topic_adapter import convert_guideline_to_topic

logger = logging.getLogger("tutor.session_service")


class SessionService:
    """Orchestrates session creation, step processing, and summary generation."""

    def __init__(self, db: DBSession):
        self.db = db
        self.session_repo = SessionRepository(db)
        self.event_repo = EventRepository(db)
        self.guideline_repo = TeachingGuidelineRepository(db)

        # Initialize LLM service and orchestrator
        settings = get_settings()
        self.llm_service = LLMService(
            api_key=settings.openai_api_key,
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
            provider=settings.resolved_tutor_provider,
        )
        self.orchestrator = TeacherOrchestrator(self.llm_service)

    def create_new_session(self, request: CreateSessionRequest, user_id: Optional[str] = None) -> CreateSessionResponse:
        """Create a new learning session with the new tutor architecture."""
        # Validate guideline exists
        guideline = self.guideline_repo.get_guideline_by_id(request.goal.guideline_id)
        if not guideline:
            raise GuidelineNotFoundException(request.goal.guideline_id)

        # Load study plan from DB if available
        study_plan_record = (
            self.db.query(StudyPlanRecord)
            .filter(StudyPlanRecord.guideline_id == request.goal.guideline_id)
            .first()
        )

        # Convert DB guideline to new Topic model
        topic = convert_guideline_to_topic(guideline, study_plan_record)

        # Create student context — use profile data if authenticated
        if user_id:
            student_context = self._build_student_context_from_profile(user_id, request)
        else:
            student_context = StudentContext(
                grade=request.student.grade,
                board=request.goal.syllabus.split(" ")[0] if request.goal.syllabus else "CBSE",
                language_level="simple" if request.student.grade <= 5 else "standard",
            )

        # Create SessionState
        session = create_session(topic=topic, student_context=student_context)
        session_id = str(uuid4())
        session.session_id = session_id

        logger.info(f"Created session {session_id} for topic {topic.topic_name}")

        # Generate welcome message
        import asyncio
        welcome = asyncio.run(self.orchestrator.generate_welcome_message(session))

        # Add welcome message to conversation history
        session.add_message(create_teacher_message(welcome))

        # Persist to DB
        self._persist_session(session_id, session, request, user_id=user_id, subject=guideline.subject if guideline else None)

        # Log event
        self.event_repo.log(
            session_id=session_id,
            node="welcome",
            step_idx=session.current_step,
            payload={"action": "session_created"},
        )

        first_turn = {
            "message": welcome,
            "hints": [],
            "step_idx": session.current_step,
        }

        return CreateSessionResponse(session_id=session_id, first_turn=first_turn)

    def process_step(self, session_id: str, request: StepRequest) -> StepResponse:
        """Process a student's answer using the new orchestrator."""
        # Load session from DB
        db_session = self.session_repo.get_by_id(session_id)
        if not db_session:
            raise SessionNotFoundException(session_id)

        # Deserialize SessionState
        session = SessionState.model_validate_json(db_session.state_json)

        # Process turn via orchestrator
        import asyncio
        turn_result = asyncio.run(
            self.orchestrator.process_turn(session, request.student_reply)
        )

        # Update database
        self._update_session_db(session_id, session)

        # Log event
        self.event_repo.log(
            session_id=session_id,
            node="turn",
            step_idx=session.current_step,
            payload={
                "intent": turn_result.intent,
                "state_changed": turn_result.state_changed,
            },
        )

        # Build response (maintain same REST contract)
        next_turn = {
            "message": turn_result.response,
            "hints": [],
            "step_idx": session.current_step,
            "mastery_score": session.overall_mastery,
            "is_complete": session.is_complete,
        }

        # Map intent to routing for backward compatibility
        routing = "Advance" if turn_result.intent == "continuation" else "Continue"

        # Build grading result if answer was evaluated
        last_grading = None
        if turn_result.intent == "answer":
            logs = self.orchestrator.agent_logs.get_recent_logs(session.session_id, limit=1)
            if logs:
                output = logs[-1].output or {}
                answer_correct = output.get("answer_correct")
                if answer_correct is not None:
                    last_grading = GradingResult(
                        score=0.9 if answer_correct else 0.3,
                        rationale=output.get("reasoning", ""),
                        labels=output.get("misconceptions_detected", []),
                        confidence=0.8,
                    )

        return StepResponse(
            next_turn=next_turn,
            routing=routing,
            last_grading=last_grading,
        )

    def get_summary(self, session_id: str) -> SummaryResponse:
        """Generate session summary."""
        db_session = self.session_repo.get_by_id(session_id)
        if not db_session:
            raise SessionNotFoundException(session_id)

        session = SessionState.model_validate_json(db_session.state_json)

        misconceptions_seen = [m.description for m in session.misconceptions]
        suggestions = self._generate_suggestions(session, misconceptions_seen)

        return SummaryResponse(
            steps_completed=session.current_step - 1,
            mastery_score=round(session.overall_mastery, 2),
            misconceptions_seen=misconceptions_seen,
            suggestions=suggestions,
        )

    def _persist_session(
        self,
        session_id: str,
        session: SessionState,
        request: CreateSessionRequest,
        user_id: Optional[str] = None,
        subject: Optional[str] = None,
    ) -> None:
        """Persist new session to DB using existing schema."""
        from shared.models.entities import Session as SessionModel
        from datetime import datetime

        db_record = SessionModel(
            id=session_id,
            student_json=request.student.model_dump_json(),
            goal_json=request.goal.model_dump_json(),
            state_json=session.model_dump_json(),
            mastery=session.overall_mastery,
            step_idx=session.current_step,
            user_id=user_id,
            subject=subject,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.db.add(db_record)
        self.db.commit()
        self.db.refresh(db_record)

    def _build_student_context_from_profile(self, user_id: str, request: CreateSessionRequest) -> StudentContext:
        """Build StudentContext from user profile data when authenticated."""
        from auth.repositories.user_repository import UserRepository
        user_repo = UserRepository(self.db)
        user = user_repo.get_by_id(user_id)
        if user and user.grade and user.board:
            return StudentContext(
                grade=user.grade,
                board=user.board,
                language_level="simple" if (user.age and user.age <= 10) else "standard",
                student_name=user.name,
                student_age=user.age,
                about_me=user.about_me,
            )
        # Fallback to request data if profile is incomplete
        return StudentContext(
            grade=request.student.grade,
            board=request.goal.syllabus.split(" ")[0] if request.goal.syllabus else "CBSE",
            language_level="simple" if request.student.grade <= 5 else "standard",
        )

    def _update_session_db(self, session_id: str, session: SessionState) -> None:
        """Update existing session in DB."""
        from shared.models.entities import Session as SessionModel
        from datetime import datetime

        db_record = self.db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if db_record:
            db_record.state_json = session.model_dump_json()
            db_record.mastery = session.overall_mastery
            db_record.step_idx = session.current_step
            db_record.updated_at = datetime.utcnow()
            self.db.commit()

    def _generate_suggestions(
        self,
        session: SessionState,
        misconceptions: List[str],
    ) -> List[str]:
        suggestions = []
        mastery = session.overall_mastery
        topic_name = session.topic.topic_name if session.topic else "the topic"

        if mastery >= 0.85:
            suggestions.append(f"Excellent work on {topic_name}!")
            suggestions.append("You're ready to move to more advanced topics.")
        elif mastery >= 0.7:
            suggestions.append("Good progress! Try 3-5 more practice problems.")
        else:
            suggestions.append("Keep practicing! Review the examples.")
            suggestions.append(f"Revisit the concepts around {topic_name}")

        if misconceptions:
            top = misconceptions[:2]
            suggestions.append(f"Work on understanding: {', '.join(top)}")

        return suggestions
