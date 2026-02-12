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


def run_all_personas(args):
    """Run evaluation with all available personas."""
    all_personas = EvalConfig.all_personas()
    if not all_personas:
        print("ERROR: No persona files found in personas directory.")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Multi-Persona Evaluation Pipeline")
    print(f"  Running {len(all_personas)} personas: {[p['name'] for p in all_personas]}")
    print(f"  Topic: {args.topic_id}")
    print(f"  Max turns per run: {args.max_turns}")
    print(f"{'='*60}\n")

    results = []
    
    for i, persona_data in enumerate(all_personas, 1):
        persona_file = persona_data['file']
        print(f"[{i}/{len(all_personas)}] Running persona: {persona_data['name']} ({persona_data['persona_id']})")
        
        # Create config for this persona
        config = EvalConfig(
            topic_id=args.topic_id,
            max_turns=args.max_turns,
            student_grade=args.grade,
            persona_file=persona_file,
        )
        if args.provider:
            config.eval_llm_provider = args.provider

        started_at = datetime.now()
        timestamp = started_at.strftime("%Y%m%d_%H%M%S")
        run_dir = RUNS_DIR / f"run_{timestamp}_{persona_data['persona_id']}"
        run_dir.mkdir(parents=True, exist_ok=True)

        persona = config.load_persona()
        simulator = StudentSimulator(config, persona)
        report = ReportGenerator(run_dir, config, started_at=started_at.isoformat(), persona=persona)
        report.save_config()

        runner = SessionRunner(config, simulator, run_dir, skip_server_management=args.skip_server)
        
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
            
            # Store results for comparison report
            scores = evaluation.get("scores", {})
            avg_score = sum(scores.values()) / len(scores) if scores else 0
            results.append({
                "persona": persona_data,
                "run_dir": run_dir,
                "avg_score": avg_score,
                "scores": scores,
                "evaluation": evaluation,
                "message_count": len(conversation)
            })
            
            print(f"  ✓ {persona_data['name']}: {avg_score:.1f}/10 avg, {len(conversation)} messages")
            
        except Exception as e:
            print(f"  ✗ {persona_data['name']}: FAILED - {e}")
            results.append({
                "persona": persona_data,
                "run_dir": run_dir,
                "avg_score": 0,
                "scores": {},
                "evaluation": {"error": str(e)},
                "message_count": 0
            })
        finally:
            runner.cleanup()
    
    # Generate comparison report
    comparison_dir = RUNS_DIR / f"comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    
    generate_comparison_report(comparison_dir, args.topic_id, results)
    
    print(f"\n{'='*60}")
    print(f"  MULTI-PERSONA RESULTS")
    print(f"{'='*60}")
    for result in results:
        persona_name = result['persona']['name']
        avg_score = result['avg_score']
        print(f"  {persona_name:.<20} {avg_score:.1f}/10")
    print()
    print(f"  Individual runs saved in their respective directories")
    print(f"  Comparison report: {comparison_dir}")
    print(f"{'='*60}\n")


def generate_comparison_report(comparison_dir: Path, topic_id: str, results: list):
    """Generate a comparison report across all personas."""
    lines = [
        "# Multi-Persona Evaluation Comparison",
        "",
        f"**Topic:** {topic_id}",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Personas Evaluated:** {len(results)}",
        "",
        "---",
        "",
        "## Overview",
        "",
        "| Persona | Name | Correct% | Avg Score | Messages |",
        "|---------|------|----------|-----------|----------|",
    ]
    
    for result in results:
        persona = result['persona']
        avg_score = result['avg_score']
        correct_prob = int(persona.get('correct_answer_probability', 0.6) * 100)
        lines.append(f"| {persona['persona_id']} | {persona['name']} | {correct_prob}% | {avg_score:.1f}/10 | {result['message_count']} |")
    
    lines.extend(["", "## Detailed Scores", ""])
    
    # Get all dimension names from first successful result
    dimensions = []
    for result in results:
        if result['scores']:
            dimensions = list(result['scores'].keys())
            break
    
    if dimensions:
        lines.append("| Persona | " + " | ".join(dim.replace('_', ' ').title() for dim in dimensions) + " |")
        lines.append("|---------|" + "|".join("-------" for _ in dimensions) + "|")
        
        for result in results:
            persona_name = result['persona']['name']
            scores = result['scores']
            score_values = [f"{scores.get(dim, 0)}/10" for dim in dimensions]
            lines.append(f"| {persona_name} | " + " | ".join(score_values) + " |")
    
    # Save comparison report
    comparison_file = comparison_dir / "comparison.md"
    with open(comparison_file, "w") as f:
        f.write("\n".join(lines))
    
    # Save raw data as JSON
    comparison_json = comparison_dir / "comparison.json"
    with open(comparison_json, "w") as f:
        json.dump({
            "topic_id": topic_id,
            "generated_at": datetime.now().isoformat(),
            "results": results
        }, f, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser(description="Run tutor evaluation pipeline")
    parser.add_argument("--topic-id", required=True, help="Guideline ID for the topic")
    parser.add_argument("--skip-server", action="store_true", help="Skip server management (use already-running server)")
    parser.add_argument("--max-turns", type=int, default=20, help="Max conversation turns (default: 20)")
    parser.add_argument("--grade", type=int, default=3, help="Student grade (default: 3)")
    parser.add_argument("--provider", default=None, help="LLM provider: openai or anthropic")
    parser.add_argument("--persona", default="average_student.json", help="Persona file to use (e.g., ace.json) or 'all' to run all personas")
    args = parser.parse_args()

    # Handle "all" personas special case
    if args.persona == "all":
        run_all_personas(args)
        return

    # 1. Create config and run directory
    config = EvalConfig(
        topic_id=args.topic_id,
        max_turns=args.max_turns,
        student_grade=args.grade,
        persona_file=args.persona,
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

    # 2. Load persona and create simulator
    print("[1/6] Loading persona...")
    persona = config.load_persona()
    simulator = StudentSimulator(config, persona)

    print(f"\n{'='*60}")
    print(f"  Evaluation Pipeline")
    print(f"  Run: {run_dir.name}")
    print(f"  Tutor Model: {config.tutor_model_label}")
    print(f"  Evaluator: {config.evaluator_model_label}")
    print(f"  Topic: {config.topic_id}")
    print(f"  Max turns: {config.max_turns}")
    print(f"  Persona: {persona['name']} ({persona['persona_id']}, correct_prob={persona['correct_answer_probability']})")
    print(f"{'='*60}\n")

    report = ReportGenerator(run_dir, config, started_at=started_at.isoformat(), persona=persona)
    report.save_config()

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
        evaluation = evaluator.evaluate(conversation, persona=persona)

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
