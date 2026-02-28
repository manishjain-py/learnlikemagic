"""Session management business logic — new single-agent architecture."""

import json
import logging
from typing import Optional, List
from sqlalchemy import update
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
from shared.utils.exceptions import SessionNotFoundException, GuidelineNotFoundException, StaleStateError

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

        # Initialize LLM service — read config from DB (once at session start)
        from shared.services.llm_config_service import LLMConfigService
        settings = get_settings()
        tutor_config = LLMConfigService(db).get_config("tutor")
        self.llm_service = LLMService(
            api_key=settings.openai_api_key,
            provider=tutor_config["provider"],
            model_id=tutor_config["model_id"],
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        )
        self.orchestrator = TeacherOrchestrator(self.llm_service)

    def create_new_session(self, request: CreateSessionRequest, user_id: Optional[str] = None) -> CreateSessionResponse:
        """Create a new learning session with mode support."""
        mode = request.mode if hasattr(request, 'mode') else "teach_me"

        # Validate guideline exists
        guideline = self.guideline_repo.get_guideline_by_id(request.goal.guideline_id)
        if not guideline:
            raise GuidelineNotFoundException(request.goal.guideline_id)

        # Guard: prevent duplicate incomplete exams for same user+guideline
        if mode == "exam" and user_id and request.goal.guideline_id:
            existing = self._find_incomplete_session(user_id, request.goal.guideline_id, "exam")
            if existing:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "An incomplete exam already exists for this topic",
                        "existing_session_id": existing,
                    },
                )

        # Load study plan from DB if available
        study_plan_record = (
            self.db.query(StudyPlanRecord)
            .filter(StudyPlanRecord.guideline_id == request.goal.guideline_id)
            .first()
        )

        # Convert DB guideline to new Topic model
        topic = convert_guideline_to_topic(guideline, study_plan_record)

        # Create student context
        if user_id:
            student_context = self._build_student_context_from_profile(user_id, request)
        else:
            student_context = StudentContext(
                grade=request.student.grade,
                board=request.goal.syllabus.split(" ")[0] if request.goal.syllabus else "CBSE",
                language_level="simple" if request.student.grade <= 5 else "standard",
            )

        # Create mode-specific session
        session = create_session(topic=topic, student_context=student_context, mode=mode)
        session_id = str(uuid4())
        session.session_id = session_id

        logger.info(f"Created session {session_id} for topic {topic.topic_name} mode={mode}")

        # For exam mode, generate questions before welcome (sync call)
        import asyncio
        if mode == "exam":
            from tutor.services.exam_service import ExamService
            exam_svc = ExamService(self.llm_service)
            session.exam_questions = exam_svc.generate_questions(session)
            logger.info(f"Generated {len(session.exam_questions)} exam questions for session {session_id}")

        # Generate mode-specific welcome
        if mode == "clarify_doubts":
            welcome = asyncio.run(self.orchestrator.generate_clarify_welcome(session))
        elif mode == "exam":
            welcome = asyncio.run(self.orchestrator.generate_exam_welcome(session))
            # Append first question to welcome
            if session.exam_questions:
                first_q = session.exam_questions[0]
                welcome = f"{welcome}\n\n**Question 1:** {first_q.question_text}"
        else:
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
            payload={"action": "session_created", "mode": mode},
        )

        first_turn = {
            "message": welcome,
            "hints": [],
            "step_idx": session.current_step,
        }
        if mode == "exam":
            first_turn["exam_progress"] = {
                "current_question": 1,
                "total_questions": len(session.exam_questions),
                "answered_questions": 0,
            }
            first_turn["exam_questions"] = [
                {"question_idx": q.question_idx, "question_text": q.question_text}
                for q in session.exam_questions
            ]

        # Build response
        response = CreateSessionResponse(session_id=session_id, first_turn=first_turn, mode=mode)

        # For clarify_doubts, include past discussions
        if mode == "clarify_doubts" and user_id and request.goal.guideline_id:
            past = self._get_past_discussions(user_id, request.goal.guideline_id)
            if past:
                response.past_discussions = past

        return response

    def process_step(self, session_id: str, request: StepRequest) -> StepResponse:
        """Process a student's answer using the new orchestrator."""
        # Load session from DB
        db_session = self.session_repo.get_by_id(session_id)
        if not db_session:
            raise SessionNotFoundException(session_id)

        expected_version = db_session.state_version or 1

        # Deserialize SessionState
        session = SessionState.model_validate_json(db_session.state_json)

        # Process turn via orchestrator
        import asyncio
        turn_result = asyncio.run(
            self.orchestrator.process_turn(session, request.student_reply)
        )

        # Update database with version check
        self._persist_session_state(session_id, session, expected_version)

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
            "audio_text": turn_result.audio_text,
            "hints": [],
            "step_idx": session.current_step,
            "mastery_score": session.overall_mastery,
            "is_complete": session.exam_finished if session.mode == "exam" else session.is_complete,
        }

        if session.mode == "exam":
            next_turn["exam_progress"] = {
                "current_question": min(session.exam_current_question_idx + 1, len(session.exam_questions)),
                "total_questions": len(session.exam_questions),
                "answered_questions": session.exam_current_question_idx,
            }
            if session.exam_finished and session.exam_feedback:
                next_turn["exam_feedback"] = session.exam_feedback.model_dump()
                next_turn["exam_results"] = [
                    {
                        "question_idx": q.question_idx,
                        "question_text": q.question_text,
                        "student_answer": q.student_answer,
                        "result": q.result,
                        "score": q.score,
                        "marks_rationale": q.marks_rationale,
                        "feedback": q.feedback,
                        "expected_answer": q.expected_answer,
                    }
                    for q in session.exam_questions
                ]

        # Include clarify_doubts-specific data
        if session.mode == "clarify_doubts":
            next_turn["concepts_discussed"] = session.concepts_discussed

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
            mode=session.mode,
            guideline_id=request.goal.guideline_id,
            state_version=1,
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
            db_record.mode = session.mode
            db_record.is_paused = session.is_paused if session.mode == "teach_me" else False
            db_record.updated_at = datetime.utcnow()
            self.db.commit()

    def _persist_session_state(
        self, session_id: str, session: SessionState, expected_version: int
    ) -> None:
        """Single transactional write for all session state.
        Raises StaleStateError if state_version doesn't match."""
        from shared.models.entities import Session as SessionModel
        from datetime import datetime

        result = self.db.execute(
            update(SessionModel)
            .where(
                SessionModel.id == session_id,
                SessionModel.state_version == expected_version,
            )
            .values(
                state_json=session.model_dump_json(),
                mastery=session.overall_mastery,
                step_idx=session.current_step,
                state_version=expected_version + 1,
                mode=session.mode,
                is_paused=session.is_paused if session.mode == "teach_me" else False,
                exam_score=session.exam_total_correct if session.mode == "exam" and session.exam_finished else None,
                exam_total=len(session.exam_questions) if session.mode == "exam" and session.exam_finished else None,
                updated_at=datetime.utcnow(),
            )
        )
        if result.rowcount == 0:
            self.db.rollback()
            raise StaleStateError(f"Session {session_id} was modified concurrently (expected version {expected_version})")
        self.db.commit()

    def pause_session(self, session_id: str) -> dict:
        """Pause a Teach Me session with version-safe persistence."""
        db_session = self.session_repo.get_by_id(session_id)
        if not db_session:
            raise SessionNotFoundException(session_id)
        expected_version = db_session.state_version or 1

        session = SessionState.model_validate_json(db_session.state_json)
        session.is_paused = True

        self._persist_session_state(session_id, session, expected_version)

        return {
            "coverage": session.coverage_percentage,
            "concepts_covered": list(session.concepts_covered_set),
            "message": f"You've covered {session.coverage_percentage:.0f}% so far. You can pick up where you left off anytime.",
        }

    def resume_session(self, session_id: str) -> dict:
        """Resume a paused session with version-safe persistence."""
        db_session = self.session_repo.get_by_id(session_id)
        if not db_session:
            raise SessionNotFoundException(session_id)
        expected_version = db_session.state_version or 1

        session = SessionState.model_validate_json(db_session.state_json)
        session.is_paused = False

        self._persist_session_state(session_id, session, expected_version)

        # Return conversation history for chat replay
        history = [
            {"role": m.role, "content": m.content}
            for m in session.full_conversation_log
        ]

        return {
            "session_id": session_id,
            "message": "Session resumed",
            "current_step": session.current_step,
            "conversation_history": history,
        }

    def end_clarify_session(self, session_id: str) -> dict:
        """End a Clarify Doubts session with version-safe persistence."""
        db_session = self.session_repo.get_by_id(session_id)
        if not db_session:
            raise SessionNotFoundException(session_id)
        expected_version = db_session.state_version or 1

        session = SessionState.model_validate_json(db_session.state_json)
        session.clarify_complete = True

        self._persist_session_state(session_id, session, expected_version)

        return {
            "concepts_discussed": session.concepts_discussed,
            "message": "Doubts session ended successfully.",
        }

    def end_exam(self, session_id: str) -> dict:
        """End an exam early with version-safe persistence."""
        from tutor.orchestration.orchestrator import TeacherOrchestrator

        db_session = self.session_repo.get_by_id(session_id)
        if not db_session:
            raise SessionNotFoundException(session_id)
        expected_version = db_session.state_version or 1

        session = SessionState.model_validate_json(db_session.state_json)
        session.exam_finished = True
        session.exam_feedback = TeacherOrchestrator._build_exam_feedback(session)

        self._persist_session_state(session_id, session, expected_version)

        total = len(session.exam_questions)
        total_score = round(sum(q.score for q in session.exam_questions), 1)
        return {
            "score": total_score,
            "total": total,
            "percentage": round(total_score / total * 100, 1) if total else 0.0,
            "feedback": session.exam_feedback.model_dump() if session.exam_feedback else None,
        }

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

    def _find_incomplete_session(self, user_id: str, guideline_id: str, mode: str) -> Optional[str]:
        """Find an incomplete session with actual progress for user+guideline+mode.

        Returns session_id or None. Skips orphaned sessions with zero progress
        (e.g. exam with 0 answers, teach_me with 0% coverage) so they don't
        block new session creation.
        """
        sessions = self.session_repo.list_by_guideline(
            user_id=user_id, guideline_id=guideline_id, mode=mode,
        )
        for s in sessions:
            if s["is_complete"]:
                continue
            # Skip zero-progress orphaned sessions
            if mode == "exam" and (s.get("exam_answered") or 0) == 0:
                continue
            if mode == "teach_me" and (s.get("coverage") or 0) == 0:
                continue
            return s["session_id"]
        return None

    def _get_past_discussions(self, user_id: str, guideline_id: str) -> list[dict]:
        """Get past Clarify Doubts sessions for this user + guideline."""
        from shared.models.entities import Session as SessionModel

        rows = (
            self.db.query(SessionModel)
            .filter(
                SessionModel.user_id == user_id,
                SessionModel.guideline_id == guideline_id,
                SessionModel.mode == "clarify_doubts",
            )
            .order_by(SessionModel.created_at.desc())
            .limit(5)
            .all()
        )

        results = []
        for row in rows:
            try:
                state = json.loads(row.state_json)
                concepts = state.get("concepts_discussed", [])
                if concepts:
                    results.append({
                        "session_date": row.created_at.isoformat() if row.created_at else None,
                        "concepts_discussed": concepts,
                    })
            except (json.JSONDecodeError, TypeError):
                continue
        return results
