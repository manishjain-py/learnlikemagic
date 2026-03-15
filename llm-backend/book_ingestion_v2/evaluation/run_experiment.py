"""
Book Ingestion Evaluation Runner

Runs the topic extraction pipeline on a chapter and evaluates the output,
or evaluates existing extracted topics without re-running extraction.

Usage:
    cd llm-backend

    # Evaluate existing topics (no re-extraction)
    python -m book_ingestion_v2.evaluation.run_experiment --chapter-id <id> --skip-extraction

    # Run fresh extraction + evaluate
    python -m book_ingestion_v2.evaluation.run_experiment --chapter-id <id>

    # Multiple runs for variance reduction
    python -m book_ingestion_v2.evaluation.run_experiment --chapter-id <id> --skip-extraction --runs 3

    # Use Anthropic as evaluator
    python -m book_ingestion_v2.evaluation.run_experiment --chapter-id <id> --skip-extraction --provider anthropic
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Add llm-backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from book_ingestion_v2.evaluation.config import IngestionEvalConfig, RUNS_DIR, RESULTS_FILE


def get_short_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent.parent),
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def run_single(config: IngestionEvalConfig, skip_extraction: bool) -> dict:
    """Run a single evaluation pass and return results."""
    from database import get_db_manager
    from book_ingestion_v2.evaluation.pipeline_runner import PipelineRunner
    from book_ingestion_v2.evaluation.evaluator import IngestionEvaluator
    from book_ingestion_v2.evaluation.report_generator import IngestionReportGenerator

    started_at = datetime.now()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    mode = "existing" if skip_extraction else "fresh"
    run_dir = RUNS_DIR / f"{timestamp}_{mode}_ch{config.chapter_number}"
    run_dir.mkdir(parents=True, exist_ok=True)

    report = IngestionReportGenerator(run_dir, config, started_at=started_at.isoformat())
    report.save_config()

    try:
        db_manager = get_db_manager()
        db = db_manager.session_factory()

        try:
            runner = PipelineRunner(db)

            if skip_extraction:
                print("  Loading existing topics from DB...")
                pipeline_output = runner.load_existing(config.chapter_id)
            else:
                print("  Running extraction pipeline...")
                pipeline_output = runner.run_extraction(config.chapter_id)

            topic_count = len(pipeline_output.get("topics", []))
            page_count = len(pipeline_output.get("original_pages", []))
            print(f"  Got {topic_count} topics from {page_count} pages")

            report.save_pipeline_output(pipeline_output)
            report.save_topics_md(pipeline_output)

            # Evaluate
            print(f"  Evaluating with {config.evaluator_model_label}...")
            evaluator = IngestionEvaluator(config)
            evaluation = evaluator.evaluate(pipeline_output)

            report.save_evaluation_json(evaluation)
            report.save_review(evaluation, pipeline_output)

            scores = evaluation.get("scores", {})
            avg_score = sum(scores.values()) / len(scores) if scores else 0

            return {
                "avg_score": avg_score,
                "scores": scores,
                "topic_count": topic_count,
                "problems": [
                    f"[{p.get('severity', '?').upper()}] {p.get('title', '')} (root: {p.get('root_cause', '?')})"
                    for p in evaluation.get("problems", [])[:5]
                ],
                "run_dir": str(run_dir),
                "status": "ok",
            }
        finally:
            db.close()

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "avg_score": 0,
            "scores": {},
            "topic_count": 0,
            "problems": [f"CRASH: {e}"],
            "run_dir": str(run_dir),
            "status": "crash",
        }


def run_experiment(
    config: IngestionEvalConfig,
    skip_extraction: bool,
    runs: int = 1,
) -> dict:
    """Run evaluation, optionally multiple times for variance reduction."""
    t0 = time.time()
    all_results = []

    for run_num in range(1, runs + 1):
        label = f"[run {run_num}/{runs}]" if runs > 1 else ""
        print(f"  {label} Starting evaluation...")
        result = run_single(config, skip_extraction)
        result["run_num"] = run_num
        all_results.append(result)
        status = "ok" if result["status"] == "ok" else "CRASH"
        print(f"    {status} — avg: {result['avg_score']:.1f}/10, {result['topic_count']} topics")

    elapsed = time.time() - t0

    ok_results = [r for r in all_results if r["status"] == "ok"]
    if not ok_results:
        return {
            "avg_score": 0,
            "scores": {},
            "problems": ["ALL RUNS CRASHED"],
            "per_run": all_results,
            "elapsed_seconds": elapsed,
            "status": "crash",
            "individual_scores": [],
        }

    # Average each dimension across all ok runs
    all_dims = set()
    for r in ok_results:
        all_dims.update(r["scores"].keys())

    composite_scores = {}
    for dim in sorted(all_dims):
        vals = [r["scores"][dim] for r in ok_results if dim in r["scores"]]
        composite_scores[dim] = sum(vals) / len(vals) if vals else 0

    composite_avg = sum(composite_scores.values()) / len(composite_scores) if composite_scores else 0
    individual_scores = [r["avg_score"] for r in ok_results]

    all_problems = []
    for r in ok_results:
        all_problems.extend(r["problems"])

    if runs > 1:
        scores_str = ", ".join(f"{s:.1f}" for s in individual_scores)
        print(f"\n  Averaged {len(ok_results)} runs: [{scores_str}] -> {composite_avg:.2f}")

    return {
        "avg_score": composite_avg,
        "scores": composite_scores,
        "problems": all_problems[:10],
        "per_run": all_results,
        "elapsed_seconds": elapsed,
        "status": "ok",
        "individual_scores": individual_scores,
    }


def append_result(commit: str, avg_score: float, status: str, description: str, elapsed: float, scores: dict):
    """Append a row to results.tsv."""
    header = "commit\tavg_score\telapsed_min\tstatus\tdescription\tscores_json\n"
    if not RESULTS_FILE.exists():
        with open(RESULTS_FILE, "w") as f:
            f.write(header)

    scores_json = json.dumps(scores)
    elapsed_min = f"{elapsed / 60:.1f}"
    with open(RESULTS_FILE, "a") as f:
        f.write(f"{commit}\t{avg_score:.4f}\t{elapsed_min}\t{status}\t{description}\t{scores_json}\n")


def main():
    parser = argparse.ArgumentParser(description="Run book ingestion evaluation")
    parser.add_argument("--chapter-id", required=True, help="Chapter ID to evaluate")
    parser.add_argument("--skip-extraction", action="store_true", help="Use existing topics from DB (don't re-run pipeline)")
    parser.add_argument("--runs", type=int, default=1, help="Number of evaluation runs to average")
    parser.add_argument("--provider", default=None, help="LLM provider for evaluator (openai/anthropic)")
    parser.add_argument("--description", default="", help="Description for results.tsv")
    parser.add_argument("--email", default=None, help="Email address for HTML report")

    args = parser.parse_args()

    config = IngestionEvalConfig(chapter_id=args.chapter_id)
    if args.provider:
        config.evaluator_provider = args.provider

    # Resolve chapter metadata for display and email
    chapter_info = {"chapter_number": "?", "chapter_title": "?"}
    book_metadata = {"title": "?", "subject": "?", "grade": "?", "board": "?"}
    try:
        from database import get_db_manager
        from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
        from shared.repositories.book_repository import BookRepository
        db_manager = get_db_manager()
        db = db_manager.session_factory()
        try:
            chapter = ChapterRepository(db).get_by_id(args.chapter_id)
            if chapter:
                config.chapter_number = chapter.chapter_number
                config.book_id = chapter.book_id
                chapter_info = {
                    "chapter_number": chapter.chapter_number,
                    "chapter_title": chapter.chapter_title,
                }
                book = BookRepository(db).get_by_id(chapter.book_id)
                if book:
                    book_metadata = {
                        "title": book.title,
                        "subject": book.subject,
                        "grade": book.grade,
                        "board": book.board,
                    }
        finally:
            db.close()
    except Exception:
        pass

    mode = "existing topics" if args.skip_extraction else "fresh extraction"

    print(f"\n{'='*60}")
    print(f"  Book Ingestion Evaluation")
    print(f"  Chapter: {args.chapter_id}")
    print(f"  Mode: {mode}")
    print(f"  Evaluator: {config.evaluator_model_label}")
    if args.runs > 1:
        print(f"  Runs: {args.runs} (averaging)")
    if args.description:
        print(f"  Description: {args.description}")
    print(f"{'='*60}\n")

    results = run_experiment(config, args.skip_extraction, runs=args.runs)

    commit = get_short_commit()
    avg = results["avg_score"]
    scores = results["scores"]
    elapsed = results["elapsed_seconds"]

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Commit: {commit}")
    print(f"  Avg Score: {avg:.2f}/10")
    print(f"  Elapsed: {elapsed/60:.1f} minutes")
    print()
    print("  Scores:")
    for dim, score in scores.items():
        print(f"    {dim.replace('_', ' ').title():.<30} {score:.1f}/10")
    print()
    individual = results.get("individual_scores", [])
    if len(individual) > 1:
        scores_str = ", ".join(f"{s:.1f}" for s in individual)
        print(f"  Individual runs: [{scores_str}]")
    print(f"{'='*60}")

    # Machine-readable output
    print(f"\n---")
    print(f"avg_score: {avg:.6f}")
    print(f"elapsed_min: {elapsed/60:.1f}")
    print(f"commit: {commit}")

    # Append to results.tsv
    if args.description:
        status = "crash" if results["status"] == "crash" else "pending"
        append_result(commit, avg, status, args.description, elapsed, scores)

    # Email report
    if args.email:
        from book_ingestion_v2.evaluation.email_report import send_ingestion_report
        run_dirs = [r["run_dir"] for r in results.get("per_run", []) if r.get("run_dir")]
        send_ingestion_report(
            description=args.description or "baseline evaluation",
            status="crash" if results["status"] == "crash" else "pending",
            scores=scores,
            baseline_scores=None,
            avg_score=avg,
            baseline_avg=None,
            chapter_info=chapter_info,
            book_metadata=book_metadata,
            email_to=args.email,
            run_dirs=run_dirs,
        )

    return results


if __name__ == "__main__":
    main()
