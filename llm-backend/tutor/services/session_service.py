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
from tutor.models.session_state import SessionState, CardPhaseState, create_session
from tutor.models.messages import StudentContext, create_teacher_message
from tutor.services.topic_adapter import convert_guideline_to_topic
from shared.repositories.explanation_repository import ExplanationRepository

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
        from shared.services.feature_flag_service import FeatureFlagService
        settings = get_settings()
        config_service = LLMConfigService(db)
        tutor_config = config_service.get_config("tutor")
        fast_config = config_service.get_config("fast_model")
        self.llm_service = LLMService(
            api_key=settings.openai_api_key,
            provider=tutor_config["provider"],
            model_id=tutor_config["model_id"],
            fast_model_id=fast_config["model_id"],
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        )
        visuals_enabled = FeatureFlagService(db).is_enabled("show_visuals_in_tutor_flow")
        self.orchestrator = TeacherOrchestrator(self.llm_service, visuals_enabled=visuals_enabled)

    def create_new_session(self, request: CreateSessionRequest, user_id: Optional[str] = None) -> CreateSessionResponse:
        """Create a new learning session with mode support."""
        mode = request.mode if hasattr(request, 'mode') else "teach_me"

        # Validate guideline exists
        guideline = self.guideline_repo.get_guideline_by_id(request.goal.guideline_id)
        if not guideline:
            raise GuidelineNotFoundException(request.goal.guideline_id)

        # Detect refresher topic
        is_refresher = bool(guideline.metadata and guideline.metadata.is_refresher)

        if is_refresher and mode != "teach_me":
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Refresher topics only support Teach Me mode")

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

        # Build student context FIRST (needed for personalized plan generation)
        if user_id:
            student_context = self._build_student_context_from_profile(user_id, request)
        else:
            student_context = StudentContext(
                grade=request.student.grade,
                board=request.goal.syllabus.split(" ")[0] if request.goal.syllabus else "CBSE",
                language_level="simple" if request.student.grade <= 5 else "standard",
            )

        # Load personalized study plan from DB — teach_me doesn't need one
        # (pre-computed explanation cards ARE the lesson), but other modes may.
        study_plan_record = None
        if mode != "teach_me":
            if user_id:
                study_plan_record = (
                    self.db.query(StudyPlanRecord)
                    .filter(
                        StudyPlanRecord.user_id == user_id,
                        StudyPlanRecord.guideline_id == request.goal.guideline_id,
                    )
                    .first()
                )
            if not study_plan_record:
                study_plan_record = (
                    self.db.query(StudyPlanRecord)
                    .filter(StudyPlanRecord.guideline_id == request.goal.guideline_id)
                    .first()
                )

        # Convert DB guideline to new Topic model
        topic = convert_guideline_to_topic(guideline, study_plan_record, is_refresher=is_refresher)

        # Practice mode has its own creation flow — context resolution + practice plan + dynamic welcome
        if mode == "practice":
            return self._create_practice_session(
                request=request,
                user_id=user_id,
                guideline=guideline,
                topic=topic,
                student_context=student_context,
            )

        # Create mode-specific session
        session = create_session(topic=topic, student_context=student_context, mode=mode)
        session_id = str(uuid4())
        session.session_id = session_id
        session.is_refresher = is_refresher

        logger.info(f"Created session {session_id} for topic {topic.topic_name} mode={mode} is_refresher={is_refresher}")

        import asyncio

        # Check for pre-computed explanations (teach_me mode only)
        explanations = []
        if mode == "teach_me":
            try:
                explanation_repo = ExplanationRepository(self.db)
                explanations = explanation_repo.get_by_guideline_id(request.goal.guideline_id)
            except Exception:
                explanations = []

        if explanations and mode == "teach_me":
            # Card phase: skip welcome LLM call AND explanation phase init
            # Use first available variant (don't assume "A" exists — it may have failed validation)
            first_variant = explanations[0]

            session.card_phase = CardPhaseState(
                guideline_id=request.goal.guideline_id,
                active=True,
                current_variant_key=first_variant.variant_key,
                current_card_idx=0,
                total_cards=len(first_variant.cards_json),
                variants_shown=[first_variant.variant_key],
                available_variant_keys=[e.variant_key for e in explanations],
            )

            # Welcome is the first card (card_type="welcome") — use its content for the message
            first_card = first_variant.cards_json[0] if first_variant.cards_json else {}
            welcome = first_card.get("content", "")
            audio_text = first_card.get("audio_text", welcome)

            first_turn = {
                "message": welcome,
                "audio_text": audio_text,
                "hints": [],
                "step_idx": session.current_step,
                "total_steps": session.topic.study_plan.total_steps if session.topic else 0,
                # Card phase fields
                "explanation_cards": first_variant.cards_json,
                "session_phase": "card_phase",
                "card_phase_state": {
                    "current_variant_key": first_variant.variant_key,
                    "current_card_idx": 0,
                    "total_cards": len(first_variant.cards_json),
                    "available_variants": len(explanations),
                },
            }
            logger.info(f"Card phase initialized for session {session_id}: variant={first_variant.variant_key}, cards={len(first_variant.cards_json)}")
        else:
            # Existing path: init explanation phase + dynamic welcome
            if mode == "teach_me":
                first_step = session.topic.study_plan.get_step(1) if session.topic else None
                if first_step and first_step.type == "explain":
                    session.start_explanation(first_step.concept, first_step.step_id)

            # For exam mode, generate questions before welcome
            if mode == "exam":
                from tutor.services.exam_service import ExamService
                exam_svc = ExamService(self.llm_service)
                session.exam_questions = exam_svc.generate_questions(session)
                logger.info(f"Generated {len(session.exam_questions)} exam questions for session {session_id}")

            # Generate mode-specific welcome
            if mode == "clarify_doubts":
                welcome, audio_text = asyncio.run(self.orchestrator.generate_clarify_welcome(session))
            elif mode == "exam":
                welcome, audio_text = asyncio.run(self.orchestrator.generate_exam_welcome(session))
                if session.exam_questions:
                    first_q = session.exam_questions[0]
                    welcome = f"{welcome}\n\n**Question 1:** {first_q.question_text}"
            else:
                welcome, audio_text = asyncio.run(self.orchestrator.generate_welcome_message(session))

            first_turn = {
                "message": welcome,
                "audio_text": audio_text,
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

        # Steps 5-8 happen for BOTH paths (card phase and dynamic):
        session.add_message(create_teacher_message(welcome, audio_text=audio_text))

        self._persist_session(session_id, session, request, user_id=user_id, subject=guideline.subject if guideline else None)

        self.event_repo.log(
            session_id=session_id,
            node="welcome",
            step_idx=session.current_step,
            payload={"action": "session_created", "mode": mode},
        )

        # Build response
        response = CreateSessionResponse(session_id=session_id, first_turn=first_turn, mode=mode)

        # For clarify_doubts, include past discussions
        if mode == "clarify_doubts" and user_id and request.goal.guideline_id:
            past = self._get_past_discussions(user_id, request.goal.guideline_id)
            if past:
                response.past_discussions = past

        return response

    def _create_practice_session(
        self,
        request: CreateSessionRequest,
        user_id: Optional[str],
        guideline,
        topic,
        student_context: StudentContext,
    ) -> CreateSessionResponse:
        """Create a Let's Practice session.

        Flow:
        1. Resolve practice context (explicit source, auto-attach, or cold start)
        2. Generate a practice-focused study plan (question-heavy, no explain steps)
        3. Replace topic.study_plan with the practice plan
        4. Create SessionState with mode='practice' and seeded mastery
        5. Generate dynamic practice welcome
        6. Persist and return first turn
        """
        import asyncio

        source_session_id = getattr(request, "source_session_id", None)
        context_data = self._resolve_practice_context(
            user_id, request.goal.guideline_id, source_session_id
        )

        # Generate a practice-specific plan. On failure, keep the existing plan
        # from the topic so the session can still start (non-fatal fallback).
        practice_plan = self._generate_practice_plan_for_session(
            guideline=guideline,
            student_context=student_context,
            context_data=context_data,
        )
        if practice_plan is not None and practice_plan.steps:
            topic.study_plan = practice_plan
        else:
            logger.warning(
                "Practice plan generation failed — falling back to the existing "
                "topic study plan for session creation."
            )

        # Create session with mode='practice' — create_session will seed mastery
        session = create_session(topic=topic, student_context=student_context, mode="practice")
        session_id = str(uuid4())
        session.session_id = session_id
        session.practice_source = context_data["source"]
        session.source_session_id = context_data.get("source_session_id")

        # Inject the explanation summary for post-Teach-Me practice sessions.
        # The system prompt builder reads this and renders the explanation context section.
        if context_data.get("explanation_summary"):
            session.precomputed_explanation_summary = context_data["explanation_summary"]

        logger.info(
            f"Created practice session {session_id} for topic {topic.topic_name} "
            f"source={context_data['source']} source_session_id={context_data.get('source_session_id')}"
        )

        # Generate dynamic practice welcome (skips card phase, straight to first question)
        welcome, audio_text = asyncio.run(
            self.orchestrator.generate_practice_welcome(session)
        )
        session.add_message(create_teacher_message(welcome, audio_text=audio_text))

        first_turn = {
            "message": welcome,
            "audio_text": audio_text,
            "hints": [],
            "step_idx": session.current_step,
            "session_phase": "interactive",  # practice skips card phase
        }

        self._persist_session(
            session_id, session, request,
            user_id=user_id,
            subject=guideline.subject if guideline else None,
        )

        self.event_repo.log(
            session_id=session_id,
            node="welcome",
            step_idx=session.current_step,
            payload={
                "action": "session_created",
                "mode": "practice",
                "practice_source": context_data["source"],
            },
        )

        return CreateSessionResponse(
            session_id=session_id,
            first_turn=first_turn,
            mode="practice",
        )

    def _resolve_practice_context(
        self,
        user_id: Optional[str],
        guideline_id: str,
        source_session_id: Optional[str] = None,
    ) -> dict:
        """Resolve context for a practice session (FR-19, FR-21, FR-22).

        Priority:
        1. Explicit source_session_id (from Teach Me CTA handoff)
        2. Auto-detect most recent completed Teach Me session
        3. Cold start (no context)

        Reads all required data points directly from the source session's
        CardPhaseState — no new storage needed.
        """
        source_state = None

        if source_session_id:
            # Explicit handoff from Teach Me CTA
            db_row = self.session_repo.get_by_id(source_session_id)
            if db_row:
                try:
                    source_state = SessionState.model_validate_json(db_row.state_json)
                except Exception as e:
                    logger.warning(
                        f"Failed to load explicit source session {source_session_id}: {e}"
                    )
        elif user_id:
            # Auto-attach from most recent completed Teach Me (FR-21)
            source_state = self.session_repo.find_most_recent_completed_teach_me(
                user_id, guideline_id
            )

        if source_state is None or source_state.card_phase is None:
            # Truly cold start (FR-22)
            return {
                "source": "cold",
                "source_session_id": None,
                "explanation_summary": None,
                "variants_shown": [],
                "remedial_cards": {},
                "check_in_struggles": [],
            }

        # Context attached — read everything from source session's CardPhaseState (FR-19)
        return {
            "source": "teach_me",
            "source_session_id": source_state.session_id,
            "explanation_summary": source_state.precomputed_explanation_summary,
            "variants_shown": list(source_state.card_phase.variants_shown),
            "remedial_cards": {
                idx: [rc.model_dump() for rc in cards]
                for idx, cards in source_state.card_phase.remedial_cards.items()
            },
            "check_in_struggles": [
                evt.model_dump() for evt in source_state.card_phase.check_in_struggles
            ],
        }

    def _generate_practice_plan_for_session(
        self,
        guideline,
        student_context: StudentContext,
        context_data: dict,
    ):
        """Generate a practice-focused study plan via StudyPlanGeneratorService.

        Returns a tutor StudyPlan model, or None on failure (caller falls back).
        """
        try:
            from shared.models.entities import TeachingGuideline as GuidelineEntity
            from shared.services.llm_config_service import LLMConfigService
            from shared.prompts import PromptLoader
            from study_plans.services.generator_service import StudyPlanGeneratorService
            from tutor.services.topic_adapter import convert_session_plan_to_study_plan

            # Load the ORM entity (generator expects TeachingGuideline, not GuidelineResponse)
            guideline_entity = (
                self.db.query(GuidelineEntity)
                .filter(GuidelineEntity.id == guideline.id)
                .first()
            )
            if not guideline_entity:
                logger.warning(f"Guideline entity not found for {guideline.id}")
                return None

            # Create LLM service with study_plan_generator config
            settings = get_settings()
            gen_config = LLMConfigService(self.db).get_config("study_plan_generator")
            gen_llm = LLMService(
                api_key=settings.openai_api_key,
                provider=gen_config["provider"],
                model_id=gen_config["model_id"],
                gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
                anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
            )

            generator = StudyPlanGeneratorService(gen_llm, PromptLoader)
            is_cold_start = (context_data["source"] == "cold")
            result = generator.generate_practice_plan(
                guideline=guideline_entity,
                student_context=student_context,
                check_in_struggles=context_data.get("check_in_struggles"),
                is_cold_start=is_cold_start,
            )

            return convert_session_plan_to_study_plan(result["plan"])

        except Exception as e:
            logger.error(f"Failed to generate practice plan: {e}", exc_info=True)
            return None

    def process_step(self, session_id: str, request: StepRequest) -> StepResponse:
        """Process a student's answer using the new orchestrator."""
        # Load session from DB
        db_session = self.session_repo.get_by_id(session_id)
        if not db_session:
            raise SessionNotFoundException(session_id)

        expected_version = db_session.state_version or 1

        # Deserialize SessionState
        session = SessionState.model_validate_json(db_session.state_json)

        if session.is_in_card_phase():
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Session is in card phase. Use /card-action endpoint.")

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

        # Build response (maintain same REST contract). is_complete now comes
        # from SessionState.is_complete — single source of truth across all modes.
        next_turn = {
            "message": turn_result.response,
            "audio_text": turn_result.audio_text,
            "hints": [],
            "step_idx": session.current_step,
            "mastery_score": session.overall_mastery,
            "is_complete": session.is_complete,
        }

        if turn_result.visual_explanation:
            next_turn["visual_explanation"] = turn_result.visual_explanation
        if turn_result.question_format:
            next_turn["question_format"] = turn_result.question_format

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

        concepts_taught = session.session_summary.concepts_taught if session.session_summary else []

        return SummaryResponse(
            steps_completed=session.current_step - 1,
            mastery_score=round(session.overall_mastery, 2),
            misconceptions_seen=misconceptions_seen,
            suggestions=suggestions,
            concepts_taught=concepts_taught,
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
            # Load personality and enrichment preferences (if exists)
            tutor_brief = None
            personality_json = None
            attention_span = None
            preferred_examples = ["food", "sports", "games"]  # default
            try:
                from auth.repositories.personality_repository import PersonalityRepository
                from auth.repositories.enrichment_repository import EnrichmentRepository
                personality_repo = PersonalityRepository(self.db)
                personality = personality_repo.get_latest_ready(user_id)
                if personality:
                    tutor_brief = personality.tutor_brief
                    personality_json = personality.personality_json
                    if personality_json and personality_json.get("example_themes"):
                        preferred_examples = personality_json["example_themes"]
                # Load attention span from enrichment
                enrichment_repo = EnrichmentRepository(self.db)
                enrichment = enrichment_repo.get_by_user_id(user_id)
                if enrichment and enrichment.attention_span:
                    attention_span = enrichment.attention_span
            except Exception:
                pass  # Personality/enrichment not available — use defaults

            return StudentContext(
                grade=user.grade,
                board=user.board,
                language_level="simple" if (user.age and user.age <= 10) else "standard",
                preferred_examples=preferred_examples,
                student_name=user.preferred_name or user.name,
                student_age=user.age,
                about_me=user.about_me,
                text_language_preference=user.text_language_preference or 'en',
                audio_language_preference=user.audio_language_preference or 'en',
                tutor_brief=tutor_brief,
                personality_json=personality_json,
                attention_span=attention_span,
            )
        # Fallback to request data if profile is incomplete
        return StudentContext(
            grade=request.student.grade,
            board=request.goal.syllabus.split(" ")[0] if request.goal.syllabus else "CBSE",
            language_level="simple" if request.student.grade <= 5 else "standard",
        )

    def _generate_personalized_plan(
        self,
        guideline,
        user_id: str,
        student_context: StudentContext,
    ) -> Optional[StudyPlanRecord]:
        """Generate a personalized study plan for this student+guideline.

        Returns the saved StudyPlanRecord, or None if generation fails.
        """
        try:
            from shared.models.entities import TeachingGuideline as GuidelineEntity
            from shared.services.llm_config_service import LLMConfigService
            from shared.prompts import PromptLoader
            from study_plans.services.generator_service import StudyPlanGeneratorService

            # Load the ORM entity (generator expects TeachingGuideline, not GuidelineResponse)
            guideline_entity = (
                self.db.query(GuidelineEntity)
                .filter(GuidelineEntity.id == guideline.id)
                .first()
            )
            if not guideline_entity:
                logger.warning(f"Guideline entity not found for {guideline.id}")
                return None

            # Create LLM service with study_plan_generator config
            settings = get_settings()
            gen_config = LLMConfigService(self.db).get_config("study_plan_generator")
            gen_llm = LLMService(
                api_key=settings.openai_api_key,
                provider=gen_config["provider"],
                model_id=gen_config["model_id"],
                gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
                anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
            )

            generator = StudyPlanGeneratorService(gen_llm, PromptLoader)
            result = generator.generate_plan(guideline_entity, student_context=student_context)

            # Save to DB
            import json
            record = StudyPlanRecord(
                id=str(uuid4()),
                guideline_id=guideline.id,
                user_id=user_id,
                plan_json=json.dumps(result["plan"]),
                generator_model=result.get("model"),
                generation_reasoning=result.get("reasoning"),
                status="generated",
            )
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)

            logger.info(f"Generated personalized study plan {record.id} for user={user_id} guideline={guideline.id}")
            return record

        except Exception as e:
            logger.error(f"Failed to generate personalized plan: {e}", exc_info=True)
            try:
                self.db.rollback()
            except Exception:
                pass
            return None

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
            db_record.is_paused = session.is_paused if session.mode in ("teach_me", "practice") else False
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
                is_paused=session.is_paused if session.mode in ("teach_me", "practice") else False,
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
        """Pause a Teach Me or Practice session with version-safe persistence."""
        db_session = self.session_repo.get_by_id(session_id)
        if not db_session:
            raise SessionNotFoundException(session_id)
        expected_version = db_session.state_version or 1

        session = SessionState.model_validate_json(db_session.state_json)

        if session.mode not in ("teach_me", "practice"):
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail="Only Teach Me and Practice sessions can be paused",
            )

        session.is_paused = True
        self._persist_session_state(session_id, session, expected_version)

        # Mode-specific pause summary
        if session.mode == "practice":
            return {
                "coverage": session.coverage_percentage,
                "concepts_covered": list(session.concepts_covered_set),
                "message": (
                    f"Paused after {session.practice_questions_answered} question(s). "
                    "You can pick up where you left off anytime."
                ),
            }

        # teach_me
        return {
            "coverage": session.coverage_percentage,
            "concepts_covered": list(session.concepts_covered_set),
            "message": (
                f"You've covered {session.coverage_percentage:.0f}% so far. "
                "You can pick up where you left off anytime."
            ),
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

    def end_practice_session(self, session_id: str) -> dict:
        """End a practice session early (FR-16).

        Marks the session complete by setting practice_mastery_achieved=True
        so is_complete returns True and the session persists as finished.
        """
        db_session = self.session_repo.get_by_id(session_id)
        if not db_session:
            raise SessionNotFoundException(session_id)
        expected_version = db_session.state_version or 1

        session = SessionState.model_validate_json(db_session.state_json)

        if session.mode != "practice":
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail="Only practice sessions can be ended via this endpoint",
            )

        session.practice_mastery_achieved = True
        session.is_paused = False

        self._persist_session_state(session_id, session, expected_version)

        return {
            "is_complete": True,
            "questions_answered": session.practice_questions_answered,
            "message": (
                f"Session ended. You answered {session.practice_questions_answered} "
                f"question(s)."
            ),
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

    def process_feedback(
        self,
        session_id: str,
        user_id: str,
        guideline_id: str,
        feedback_text: str,
        session_state: SessionState,
        expected_version: int,
        action: str = "continue",
    ) -> dict:
        """Process mid-session feedback: save record, regenerate plan, splice into session."""
        from shared.models.entities import (
            SessionFeedback,
            TeachingGuideline as GuidelineEntity,
        )
        from shared.services.llm_config_service import LLMConfigService
        from shared.prompts import PromptLoader
        from study_plans.services.generator_service import StudyPlanGeneratorService
        from tutor.services.topic_adapter import _convert_study_plan

        # 1. Save feedback record
        feedback_record = SessionFeedback(
            id=str(uuid4()),
            user_id=user_id,
            guideline_id=guideline_id,
            session_id=session_id,
            feedback_text=feedback_text,
            step_at_feedback=session_state.current_step,
            total_steps_at_feedback=session_state.topic.study_plan.total_steps if session_state.topic else 0,
            plan_regenerated=False,
        )
        self.db.add(feedback_record)
        self.db.flush()

        # 2. Load guideline entity
        guideline_entity = (
            self.db.query(GuidelineEntity)
            .filter(GuidelineEntity.id == guideline_id)
            .first()
        )
        if not guideline_entity:
            raise GuidelineNotFoundException(guideline_id)

        # 3. Generate new plan with feedback context
        settings = get_settings()
        gen_config = LLMConfigService(self.db).get_config("study_plan_generator")
        gen_llm = LLMService(
            api_key=settings.openai_api_key,
            provider=gen_config["provider"],
            model_id=gen_config["model_id"],
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        )

        generator = StudyPlanGeneratorService(gen_llm, PromptLoader)
        concepts_covered = list(session_state.concepts_covered_set)
        current_step = session_state.current_step
        total_steps = session_state.topic.study_plan.total_steps if session_state.topic else 0

        result = generator.generate_plan_with_feedback(
            guideline=guideline_entity,
            student_context=session_state.student_context,
            feedback_text=feedback_text,
            concepts_covered=concepts_covered,
            current_step=current_step,
            total_steps=total_steps,
        )

        # 4. Upsert study_plans record
        existing_plan = (
            self.db.query(StudyPlanRecord)
            .filter(
                StudyPlanRecord.user_id == user_id,
                StudyPlanRecord.guideline_id == guideline_id,
            )
            .first()
        )
        if existing_plan:
            existing_plan.plan_json = json.dumps(result["plan"])
            existing_plan.generator_model = result.get("model")
            existing_plan.generation_reasoning = result.get("reasoning")
            existing_plan.version = (existing_plan.version or 1) + 1
        else:
            new_plan = StudyPlanRecord(
                id=str(uuid4()),
                guideline_id=guideline_id,
                user_id=user_id,
                plan_json=json.dumps(result["plan"]),
                generator_model=result.get("model"),
                generation_reasoning=result.get("reasoning"),
                status="generated",
            )
            self.db.add(new_plan)
        self.db.flush()

        feedback_record.plan_regenerated = True

        # 5. Apply new plan to session based on action
        # Build a mock StudyPlanRecord to pass to _convert_study_plan
        mock_record = type("MockRecord", (), {
            "plan_json": json.dumps(result["plan"]),
        })()

        guideline_resp = self.guideline_repo.get_guideline_by_id(guideline_id)
        new_study_plan = _convert_study_plan(mock_record, guideline_resp)

        from tutor.models.study_plan import StudyPlan as TutorStudyPlan

        if action == "restart":
            # RESTART: replace entire plan and reset session to step 1
            # Re-number all steps from 1
            for i, step in enumerate(new_study_plan.steps, start=1):
                step.step_id = i

            session_state.topic.study_plan = new_study_plan
            session_state.current_step = 1
            session_state.concepts_covered_set = set()
            session_state.mastery_estimates = {}
            session_state.misconceptions = []
            session_state.weak_areas = []
            session_state.last_question = None
            session_state.awaiting_response = False
            session_state.explanation_phases = {}
            session_state.current_explanation_concept = None
            session_state.conversation_history = []
            # Keep full_conversation_log for audit

            # Initialize mastery for all concepts
            for step in new_study_plan.steps:
                session_state.mastery_estimates[step.concept] = 0.0

            # Initialize explanation for first step if explain type
            first_step = session_state.current_step_data
            if first_step and first_step.type == "explain":
                session_state.start_explanation(first_step.concept, first_step.step_id)

            # Generate a new welcome message for the restarted session
            import asyncio
            welcome, audio_text = asyncio.run(
                self.orchestrator.generate_welcome_message(session_state)
            )
            session_state.add_message(create_teacher_message(welcome, audio_text=audio_text))

            session_state.session_summary.turn_timeline.append(
                f"[FEEDBACK-RESTART] Session restarted per feedback: {feedback_text[:60]}"
            )
        else:
            # CONTINUE: splice new plan from current step forward
            # Keep completed steps (1..current_step)
            kept_steps = []
            if session_state.topic:
                for step in session_state.topic.study_plan.steps:
                    if step.step_id < current_step:
                        kept_steps.append(step)

            # Filter new plan steps: remove concepts already covered
            covered_set = session_state.concepts_covered_set
            new_remaining = [
                s for s in new_study_plan.steps
                if s.concept not in covered_set
            ]

            # Re-number remaining steps
            for i, step in enumerate(new_remaining, start=current_step):
                step.step_id = i

            session_state.topic.study_plan = TutorStudyPlan(steps=kept_steps + new_remaining)

            # Initialize mastery estimates for new concepts
            for step in new_remaining:
                if step.concept not in session_state.mastery_estimates:
                    session_state.mastery_estimates[step.concept] = 0.0

            # Initialize explanation phase for current step if it's an explain step
            current_step_data = session_state.current_step_data
            if current_step_data and current_step_data.type == "explain":
                if current_step_data.concept not in session_state.explanation_phases:
                    session_state.start_explanation(current_step_data.concept, current_step_data.step_id)

            session_state.session_summary.turn_timeline.append(
                f"[FEEDBACK] Parent/student feedback: {feedback_text[:60]}"
            )

        # 9. Persist with CAS
        self._persist_session_state(session_id, session_state, expected_version)

        # Count feedback for this session
        feedback_count = (
            self.db.query(SessionFeedback)
            .filter(SessionFeedback.session_id == session_id)
            .count()
        )

        new_total = session_state.topic.study_plan.total_steps if session_state.topic else 0

        logger.info(f"Processed feedback for session {session_id}: action={action} new_total_steps={new_total}")
        msg = (
            "Session restarted with an updated plan"
            if action == "restart"
            else "Study plan updated based on your feedback"
        )
        return {
            "success": True,
            "message": msg,
            "new_total_steps": new_total,
            "feedback_count": feedback_count,
        }

    # ─── Card Phase Methods ───────────────────────────────────────────────────

    def simplify_card(self, session_id: str, card_idx: int, reason: str) -> dict:
        """Generate a simplified version of a specific explanation card."""
        db_session = self.session_repo.get_by_id(session_id)
        if not db_session:
            raise SessionNotFoundException(session_id)
        expected_version = db_session.state_version or 1

        session = SessionState.model_validate_json(db_session.state_json)

        if not session.is_in_card_phase():
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Session is not in card phase")

        if session.is_refresher:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Card simplification is not available for refresher topics")

        # Load current variant cards
        explanation_repo = ExplanationRepository(self.db)
        explanation = explanation_repo.get_variant(
            session.card_phase.guideline_id,
            session.card_phase.current_variant_key,
        )
        if not explanation or not explanation.cards_json:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Current variant cards not found")

        all_cards = explanation.cards_json
        if card_idx < 0 or card_idx >= len(all_cards):
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=f"Invalid card_idx: {card_idx}")

        # Always use the ORIGINAL base card as the primary input to prevent
        # recursive title/content stacking. Pass previous attempts as separate context.
        existing = session.card_phase.remedial_cards.get(card_idx, [])
        depth = len(existing) + 1

        target_card = all_cards[card_idx]
        card_title = target_card.get("title", "Untitled")
        card_content = target_card.get("content", "")

        # Collect previous simplification attempts so the LLM can avoid repeating them
        previous_attempts = [r.card for r in existing] if existing else []

        import asyncio

        # Strip audio_text from cards to save tokens — LLM only needs display content
        cards_for_llm = [
            {k: v for k, v in c.items() if k != "audio_text"}
            for c in all_cards
        ]

        card_dict = asyncio.run(
            self.orchestrator.generate_simplified_card(
                session=session,
                card_title=card_title,
                card_content=card_content,
                all_cards=cards_for_llm,
                reason=reason,
                previous_attempts=previous_attempts,
            )
        )

        variant_key = session.card_phase.current_variant_key
        card_id = f"remedial_{variant_key}_{card_idx}_{depth}"

        from tutor.models.session_state import RemedialCard, ConfusionEvent
        remedial = RemedialCard(
            card_id=card_id,
            source_card_idx=card_idx,
            depth=depth,
            card=card_dict,
        )

        if card_idx not in session.card_phase.remedial_cards:
            session.card_phase.remedial_cards[card_idx] = []
        session.card_phase.remedial_cards[card_idx].append(remedial)

        # Track confusion event
        existing_event = next(
            (e for e in session.card_phase.confusion_events if e.base_card_idx == card_idx),
            None,
        )
        base_title = all_cards[card_idx].get("title", "Untitled")
        if existing_event:
            existing_event.depth_reached = depth
        else:
            session.card_phase.confusion_events.append(
                ConfusionEvent(base_card_idx=card_idx, base_card_title=base_title, depth_reached=depth)
            )

        self.event_repo.log(
            session_id=session_id,
            node="card_confusion_tap",
            step_idx=session.current_step,
            payload={
                "guideline_id": session.card_phase.guideline_id,
                "variant_key": variant_key,
                "base_card_idx": card_idx,
                "base_card_title": base_title,
                "simplification_depth": depth,
                "reason": reason,
            },
        )

        self._persist_session_state(session_id, session, expected_version)

        return {
            "action": "insert_card",
            "card": card_dict,
            "card_id": card_id,
            "insert_after": f"{variant_key}_{card_idx}" if depth == 1 else f"remedial_{variant_key}_{card_idx}_{depth - 1}",
        }

    def complete_card_phase(self, session_id: str, action: str, check_in_events=None) -> dict:
        """Handle card phase completion. action: 'clear' or 'explain_differently'.

        NEW BEHAVIOR (Teach Me / Practice split):
        - 'clear' → end the Teach Me session (no bridge turn, no v2 plan, no
          transition to interactive phase). The frontend shows a summary + a
          "Let's Practice" CTA. Practice is a separate session created via the
          CTA handoff.
        - 'explain_differently' → switch to the next unseen variant. If all
          variants are exhausted, also end the session (with a gentler message).
        """
        db_session = self.session_repo.get_by_id(session_id)
        if not db_session:
            raise SessionNotFoundException(session_id)
        expected_version = db_session.state_version or 1

        session = SessionState.model_validate_json(db_session.state_json)

        if not session.is_in_card_phase():
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Session is not in card phase")

        if session.is_refresher:
            session.complete_card_phase()
            session.is_paused = False
            self._persist_session_state(session_id, session, expected_version)
            return {
                "action": "session_complete",
                "message": "You've refreshed the basics and are ready to dive into the chapter!",
                "audio_text": "You've refreshed the basics and are ready to dive into the chapter!",
                "is_complete": True,
            }

        # Store check-in struggle events from frontend (before action branching —
        # struggles are valuable whether the student says "clear" or "explain_differently")
        if check_in_events and session.card_phase:
            from tutor.models.session_state import CheckInStruggleEvent
            for evt in check_in_events:
                session.card_phase.check_in_struggles.append(
                    CheckInStruggleEvent(
                        card_idx=evt.card_idx,
                        card_title=evt.card_title or f"Check-in at card {evt.card_idx}",
                        activity_type=evt.activity_type,
                        wrong_count=evt.wrong_count,
                        hints_shown=evt.hints_shown,
                        confused_pairs=evt.confused_pairs,
                        auto_revealed=evt.auto_revealed,
                    )
                )

        if action == "clear":
            return self._finalize_teach_me_session(session, session_id, expected_version)

        elif action == "explain_differently":
            # Find next unseen variant
            unseen = [
                k for k in session.card_phase.available_variant_keys
                if k not in session.card_phase.variants_shown
            ]

            if unseen:
                return self._switch_variant_internal(session, session_id, unseen[0], expected_version)
            # All variants exhausted — end the session with a gentle nudge to practice
            return self._finalize_teach_me_session(
                session, session_id, expected_version,
                custom_message="We've looked at this from a few angles. Let's practice to see what stuck!",
            )

        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown card action: {action}")

    def _finalize_teach_me_session(
        self,
        session: SessionState,
        session_id: str,
        expected_version: int,
        custom_message: Optional[str] = None,
    ) -> dict:
        """End a Teach Me session after card phase. No bridge turn, no v2 plan.

        This is the new completion path — the session is considered done once
        the card phase is marked completed. The student will see a summary
        screen with a prominent "Let's Practice" CTA in the frontend.
        """
        session.complete_card_phase()

        # Build and persist the explanation summary. Stored on the session so a
        # later Practice session (launched via the CTA or auto-attached) can read
        # it as shared vocabulary via `source_state.precomputed_explanation_summary`.
        precomputed_summary = self._build_precomputed_summary(session)
        session.precomputed_explanation_summary = precomputed_summary

        # Add card concepts to coverage set. We use the actual cards the student saw,
        # not the plan steps — the cards are the source of truth for what was taught.
        if session.card_phase:
            explanation_repo = ExplanationRepository(self.db)
            for vk in session.card_phase.variants_shown:
                exp = explanation_repo.get_variant(session.card_phase.guideline_id, vk)
                if exp and exp.cards_json:
                    for card in exp.cards_json:
                        concept = card.get("concept") or card.get("title")
                        if concept:
                            session.concepts_covered_set.add(concept)
                            session.card_covered_concepts.add(concept)

        # Clear paused state — the session is now complete, not paused
        session.is_paused = False

        self._persist_session_state(session_id, session, expected_version)

        message = custom_message or "Nice work! You've covered the key ideas. Ready to practice?"

        return {
            "action": "teach_me_complete",
            "message": message,
            "audio_text": message,
            "is_complete": True,
            "coverage": session.coverage_percentage,
            "concepts_covered": list(session.concepts_covered_set),
            "guideline_id": session.card_phase.guideline_id if session.card_phase else None,
        }

    def _switch_variant_internal(
        self, session: SessionState, session_id: str, variant_key: str, expected_version: int
    ) -> dict:
        """Load a different explanation variant during card phase (internal, avoids double session load)."""
        explanation_repo = ExplanationRepository(self.db)
        explanation = explanation_repo.get_variant(
            session.card_phase.guideline_id, variant_key
        )
        if not explanation:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"Variant {variant_key} not found")

        session.card_phase.current_variant_key = variant_key
        session.card_phase.current_card_idx = 0
        session.card_phase.total_cards = len(explanation.cards_json)
        session.card_phase.variants_shown.append(variant_key)

        # Clear remedial cards from previous variant (clean slate for new variant)
        session.card_phase.remedial_cards = {}

        self._persist_session_state(session_id, session, expected_version)

        return {
            "action": "switch_variant",
            "cards": explanation.cards_json,
            "variant_key": variant_key,
            "variant_label": explanation.variant_label,
        }

    def _build_precomputed_summary(self, session: SessionState) -> str:
        """Build summary of shown explanations for tutor system prompt injection."""
        if not session.card_phase:
            return ""

        explanation_repo = ExplanationRepository(self.db)
        summaries = []
        for variant_key in session.card_phase.variants_shown:
            explanation = explanation_repo.get_variant(
                session.card_phase.guideline_id, variant_key
            )
            if explanation and explanation.summary_json:
                s = explanation.summary_json
                # Prefer teaching_notes (richer), fallback to structured labels
                if s.get("teaching_notes"):
                    summaries.append(
                        f"Variant '{s.get('approach_label', variant_key)}':\n"
                        f"{s['teaching_notes']}"
                    )
                else:
                    summaries.append(
                        f"Variant '{s.get('approach_label', variant_key)}': "
                        f"Topics covered: {', '.join(s.get('card_titles', []))}. "
                        f"Analogies used: {', '.join(s.get('key_analogies', []))}. "
                        f"Examples used: {', '.join(s.get('key_examples', []))}."
                    )

            # Append visual summaries from cards that have pre-computed visuals
            if explanation and explanation.cards_json:
                visual_notes = []
                for card in explanation.cards_json:
                    ve = card.get("visual_explanation")
                    if isinstance(ve, dict) and ve.get("visual_summary"):
                        visual_notes.append(
                            f"Card {card.get('card_idx', '?')} visual: {ve['visual_summary']}"
                        )
                if visual_notes:
                    summaries.append(
                        "Visuals the student could play:\n" + "\n".join(visual_notes)
                    )

        # Append per-card confusion summary if any confusion events exist
        if session.card_phase and session.card_phase.confusion_events:
            confusion_lines = []
            for evt in session.card_phase.confusion_events:
                status = "escalated to interactive" if evt.escalated else f"resolved after depth-{evt.depth_reached}"
                confusion_lines.append(
                    f"- Card {evt.base_card_idx} \"{evt.base_card_title}\": "
                    f"{evt.depth_reached} simplification(s), {status}"
                )
            summaries.append(
                "Cards that needed simplification:\n" + "\n".join(confusion_lines)
            )

        # Append check-in struggle summary (separate from simplification)
        if session.card_phase and session.card_phase.check_in_struggles:
            struggle_lines = []
            for evt in session.card_phase.check_in_struggles:
                pair_details_parts = []
                for p in evt.confused_pairs:
                    if p.get("wrong_count", 0) > 0:
                        wrong_picks = p.get("wrong_picks", [])
                        if wrong_picks:
                            # Show what the student actually picked wrong
                            picks_str = ", ".join(f'"{wp}"' for wp in wrong_picks[:3])
                            pair_details_parts.append(
                                f'for "{p.get("left", "?")}" (correct: "{p.get("right", "?")}") '
                                f'student picked: {picks_str} ({p["wrong_count"]}x wrong)'
                            )
                        else:
                            pair_details_parts.append(
                                f'confused "{p.get("left", "?")}" with "{p.get("right", "?")}" ({p["wrong_count"]}x)'
                            )
                pair_details = ", ".join(pair_details_parts)
                auto = f", {evt.auto_revealed} pair(s) auto-revealed" if evt.auto_revealed else ""
                struggle_lines.append(
                    f"- \"{evt.card_title}\": {evt.wrong_count} wrong attempts"
                    f"{', ' + pair_details if pair_details else ''}{auto}"
                )
            summaries.append(
                "Check-in struggles:\n" + "\n".join(struggle_lines)
            )

        return "\n".join(summaries)

    def _extract_card_covered_concepts(self, session: SessionState) -> set[str]:
        """Extract concepts covered by card-phase explanation steps."""
        concepts = set()
        if not session.topic or not session.topic.study_plan:
            return concepts
        for step in session.topic.study_plan.steps:
            if step.type == "explain":
                concepts.add(step.concept)
        concepts.update(session.concepts_covered_set)
        return concepts

    def _generate_v2_session_plan(self, session: SessionState) -> None:
        """Generate a v2 session plan from explanation data and replace the study plan.

        Called at card completion. Uses the actual variants the student saw.
        """
        if not session.card_phase or not session.topic:
            logger.warning("Cannot generate v2 plan: missing card_phase or topic")
            return

        try:
            explanation_repo = ExplanationRepository(self.db)
            guideline_repo = TeachingGuidelineRepository(self.db)

            guideline = guideline_repo.get_by_id(session.card_phase.guideline_id)
            if not guideline:
                logger.warning(f"Guideline {session.card_phase.guideline_id} not found for v2 plan")
                return

            # Collect summaries and card titles from shown variants
            explanation_summaries = []
            card_titles = []
            for variant_key in session.card_phase.variants_shown:
                explanation = explanation_repo.get_variant(
                    session.card_phase.guideline_id, variant_key
                )
                if explanation:
                    if explanation.summary_json:
                        explanation_summaries.append(explanation.summary_json)
                    if explanation.cards_json:
                        # Use card titles from the last variant shown
                        card_titles = [c.get("title", "") for c in explanation.cards_json if isinstance(c, dict)]

            if not explanation_summaries:
                logger.warning("No explanation summaries found for v2 plan generation")
                return

            # Build student context
            student_context = session.student_context if hasattr(session, "student_context") else None

            from study_plans.services.generator_service import StudyPlanGeneratorService
            from shared.utils.prompt_loader import PromptLoader

            llm_config_service = self._get_llm_config_service()
            llm_service = llm_config_service.get_llm_service("study_plan_generator")
            prompt_loader = PromptLoader()

            generator = StudyPlanGeneratorService(llm_service, prompt_loader)
            result = generator.generate_session_plan(
                guideline=guideline,
                explanation_summaries=explanation_summaries,
                card_titles=card_titles,
                variants_shown=list(session.card_phase.variants_shown),
                student_context=student_context,
            )

            # Convert to StudyPlan model and replace the session's plan
            from tutor.services.topic_adapter import convert_session_plan_to_study_plan
            new_plan = convert_session_plan_to_study_plan(result["plan"])
            session.topic.study_plan = new_plan

            # Reset step to 1 for the new plan
            session.current_step = 1

            logger.info(f"Generated v2 session plan with {len(new_plan.steps)} steps")

        except Exception as e:
            logger.error(f"Failed to generate v2 session plan, keeping existing: {e}", exc_info=True)
            # Non-fatal — session continues with the existing v1 plan

    def _advance_past_explanation_steps(self, session: SessionState):
        """After successful card phase, skip consecutive leading explain steps.

        Cards cover the topic's introductory explanation holistically. This method
        skips consecutive "explain" steps at the start of the study plan, landing
        on the first non-explain step (typically "check" or "practice").
        """
        if not session.topic or not session.topic.study_plan:
            return

        while session.current_step <= session.topic.study_plan.total_steps:
            step = session.topic.study_plan.get_step(session.current_step)
            if step and step.type == "explain":
                session.concepts_covered_set.add(step.concept)
                session.advance_step()
            else:
                break  # Found a non-explain step — stop here

    def _init_dynamic_fallback(self, session: SessionState):
        """Initialize ExplanationPhase for dynamic fallback after all card variants exhausted."""
        first_step = session.topic.study_plan.get_step(1) if session.topic else None
        if first_step and first_step.type == "explain":
            session.start_explanation(first_step.concept, first_step.step_id)

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
