"""
Session Experience Experiment Runner

Runs the 3-stage pipeline:
1. SIMULATE — Full session across multiple topics (with prompt capture)
2. EVALUATE — Naturalness judge flags specific messages
3. ANALYZE — Trace flagged messages to prompt instructions

Usage:
    cd llm-backend

    # Run with defaults (3 topics, average_student persona)
    python -m autoresearch.session_experience.run_experiment --skip-server

    # With email report
    python -m autoresearch.session_experience.run_experiment --skip-server --email manish@example.com

    # Specific topic
    python -m autoresearch.session_experience.run_experiment --skip-server --topic-id <id>

    # Quick mode (1 topic, 12 turns)
    python -m autoresearch.session_experience.run_experiment --skip-server --quick
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autoresearch.session_experience.evaluation.config import (
    SessionExperienceConfig,
    RUNS_DIR,
    TOPIC_POOL,
    select_topics,
)
from autoresearch.session_experience.evaluation.session_runner import run_session_with_prompts
from autoresearch.session_experience.evaluation.experience_evaluator import ExperienceEvaluator
from autoresearch.session_experience.evaluation.prompt_analyzer import PromptAnalyzer
from autoresearch.session_experience.evaluation.report_generator import SessionExperienceReportGenerator

AUTORESEARCH_DIR = Path(__file__).parent
RESULTS_FILE = AUTORESEARCH_DIR / "results.tsv"

DEFAULT_PERSONA = "average_student.json"
DEFAULT_MAX_TURNS = 20
QUICK_MAX_TURNS = 12


def get_prompt_diff() -> str:
    """Get git diff of prompt files."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--", "tutor/prompts/", "tutor/agents/master_tutor.py", "tutor/services/session_service.py"],
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
    config: SessionExperienceConfig,
    persona: dict,
    topic: dict,
    skip_server: bool,
    restart_server: bool,
) -> dict:
    """Run one session on one topic: simulate → evaluate → analyze."""
    topic_id = topic["id"]
    topic_name = topic["name"]
    config.topic_id = topic_id

    started_at = datetime.now()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    topic_slug = topic_name.replace(" ", "_").replace(":", "")[:40]
    run_dir = RUNS_DIR / f"exp_{timestamp}_{topic_slug}"
    run_dir.mkdir(parents=True, exist_ok=True)

    report = SessionExperienceReportGenerator(
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

        # Stage 2: Evaluate naturalness
        print(f"    [evaluate] Running naturalness judge...")
        evaluator = ExperienceEvaluator(config)
        evaluation = evaluator.evaluate(
            conversation, persona=persona,
            card_phase_data=card_phase_data,
            topic_name=topic_name,
        )

        report.save_experience_evaluation(evaluation)
        report.save_issues_summary(evaluation)

        flagged = evaluation.get("flagged_messages", [])
        score = evaluation.get("overall_naturalness_score", 0)
        counts = evaluation.get("issue_count_by_severity", {})
        print(
            f"    [evaluate] Naturalness: {score}/10, "
            f"flagged: {counts.get('critical', 0)}C {counts.get('major', 0)}M {counts.get('minor', 0)}m"
        )

        # Stage 3: Analyze prompts (only if issues found)
        analysis = {"analyses": [], "cross_cutting_patterns": [], "top_recommendation": ""}
        if flagged and prompts:
            print(f"    [analyze] Tracing {len(flagged)} issues to prompt instructions...")
            analyzer = PromptAnalyzer(config)
            analysis = analyzer.analyze(flagged, conversation, prompts)
            report.save_prompt_analysis(analysis)
            patterns = analysis.get("cross_cutting_patterns", [])
            print(f"    [analyze] Found {len(patterns)} cross-cutting patterns")
        elif flagged and not prompts:
            print(f"    [analyze] Skipped — no prompts captured (agent logs unavailable)")
        else:
            print(f"    [analyze] Skipped — no issues flagged")

        report.save_review(evaluation, analysis)

        # Compute weighted issue score: critical=3, major=2, minor=1
        weighted_issues = (
            counts.get("critical", 0) * 3
            + counts.get("major", 0) * 2
            + counts.get("minor", 0) * 1
        )

        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "naturalness_score": score,
            "weighted_issues": weighted_issues,
            "issue_counts": counts,
            "flagged_count": len(flagged),
            "message_count": len(conversation),
            "prompts_captured": len(prompts),
            "top_recommendation": analysis.get("top_recommendation", ""),
            "patterns": [p.get("pattern", "") for p in analysis.get("cross_cutting_patterns", [])],
            "run_dir": str(run_dir),
            "status": "ok",
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "naturalness_score": 0,
            "weighted_issues": 99,
            "issue_counts": {},
            "flagged_count": 0,
            "message_count": 0,
            "prompts_captured": 0,
            "top_recommendation": "",
            "patterns": [],
            "run_dir": str(run_dir),
            "status": f"crash: {e}",
        }


def run_experiment(
    topics: list[dict],
    config: SessionExperienceConfig,
    persona: dict,
    skip_server: bool,
    restart_server: bool,
    runs_per_topic: int = 1,
) -> dict:
    """Run the full experiment across all selected topics.

    When runs_per_topic > 1, each topic is evaluated multiple times and
    scores are averaged. This reduces stochastic variance from the student
    simulator's dice rolls (~1-2 point single-run variance → ~0.5 with 3 runs).
    """
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
            "avg_naturalness": 0,
            "avg_weighted_issues": 99,
            "per_topic": all_results,
            "elapsed_seconds": elapsed,
            "status": "crash",
            "individual_scores": [],
        }

    avg_naturalness = sum(r["naturalness_score"] for r in ok_results) / len(ok_results)
    avg_weighted_issues = sum(r["weighted_issues"] for r in ok_results) / len(ok_results)
    individual_scores = [r["naturalness_score"] for r in ok_results]

    # Aggregate patterns across topics
    all_patterns = []
    for r in ok_results:
        all_patterns.extend(r["patterns"])

    # Aggregate recommendations
    recommendations = [r["top_recommendation"] for r in ok_results if r["top_recommendation"]]

    if runs_per_topic > 1:
        scores_str = ", ".join(f"{s}" for s in individual_scores)
        print(f"\n  Averaged {len(ok_results)} runs: [{scores_str}] → nat={avg_naturalness:.2f}, issues={avg_weighted_issues:.1f}")

    return {
        "avg_naturalness": avg_naturalness,
        "avg_weighted_issues": avg_weighted_issues,
        "per_topic": all_results,
        "elapsed_seconds": elapsed,
        "status": "ok",
        "all_patterns": all_patterns,
        "recommendations": recommendations,
        "individual_scores": individual_scores,
    }


def load_baseline() -> dict | None:
    """Load baseline from results.tsv."""
    if not RESULTS_FILE.exists():
        return None
    with open(RESULTS_FILE) as f:
        lines = f.readlines()
    for line in lines[1:]:
        parts = line.strip().split("\t")
        if len(parts) >= 6 and parts[3] in ("keep", "baseline"):
            try:
                return {
                    "avg_naturalness": float(parts[1]),
                    "avg_weighted_issues": float(parts[2]),
                }
            except (ValueError, json.JSONDecodeError):
                continue
    return None


def append_result(
    commit: str,
    avg_naturalness: float,
    avg_weighted_issues: float,
    status: str,
    description: str,
    elapsed: float,
    topics_used: list[str],
    details_json: str,
):
    """Append a row to results.tsv."""
    header = "commit\tavg_naturalness\tavg_weighted_issues\tstatus\tdescription\telapsed_min\ttopics\tdetails_json\n"
    if not RESULTS_FILE.exists():
        with open(RESULTS_FILE, "w") as f:
            f.write(header)

    elapsed_min = f"{elapsed / 60:.1f}"
    topics_str = "|".join(topics_used)
    with open(RESULTS_FILE, "a") as f:
        f.write(f"{commit}\t{avg_naturalness:.2f}\t{avg_weighted_issues:.1f}\t{status}\t{description}\t{elapsed_min}\t{topics_str}\t{details_json}\n")


def main():
    parser = argparse.ArgumentParser(description="Run session experience experiment")
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
        # Single topic mode
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

    # Build config
    from database import get_db_manager
    db = get_db_manager().session_factory()
    try:
        config = SessionExperienceConfig.from_db(db, max_turns=max_turns)
    finally:
        db.close()

    if args.provider:
        config.evaluator_provider = args.provider
        config.simulator_provider = args.provider
        config.analyzer_provider = args.provider

    persona = config.load_persona()

    print(f"\n{'='*60}")
    print(f"  Session Experience Experiment")
    print(f"  Topics: {[t['name'] for t in topics]}")
    print(f"  Persona: {persona['name']} ({persona['persona_id']})")
    print(f"  Max turns: {max_turns}")
    if args.description:
        print(f"  Description: {args.description}")
    print(f"{'='*60}")

    if args.runs > 1:
        print(f"  Runs per topic: {args.runs} (averaging to reduce variance)")

    # Run
    results = run_experiment(topics, config, persona, args.skip_server, args.restart_server, runs_per_topic=args.runs)

    # Print results
    commit = get_short_commit()
    avg_nat = results["avg_naturalness"]
    avg_issues = results["avg_weighted_issues"]
    elapsed = results["elapsed_seconds"]

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Commit: {commit}")
    print(f"  Avg Naturalness Score: {avg_nat:.2f}/10")
    print(f"  Avg Weighted Issues: {avg_issues:.1f}")
    print(f"  Elapsed: {elapsed/60:.1f} minutes")
    print()
    individual = results.get("individual_scores", [])
    if len(individual) > 1:
        scores_str = ", ".join(f"{s}" for s in individual)
        print(f"  Individual scores: [{scores_str}]")
        print()
    print("  Per Run:")
    for r in results["per_topic"]:
        status = "ok" if r["status"] == "ok" else "CRASH"
        run_label = f" (run {r.get('run_num', '?')})" if len(individual) > 1 else ""
        print(
            f"    {r['topic_name'][:35]:.<38} nat={r['naturalness_score']}/10  "
            f"issues={r['weighted_issues']}  ({status}){run_label}"
        )

    if results.get("recommendations"):
        print()
        print("  Top Recommendations:")
        for rec in results["recommendations"][:3]:
            print(f"    - {rec}")

    print(f"{'='*60}")

    # Machine-readable output
    print(f"\n---")
    print(f"avg_naturalness: {avg_nat:.6f}")
    print(f"avg_weighted_issues: {avg_issues:.1f}")
    print(f"elapsed_min: {elapsed/60:.1f}")
    print(f"commit: {commit}")
    print(f"status: {'crash' if results['status'] == 'crash' else 'pending'}")

    # Append to results.tsv
    topic_names = [r["topic_name"] for r in results["per_topic"]]
    details = json.dumps({
        "per_topic": [
            {"name": r["topic_name"], "score": r["naturalness_score"], "issues": r["weighted_issues"]}
            for r in results["per_topic"]
        ]
    })
    append_result(commit, avg_nat, avg_issues, "pending", args.description or "(no desc)", elapsed, topic_names, details)

    # Email
    if args.email:
        baseline = load_baseline()
        prompt_diff = get_prompt_diff()
        run_dirs = [r["run_dir"] for r in results.get("per_topic", []) if r.get("run_dir")]
        from autoresearch.session_experience.email_report import send_experience_report
        send_experience_report(
            iteration=args.iteration,
            description=args.description or "(no description)",
            avg_naturalness=avg_nat,
            avg_weighted_issues=avg_issues,
            baseline=baseline,
            per_topic=results["per_topic"],
            recommendations=results.get("recommendations", []),
            prompt_diff=prompt_diff,
            email_to=args.email,
            run_dirs=run_dirs,
        )

    return results


if __name__ == "__main__":
    main()
