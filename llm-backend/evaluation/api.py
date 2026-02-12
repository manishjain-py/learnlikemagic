"""Evaluation pipeline API endpoints."""
import json
import logging
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path

from fastapi import APIRouter, HTTPException

from evaluation.config import RUNS_DIR

logger = logging.getLogger("evaluation.api")

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


# ──────────────────────────────────────────────
# Pipeline State
# ──────────────────────────────────────────────


class EvalStatus(str, Enum):
    idle = "idle"
    loading_persona = "loading_persona"
    running_session = "running_session"
    evaluating = "evaluating"
    generating_reports = "generating_reports"
    complete = "complete"
    failed = "failed"


_eval_state = {
    "status": EvalStatus.idle,
    "run_id": None,
    "detail": "",
    "turn": 0,
    "max_turns": 0,
    "error": None,
}
_eval_lock = threading.Lock()


def _update_eval_state(**kwargs):
    with _eval_lock:
        _eval_state.update(kwargs)


# ──────────────────────────────────────────────
# Background Pipeline Runner
# ──────────────────────────────────────────────


def _run_evaluation_pipeline(topic_id: str, persona_file: str, max_turns: int):
    """Thread target that runs the full evaluation pipeline."""
    from evaluation.config import EvalConfig
    from evaluation.student_simulator import StudentSimulator
    from evaluation.session_runner import SessionRunner
    from evaluation.evaluator import ConversationEvaluator
    from evaluation.report_generator import ReportGenerator

    runner = None
    run_dir = None
    try:
        config = EvalConfig(
            topic_id=topic_id,
            persona_file=persona_file,
            max_turns=max_turns,
        )

        if config.eval_llm_provider == "anthropic":
            if not config.anthropic_api_key:
                raise RuntimeError("ANTHROPIC_API_KEY not found in environment")
        else:
            if not config.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY not found in environment")

        started_at = datetime.now()
        timestamp = started_at.strftime("%Y%m%d_%H%M%S")
        run_dir = RUNS_DIR / f"run_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        _update_eval_state(run_id=f"run_{timestamp}")

        _update_eval_state(status=EvalStatus.loading_persona, detail="Loading persona...")
        persona = config.load_persona()
        simulator = StudentSimulator(config, persona)
        
        report = ReportGenerator(run_dir, config, started_at=started_at.isoformat(), persona=persona)
        report.save_config()

        _update_eval_state(
            status=EvalStatus.running_session,
            detail="Starting session...",
            turn=0,
            max_turns=max_turns,
        )

        def on_turn(turn, total):
            _update_eval_state(turn=turn, detail=f"Turn {turn}/{total}")

        runner = SessionRunner(
            config, simulator, run_dir,
            skip_server_management=True,
            on_turn=on_turn,
        )
        runner.start_server()
        conversation = runner.run_session()
        metadata = runner.session_metadata

        report.save_conversation_md(conversation)
        report.save_conversation_json(conversation, metadata)

        _update_eval_state(status=EvalStatus.evaluating, detail="Running LLM evaluation...")
        evaluator = ConversationEvaluator(config)
        evaluation = evaluator.evaluate(conversation, persona=persona)

        _update_eval_state(status=EvalStatus.generating_reports, detail="Generating reports...")
        report.save_evaluation_json(evaluation)
        report.save_review(evaluation)
        report.save_problems(evaluation)

        _update_eval_state(status=EvalStatus.complete, detail="Evaluation complete")

    except Exception as e:
        import traceback
        logger.error(f"Evaluation pipeline failed: {e}")
        _update_eval_state(status=EvalStatus.failed, error=str(e), detail=f"Failed: {e}")
        try:
            if run_dir and run_dir.exists():
                error_path = run_dir / "error.txt"
                error_path.write_text(f"{datetime.now().isoformat()}\n{e}\n\n{traceback.format_exc()}")
        except Exception:
            pass
    finally:
        if runner:
            try:
                runner.cleanup()
            except Exception:
                pass


def _run_session_evaluation(session_id: str):
    """Thread target that evaluates an existing session's conversation."""
    from evaluation.config import EvalConfig
    from evaluation.evaluator import ConversationEvaluator
    from evaluation.report_generator import ReportGenerator
    from database import get_db_manager
    from tutor.models.session_state import SessionState

    run_dir = None
    try:
        config = EvalConfig()

        if config.eval_llm_provider == "anthropic":
            if not config.anthropic_api_key:
                raise RuntimeError("ANTHROPIC_API_KEY not found in environment")
        else:
            if not config.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY not found in environment")

        # Load session from DB
        db_manager = get_db_manager()
        db = db_manager.session_factory()
        try:
            from shared.models.entities import Session as SessionModel
            db_session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            if not db_session:
                raise RuntimeError(f"Session not found: {session_id}")
            session = SessionState.model_validate_json(db_session.state_json)
        finally:
            db.close()

        # Extract messages: prefer full_conversation_log, fall back to conversation_history
        messages = session.full_conversation_log if session.full_conversation_log else session.conversation_history

        if not messages:
            raise RuntimeError("Session has no messages to evaluate")

        # Convert to evaluator format: role "teacher" → "tutor", add turn numbers
        conversation = []
        turn = 0
        for msg in messages:
            role = "tutor" if msg.role == "teacher" else "student"
            if role == "student":
                turn += 1
            conversation.append({
                "role": role,
                "content": msg.content,
                "turn": turn,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else "",
            })

        # Extract topic info for evaluation context
        topic_info = None
        if session.topic:
            topic_info = {
                "topic_name": session.topic.topic_name,
                "grade_level": session.topic.grade_level if hasattr(session.topic, "grade_level") else None,
                "guidelines": {
                    "learning_objectives": session.topic.learning_objectives if hasattr(session.topic, "learning_objectives") else [],
                    "common_misconceptions": session.topic.common_misconceptions if hasattr(session.topic, "common_misconceptions") else [],
                },
            }

        # Set up run directory
        started_at = datetime.now()
        timestamp = started_at.strftime("%Y%m%d_%H%M%S")
        run_dir = RUNS_DIR / f"run_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        _update_eval_state(run_id=f"run_{timestamp}")

        # Save config with source info
        config.topic_id = session.topic.topic_name if session.topic else "unknown"
        report = ReportGenerator(run_dir, config, started_at=started_at.isoformat())

        config_data = config.to_dict()
        config_data["started_at"] = started_at.isoformat()
        config_data["source"] = "existing_session"
        config_data["source_session_id"] = session_id
        with open(run_dir / "config.json", "w") as f:
            json.dump(config_data, f, indent=2)

        # Save conversation
        report.save_conversation_md(conversation)
        report.save_conversation_json(conversation, {"source_session_id": session_id})

        # Evaluate
        _update_eval_state(status=EvalStatus.evaluating, detail="Running LLM evaluation...")
        evaluator = ConversationEvaluator(config)
        evaluation = evaluator.evaluate(conversation, topic_info)

        _update_eval_state(status=EvalStatus.generating_reports, detail="Generating reports...")
        report.save_evaluation_json(evaluation)
        report.save_review(evaluation)
        report.save_problems(evaluation)

        _update_eval_state(status=EvalStatus.complete, detail="Evaluation complete")

    except Exception as e:
        import traceback
        logger.error(f"Session evaluation failed: {e}")
        _update_eval_state(status=EvalStatus.failed, error=str(e), detail=f"Failed: {e}")
        try:
            if run_dir and run_dir.exists():
                error_path = run_dir / "error.txt"
                error_path.write_text(f"{datetime.now().isoformat()}\n{e}\n\n{traceback.format_exc()}")
        except Exception:
            pass


def _retry_evaluation(run_dir: Path):
    """Re-run evaluation + reports on an existing conversation."""
    from evaluation.config import EvalConfig
    from evaluation.evaluator import ConversationEvaluator
    from evaluation.report_generator import ReportGenerator

    try:
        with open(run_dir / "config.json") as f:
            config_data = json.load(f)

        with open(run_dir / "conversation.json") as f:
            conv_data = json.load(f)

        conversation = conv_data.get("messages", [])
        topic_id = config_data.get("topic_id", "")

        config = EvalConfig(
            topic_id=topic_id,
            persona_file=config_data.get("persona_file", "average_student.json"),
            max_turns=config_data.get("max_turns", 20),
        )

        # Load persona if available
        persona = None
        try:
            persona = config.load_persona()
        except:
            pass  # Persona loading failed, continue without it

        _update_eval_state(status=EvalStatus.evaluating, detail="Running LLM evaluation...")
        evaluator = ConversationEvaluator(config)
        evaluation = evaluator.evaluate(conversation, persona=persona)

        _update_eval_state(status=EvalStatus.generating_reports, detail="Generating reports...")
        report = ReportGenerator(run_dir, config, started_at=config_data.get("started_at"), persona=persona)
        report.save_evaluation_json(evaluation)
        report.save_review(evaluation)
        report.save_problems(evaluation)

        _update_eval_state(status=EvalStatus.complete, detail="Evaluation complete")

    except Exception as e:
        import traceback
        logger.error(f"Evaluation retry failed: {e}")
        _update_eval_state(status=EvalStatus.failed, error=str(e), detail=f"Failed: {e}")
        try:
            error_path = run_dir / "error.txt"
            error_path.write_text(f"{datetime.now().isoformat()}\n{e}\n\n{traceback.format_exc()}")
        except Exception:
            pass


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────


@router.post("/evaluate-session")
async def evaluate_session(request: dict = None):
    """Evaluate an existing tutoring session's conversation."""
    request = request or {}
    session_id = request.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    with _eval_lock:
        if _eval_state["status"] not in (EvalStatus.idle, EvalStatus.complete, EvalStatus.failed):
            raise HTTPException(status_code=409, detail="Evaluation already running")
        _eval_state.update({
            "status": EvalStatus.evaluating,
            "run_id": None,
            "detail": "Loading session...",
            "turn": 0,
            "max_turns": 0,
            "error": None,
        })

    thread = threading.Thread(
        target=_run_session_evaluation,
        args=(session_id,),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "session_id": session_id}


@router.post("/start")
async def start_evaluation(request: dict = None):
    """Start a new evaluation run in a background thread."""
    request = request or {}
    topic_id = request.get("topic_id", "")
    persona_file = request.get("persona_file", "average_student.json")
    max_turns = request.get("max_turns", 20)

    with _eval_lock:
        if _eval_state["status"] not in (EvalStatus.idle, EvalStatus.complete, EvalStatus.failed):
            raise HTTPException(status_code=409, detail="Evaluation already running")
        _eval_state.update({
            "status": EvalStatus.loading_persona,
            "run_id": None,
            "detail": "Initializing...",
            "turn": 0,
            "max_turns": max_turns,
            "error": None,
        })

    thread = threading.Thread(
        target=_run_evaluation_pipeline,
        args=(topic_id, persona_file, max_turns),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "topic_id": topic_id, "max_turns": max_turns}


@router.get("/status")
async def get_evaluation_status():
    """Get the current evaluation pipeline status."""
    with _eval_lock:
        return {
            "status": _eval_state["status"],
            "run_id": _eval_state["run_id"],
            "detail": _eval_state["detail"],
            "turn": _eval_state["turn"],
            "max_turns": _eval_state["max_turns"],
            "error": _eval_state["error"],
        }


@router.get("/runs")
async def list_evaluation_runs():
    """List all evaluation runs with summary data."""
    if not RUNS_DIR.exists():
        return []

    runs = []
    for run_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
        if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
            continue

        config_path = run_dir / "config.json"
        conversation_path = run_dir / "conversation.json"
        evaluation_path = run_dir / "evaluation.json"

        if not config_path.exists():
            continue

        try:
            with open(config_path) as f:
                config = json.load(f)

            ts_str = run_dir.name.replace("run_", "")
            timestamp = datetime.strptime(ts_str, "%Y%m%d_%H%M%S").isoformat()

            message_count = 0
            if conversation_path.exists():
                with open(conversation_path) as f:
                    conv_data = json.load(f)
                    message_count = conv_data.get("message_count", 0)

            avg_score = None
            scores = {}
            if evaluation_path.exists():
                with open(evaluation_path) as f:
                    eval_data = json.load(f)
                    avg_score = eval_data.get("avg_score")
                    scores = eval_data.get("scores", {})

            runs.append({
                "run_id": run_dir.name,
                "timestamp": config.get("started_at", timestamp),
                "topic_id": config.get("topic_id", "unknown"),
                "message_count": message_count,
                "avg_score": avg_score,
                "scores": scores,
                "source": config.get("source", "simulated"),
                "source_session_id": config.get("source_session_id"),
            })
        except Exception as e:
            logger.warning(f"Failed to read run {run_dir.name}: {e}")
            continue

    return runs


@router.get("/runs/{run_id}")
async def get_evaluation_run(run_id: str):
    """Get full data for a specific evaluation run."""
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    result = {"run_id": run_id}

    config_path = run_dir / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            result["config"] = json.load(f)

    conversation_path = run_dir / "conversation.json"
    if conversation_path.exists():
        with open(conversation_path) as f:
            conv_data = json.load(f)
            result["messages"] = conv_data.get("messages", [])
            result["message_count"] = conv_data.get("message_count", 0)

    evaluation_path = run_dir / "evaluation.json"
    if evaluation_path.exists():
        with open(evaluation_path) as f:
            result["evaluation"] = json.load(f)

    return result


@router.post("/runs/{run_id}/retry-evaluation")
async def retry_evaluation(run_id: str):
    """Re-run just the evaluation + report steps on an existing conversation."""
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    conversation_path = run_dir / "conversation.json"
    if not conversation_path.exists():
        raise HTTPException(status_code=400, detail="No conversation.json in this run")

    config_path = run_dir / "config.json"
    if not config_path.exists():
        raise HTTPException(status_code=400, detail="No config.json in this run")

    with _eval_lock:
        if _eval_state["status"] not in (EvalStatus.idle, EvalStatus.complete, EvalStatus.failed):
            raise HTTPException(status_code=409, detail="Evaluation already running")
        _eval_state.update({
            "status": EvalStatus.evaluating,
            "run_id": run_id,
            "detail": "Re-running evaluation...",
            "turn": 0,
            "max_turns": 0,
            "error": None,
        })

    thread = threading.Thread(
        target=_retry_evaluation,
        args=(run_dir,),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "run_id": run_id}
