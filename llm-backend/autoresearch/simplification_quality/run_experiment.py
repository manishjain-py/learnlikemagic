"""
Simplification Quality Experiment Runner

Tests the "I didn't understand" card simplification feature:
1. Creates a tutoring session for a topic
2. Samples 2-3 random cards from the explanation deck
3. For each card, calls "I didn't understand" with a random reason (depth 1)
4. Evaluates the quality of the simplified card
5. Calls "I didn't understand" again with a different reason (depth 2)
6. Evaluates the depth-2 simplified card
7. Aggregates scores across all cards and depths

Usage:
    cd llm-backend

    # Run with defaults (1 topic, 2 cards per run)
    python -m autoresearch.simplification_quality.run_experiment --skip-server

    # With email report
    python -m autoresearch.simplification_quality.run_experiment --skip-server --email manish@simplifyloop.com

    # More topics
    python -m autoresearch.simplification_quality.run_experiment --skip-server --topics 3 --cards 3
"""

import argparse
import json
import random
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autoresearch.simplification_quality.evaluation.config import (
    SimplificationConfig,
    RUNS_DIR,
    TOPIC_POOL,
    REASONS,
    select_topics,
    select_cards,
)
from autoresearch.simplification_quality.evaluation.evaluator import SimplificationEvaluator

import requests

AUTORESEARCH_DIR = Path(__file__).parent
RESULTS_FILE = AUTORESEARCH_DIR / "results.tsv"

DIMENSIONS = ["reason_adherence", "content_differentiation", "simplicity", "concept_accuracy", "presentation_quality"]


def get_prompt_diff() -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--", "tutor/prompts/", "tutor/agents/master_tutor.py",
             "tutor/services/session_service.py"],
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


def _extract_scores(evaluation: dict) -> dict[str, float]:
    """Extract numeric scores from evaluation dimensions."""
    scores = {}
    for dim in DIMENSIONS:
        dim_data = evaluation.get(dim, {})
        scores[dim] = float(dim_data.get("score", 0)) if isinstance(dim_data, dict) else 0.0
    return scores


def _avg_scores(scores_list: list[dict[str, float]]) -> dict[str, float]:
    """Average scores across a list of score dicts."""
    if not scores_list:
        return {dim: 0.0 for dim in DIMENSIONS}
    avg = {}
    for dim in DIMENSIONS:
        vals = [s[dim] for s in scores_list]
        avg[dim] = sum(vals) / len(vals)
    return avg


def run_single_topic(
    config: SimplificationConfig,
    topic: dict,
    run_dir: Path,
    seed: int | None = None,
) -> dict:
    """Run simplification quality test on one topic."""
    topic_name = topic["name"]
    rng = random.Random(seed)

    try:
        # 1. Create session
        print(f"    [session] Creating session for: {topic_name}...")
        resp = requests.post(f"{config.base_url}/sessions", json={
            "student": {"id": "eval-student", "grade": config.student_grade},
            "goal": {
                "chapter": "Place Value",
                "syllabus": f"CBSE Grade {config.student_grade} Math",
                "learning_objectives": ["Understand place value"],
                "guideline_id": topic["id"],
            },
            "mode": "teach_me",
        })
        resp.raise_for_status()
        session_data = resp.json()
        session_id = session_data["session_id"]
        explanation_cards = session_data["first_turn"]["explanation_cards"]

        print(f"    [session] Got {len(explanation_cards)} cards, session={session_id[:8]}...")

        # 2. Sample cards
        card_indices = select_cards(explanation_cards, config.cards_per_run, seed)
        print(f"    [sample] Testing cards: {card_indices}")

        # 3. For each card, test depth 1 and depth 2
        results = []
        all_scores = []

        for card_idx in card_indices:
            original_card = explanation_cards[card_idx]
            card_title = original_card.get("title", f"Card {card_idx}")

            try:
                # Depth 1: random reason
                reason1 = rng.choice(REASONS)
                print(f"    [depth-1] Card {card_idx} ({card_title[:30]}) reason={reason1}")
                resp1 = requests.post(
                    f"{config.base_url}/sessions/{session_id}/simplify-card",
                    json={"card_idx": card_idx, "reason": reason1},
                )
                resp1.raise_for_status()
                simplified1 = resp1.json()["card"]

                # Evaluate depth 1
                evaluator = SimplificationEvaluator(config)
                eval1 = evaluator.evaluate(
                    original_card, simplified1, reason1, [],
                    config.student_grade, topic_name,
                )
                scores1 = _extract_scores(eval1)
                avg1 = sum(scores1.values()) / len(scores1)
                all_scores.append(scores1)
                print(f"    [depth-1] Score: {avg1:.1f}/10")

                # Depth 2: different random reason
                reason2 = rng.choice([r for r in REASONS if r != reason1])
                print(f"    [depth-2] Card {card_idx} ({card_title[:30]}) reason={reason2}")
                resp2 = requests.post(
                    f"{config.base_url}/sessions/{session_id}/simplify-card",
                    json={"card_idx": card_idx, "reason": reason2},
                )
                resp2.raise_for_status()
                simplified2 = resp2.json()["card"]

                # Evaluate depth 2
                eval2 = evaluator.evaluate(
                    original_card, simplified2, reason2, [simplified1],
                    config.student_grade, topic_name,
                )
                scores2 = _extract_scores(eval2)
                avg2 = sum(scores2.values()) / len(scores2)
                all_scores.append(scores2)
                print(f"    [depth-2] Score: {avg2:.1f}/10")

                results.append({
                    "card_idx": card_idx,
                    "card_title": card_title,
                    "original_card": original_card,
                    "depth_1": {"reason": reason1, "card": simplified1, "evaluation": eval1, "scores": scores1},
                    "depth_2": {"reason": reason2, "card": simplified2, "evaluation": eval2, "scores": scores2},
                })

            except Exception as e:
                traceback.print_exc()
                print(f"    [error] Card {card_idx} failed: {e}")
                continue

        if not results:
            return {
                "topic_id": topic["id"],
                "topic_name": topic_name,
                "avg_score": 0,
                "per_dimension": {dim: 0.0 for dim in DIMENSIONS},
                "depth_1_avg": 0,
                "depth_2_avg": 0,
                "cards_tested": 0,
                "run_dir": str(run_dir),
                "status": "crash: all cards failed",
            }

        # Aggregate
        per_dim = _avg_scores(all_scores)
        avg_score = sum(per_dim.values()) / len(per_dim)

        depth1_scores = [r["depth_1"]["scores"] for r in results]
        depth2_scores = [r["depth_2"]["scores"] for r in results]
        depth1_avg = sum(sum(s.values()) / len(s) for s in depth1_scores) / len(depth1_scores)
        depth2_avg = sum(sum(s.values()) / len(s) for s in depth2_scores) / len(depth2_scores)

        # Save artifacts
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_dir / "cards_detail.json", "w") as f:
            json.dump(results, f, indent=2, default=str)
        with open(run_dir / "evaluation.json", "w") as f:
            json.dump({
                "topic": topic,
                "avg_score": avg_score,
                "per_dimension": per_dim,
                "depth_1_avg": depth1_avg,
                "depth_2_avg": depth2_avg,
                "cards_tested": len(results),
            }, f, indent=2)

        return {
            "topic_id": topic["id"],
            "topic_name": topic_name,
            "avg_score": avg_score,
            "per_dimension": per_dim,
            "depth_1_avg": depth1_avg,
            "depth_2_avg": depth2_avg,
            "cards_tested": len(results),
            "run_dir": str(run_dir),
            "status": "ok",
        }

    except Exception as e:
        traceback.print_exc()
        return {
            "topic_id": topic["id"],
            "topic_name": topic_name,
            "avg_score": 0,
            "per_dimension": {dim: 0.0 for dim in DIMENSIONS},
            "depth_1_avg": 0,
            "depth_2_avg": 0,
            "cards_tested": 0,
            "run_dir": str(run_dir),
            "status": f"crash: {e}",
        }


def run_experiment(
    config: SimplificationConfig,
    topics: list[dict],
    seed: int | None = None,
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

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            topic_slug = topic["name"].replace(" ", "_").replace(":", "")[:40]
            run_dir = RUNS_DIR / f"simpl_{timestamp}_{topic_slug}"
            run_dir.mkdir(parents=True, exist_ok=True)

            run_seed = seed + run_num if seed is not None else None
            result = run_single_topic(config, topic, run_dir, seed=run_seed)
            result["run_num"] = run_num
            all_results.append(result)

    elapsed = time.time() - t0

    ok_results = [r for r in all_results if r["status"] == "ok"]
    if not ok_results:
        return {
            "avg_score": 0,
            "per_dimension": {dim: 0.0 for dim in DIMENSIONS},
            "depth_1_avg": 0,
            "depth_2_avg": 0,
            "per_topic": all_results,
            "elapsed_seconds": elapsed,
            "status": "crash",
        }

    avg_score = sum(r["avg_score"] for r in ok_results) / len(ok_results)
    depth1_avg = sum(r["depth_1_avg"] for r in ok_results) / len(ok_results)
    depth2_avg = sum(r["depth_2_avg"] for r in ok_results) / len(ok_results)

    # Average per-dimension across all OK results
    per_dim = {}
    for dim in DIMENSIONS:
        vals = [r["per_dimension"][dim] for r in ok_results]
        per_dim[dim] = sum(vals) / len(vals)

    if runs_per_topic > 1:
        scores = [r["avg_score"] for r in ok_results]
        scores_str = ", ".join(f"{s:.1f}" for s in scores)
        print(f"\n  Averaged {len(ok_results)} runs: [{scores_str}] -> avg={avg_score:.2f}")

    return {
        "avg_score": avg_score,
        "per_dimension": per_dim,
        "depth_1_avg": depth1_avg,
        "depth_2_avg": depth2_avg,
        "per_topic": all_results,
        "elapsed_seconds": elapsed,
        "status": "ok",
    }


def load_baseline() -> dict | None:
    if not RESULTS_FILE.exists():
        return None
    with open(RESULTS_FILE) as f:
        lines = f.readlines()
    for line in lines[1:]:
        parts = line.strip().split("\t")
        if len(parts) >= 8 and parts[7] in ("keep", "baseline"):
            try:
                return {"avg_score": float(parts[1])}
            except (ValueError, json.JSONDecodeError):
                continue
    return None


def append_result(
    commit: str,
    avg_score: float,
    avg_reason_adherence: float,
    avg_differentiation: float,
    avg_simplicity: float,
    avg_accuracy: float,
    avg_presentation: float,
    status: str,
    description: str,
    elapsed: float,
    topics_used: list[str],
    details_json: str,
):
    header = "commit\tavg_score\tavg_reason_adherence\tavg_differentiation\tavg_simplicity\tavg_accuracy\tavg_presentation\tstatus\tdescription\telapsed_min\ttopics\tdetails_json\n"
    if not RESULTS_FILE.exists():
        with open(RESULTS_FILE, "w") as f:
            f.write(header)

    elapsed_min = f"{elapsed / 60:.1f}"
    topics_str = "|".join(topics_used)
    with open(RESULTS_FILE, "a") as f:
        f.write(
            f"{commit}\t{avg_score:.2f}\t{avg_reason_adherence:.2f}\t{avg_differentiation:.2f}\t"
            f"{avg_simplicity:.2f}\t{avg_accuracy:.2f}\t{avg_presentation:.2f}\t"
            f"{status}\t{description}\t{elapsed_min}\t{topics_str}\t{details_json}\n"
        )


def main():
    parser = argparse.ArgumentParser(description="Run simplification quality experiment")
    parser.add_argument("--topics", type=int, default=1, help="Number of topics (default 1)")
    parser.add_argument("--cards", type=int, default=2, help="Cards per topic to test (default 2)")
    parser.add_argument("--skip-server", action="store_true")
    parser.add_argument("--restart-server", action="store_true")
    parser.add_argument("--email", default=None)
    parser.add_argument("--description", default="")
    parser.add_argument("--iteration", type=int, default=0)
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument("--provider", default=None, help="LLM provider override (openai/anthropic)")
    parser.add_argument("--runs", type=int, default=1, help="Runs per topic (default 1)")
    args = parser.parse_args()

    # Server management
    if not args.skip_server:
        try:
            from autoresearch.session_experience.evaluation.session_runner import ServerManager
            server = ServerManager(restart=args.restart_server)
            server.start()
        except ImportError:
            print("  [warn] Could not import server manager, assuming server is running")

    # Resolve topics
    topics = select_topics(args.topics, seed=args.seed)

    # Build config
    from database import get_db_manager
    db = get_db_manager().session_factory()
    try:
        config = SimplificationConfig.from_db(db, cards_per_run=args.cards)
    finally:
        db.close()

    if args.provider:
        config.evaluator_provider = args.provider

    print(f"\n{'='*60}")
    print(f"  Simplification Quality Experiment")
    print(f"  Topics: {[t['name'] for t in topics]}")
    print(f"  Cards per topic: {config.cards_per_run}")
    print(f"  Grade: {config.student_grade}")
    if args.description:
        print(f"  Description: {args.description}")
    print(f"{'='*60}")

    if args.runs > 1:
        print(f"  Runs per topic: {args.runs} (averaging to reduce variance)")

    # Run
    results = run_experiment(config, topics, seed=args.seed, runs_per_topic=args.runs)

    # Print results
    commit = get_short_commit()
    avg = results["avg_score"]
    per_dim = results["per_dimension"]
    d1 = results["depth_1_avg"]
    d2 = results["depth_2_avg"]
    elapsed = results["elapsed_seconds"]

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Commit: {commit}")
    print(f"  Avg Score: {avg:.2f}/10")
    print(f"  Depth 1 Avg: {d1:.2f}/10")
    print(f"  Depth 2 Avg: {d2:.2f}/10")
    print()
    print(f"  Per Dimension:")
    print(f"    Reason Adherence:       {per_dim['reason_adherence']:.2f}/10")
    print(f"    Content Differentiation: {per_dim['content_differentiation']:.2f}/10")
    print(f"    Simplicity:             {per_dim['simplicity']:.2f}/10")
    print(f"    Concept Accuracy:       {per_dim['concept_accuracy']:.2f}/10")
    print(f"    Presentation Quality:   {per_dim['presentation_quality']:.2f}/10")
    print()
    print(f"  Elapsed: {elapsed/60:.1f} minutes")
    print()
    print("  Per Run:")
    for r in results["per_topic"]:
        status = "ok" if r["status"] == "ok" else "CRASH"
        run_label = f" (run {r.get('run_num', '?')})" if args.runs > 1 else ""
        print(
            f"    {r['topic_name'][:35]:.<38} avg={r['avg_score']:.1f}  "
            f"d1={r['depth_1_avg']:.1f}  d2={r['depth_2_avg']:.1f}  "
            f"cards={r['cards_tested']}  ({status}){run_label}"
        )

    print(f"{'='*60}")

    # Machine-readable output
    print(f"\n---")
    print(f"avg_score: {avg:.6f}")
    print(f"avg_reason_adherence: {per_dim['reason_adherence']:.1f}")
    print(f"avg_differentiation: {per_dim['content_differentiation']:.1f}")
    print(f"avg_simplicity: {per_dim['simplicity']:.1f}")
    print(f"avg_accuracy: {per_dim['concept_accuracy']:.1f}")
    print(f"avg_presentation: {per_dim['presentation_quality']:.1f}")
    print(f"elapsed_min: {elapsed/60:.1f}")
    print(f"commit: {commit}")
    print(f"status: {'crash' if results['status'] == 'crash' else 'pending'}")

    # Append to results.tsv
    topic_names = [r["topic_name"] for r in results["per_topic"]]
    details = json.dumps({
        "per_topic": [
            {
                "name": r["topic_name"],
                "avg": r["avg_score"],
                "d1": r["depth_1_avg"],
                "d2": r["depth_2_avg"],
                "cards": r["cards_tested"],
            }
            for r in results["per_topic"]
        ]
    })
    append_result(
        commit, avg,
        per_dim["reason_adherence"],
        per_dim["content_differentiation"],
        per_dim["simplicity"],
        per_dim["concept_accuracy"],
        per_dim["presentation_quality"],
        "pending", args.description or "(no desc)", elapsed, topic_names, details,
    )

    # Email
    if args.email:
        baseline = load_baseline()
        prompt_diff = get_prompt_diff()
        run_dirs = [r["run_dir"] for r in results.get("per_topic", []) if r.get("run_dir")]
        from autoresearch.simplification_quality.email_report import send_simplification_report
        send_simplification_report(
            iteration=args.iteration,
            description=args.description or "(no description)",
            avg_score=avg,
            per_dimension=per_dim,
            depth_1_avg=d1,
            depth_2_avg=d2,
            baseline=baseline,
            per_topic=results["per_topic"],
            prompt_diff=prompt_diff,
            email_to=args.email,
            run_dirs=run_dirs,
        )

    return results


if __name__ == "__main__":
    main()
