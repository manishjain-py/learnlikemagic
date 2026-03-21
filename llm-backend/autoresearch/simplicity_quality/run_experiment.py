"""
Simplicity Quality Experiment Runner

Runs the 2-stage pipeline:
1. SIMULATE — Full session across multiple topics (with prompt capture)
2. EVALUATE — Simplicity judge scores cards + tutor messages, flags complex parts

Usage:
    cd llm-backend

    # Run with defaults (3 topics, average_student persona)
    python -m autoresearch.simplicity_quality.run_experiment --skip-server

    # With email report
    python -m autoresearch.simplicity_quality.run_experiment --skip-server --email manish@simplifyloop.com

    # Quick mode (1 topic, 12 turns)
    python -m autoresearch.simplicity_quality.run_experiment --skip-server --quick
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autoresearch.simplicity_quality.evaluation.config import (
    SimplicityConfig,
    RUNS_DIR,
    TOPIC_POOL,
    select_topics,
)
from autoresearch.session_experience.evaluation.session_runner import run_session_with_prompts
from autoresearch.simplicity_quality.evaluation.simplicity_evaluator import SimplicityEvaluator
from autoresearch.simplicity_quality.evaluation.report_generator import SimplicityReportGenerator

AUTORESEARCH_DIR = Path(__file__).parent
RESULTS_FILE = AUTORESEARCH_DIR / "results.tsv"

DEFAULT_PERSONA = "average_student.json"
DEFAULT_MAX_TURNS = 20
QUICK_MAX_TURNS = 12


def get_prompt_diff() -> str:
    """Get git diff of prompt files."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--", "tutor/prompts/", "tutor/agents/master_tutor.py",
             "tutor/services/session_service.py", "book_ingestion_v2/prompts/"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent.parent),
        )
        return result.stdout.strip() or "(no changes)"
    except Exception:
        return "(could not compute diff)"


def get_short_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(Path(__file__).parent.parent.parent),
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def run_single_topic(
    config: SimplicityConfig,
    persona: dict,
    topic: dict,
    skip_server: bool,
    restart_server: bool,
) -> dict:
    """Run one session on one topic: simulate -> evaluate simplicity."""
    topic_id = topic["id"]
    topic_name = topic["name"]
    config.topic_id = topic_id

    started_at = datetime.now()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    topic_slug = topic_name.replace(" ", "_").replace(":", "")[:40]
    run_dir = RUNS_DIR / f"simp_{timestamp}_{topic_slug}"
    run_dir.mkdir(parents=True, exist_ok=True)

    report = SimplicityReportGenerator(
        run_dir, config, topic_name=topic_name,
        started_at=started_at.isoformat(), persona=persona,
    )
    report.save_config()

    try:
        # Stage 1: Simulate
        print(f"    [simulate] Running session: {topic_name}...")
        session_data = run_session_with_prompts(
            config, persona, run_dir,
            skip_server=skip_server,
            restart_server=restart_server,
        )

        conversation = session_data["conversation"]
        prompts = session_data["prompts"]
        card_phase_data = session_data["card_phase_data"]

        report.save_conversation_md(conversation, card_phase_data=card_phase_data)
        report.save_conversation_json(
            conversation, prompts,
            metadata=session_data["session_metadata"],
            card_phase_data=card_phase_data,
        )

        print(f"    [simulate] Done: {len(conversation)} messages, {len(prompts)} prompts captured")

        # Stage 2: Evaluate simplicity
        print(f"    [evaluate] Running simplicity judge...")
        evaluator = SimplicityEvaluator(config)
        evaluation = evaluator.evaluate(
            conversation, persona=persona,
            card_phase_data=card_phase_data,
            topic_name=topic_name,
        )

        report.save_simplicity_evaluation(evaluation)
        report.save_review(evaluation)

        flagged = evaluation.get("flagged_messages", [])
        overall = evaluation.get("overall_simplicity_score", 0)
        card_score = evaluation.get("card_phase_simplicity")
        tutor_score = evaluation.get("interactive_tutor_simplicity", 0)
        relatability = evaluation.get("relatability", 0)
        progressive = evaluation.get("progressive_building", 0)
        counts = evaluation.get("issue_count_by_severity", {})

        card_str = f"cards={card_score}" if card_score is not None else "cards=n/a"
        print(
            f"    [evaluate] Simplicity: {overall}/10 ({card_str} tutor={tutor_score}) "
            f"flagged: {counts.get('critical', 0)}C {counts.get('major', 0)}M {counts.get('minor', 0)}m"
        )

        # Compute weighted issue score
        weighted_issues = (
            counts.get("critical", 0) * 3
            + counts.get("major", 0) * 2
            + counts.get("minor", 0) * 1
        )

        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "overall_simplicity": overall,
            "card_simplicity": card_score,
            "tutor_simplicity": tutor_score,
            "relatability": relatability,
            "progressive_building": progressive,
            "weighted_issues": weighted_issues,
            "issue_counts": counts,
            "flagged_count": len(flagged),
            "message_count": len(conversation),
            "run_dir": str(run_dir),
            "status": "ok",
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "overall_simplicity": 0,
            "card_simplicity": None,
            "tutor_simplicity": 0,
            "relatability": 0,
            "progressive_building": 0,
            "weighted_issues": 99,
            "issue_counts": {},
            "flagged_count": 0,
            "message_count": 0,
            "run_dir": str(run_dir),
            "status": f"crash: {e}",
        }


def run_experiment(
    topics: list[dict],
    config: SimplicityConfig,
    persona: dict,
    skip_server: bool,
    restart_server: bool,
    runs_per_topic: int = 1,
) -> dict:
    """Run the full experiment across all selected topics."""
    t0 = time.time()
    all_results = []

    total_runs = len(topics) * runs_per_topic
    run_idx = 0

    for i, topic in enumerate(topics, 1):
        for run_num in range(1, runs_per_topic + 1):
            run_idx += 1
            label = f"[{run_idx}/{total_runs}] {topic['name']}"
            if runs_per_topic > 1:
                label += f" (run {run_num}/{runs_per_topic})"
            print(f"\n  {label}")
            result = run_single_topic(config, persona, topic, skip_server, restart_server)
            result["run_num"] = run_num
            all_results.append(result)

    elapsed = time.time() - t0

    ok_results = [r for r in all_results if r["status"] == "ok"]
    if not ok_results:
        return {
            "avg_simplicity": 0,
            "avg_card_simplicity": None,
            "avg_tutor_simplicity": 0,
            "avg_weighted_issues": 99,
            "avg_relatability": 0,
            "avg_progressive_building": 0,
            "per_topic": all_results,
            "elapsed_seconds": elapsed,
            "status": "crash",
        }

    avg_simplicity = sum(r["overall_simplicity"] for r in ok_results) / len(ok_results)
    avg_weighted_issues = sum(r["weighted_issues"] for r in ok_results) / len(ok_results)
    avg_relatability = sum(r["relatability"] for r in ok_results) / len(ok_results)
    avg_progressive = sum(r["progressive_building"] for r in ok_results) / len(ok_results)

    card_scores = [r["card_simplicity"] for r in ok_results if r["card_simplicity"] is not None]
    avg_card = sum(card_scores) / len(card_scores) if card_scores else None

    tutor_scores = [r["tutor_simplicity"] for r in ok_results]
    avg_tutor = sum(tutor_scores) / len(tutor_scores) if tutor_scores else 0

    if runs_per_topic > 1:
        scores = [r["overall_simplicity"] for r in ok_results]
        scores_str = ", ".join(f"{s}" for s in scores)
        print(f"\n  Averaged {len(ok_results)} runs: [{scores_str}] -> simplicity={avg_simplicity:.2f}")

    return {
        "avg_simplicity": avg_simplicity,
        "avg_card_simplicity": avg_card,
        "avg_tutor_simplicity": avg_tutor,
        "avg_weighted_issues": avg_weighted_issues,
        "avg_relatability": avg_relatability,
        "avg_progressive_building": avg_progressive,
        "per_topic": all_results,
        "elapsed_seconds": elapsed,
        "status": "ok",
    }


def load_baseline() -> dict | None:
    """Load baseline from results.tsv."""
    if not RESULTS_FILE.exists():
        return None
    with open(RESULTS_FILE) as f:
        lines = f.readlines()
    for line in lines[1:]:
        parts = line.strip().split("\t")
        if len(parts) >= 7 and parts[5] in ("keep", "baseline"):
            try:
                return {
                    "avg_simplicity": float(parts[1]),
                    "avg_weighted_issues": float(parts[4]),
                }
            except (ValueError, json.JSONDecodeError):
                continue
    return None


def append_result(
    commit: str,
    avg_simplicity: float,
    avg_card_simplicity: float | None,
    avg_tutor_simplicity: float,
    avg_weighted_issues: float,
    status: str,
    description: str,
    elapsed: float,
    topics_used: list[str],
    details_json: str,
):
    """Append a row to results.tsv."""
    header = "commit\tavg_simplicity\tavg_card_simplicity\tavg_tutor_simplicity\tavg_weighted_issues\tstatus\tdescription\telapsed_min\ttopics\tdetails_json\n"
    if not RESULTS_FILE.exists():
        with open(RESULTS_FILE, "w") as f:
            f.write(header)

    elapsed_min = f"{elapsed / 60:.1f}"
    card_str = f"{avg_card_simplicity:.2f}" if avg_card_simplicity is not None else "n/a"
    topics_str = "|".join(topics_used)
    with open(RESULTS_FILE, "a") as f:
        f.write(f"{commit}\t{avg_simplicity:.2f}\t{card_str}\t{avg_tutor_simplicity:.2f}\t{avg_weighted_issues:.1f}\t{status}\t{description}\t{elapsed_min}\t{topics_str}\t{details_json}\n")


def main():
    parser = argparse.ArgumentParser(description="Run simplicity quality experiment")
    parser.add_argument("--topic-id", default=None, help="Single topic ID (overrides rotation)")
    parser.add_argument("--topics", type=int, default=None, help="Number of topics to rotate")
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--skip-server", action="store_true")
    parser.add_argument("--restart-server", action="store_true")
    parser.add_argument("--quick", action="store_true", help="Quick mode: 1 topic, 12 turns")
    parser.add_argument("--email", default=None)
    parser.add_argument("--description", default="")
    parser.add_argument("--iteration", type=int, default=0)
    parser.add_argument("--seed", type=int, default=None, help="Random seed for topic selection")
    parser.add_argument("--provider", default=None, help="LLM provider override (openai/anthropic)")
    parser.add_argument("--runs", type=int, default=1, help="Runs per topic (default 1; use 2-3 to reduce variance)")
    args = parser.parse_args()

    # Resolve topics
    if args.topic_id:
        topic_match = next((t for t in TOPIC_POOL if t["id"] == args.topic_id), None)
        if topic_match:
            topics = [topic_match]
        else:
            topics = [{"id": args.topic_id, "name": "Custom Topic"}]
    elif args.quick:
        topics = select_topics(1, seed=args.seed)
    else:
        n = args.topics or 3
        topics = select_topics(n, seed=args.seed)

    max_turns = args.max_turns or (QUICK_MAX_TURNS if args.quick else DEFAULT_MAX_TURNS)

    # Build config from DB (no hardcoded models)
    from database import get_db_manager
    db = get_db_manager().session_factory()
    try:
        config = SimplicityConfig.from_db(db, max_turns=max_turns)
    finally:
        db.close()

    if args.provider:
        config.evaluator_provider = args.provider
        config.simulator_provider = args.provider

    persona = config.load_persona()

    print(f"\n{'='*60}")
    print(f"  Simplicity Quality Experiment")
    print(f"  Topics: {[t['name'] for t in topics]}")
    print(f"  Persona: {persona['name']} ({persona['persona_id']})")
    print(f"  Max turns: {max_turns}")
    print(f"  Evaluator: {config.evaluator_model_label}")
    if args.description:
        print(f"  Description: {args.description}")
    print(f"{'='*60}")

    if args.runs > 1:
        print(f"  Runs per topic: {args.runs} (averaging to reduce variance)")

    # Run
    results = run_experiment(topics, config, persona, args.skip_server, args.restart_server, runs_per_topic=args.runs)

    # Print results
    commit = get_short_commit()
    avg_simp = results["avg_simplicity"]
    avg_card = results["avg_card_simplicity"]
    avg_tutor = results["avg_tutor_simplicity"]
    avg_issues = results["avg_weighted_issues"]
    avg_rel = results["avg_relatability"]
    avg_prog = results["avg_progressive_building"]
    elapsed = results["elapsed_seconds"]

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Commit: {commit}")
    print(f"  Overall Simplicity: {avg_simp:.2f}/10")
    card_str = f"{avg_card:.2f}" if avg_card is not None else "n/a"
    print(f"  Card Phase Simplicity: {card_str}/10")
    print(f"  Interactive Tutor Simplicity: {avg_tutor:.2f}/10")
    print(f"  Weighted Issues: {avg_issues:.1f}")
    print(f"  Relatability: {avg_rel:.2f}/10")
    print(f"  Progressive Building: {avg_prog:.2f}/10")
    print(f"  Elapsed: {elapsed/60:.1f} minutes")
    print()
    print("  Per Run:")
    for r in results["per_topic"]:
        status = "ok" if r["status"] == "ok" else "CRASH"
        c_str = f"cards={r['card_simplicity']}" if r.get("card_simplicity") is not None else "cards=n/a"
        print(
            f"    {r['topic_name'][:35]:.<38} simp={r['overall_simplicity']}/10  "
            f"{c_str}  tutor={r['tutor_simplicity']}  issues={r['weighted_issues']}  ({status})"
        )

    print(f"{'='*60}")

    # Machine-readable output
    print(f"\n---")
    print(f"avg_simplicity: {avg_simp:.6f}")
    print(f"avg_weighted_issues: {avg_issues:.1f}")
    print(f"elapsed_min: {elapsed/60:.1f}")
    print(f"commit: {commit}")
    print(f"status: {'crash' if results['status'] == 'crash' else 'pending'}")

    # Append to results.tsv
    topic_names = [r["topic_name"] for r in results["per_topic"]]
    details = json.dumps({
        "per_topic": [
            {
                "name": r["topic_name"],
                "overall": r["overall_simplicity"],
                "card": r["card_simplicity"],
                "tutor": r["tutor_simplicity"],
                "issues": r["weighted_issues"],
            }
            for r in results["per_topic"]
        ]
    })
    append_result(
        commit, avg_simp, avg_card, avg_tutor, avg_issues,
        "pending", args.description or "(no desc)", elapsed, topic_names, details,
    )

    # Email
    if args.email:
        baseline = load_baseline()
        prompt_diff = get_prompt_diff()
        run_dirs = [r["run_dir"] for r in results.get("per_topic", []) if r.get("run_dir")]
        from autoresearch.simplicity_quality.email_report import send_simplicity_report
        send_simplicity_report(
            iteration=args.iteration,
            description=args.description or "(no description)",
            avg_simplicity=avg_simp,
            avg_card_simplicity=avg_card,
            avg_tutor_simplicity=avg_tutor,
            avg_weighted_issues=avg_issues,
            avg_relatability=avg_rel,
            avg_progressive_building=avg_prog,
            baseline=baseline,
            per_topic=results["per_topic"],
            prompt_diff=prompt_diff,
            email_to=args.email,
            run_dirs=run_dirs,
        )

    return results


if __name__ == "__main__":
    main()
