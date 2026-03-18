"""
Autoresearch Experiment Runner — Explanation Quality

Generates explanation cards for a topic (all 3 variants), evaluates each
with an LLM judge, and produces a composite quality score.

This is the explanation-quality equivalent of the tutor teaching quality
runner — a single command that produces a numeric quality metric.

Usage:
    cd llm-backend

    # Run a single experiment
    python -m autoresearch.explanation_quality.run_experiment

    # With email report
    python -m autoresearch.explanation_quality.run_experiment --email manish@example.com

    # Specific topic
    python -m autoresearch.explanation_quality.run_experiment --topic-id <guideline-id>

    # Quick mode (1 variant instead of 3)
    python -m autoresearch.explanation_quality.run_experiment --quick
"""

import argparse
import json
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Add llm-backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autoresearch.explanation_quality.evaluation.config import ExplanationEvalConfig, RUNS_DIR
from autoresearch.explanation_quality.evaluation.evaluator import ExplanationEvaluator
from autoresearch.explanation_quality.evaluation.report_generator import ExplanationReportGenerator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AUTORESEARCH_DIR = Path(__file__).parent
RESULTS_FILE = AUTORESEARCH_DIR / "results.tsv"

# Topic rotation pool — 4 diverse topics to prevent prompt overfitting.
# Conceptual, comparison, procedural, and classification.
TOPIC_POOL = [
    "b8d0b705-7a49-4fe1-bd06-eff6fec0f8b6",  # Reviewing 3-Digit Place Value
    "67607ac3-adfa-43c7-88ad-032a5ce7e18b",  # Comparing and Ordering 4-Digit Numbers
    "08ffca67-f71d-40b4-b60d-658bc688f74d",  # 3-Digit Addition: Regrouping in One Column
    "fae34b12-47dd-4ca8-9578-ae64f28ee9a6",  # Odd and Even Numbers
]

# Variant configs (same as ExplanationGeneratorService)
VARIANT_CONFIGS = [
    {"key": "A", "label": "Everyday Analogies", "approach": "analogy-driven with real-world examples"},
    {"key": "B", "label": "Visual Walkthrough", "approach": "diagram-heavy with visual step-by-step"},
    {"key": "C", "label": "Step-by-Step Procedure", "approach": "procedural walkthrough"},
]

QUICK_VARIANTS = [VARIANT_CONFIGS[0]]  # Just variant A for quick mode


def get_prompt_diff() -> str:
    """Get git diff of explanation prompt files (the modifiable surface)."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--", "book_ingestion_v2/prompts/"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent.parent),
        )
        return result.stdout.strip() or "(no changes)"
    except Exception:
        return "(could not compute diff)"


def pick_topic(topic_id: str | None = None) -> str:
    """Pick a topic — use provided ID, or rotate randomly from pool."""
    if topic_id:
        return topic_id
    return random.choice(TOPIC_POOL)


def load_guideline(topic_id: str) -> dict:
    """Load a teaching guideline from the database."""
    from database import get_db_manager
    from shared.models.entities import TeachingGuideline

    db = get_db_manager().session_factory()
    try:
        g = db.query(TeachingGuideline).filter(
            TeachingGuideline.id == topic_id,
        ).first()
        if not g:
            print(f"ERROR: Guideline {topic_id} not found")
            sys.exit(1)
        return {
            "id": g.id,
            "topic_title": g.topic_title or g.topic,
            "topic": g.topic,
            "subject": g.subject,
            "grade": g.grade,
            "chapter": g.chapter,
            "guideline": g.guideline or g.description or "",
            "prior_topics_context": g.prior_topics_context,
        }
    finally:
        db.close()


def generate_cards(guideline: dict, variant_config: dict, config: ExplanationEvalConfig) -> list[dict] | None:
    """Generate explanation cards for one variant using the explanation generation prompt.

    Calls the generation prompt directly (no DB storage) to evaluate
    what the prompt produces in isolation.
    """
    from database import get_db_manager
    from shared.models.entities import TeachingGuideline
    from book_ingestion_v2.services.explanation_generator_service import ExplanationGeneratorService

    db = get_db_manager().session_factory()
    try:
        guideline_obj = db.query(TeachingGuideline).filter(
            TeachingGuideline.id == guideline["id"],
        ).first()
        if not guideline_obj:
            return None

        llm = config.create_llm_service("generator")
        service = ExplanationGeneratorService(db, llm)
        cards, summary = service._generate_variant(guideline_obj, variant_config)

        if cards is None:
            return None

        return [c.model_dump() for c in cards]
    except Exception as e:
        print(f"    Generation failed for variant {variant_config['key']}: {e}")
        return None
    finally:
        db.close()


def run_single_variant(
    guideline: dict,
    variant_config: dict,
    config: ExplanationEvalConfig,
    run_dir: Path,
) -> dict:
    """Generate + evaluate one variant. Returns result dict."""
    variant_key = variant_config["key"]
    variant_label = variant_config["label"]

    # Generate cards
    cards = generate_cards(guideline, variant_config, config)
    if cards is None:
        return {
            "variant_key": variant_key,
            "variant_label": variant_label,
            "avg_score": 0,
            "scores": {},
            "problems": [f"GENERATION FAILED for variant {variant_key}"],
            "card_count": 0,
            "status": "crash",
        }

    # Save cards
    report = ExplanationReportGenerator(run_dir, config)
    report.save_cards(variant_key, variant_label, cards)

    # Evaluate
    evaluator = ExplanationEvaluator(config)
    evaluation = evaluator.evaluate(
        cards=cards,
        topic_title=guideline["topic_title"],
        grade=guideline["grade"],
        subject=guideline["subject"],
        guideline_text=guideline["guideline"],
    )

    # Save evaluation
    report.save_evaluation(variant_key, evaluation)

    scores = evaluation.get("scores", {})
    avg_score = sum(scores.values()) / len(scores) if scores else 0
    problems = evaluation.get("problems", [])

    return {
        "variant_key": variant_key,
        "variant_label": variant_label,
        "avg_score": avg_score,
        "scores": scores,
        "problems": [
            f"[{p.get('severity', '?').upper()}] {p.get('title', '')} (root: {p.get('root_cause', '?')})"
            for p in problems[:5]
        ],
        "card_count": len(cards),
        "status": "ok",
    }


def run_experiment(
    topic_id: str | None = None,
    variants: list[dict] | None = None,
    provider: str | None = None,
    runs: int = 1,
) -> dict:
    """Run the full experiment: pick topic, generate all variants, evaluate, average."""
    t0 = time.time()

    # Pick topic
    selected_topic_id = pick_topic(topic_id)
    guideline = load_guideline(selected_topic_id)
    variant_list = variants or VARIANT_CONFIGS

    from database import get_db_manager
    db = get_db_manager().session_factory()
    try:
        config = ExplanationEvalConfig.from_db(
            db,
            topic_id=selected_topic_id,
            topic_title=guideline["topic_title"],
            grade=guideline["grade"],
            subject=guideline["subject"],
        )
    finally:
        db.close()

    if provider:
        config.evaluator_provider = provider

    all_results = []

    for run_num in range(1, runs + 1):
        started_at = datetime.now()
        timestamp = started_at.strftime("%Y%m%d_%H%M%S")
        run_dir = RUNS_DIR / f"expl_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        report = ExplanationReportGenerator(run_dir, config, started_at=started_at.isoformat())
        report.save_config()

        run_variant_results = []
        for vc in variant_list:
            run_label = f"[run {run_num}/{runs}] " if runs > 1 else ""
            print(f"  {run_label}Variant {vc['key']} ({vc['label']}) — generating + evaluating...")
            result = run_single_variant(guideline, vc, config, run_dir)
            result["run_num"] = run_num
            run_variant_results.append(result)
            status = "ok" if result["status"] == "ok" else "CRASH"
            print(f"    {status} — {result['card_count']} cards, {result['avg_score']:.1f}/10")

        # Save combined review
        evaluations = {}
        for r in run_variant_results:
            if r["status"] == "ok":
                eval_path = run_dir / f"evaluation_{r['variant_key']}.json"
                if eval_path.exists():
                    evaluations[r["variant_key"]] = json.loads(eval_path.read_text())
        if evaluations:
            report.save_review(evaluations, guideline["topic_title"])

        all_results.extend(run_variant_results)

    elapsed = time.time() - t0

    # Aggregate scores across all ok variants and runs
    ok_results = [r for r in all_results if r["status"] == "ok"]
    if not ok_results:
        return {
            "avg_score": 0,
            "scores": {},
            "problems": ["ALL VARIANTS CRASHED"],
            "per_variant": all_results,
            "elapsed_seconds": elapsed,
            "status": "crash",
            "topic_id": selected_topic_id,
            "topic_title": guideline["topic_title"],
            "individual_scores": [],
        }

    # Average each dimension across all ok results
    all_dims = set()
    for r in ok_results:
        all_dims.update(r["scores"].keys())

    composite_scores = {}
    for dim in sorted(all_dims):
        vals = [r["scores"][dim] for r in ok_results if dim in r["scores"]]
        composite_scores[dim] = sum(vals) / len(vals) if vals else 0

    composite_avg = sum(composite_scores.values()) / len(composite_scores) if composite_scores else 0
    individual_scores = [r["avg_score"] for r in ok_results]

    # Aggregate problems
    all_problems = []
    for r in ok_results:
        all_problems.extend(r["problems"])

    if len(individual_scores) > 1:
        scores_str = ", ".join(f"{s:.1f}" for s in individual_scores)
        print(f"\n  Averaged {len(ok_results)} evaluations: [{scores_str}] -> {composite_avg:.2f}")

    return {
        "avg_score": composite_avg,
        "scores": composite_scores,
        "problems": all_problems[:10],
        "per_variant": all_results,
        "elapsed_seconds": elapsed,
        "status": "ok",
        "topic_id": selected_topic_id,
        "topic_title": guideline["topic_title"],
        "individual_scores": individual_scores,
    }


def load_baseline() -> dict | None:
    """Load baseline scores from results.tsv."""
    if not RESULTS_FILE.exists():
        return None
    with open(RESULTS_FILE) as f:
        lines = f.readlines()
    for line in lines[1:]:
        parts = line.strip().split("\t")
        if len(parts) >= 7 and parts[3] in ("keep", "baseline"):
            try:
                return {
                    "avg_score": float(parts[1]),
                    "scores": json.loads(parts[6]) if len(parts) > 6 else {},
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
    topic_title: str,
    scores: dict,
):
    """Append a row to results.tsv."""
    header = "commit\tavg_score\telapsed_min\tstatus\tdescription\ttopic\tscores_json\n"
    if not RESULTS_FILE.exists():
        with open(RESULTS_FILE, "w") as f:
            f.write(header)

    scores_json = json.dumps(scores)
    elapsed_min = f"{elapsed / 60:.1f}"
    with open(RESULTS_FILE, "a") as f:
        f.write(f"{commit}\t{avg_score:.4f}\t{elapsed_min}\t{status}\t{description}\t{topic_title}\t{scores_json}\n")


def get_short_commit() -> str:
    """Get current short git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent.parent),
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main():
    parser = argparse.ArgumentParser(description="Run explanation quality experiment")
    parser.add_argument("--topic-id", default=None, help="Guideline ID (random from pool if not set)")
    parser.add_argument("--quick", action="store_true", help="Quick mode (1 variant instead of 3)")
    parser.add_argument("--provider", default=None, help="LLM provider for evaluator (openai/anthropic)")
    parser.add_argument("--email", default=None, help="Email address for iteration report")
    parser.add_argument("--description", default="", help="Description of what this experiment tries")
    parser.add_argument("--iteration", type=int, default=0, help="Iteration number")
    parser.add_argument("--runs", type=int, default=1, help="Number of runs to average")
    args = parser.parse_args()

    variants = QUICK_VARIANTS if args.quick else VARIANT_CONFIGS

    print(f"\n{'='*60}")
    print(f"  Explanation Quality Experiment")
    print(f"  Topic: {'random from pool' if not args.topic_id else args.topic_id}")
    print(f"  Variants: {[v['key'] for v in variants]}")
    if args.description:
        print(f"  Description: {args.description}")
    print(f"{'='*60}\n")

    # Run experiment
    results = run_experiment(
        topic_id=args.topic_id,
        variants=variants,
        provider=args.provider,
        runs=args.runs,
    )

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
    print(f"  Topic: {results['topic_title']}")
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
        print(f"  Individual variants: [{scores_str}]")
    print()
    print("  Per Variant:")
    for r in results["per_variant"]:
        s = "ok" if r["status"] == "ok" else "CRASH"
        print(f"    Variant {r['variant_key']} ({r['variant_label']:.<25}) {r['avg_score']:.1f}/10  ({s}, {r['card_count']} cards)")
    print(f"{'='*60}")

    # Machine-readable output
    print(f"\n---")
    print(f"avg_score: {avg:.6f}")
    print(f"elapsed_min: {elapsed/60:.1f}")
    print(f"commit: {commit}")
    print(f"status: {status}")

    # Append to results.tsv
    append_result(commit, avg, status, args.description or "(no description)", elapsed, results["topic_title"], scores)

    # Email report
    if args.email:
        baseline = load_baseline()
        prompt_diff = get_prompt_diff()
        run_dirs = []
        for r in results.get("per_variant", []):
            # Derive run_dir from any saved evaluation file
            pass  # email_report reads from results directly

        from autoresearch.explanation_quality.email_report import send_iteration_report
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
            topic_title=results["topic_title"],
        )

    return results


if __name__ == "__main__":
    main()
