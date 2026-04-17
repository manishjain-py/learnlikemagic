"""Practice attempt grading — runs as a background worker spawned on submit.

Pipeline per attempt:
  1. Load attempt; bail if status != 'grading' (idempotent).
  2. Walk all 10 questions:
       - Structured (11 formats): deterministic 0/1 scoring from question_json
         + student answer. Wrong/blank → enqueue an LLM rationale task.
       - Free-form: enqueue an LLM grading task (fractional 0-1 + rationale).
  3. Run all LLM tasks in parallel via ThreadPoolExecutor(max_workers=10).
  4. Assemble grading_json + half-point-rounded total_score; save.
  Any unhandled error → mark_grading_failed(error).

Runs with the `practice_grader` LLM config (openai/gpt-4o-mini,
reasoning_effort=none). LLMService's built-in retry handles rate limits /
timeouts with initial_retry_delay=10 for 10/20/40s backoff per impl plan §6.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from shared.repositories.practice_attempt_repository import PracticeAttemptRepository
from shared.services.llm_service import LLMService
from tutor.prompts.practice_grading import (
    FREE_FORM_GRADING_PROMPT,
    PER_PICK_RATIONALE_PROMPT,
)

logger = logging.getLogger(__name__)


# ─── LLM output schemas ───────────────────────────────────────────────────

class FreeFormGradingOutput(BaseModel):
    score: float = Field(ge=0, le=1, description="Grade in [0,1], half-credit allowed")
    rationale: str = Field(description="One-sentence kid-friendly feedback")


class PickRationaleOutput(BaseModel):
    rationale: str = Field(description="One-sentence kid-friendly explanation of the correct answer")


# Threshold for turning a free-form fractional score into boolean correct.
FF_CORRECT_THRESHOLD = 0.75

# Max workers for parallel LLM calls during grading.
GRADING_PARALLELISM = 10


class PracticeGradingService:
    """Grades one practice attempt end-to-end."""

    def __init__(self, db: DBSession, llm_service: LLMService):
        self.db = db
        self.llm = llm_service
        self.attempt_repo = PracticeAttemptRepository(db)

        self._ff_schema = LLMService.make_schema_strict(
            FreeFormGradingOutput.model_json_schema()
        )
        self._rationale_schema = LLMService.make_schema_strict(
            PickRationaleOutput.model_json_schema()
        )

    # ─── Entry point ──────────────────────────────────────────────────────

    def grade_attempt(self, attempt_id: str) -> None:
        """Grade one attempt. Idempotent — silently no-ops if the attempt is
        not in 'grading' state. Any failure marks the attempt as
        'grading_failed' with the error message; callers don't need to catch.
        """
        try:
            attempt = self.attempt_repo.get(attempt_id)
            if attempt is None:
                logger.warning(f"Grade attempt {attempt_id}: not found")
                return
            if attempt.status != "grading":
                logger.info(
                    f"Grade attempt {attempt_id}: status is {attempt.status!r}, "
                    f"not 'grading' — skipping"
                )
                return

            questions = attempt.questions_snapshot_json or []
            answers = attempt.answers_json or {}

            if not questions:
                raise ValueError("questions_snapshot_json is empty")

            # Phase 1: deterministic pass + build LLM task list
            grading: dict[int, dict] = {}
            ff_tasks: list[tuple[int, dict, Any]] = []       # free-form grading
            pick_tasks: list[tuple[int, dict, Any]] = []     # wrong-pick rationale

            for q_idx, q in enumerate(questions):
                student_answer = answers.get(str(q_idx))
                fmt = q.get("_format") or q.get("format")

                if fmt == "free_form":
                    grading[q_idx] = self._init_grading(q_idx, q, student_answer)
                    ff_tasks.append((q_idx, q, student_answer))
                else:
                    correct_summary = self._summarize_correct(q)
                    is_correct = self._check_structured(q, student_answer)
                    grading[q_idx] = self._init_grading(
                        q_idx, q, student_answer,
                        score=1.0 if is_correct else 0.0,
                        correct=is_correct,
                        correct_answer_summary=correct_summary,
                    )
                    if not is_correct:
                        pick_tasks.append((q_idx, q, student_answer))

            # Phase 2: parallel LLM calls
            if ff_tasks or pick_tasks:
                with ThreadPoolExecutor(max_workers=GRADING_PARALLELISM) as pool:
                    futures = {}
                    for q_idx, q, student_answer in ff_tasks:
                        futures[pool.submit(self._grade_free_form, q, student_answer)] = (
                            "ff", q_idx,
                        )
                    for q_idx, q, student_answer in pick_tasks:
                        futures[pool.submit(self._explain_wrong_pick, q, student_answer)] = (
                            "pick", q_idx,
                        )

                    for future in as_completed(futures):
                        task_type, q_idx = futures[future]
                        result = future.result()  # let exceptions propagate
                        if task_type == "ff":
                            grading[q_idx]["score"] = result.score
                            grading[q_idx]["correct"] = result.score >= FF_CORRECT_THRESHOLD
                            grading[q_idx]["rationale"] = result.rationale
                        else:  # pick
                            grading[q_idx]["rationale"] = result.rationale

            # Phase 3: assemble + persist
            raw_total = sum(g["score"] for g in grading.values())
            total_score = round(raw_total * 2) / 2  # half-point rounded

            grading_json = {str(i): grading[i] for i in sorted(grading)}
            self.attempt_repo.save_grading(attempt_id, grading_json, total_score)
            logger.info(
                f"Graded attempt {attempt_id}: score={total_score}/"
                f"{attempt.total_possible}, ff={len(ff_tasks)}, wrong={len(pick_tasks)}"
            )

        except Exception as e:
            logger.exception(f"Grading failed for attempt {attempt_id}")
            try:
                self.attempt_repo.mark_grading_failed(attempt_id, str(e))
            except Exception:
                logger.exception(
                    f"Failed to mark attempt {attempt_id} as grading_failed"
                )

    # ─── Deterministic structured grading ─────────────────────────────────

    def _check_structured(self, q: dict, student_answer: Any) -> bool:
        """Return True if student_answer matches the stored correct answer.

        Student-answer shapes (stabilized in Step 9a; lenient here to avoid
        false-wrongs during bring-up):
          - pick_one / fill_blank / tap_to_eliminate / predict_then_reveal: int (index)
          - true_false: bool
          - match_pairs: dict mapping left → right
          - sort_buckets / swipe_classify: list[int] — bucket_idx per item
          - sequence: list[str] — ordered items
          - spot_the_error / odd_one_out: int (index)
        """
        if student_answer is None:
            return False
        fmt = q.get("_format") or q.get("format")

        if fmt in ("pick_one", "fill_blank", "tap_to_eliminate", "predict_then_reveal"):
            try:
                return int(student_answer) == int(q.get("correct_index"))
            except (TypeError, ValueError):
                return False

        if fmt == "true_false":
            return bool(student_answer) == bool(q.get("correct_answer_bool"))

        if fmt == "match_pairs":
            expected = {p["left"]: p["right"] for p in (q.get("pairs") or [])}
            if not isinstance(student_answer, dict):
                return False
            if len(student_answer) != len(expected):
                return False
            return all(expected.get(k) == v for k, v in student_answer.items())

        if fmt in ("sort_buckets", "swipe_classify"):
            expected = [bi.get("correct_bucket") for bi in (q.get("bucket_items") or [])]
            if not isinstance(student_answer, list):
                return False
            if len(student_answer) != len(expected):
                return False
            try:
                return [int(x) for x in student_answer] == [int(x) for x in expected]
            except (TypeError, ValueError):
                return False

        if fmt == "sequence":
            expected = q.get("sequence_items") or []
            if not isinstance(student_answer, list):
                return False
            return student_answer == expected

        if fmt == "spot_the_error":
            try:
                return int(student_answer) == int(q.get("error_index"))
            except (TypeError, ValueError):
                return False

        if fmt == "odd_one_out":
            try:
                return int(student_answer) == int(q.get("odd_index"))
            except (TypeError, ValueError):
                return False

        return False

    def _summarize_correct(self, q: dict) -> Any:
        """Short human-readable correct answer for storage in grading_json
        and to feed the per-pick rationale prompt. Mirrors the frontend
        admin viewer's summarizeCorrectAnswer — keep in sync.
        """
        fmt = q.get("_format") or q.get("format")

        if fmt in ("pick_one", "fill_blank", "tap_to_eliminate", "predict_then_reveal"):
            opts = q.get("options") or []
            idx = q.get("correct_index", 0)
            return opts[idx] if 0 <= idx < len(opts) else None

        if fmt == "true_false":
            return "TRUE" if q.get("correct_answer_bool") else "FALSE"

        if fmt == "match_pairs":
            return [
                {"left": p.get("left"), "right": p.get("right")}
                for p in (q.get("pairs") or [])
            ]

        if fmt in ("sort_buckets", "swipe_classify"):
            names = q.get("bucket_names") or []
            return [
                {
                    "text": bi.get("text"),
                    "bucket": names[bi["correct_bucket"]]
                    if 0 <= bi.get("correct_bucket", -1) < len(names) else None,
                }
                for bi in (q.get("bucket_items") or [])
            ]

        if fmt == "sequence":
            return q.get("sequence_items") or []

        if fmt == "spot_the_error":
            steps = q.get("error_steps") or []
            idx = q.get("error_index", 0)
            return {"index": idx, "step": steps[idx] if 0 <= idx < len(steps) else None}

        if fmt == "odd_one_out":
            items = q.get("odd_items") or []
            idx = q.get("odd_index", 0)
            return {"index": idx, "item": items[idx] if 0 <= idx < len(items) else None}

        return None

    def _summarize_pick(self, q: dict, student_answer: Any) -> str:
        """Human-readable version of the student's pick for the rationale prompt."""
        if student_answer is None:
            return "(blank — no answer given)"
        fmt = q.get("_format") or q.get("format")

        try:
            if fmt in ("pick_one", "fill_blank", "tap_to_eliminate", "predict_then_reveal"):
                opts = q.get("options") or []
                idx = int(student_answer)
                return opts[idx] if 0 <= idx < len(opts) else f"(invalid index {idx})"
            if fmt == "true_false":
                return "TRUE" if student_answer else "FALSE"
            if fmt == "match_pairs":
                return json.dumps(student_answer)
            if fmt in ("sort_buckets", "swipe_classify"):
                names = q.get("bucket_names") or []
                items = q.get("bucket_items") or []
                if isinstance(student_answer, list) and len(student_answer) == len(items):
                    return json.dumps([
                        {
                            "text": items[i].get("text"),
                            "bucket": names[int(b)] if 0 <= int(b) < len(names) else None,
                        }
                        for i, b in enumerate(student_answer)
                    ])
                return str(student_answer)
            if fmt == "sequence":
                return " → ".join(str(x) for x in student_answer) if isinstance(student_answer, list) else str(student_answer)
            if fmt == "spot_the_error":
                steps = q.get("error_steps") or []
                idx = int(student_answer)
                return f"Step {idx}: {steps[idx]}" if 0 <= idx < len(steps) else f"(invalid step {idx})"
            if fmt == "odd_one_out":
                items = q.get("odd_items") or []
                idx = int(student_answer)
                return items[idx] if 0 <= idx < len(items) else f"(invalid index {idx})"
        except (TypeError, ValueError):
            pass
        return str(student_answer)

    # ─── LLM calls ────────────────────────────────────────────────────────

    def _grade_free_form(self, q: dict, student_answer: Any) -> FreeFormGradingOutput:
        """LLM-grade one free-form answer. Returns score + rationale."""
        prompt = (
            FREE_FORM_GRADING_PROMPT
            .replace("{question_text}", str(q.get("question_text", "")))
            .replace("{expected_answer}", str(q.get("expected_answer", "")))
            .replace("{grading_rubric}", str(q.get("grading_rubric", "")))
            .replace(
                "{student_answer}",
                str(student_answer) if student_answer is not None else "(blank — no answer given)",
            )
        )
        response = self.llm.call(
            prompt=prompt,
            reasoning_effort="none",
            json_schema=self._ff_schema,
            schema_name="FreeFormGradingOutput",
        )
        parsed = self.llm.parse_json_response(response["output_text"])
        return FreeFormGradingOutput.model_validate(parsed)

    def _explain_wrong_pick(self, q: dict, student_answer: Any) -> PickRationaleOutput:
        """LLM rationale for one wrong/blank structured answer."""
        fmt = q.get("_format") or q.get("format") or ""
        prompt = (
            PER_PICK_RATIONALE_PROMPT
            .replace("{format}", fmt)
            .replace("{question_text}", str(q.get("question_text", "")))
            .replace("{correct_answer_summary}", json.dumps(self._summarize_correct(q), ensure_ascii=False))
            .replace("{student_pick_summary}", self._summarize_pick(q, student_answer))
            .replace("{explanation_why}", str(q.get("explanation_why", "")))
        )
        response = self.llm.call(
            prompt=prompt,
            reasoning_effort="none",
            json_schema=self._rationale_schema,
            schema_name="PickRationaleOutput",
        )
        parsed = self.llm.parse_json_response(response["output_text"])
        return PickRationaleOutput.model_validate(parsed)

    # ─── grading_json builders ────────────────────────────────────────────

    def _init_grading(
        self,
        q_idx: int,
        q: dict,
        student_answer: Any,
        score: float = 0.0,
        correct: bool = False,
        correct_answer_summary: Any = None,
    ) -> dict:
        """Per-question grading entry. `visual_explanation_code` is a nullable
        slot pre-wired for FR-43 (Pixi on eval cards, deferred).
        """
        return {
            "q_idx": q_idx,
            "format": q.get("_format") or q.get("format"),
            "difficulty": q.get("_difficulty") or q.get("difficulty"),
            "concept_tag": q.get("_concept_tag") or q.get("concept_tag"),
            "score": score,
            "correct": correct,
            "student_answer": student_answer,
            "correct_answer_summary": correct_answer_summary,
            "rationale": None,
            "visual_explanation_code": None,
        }
