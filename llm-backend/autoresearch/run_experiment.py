"""
Autoresearch Experiment Runner

Runs the evaluation pipeline against a fixed set of personas,
computes a single composite score, and optionally emails a report.

This is the autoresearch equivalent of running `uv run train.py` —
a single command that produces a numeric quality metric.

Usage:
    cd llm-backend

    # Run a single experiment (requires server running)
    python -m autoresearch.run_experiment --skip-server

    # With email report
    python -m autoresearch.run_experiment --skip-server --email manish@example.com

    # Custom personas
    python -m autoresearch.run_experiment --skip-server --personas average_student,ace,struggler

    # Quick mode (fewer turns, fewer personas — for faster iteration)
    python -m autoresearch.run_experiment --skip-server --quick
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Add llm-backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluation.config import EvalConfig, RUNS_DIR
from evaluation.student_simulator import StudentSimulator
from evaluation.session_runner import SessionRunner
from evaluation.evaluator import ConversationEvaluator
from evaluation.report_generator import ReportGenerator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AUTORESEARCH_DIR = Path(__file__).parent
RESULTS_FILE = AUTORESEARCH_DIR / "results.tsv"

# Single persona: the average student — our primary target user.
# This is the student who needs the tutor app the most: average IQ, needs
# simple language, concrete examples, patient scaffolding. If we optimize
# for this student, we serve our core audience.
DEFAULT_PERSONAS = ["average_student.json"]
QUICK_PERSONAS = ["average_student.json"]

DEFAULT_MAX_TURNS = 20
QUICK_MAX_TURNS = 12


def get_prompt_diff() -> str:
    """Get git diff of prompt files (the modifiable surface)."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--", "tutor/prompts/"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
        )
        return result.stdout.strip() or "(no changes)"
    except Exception:
        return "(could not compute diff)"


def resolve_topic_id(subject: str = "Mathematics", chapter: str = "Fractions") -> str:
    """Resolve a topic ID from the database. Falls back to env var."""
    topic_id = __import__("os").environ.get("AUTORESEARCH_TOPIC_ID")
    if topic_id:
        return topic_id

    try:
        from database import get_db_manager
        from shared.models.entities import TeachingGuideline
        from sqlalchemy import func

        db_manager = get_db_manager()
        db = db_manager.session_factory()
        try:
            guideline = db.query(TeachingGuideline).filter(
                func.lower(TeachingGuideline.subject) == subject.lower(),
                func.lower(TeachingGuideline.chapter) == chapter.lower(),
            ).order_by(
                TeachingGuideline.review_status.desc(),
                TeachingGuideline.chapter_sequence,
                TeachingGuideline.topic_sequence,
            ).first()
            if guideline:
                return guideline.id
        finally:
            db.close()
    except Exception as e:
        print(f"  Warning: DB lookup failed ({e}), set AUTORESEARCH_TOPIC_ID env var.")

    print("ERROR: Could not resolve topic ID. Set AUTORESEARCH_TOPIC_ID in .env")
    sys.exit(1)


def run_single_persona(
    topic_id: str,
    persona_file: str,
    max_turns: int,
    skip_server: bool,
    provider: str | None = None,
) -> dict:
    """Run one evaluation session and return results dict."""
    config = EvalConfig(
        topic_id=topic_id,
        max_turns=max_turns,
        persona_file=persona_file,
    )
    if provider:
        config.evaluator_provider = provider
        config.simulator_provider = provider

    started_at = datetime.now()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    persona_id = persona_file.replace(".json", "")
    run_dir = RUNS_DIR / f"autoresearch_{timestamp}_{persona_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    persona = config.load_persona()
    simulator = StudentSimulator(config, persona)
    report = ReportGenerator(run_dir, config, started_at=started_at.isoformat(), persona=persona)
    report.save_config()

    runner = SessionRunner(config, simulator, run_dir, skip_server_management=skip_server)

    try:
        runner.start_server()
        conversation = runner.run_session()
        metadata = runner.session_metadata

        report.save_conversation_md(conversation)
        report.save_conversation_json(conversation, metadata)

        evaluator = ConversationEvaluator(config)
        evaluation = evaluator.evaluate(conversation, persona=persona)

        report.save_evaluation_json(evaluation)
        report.save_review(evaluation)
        report.save_problems(evaluation)

        scores = evaluation.get("scores", {})
        avg_score = sum(scores.values()) / len(scores) if scores else 0
        problems = evaluation.get("problems", [])

        return {
            "persona_id": persona_id,
            "persona_name": persona.get("name", persona_id),
            "avg_score": avg_score,
            "scores": scores,
            "problems": [
                f"[{p.get('severity', '?').upper()}] {p.get('title', '')} (root: {p.get('root_cause', '?')})"
                for p in problems[:5]
            ],
            "message_count": len(conversation),
            "run_dir": str(run_dir),
            "status": "ok",
        }
    except Exception as e:
        return {
            "persona_id": persona_id,
            "persona_name": persona_file.replace(".json", ""),
            "avg_score": 0,
            "scores": {},
            "problems": [f"CRASH: {e}"],
            "message_count": 0,
            "run_dir": str(run_dir),
            "status": "crash",
        }
    finally:
        runner.cleanup()


def run_experiment(
    topic_id: str,
    personas: list[str],
    max_turns: int,
    skip_server: bool,
    provider: str | None = None,
) -> dict:
    """Run the full experiment across all personas. Returns composite results."""
    t0 = time.time()
    all_results = []

    for i, persona_file in enumerate(personas, 1):
        persona_id = persona_file.replace(".json", "")
        print(f"  [{i}/{len(personas)}] Running persona: {persona_id}...")
        result = run_single_persona(topic_id, persona_file, max_turns, skip_server, provider)
        all_results.append(result)
        status = "ok" if result["status"] == "ok" else "CRASH"
        print(f"    {status} — {result['persona_name']}: {result['avg_score']:.1f}/10, {result['message_count']} msgs")

    elapsed = time.time() - t0

    # Compute composite scores (average across all personas)
    ok_results = [r for r in all_results if r["status"] == "ok"]
    if not ok_results:
        return {
            "avg_score": 0,
            "scores": {},
            "problems": ["ALL PERSONAS CRASHED"],
            "per_persona": all_results,
            "elapsed_seconds": elapsed,
            "status": "crash",
        }

    # Average each dimension across personas
    all_dims = set()
    for r in ok_results:
        all_dims.update(r["scores"].keys())

    composite_scores = {}
    for dim in sorted(all_dims):
        vals = [r["scores"][dim] for r in ok_results if dim in r["scores"]]
        composite_scores[dim] = sum(vals) / len(vals) if vals else 0

    composite_avg = sum(composite_scores.values()) / len(composite_scores) if composite_scores else 0

    # Aggregate problems (deduplicate by title prefix)
    all_problems = []
    for r in ok_results:
        all_problems.extend(r["problems"])

    return {
        "avg_score": composite_avg,
        "scores": composite_scores,
        "problems": all_problems[:10],
        "per_persona": all_results,
        "elapsed_seconds": elapsed,
        "status": "ok",
    }


def load_baseline() -> dict | None:
    """Load baseline scores from results.tsv (first 'keep' or 'baseline' row)."""
    if not RESULTS_FILE.exists():
        return None
    with open(RESULTS_FILE) as f:
        lines = f.readlines()
    for line in lines[1:]:  # skip header
        parts = line.strip().split("\t")
        if len(parts) >= 6 and parts[3] in ("keep", "baseline"):
            try:
                return {
                    "avg_score": float(parts[1]),
                    "scores": json.loads(parts[5]) if len(parts) > 5 else {},
                }
            except (ValueError, json.JSONDecodeError):
                continue
    return None


def append_result(
    commit: str,
    avg_score: float,
    status: str,
    description: str,
    elapsed: float,
    scores: dict,
):
    """Append a row to results.tsv."""
    header = "commit\tavg_score\telapsed_min\tstatus\tdescription\tscores_json\n"
    if not RESULTS_FILE.exists():
        with open(RESULTS_FILE, "w") as f:
            f.write(header)

    scores_json = json.dumps(scores)
    elapsed_min = f"{elapsed / 60:.1f}"
    with open(RESULTS_FILE, "a") as f:
        f.write(f"{commit}\t{avg_score:.4f}\t{elapsed_min}\t{status}\t{description}\t{scores_json}\n")


def get_short_commit() -> str:
    """Get current short git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main():
    parser = argparse.ArgumentParser(description="Run autoresearch experiment")
    parser.add_argument("--topic-id", default=None, help="Guideline ID (or set AUTORESEARCH_TOPIC_ID)")
    parser.add_argument("--subject", default="Mathematics", help="Subject for topic resolution")
    parser.add_argument("--chapter", default="Fractions", help="Chapter for topic resolution")
    parser.add_argument("--personas", default=None, help="Comma-separated persona files (e.g., average_student.json,ace.json)")
    parser.add_argument("--max-turns", type=int, default=None, help="Max turns per session")
    parser.add_argument("--skip-server", action="store_true", help="Use already-running server")
    parser.add_argument("--quick", action="store_true", help="Quick mode (1 persona, fewer turns)")
    parser.add_argument("--provider", default=None, help="LLM provider (openai/anthropic)")
    parser.add_argument("--email", default=None, help="Email address for iteration report")
    parser.add_argument("--description", default="", help="Description of what this experiment tries")
    parser.add_argument("--iteration", type=int, default=0, help="Iteration number (for email subject)")
    args = parser.parse_args()

    # Resolve settings
    if args.quick:
        personas = QUICK_PERSONAS
        max_turns = QUICK_MAX_TURNS
    else:
        personas = DEFAULT_PERSONAS
        max_turns = DEFAULT_MAX_TURNS

    if args.personas:
        personas = [p.strip() if p.strip().endswith(".json") else f"{p.strip()}.json" for p in args.personas.split(",")]
    if args.max_turns is not None:
        max_turns = args.max_turns

    topic_id = args.topic_id or resolve_topic_id(args.subject, args.chapter)

    print(f"\n{'='*60}")
    print(f"  Autoresearch Experiment")
    print(f"  Topic: {topic_id}")
    print(f"  Personas: {[p.replace('.json', '') for p in personas]}")
    print(f"  Max turns: {max_turns}")
    if args.description:
        print(f"  Description: {args.description}")
    print(f"{'='*60}\n")

    # Run experiment
    results = run_experiment(topic_id, personas, max_turns, args.skip_server, args.provider)

    # Print results
    commit = get_short_commit()
    status = "crash" if results["status"] == "crash" else "pending"
    avg = results["avg_score"]
    scores = results["scores"]
    elapsed = results["elapsed_seconds"]

    print(f"\n{'='*60}")
    print(f"  EXPERIMENT RESULTS")
    print(f"{'='*60}")
    print(f"  Commit: {commit}")
    print(f"  Avg Score: {avg:.2f}/10")
    print(f"  Elapsed: {elapsed/60:.1f} minutes")
    print()
    print("  Scores:")
    for dim, score in scores.items():
        print(f"    {dim.replace('_', ' ').title():.<30} {score:.1f}/10")
    print()
    print("  Per Persona:")
    for r in results["per_persona"]:
        s = "ok" if r["status"] == "ok" else "CRASH"
        print(f"    {r['persona_name']:.<20} {r['avg_score']:.1f}/10  ({s})")
    print(f"{'='*60}")

    # Output machine-readable result
    print(f"\n---")
    print(f"avg_score: {avg:.6f}")
    print(f"elapsed_min: {elapsed/60:.1f}")
    print(f"commit: {commit}")
    print(f"status: {status}")

    # Email report if requested
    if args.email:
        baseline = load_baseline()
        prompt_diff = get_prompt_diff()
        from autoresearch.email_report import send_iteration_report
        send_iteration_report(
            iteration=args.iteration,
            description=args.description or "(no description)",
            status=status,
            scores=scores,
            baseline_scores=baseline["scores"] if baseline else None,
            avg_score=avg,
            baseline_avg=baseline["avg_score"] if baseline else None,
            problems_summary=results["problems"],
            prompt_diff=prompt_diff,
            email_to=args.email,
        )

    return results


if __name__ == "__main__":
    main()
