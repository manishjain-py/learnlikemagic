"""End-to-end driver: run V2 Stage 5b directly against the production DB.

Mirrors `_run_baatcheet_dialogue_generation` in sync_routes.py but without
the HTTP / chapter_jobs plumbing — we instantiate the service, call
generate_for_guideline, and dump the resulting plan + cards to disk for
follow-up visualisation.

Usage:
    cd llm-backend && venv/bin/python scripts/baatcheet_v2_run_stage5b.py <guideline_id> [--force] [--review-rounds N]
"""
import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "llm-backend"
OUT_ROOT = BACKEND_ROOT / "scripts" / "baatcheet_v2_outputs"

# Make project imports work regardless of cwd
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("guideline_id")
    parser.add_argument("--force", action="store_true", default=True,
                        help="Regenerate even if a dialogue already exists (default: True for Stage 5b smoke).")
    parser.add_argument("--review-rounds", type=int, default=1)
    parser.add_argument("--out-label", default="prod-stage5b")
    args = parser.parse_args()

    from database import get_db_manager
    from config import get_settings
    from shared.models.entities import TeachingGuideline
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
        BaatcheetDialogueGeneratorService,
    )

    db = get_db_manager().get_session()
    settings = get_settings()

    # Mirror sync_routes.py pattern for LLM config
    llm_config_svc = LLMConfigService(db)
    try:
        config = llm_config_svc.get_config("baatcheet_dialogue_generator")
    except Exception:
        config = llm_config_svc.get_config("explanation_generator")

    llm_service = LLMService(
        api_key=settings.openai_api_key,
        provider=config["provider"],
        model_id=config["model_id"],
        reasoning_effort=config["reasoning_effort"],
        gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
        anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
    )
    print(f"LLM provider={config['provider']} model={config['model_id']} effort={config['reasoning_effort']}", flush=True)

    guideline = (
        db.query(TeachingGuideline)
        .filter(TeachingGuideline.id == args.guideline_id)
        .first()
    )
    if not guideline:
        print(f"Guideline {args.guideline_id} not found", file=sys.stderr)
        sys.exit(1)

    topic = guideline.topic_title or guideline.topic
    print(f"Guideline: {guideline.id} | {topic} | grade={guideline.grade} subject={guideline.subject}", flush=True)

    out_dir = OUT_ROOT / f"prod-{args.guideline_id[:8]}" / args.out_label
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {out_dir}", flush=True)

    service = BaatcheetDialogueGeneratorService(db, llm_service)
    stage_collector: list = []

    start = time.time()
    print(f"\n=== Calling generate_for_guideline (force={args.force}, review_rounds={args.review_rounds}) ===", flush=True)
    try:
        dialogue = service.generate_for_guideline(
            guideline,
            review_rounds=args.review_rounds,
            stage_collector=stage_collector,
            force=args.force,
        )
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}", flush=True)
        # Still dump what we have for forensics
        if stage_collector:
            (out_dir / "stage_collector_partial.json").write_text(
                json.dumps(stage_collector, indent=2, default=str)
            )
            print(f"Partial stage_collector saved: {out_dir/'stage_collector_partial.json'}", flush=True)
        raise
    duration = time.time() - start

    print(f"\n=== Done in {duration:.0f}s ===", flush=True)
    print(f"  dialogue_id: {dialogue.id}", flush=True)
    print(f"  card_count: {len(dialogue.cards_json)}", flush=True)
    print(f"  has plan: {dialogue.plan_json is not None}", flush=True)
    if dialogue.plan_json:
        print(f"  plan misconceptions: {len(dialogue.plan_json.get('misconceptions', []))}", flush=True)
        print(f"  plan card_plan slots: {len(dialogue.plan_json.get('card_plan', []))}", flush=True)
        print(f"  plan spine: {dialogue.plan_json.get('spine', {}).get('situation', '')[:80]}", flush=True)

    # Dump artifacts for the visual pass + comparison
    (out_dir / "plan.json").write_text(json.dumps(dialogue.plan_json, indent=2))
    # Strip the welcome card to align with the experiment harness output shape
    # (visual pass + render scripts expect `cards` array starting from card_idx=2 OR
    # any starting idx — they preserve idx as-is. Persist as-is including welcome.)
    (out_dir / "dialogue.json").write_text(json.dumps({"cards": dialogue.cards_json}, indent=2))
    (out_dir / "stage_collector.json").write_text(json.dumps(stage_collector, indent=2, default=str))
    (out_dir / "run_summary.json").write_text(json.dumps({
        "guideline_id": guideline.id,
        "topic": topic,
        "subject": guideline.subject,
        "grade": guideline.grade,
        "duration_s": duration,
        "dialogue_id": dialogue.id,
        "card_count": len(dialogue.cards_json),
        "has_plan": dialogue.plan_json is not None,
        "review_rounds": args.review_rounds,
    }, indent=2))
    print(f"\nArtifacts: {out_dir}", flush=True)


if __name__ == "__main__":
    main()
