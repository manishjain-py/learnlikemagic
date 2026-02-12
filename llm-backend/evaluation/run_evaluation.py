"""
Evaluation Pipeline Entry Point

Orchestrates the full evaluation pipeline:
1. Configure and create run directory
2. Start server, run simulated tutoring session
3. Evaluate the conversation with an LLM judge
4. Generate reports (conversation, review, problems)
5. Clean up

Usage:
    cd llm-backend && python -m evaluation.run_evaluation --topic-id <guideline_id> [--skip-server] [--max-turns N]
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from evaluation.config import EvalConfig, RUNS_DIR, PROJECT_ROOT
from evaluation.student_simulator import StudentSimulator
from evaluation.session_runner import SessionRunner
from evaluation.evaluator import ConversationEvaluator
from evaluation.report_generator import ReportGenerator


def main():
    parser = argparse.ArgumentParser(description="Run tutor evaluation pipeline")
    parser.add_argument("--topic-id", required=True, help="Guideline ID for the topic")
    parser.add_argument("--skip-server", action="store_true", help="Skip server management (use already-running server)")
    parser.add_argument("--max-turns", type=int, default=20, help="Max conversation turns (default: 20)")
    parser.add_argument("--grade", type=int, default=3, help="Student grade (default: 3)")
    parser.add_argument("--provider", default=None, help="LLM provider: openai or anthropic")
    args = parser.parse_args()

    # 1. Create config and run directory
    config = EvalConfig(
        topic_id=args.topic_id,
        max_turns=args.max_turns,
        student_grade=args.grade,
    )
    if args.provider:
        config.eval_llm_provider = args.provider

    if config.eval_llm_provider == "anthropic":
        if not config.anthropic_api_key:
            print("ERROR: ANTHROPIC_API_KEY not found in environment. Check your .env file.")
            sys.exit(1)
    else:
        if not config.openai_api_key:
            print("ERROR: OPENAI_API_KEY not found in environment. Check your .env file.")
            sys.exit(1)

    started_at = datetime.now()
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Evaluation Pipeline")
    print(f"  Run: {run_dir.name}")
    print(f"  Tutor Model: {config.tutor_model_label}")
    print(f"  Evaluator: {config.evaluator_model_label}")
    print(f"  Topic: {config.topic_id}")
    print(f"  Max turns: {config.max_turns}")
    print(f"{'='*60}\n")

    report = ReportGenerator(run_dir, config, started_at=started_at.isoformat())
    report.save_config()

    # 2. Load persona and create simulator
    print("[1/6] Loading persona...")
    persona = config.load_persona()
    simulator = StudentSimulator(config, persona)
    print(f"  Persona: {persona['name']} (grade {persona['grade']}, correct_prob={persona['correct_answer_probability']})")

    # 3. Create session runner, start server, run session
    runner = SessionRunner(config, simulator, run_dir, skip_server_management=args.skip_server)

    try:
        print("[2/6] Starting server...")
        runner.start_server()

        print("[3/6] Running tutoring session...")
        conversation = runner.run_session()
        metadata = runner.session_metadata
        print(f"  Session complete: {len(conversation)} messages")

        # 4. Save conversation artifacts
        print("[4/6] Saving conversation...")
        report.save_conversation_md(conversation)
        report.save_conversation_json(conversation, metadata)

        # 5. Evaluate conversation
        print("[5/6] Evaluating conversation (this may take a minute)...")
        evaluator = ConversationEvaluator(config)
        evaluation = evaluator.evaluate(conversation)

        # 6. Generate review and problems reports
        print("[6/6] Generating reports...")
        report.save_evaluation_json(evaluation)
        report.save_review(evaluation)
        report.save_problems(evaluation)

        # Print summary
        scores = evaluation.get("scores", {})
        avg = sum(scores.values()) / len(scores) if scores else 0
        problems = evaluation.get("problems", [])

        print(f"\n{'='*60}")
        print(f"  RESULTS")
        print(f"{'='*60}")
        print(f"  Average Score: {avg:.1f}/10")
        print(f"  Problems Found: {len(problems)}")
        print()
        print("  Scores:")
        for dim, score in scores.items():
            print(f"    {dim.replace('_', ' ').title():.<30} {score}/10")
        print()
        if problems:
            print("  Top Problems:")
            for i, prob in enumerate(problems[:3], 1):
                print(f"    {i}. [{prob.get('severity', '?').upper()}] {prob.get('title', 'Untitled')}")
                print(f"       Root cause: {prob.get('root_cause', '?')}")
        print()
        print(f"  All artifacts saved to: {run_dir}")
        print(f"{'='*60}\n")

    finally:
        runner.cleanup()


if __name__ == "__main__":
    main()
