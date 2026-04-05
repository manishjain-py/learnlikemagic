#!/usr/bin/env python3
"""Run check-in enrichment for explanation cards.

Generates match-the-pairs activities at concept boundaries within explanation
card sequences. Follows the same pattern as run_visual_enrichment.py.

Usage:
    python scripts/run_check_in_enrichment.py --guideline-id <id> [--force] [--variant B]
    python scripts/run_check_in_enrichment.py --chapter-id <id> [--force]
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
from book_ingestion_v2.services.check_in_enrichment_service import CheckInEnrichmentService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run check-in enrichment for explanation cards")
    parser.add_argument("--guideline-id", type=str, help="Specific guideline ID to enrich")
    parser.add_argument("--chapter-id", type=str, help="Chapter ID to enrich all topics")
    parser.add_argument("--force", action="store_true", help="Re-generate even if check-ins exist")
    parser.add_argument("--variant", type=str, default=None, help="Only enrich specific variant (A, B, C)")
    args = parser.parse_args()

    if not args.guideline_id and not args.chapter_id:
        parser.error("Specify --guideline-id or --chapter-id")

    db = get_db_manager().get_session()
    settings = get_settings()

    try:
        # Set up LLM service — fallback to explanation_generator config
        llm_config_svc = LLMConfigService(db)
        try:
            config = llm_config_svc.get_config("check_in_enrichment")
        except Exception:
            logger.info("No check_in_enrichment config, falling back to explanation_generator")
            config = llm_config_svc.get_config("explanation_generator")

        llm_service = LLMService(
            api_key=settings.openai_api_key,
            provider=config["provider"],
            model_id=config["model_id"],
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        )

        service = CheckInEnrichmentService(db, llm_service)

        variant_keys = [args.variant] if args.variant else None

        if args.guideline_id:
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == args.guideline_id
            ).first()

            if not guideline:
                logger.error(f"Guideline {args.guideline_id} not found")
                return

            topic = guideline.topic_title or guideline.topic
            logger.info(f"\n{'='*60}\nEnriching: {topic} (id={args.guideline_id})\n{'='*60}")

            result = service.enrich_guideline(
                guideline, force=args.force, variant_keys=variant_keys,
            )
            logger.info(f"Result: {json.dumps(result, indent=2)}")

        elif args.chapter_id:
            # Find book_id from chapter
            from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
            chapter = ChapterRepository(db).get_by_id(args.chapter_id)
            if not chapter:
                logger.error(f"Chapter {args.chapter_id} not found")
                return

            logger.info(f"\n{'='*60}\nEnriching chapter: {chapter.title} (id={args.chapter_id})\n{'='*60}")

            result = service.enrich_chapter(
                book_id=chapter.book_id,
                chapter_id=args.chapter_id,
                force=args.force,
            )
            logger.info(f"Result: {json.dumps(result, indent=2)}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
