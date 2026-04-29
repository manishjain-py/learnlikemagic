"""End-to-end driver: run V2 Stage 5c (Baatcheet Visuals) directly against the
production DB.

Mirrors `_run_baatcheet_visual_enrichment` in sync_routes.py but without the
HTTP / chapter_jobs plumbing — instantiate the service, call enrich_guideline,
print the result.

Usage:
    cd llm-backend && venv/bin/python scripts/baatcheet_v2_run_stage5c.py <guideline_id> [--force]
"""
import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "llm-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("guideline_id")
    parser.add_argument("--force", action="store_true", default=False,
                        help="Re-enrich cards that already have pixi_code.")
    args = parser.parse_args()

    from database import get_db_manager
    from config import get_settings
    from shared.models.entities import TeachingGuideline
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.baatcheet_visual_enrichment_service import (
        BaatcheetVisualEnrichmentService,
    )

    db = get_db_manager().get_session()
    settings = get_settings()

    # Mirror sync_routes.py LLM config resolution.
    llm_config_svc = LLMConfigService(db)
    try:
        config = llm_config_svc.get_config("animation_code_gen")
    except Exception:
        try:
            config = llm_config_svc.get_config("animation_enrichment")
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

    guideline = db.query(TeachingGuideline).filter(
        TeachingGuideline.id == args.guideline_id,
    ).first()
    if not guideline:
        print(f"ERROR: guideline {args.guideline_id} not found", file=sys.stderr)
        sys.exit(2)

    topic = guideline.topic_title or guideline.topic
    print(f"Enriching baatcheet visuals for: {topic} ({args.guideline_id})")
    print(f"  LLM: provider={config['provider']} model={config['model_id']} "
          f"reasoning_effort={config.get('reasoning_effort')}")
    print(f"  force={args.force}")

    service = BaatcheetVisualEnrichmentService(db, llm_service)

    started = time.time()
    stage_collector: list = []
    result = service.enrich_guideline(
        guideline,
        force=args.force,
        heartbeat_fn=None,
        stage_collector=stage_collector,
    )
    elapsed = time.time() - started

    print(f"\nDone in {elapsed:.1f}s")
    print(json.dumps(result, indent=2, default=str))
    print(f"\nstage_collector entries: {len(stage_collector)}")
    if stage_collector:
        print("first entry:", json.dumps(stage_collector[0], indent=2, default=str))


if __name__ == "__main__":
    main()
