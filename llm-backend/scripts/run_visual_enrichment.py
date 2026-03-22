#!/usr/bin/env python3
"""Run visual enrichment for a specific guideline or set of guidelines.

Usage:
    python scripts/run_visual_enrichment.py --guideline-id <id> [--force] [--variant B]
    python scripts/run_visual_enrichment.py --all-test-topics [--force]
"""
import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from database import get_db_manager
from config import get_settings
from shared.services.llm_config_service import LLMConfigService
from shared.services.llm_service import LLMService
from shared.models.entities import TeachingGuideline
from book_ingestion_v2.services.animation_enrichment_service import AnimationEnrichmentService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Topics with pre-computed explanations (Grade 3 Math)
TEST_TOPICS = [
    {"id": "b8d0b705-7a49-4fe1-bd06-eff6fec0f8b6", "name": "Reviewing 3-Digit Place Value"},
    {"id": "08ffca67-f71d-40b4-b60d-658bc688f74d", "name": "3-Digit Addition: Regrouping in One Column"},
]


def main():
    parser = argparse.ArgumentParser(description="Run visual enrichment for explanation cards")
    parser.add_argument("--guideline-id", type=str, help="Specific guideline ID to enrich")
    parser.add_argument("--all-test-topics", action="store_true", help="Enrich all test topics")
    parser.add_argument("--force", action="store_true", help="Re-generate even if visuals exist")
    parser.add_argument("--variant", type=str, default=None, help="Only enrich specific variant (A, B, C)")
    args = parser.parse_args()

    if not args.guideline_id and not args.all_test_topics:
        parser.error("Specify --guideline-id or --all-test-topics")

    db = get_db_manager().get_session()
    settings = get_settings()

    try:
        # Set up LLM services — fallback to explanation_generator config if animation configs not seeded
        llm_config_svc = LLMConfigService(db)
        try:
            config = llm_config_svc.get_config("animation_enrichment")
        except Exception:
            logger.info("No animation_enrichment config, falling back to explanation_generator")
            config = llm_config_svc.get_config("explanation_generator")

        llm_service = LLMService(
            api_key=settings.openai_api_key,
            provider=config["provider"],
            model_id=config["model_id"],
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        )

        # Try separate code gen config, fallback to same
        try:
            code_config = llm_config_svc.get_config("animation_code_gen")
            code_llm = LLMService(
                api_key=settings.openai_api_key,
                provider=code_config["provider"],
                model_id=code_config["model_id"],
                gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
                anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
            )
        except Exception:
            logger.info("No separate animation_code_gen config, using same LLM for both")
            code_llm = llm_service

        service = AnimationEnrichmentService(db, llm_service, code_gen_llm=code_llm)

        # Build guideline list
        if args.guideline_id:
            guideline_ids = [args.guideline_id]
        else:
            guideline_ids = [t["id"] for t in TEST_TOPICS]

        variant_keys = [args.variant] if args.variant else None

        for gid in guideline_ids:
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == gid
            ).first()

            if not guideline:
                logger.error(f"Guideline {gid} not found")
                continue

            topic = guideline.topic_title or guideline.topic
            logger.info(f"\n{'='*60}\nEnriching: {topic} (id={gid})\n{'='*60}")

            result = service.enrich_guideline(
                guideline, force=args.force, variant_keys=variant_keys,
            )

            logger.info(f"Result: {json.dumps(result, indent=2)}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
