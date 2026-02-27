"""Exam question generation service."""

import json
import logging
from typing import Optional

from fastapi import HTTPException, status
from shared.services.llm_service import LLMService
from shared.utils.exceptions import LearnLikeMagicException
from tutor.models.session_state import SessionState, ExamQuestion
from tutor.prompts.exam_prompts import EXAM_QUESTION_GENERATION_PROMPT

logger = logging.getLogger("tutor.exam_service")


class ExamGenerationError(LearnLikeMagicException):
    """Raised when exam question generation fails."""

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Exam generation is temporarily unavailable. Please try again.", "type": "ExamGenerationError"},
        )


class ExamService:
    """Generates exam questions using LLM."""

    def __init__(self, llm_service: LLMService):
        self.llm = llm_service

    def generate_questions(
        self, session: SessionState, count: int = 7, timeout_s: float = 20.0
    ) -> list[ExamQuestion]:
        if not session.topic:
            raise ExamGenerationError("No topic set for exam generation")

        concepts = session.topic.study_plan.get_concepts()
        if not concepts:
            raise ExamGenerationError("No concepts found in study plan")
        misconceptions = session.topic.guidelines.common_misconceptions or []
        prompt = EXAM_QUESTION_GENERATION_PROMPT.render(
            grade=session.student_context.grade,
            topic_name=session.topic.topic_name,
            learning_objectives="\n".join(
                f"- {obj}" for obj in session.topic.guidelines.learning_objectives
            ),
            concepts="\n".join(f"- {c}" for c in concepts),
            teaching_approach=session.topic.guidelines.teaching_approach,
            common_misconceptions="\n".join(f"- {m}" for m in misconceptions) if misconceptions else "(none provided)",
            num_questions=count,
        )

        question_types = ["conceptual", "procedural", "application", "real_world", "error_spotting", "reasoning"]
        schema = {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question_text": {"type": "string"},
                            "expected_answer": {"type": "string"},
                            "concept": {"type": "string"},
                            "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                            "question_type": {"type": "string", "enum": question_types},
                        },
                        "required": ["question_text", "expected_answer", "concept", "difficulty", "question_type"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["questions"],
            "additionalProperties": False,
        }

        try:
            result = self.llm.call(
                prompt=prompt,
                reasoning_effort="medium",
                json_schema=schema,
                schema_name="ExamQuestions",
            )

            output_text = result.get("output_text", "{}")
            try:
                parsed = json.loads(output_text)
            except (json.JSONDecodeError, TypeError):
                parsed = {}

            raw_questions = parsed.get("questions", [])
            if not raw_questions:
                raise ExamGenerationError("LLM returned no questions")

            questions = []
            for idx, q in enumerate(raw_questions[:count]):
                questions.append(ExamQuestion(
                    question_idx=idx,
                    question_text=q.get("question_text", ""),
                    concept=q.get("concept", concepts[idx % len(concepts)] if concepts else "unknown"),
                    difficulty=q.get("difficulty", "medium"),
                    question_type=q.get("question_type", "conceptual"),
                    expected_answer=q.get("expected_answer", ""),
                ))

            logger.info(f"Generated {len(questions)} exam questions for session {session.session_id}")
            return questions

        except ExamGenerationError:
            raise
        except Exception as e:
            logger.error(f"Exam question generation failed: {e}")
            # Retry with fewer questions
            try:
                return self._retry_with_fewer(session, concepts, prompt, count=3)
            except Exception as retry_error:
                raise ExamGenerationError(f"Exam generation failed after retry: {retry_error}") from e

    def _retry_with_fewer(self, session, concepts, original_prompt, count=3):
        """Retry with fewer questions on failure."""
        prompt = original_prompt.replace(
            f"Generate exactly {7} questions",
            f"Generate exactly {count} questions",
        )

        question_types = ["conceptual", "procedural", "application", "real_world", "error_spotting", "reasoning"]
        schema = {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question_text": {"type": "string"},
                            "expected_answer": {"type": "string"},
                            "concept": {"type": "string"},
                            "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                            "question_type": {"type": "string", "enum": question_types},
                        },
                        "required": ["question_text", "expected_answer", "concept", "difficulty", "question_type"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["questions"],
            "additionalProperties": False,
        }

        result = self.llm.call(
            prompt=prompt,
            reasoning_effort="medium",
            json_schema=schema,
            schema_name="ExamQuestions",
        )

        output_text = result.get("output_text", "{}")
        parsed = json.loads(output_text)
        raw_questions = parsed.get("questions", [])

        questions = []
        for idx, q in enumerate(raw_questions[:count]):
            questions.append(ExamQuestion(
                question_idx=idx,
                question_text=q.get("question_text", ""),
                concept=q.get("concept", concepts[idx % len(concepts)] if concepts else "unknown"),
                difficulty=q.get("difficulty", "medium"),
                question_type=q.get("question_type", "conceptual"),
                expected_answer=q.get("expected_answer", ""),
            ))

        if not questions:
            raise ExamGenerationError("Retry also returned no questions")

        return questions
