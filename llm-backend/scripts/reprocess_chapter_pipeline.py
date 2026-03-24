#!/usr/bin/env python3
"""
Full chapter reprocessing pipeline: OCR → Topics → Sync → Explanations.

Usage:
    python scripts/reprocess_chapter_pipeline.py [--step STEP]

Steps:
    1 = OCR regeneration
    2 = Topic extraction + finalization
    3 = Topic sync to teaching_guidelines
    4 = Explanation generation
    all = Run all steps (default)

The script connects to the production database and S3 using .env config.
Each step is idempotent and can be retried independently.
"""
import sys
import os
import time
import logging
import argparse
import tempfile
from pathlib import Path
from datetime import datetime

# Set up path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

# Load .env before importing app modules
from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")

# Suppress noisy loggers
for noisy in ["httpx", "httpcore", "urllib3", "botocore", "boto3", "openai"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)


def get_db_session():
    """Create a fresh DB session."""
    from database import get_db_manager
    return get_db_manager().session_factory()


def find_chapter(db) -> tuple:
    """Find book_id and chapter_id for Chapter 1 (Place Value)."""
    from shared.repositories.book_repository import BookRepository
    from book_ingestion_v2.repositories.chapter_repository import ChapterRepository

    book_repo = BookRepository(db)
    books = book_repo.get_all(grade=1, subject="Mathematics")
    if not books:
        raise RuntimeError("No Grade 1 Mathematics book found")

    book = books[0]
    logger.info(f"Book: {book.title} (id={book.id})")

    chapter_repo = ChapterRepository(db)
    chapter = chapter_repo.get_by_book_and_number(book.id, 1)
    if not chapter:
        raise RuntimeError("Chapter 1 not found")

    logger.info(
        f"Chapter: {chapter.chapter_title} (id={chapter.id}, "
        f"pages {chapter.start_page}-{chapter.end_page}, "
        f"status={chapter.status})"
    )
    return book.id, chapter.id, book, chapter


# ─── Step 1: OCR Regeneration ───────────────────────────────────────────────

def step1_regenerate_ocr(book_id: str, chapter_id: str):
    """Re-OCR all pages for the chapter."""
    logger.info("=" * 60)
    logger.info("STEP 1: Regenerating OCR for all pages")
    logger.info("=" * 60)

    db = get_db_session()
    try:
        from book_ingestion_v2.repositories.chapter_page_repository import ChapterPageRepository
        from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
        from book_ingestion_v2.constants import OCRStatus, LLM_CONFIG_KEY
        from shared.utils.s3_client import get_s3_client
        from shared.services.ocr_service import get_ocr_service
        from shared.services.llm_config_service import LLMConfigService
        from book_ingestion_v2.services.chapter_page_service import V2_OCR_PROMPT

        page_repo = ChapterPageRepository(db)
        chapter_repo = ChapterRepository(db)
        s3_client = get_s3_client()

        # Get OCR model from config
        config = LLMConfigService(db).get_config(LLM_CONFIG_KEY)
        ocr_service = get_ocr_service(model=config["model_id"])

        chapter = chapter_repo.get_by_id(chapter_id)
        pages = page_repo.get_by_chapter_id(chapter_id)
        logger.info(f"Found {len(pages)} pages to re-OCR")

        succeeded = 0
        failed = 0

        for page in pages:
            page_num = page.page_number
            logger.info(f"  Re-OCRing page {page_num}...")

            for attempt in range(3):
                try:
                    # Download PNG from S3
                    png_data = s3_client.download_bytes(page.image_s3_key)

                    # Write to temp file for OCR
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        tmp.write(png_data)
                        tmp_path = tmp.name

                    try:
                        ocr_text = ocr_service.extract_text_from_image(
                            image_path=tmp_path, prompt=V2_OCR_PROMPT
                        )
                    finally:
                        Path(tmp_path).unlink(missing_ok=True)

                    # Upload new OCR text to S3
                    ch_num = str(chapter.chapter_number).zfill(2)
                    text_s3_key = f"books/{book_id}/chapters/{ch_num}/pages/{page_num}.txt"
                    s3_client.upload_bytes(ocr_text.encode("utf-8"), text_s3_key)

                    # Update DB record
                    page.text_s3_key = text_s3_key
                    page.ocr_status = OCRStatus.COMPLETED.value
                    page.ocr_error = None
                    page.ocr_model = ocr_service.model
                    page.ocr_completed_at = datetime.utcnow()
                    page_repo.update(page)

                    logger.info(
                        f"  Page {page_num}: OK ({len(ocr_text)} chars)"
                    )
                    succeeded += 1
                    break

                except Exception as e:
                    if attempt < 2:
                        logger.warning(
                            f"  Page {page_num}: attempt {attempt+1} failed ({e}), retrying..."
                        )
                        time.sleep(2 ** attempt)
                    else:
                        logger.error(f"  Page {page_num}: FAILED after 3 attempts: {e}")
                        page.ocr_status = OCRStatus.FAILED.value
                        page.ocr_error = str(e)
                        page_repo.update(page)
                        failed += 1

        # Update chapter completeness
        from book_ingestion_v2.services.chapter_page_service import ChapterPageService
        svc = ChapterPageService(db)
        svc._update_chapter_completeness(chapter)

        logger.info(f"OCR complete: {succeeded} succeeded, {failed} failed")
        if failed > 0:
            logger.warning(f"  {failed} pages failed OCR — topic extraction will skip them")

        return failed == 0
    finally:
        db.close()


# ─── Step 2: Topic Extraction + Finalization ─────────────────────────────────

def step2_reprocess_topics(book_id: str, chapter_id: str):
    """Wipe existing topics and run full extraction + finalization."""
    logger.info("=" * 60)
    logger.info("STEP 2: Reprocessing topics (extract + finalize)")
    logger.info("=" * 60)

    db = get_db_session()
    try:
        from book_ingestion_v2.constants import ChapterStatus, V2JobType
        from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
        from book_ingestion_v2.repositories.chapter_page_repository import ChapterPageRepository
        from book_ingestion_v2.services.chapter_job_service import ChapterJobService
        from book_ingestion_v2.services.topic_extraction_orchestrator import TopicExtractionOrchestrator
        from book_ingestion_v2.utils.chunk_builder import build_chunk_windows

        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)

        # Reset chapter status
        chapter.status = ChapterStatus.UPLOAD_COMPLETE.value
        chapter.error_message = None
        chapter.error_type = None
        chapter_repo.update(chapter)
        logger.info(f"  Chapter status reset to UPLOAD_COMPLETE")

        # Count chunks for progress tracking
        page_repo = ChapterPageRepository(db)
        pages = page_repo.get_by_chapter_id(chapter_id)
        page_numbers = [p.page_number for p in pages if p.ocr_status == "completed"]
        total_chunks = len(build_chunk_windows(page_numbers))
        logger.info(f"  {len(page_numbers)} OCR'd pages → {total_chunks} chunks")

        # Acquire job lock
        job_service = ChapterJobService(db)
        job_id = job_service.acquire_lock(
            book_id=book_id,
            chapter_id=chapter_id,
            job_type=V2JobType.TOPIC_EXTRACTION.value,
            total_items=total_chunks,
        )
        logger.info(f"  Job lock acquired: {job_id}")

        # Start job
        job_service.start_job(job_id)
        logger.info(f"  Job started, running extraction...")

        # Run extraction (this is what run_in_background_v2 normally does)
        orchestrator = TopicExtractionOrchestrator(db)
        try:
            orchestrator.extract(db, job_id, chapter_id, book_id, False)

            # Refresh session and release lock
            db2 = get_db_session()
            job_service2 = ChapterJobService(db2)
            job_service2.release_lock(job_id, status="completed")

            # Check final status
            chapter = ChapterRepository(db2).get_by_id(chapter_id)
            logger.info(f"  Extraction complete! Chapter status: {chapter.status}")
            db2.close()

            return chapter.status in [
                ChapterStatus.CHAPTER_COMPLETED.value,
                ChapterStatus.NEEDS_REVIEW.value,
            ]

        except Exception as e:
            logger.error(f"  Extraction failed: {e}")
            try:
                err_db = get_db_session()
                ChapterJobService(err_db).release_lock(job_id, status="failed", error=str(e))
                ch = ChapterRepository(err_db).get_by_id(chapter_id)
                ch.status = ChapterStatus.FAILED.value
                ch.error_message = str(e)
                ch.error_type = "retryable"
                ChapterRepository(err_db).update(ch)
                err_db.close()
            except Exception:
                pass
            raise
    finally:
        try:
            db.close()
        except Exception:
            pass


# ─── Step 3: Topic Sync ─────────────────────────────────────────────────────

def step3_sync_topics(book_id: str, chapter_id: str):
    """Sync chapter topics to teaching_guidelines table."""
    logger.info("=" * 60)
    logger.info("STEP 3: Syncing topics to teaching_guidelines")
    logger.info("=" * 60)

    db = get_db_session()
    try:
        from book_ingestion_v2.services.topic_sync_service import TopicSyncService

        service = TopicSyncService(db)
        result = service.sync_chapter(book_id, chapter_id)

        logger.info(
            f"  Synced: {result.synced_topics} topics, {len(result.errors)} errors"
        )
        if result.errors:
            for err in result.errors:
                logger.warning(f"    {err}")

        return len(result.errors) == 0
    finally:
        db.close()


# ─── Step 4: Explanation Generation ──────────────────────────────────────────

def step4_generate_explanations(book_id: str, chapter_id: str):
    """Generate explanation variants for all topics in the chapter."""
    logger.info("=" * 60)
    logger.info("STEP 4: Generating explanations for all topics")
    logger.info("=" * 60)

    db = get_db_session()
    try:
        from config import get_settings
        from shared.models.entities import TeachingGuideline
        from shared.services.llm_config_service import LLMConfigService
        from shared.services.llm_service import LLMService
        from shared.repositories.explanation_repository import ExplanationRepository
        from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
        from book_ingestion_v2.services.explanation_generator_service import ExplanationGeneratorService
        from book_ingestion_v2.services.chapter_job_service import ChapterJobService
        from book_ingestion_v2.constants import V2JobType

        settings = get_settings()
        config = LLMConfigService(db).get_config("explanation_generator")
        llm_service = LLMService(
            api_key=settings.openai_api_key,
            provider=config["provider"],
            model_id=config["model_id"],
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        )

        # Get chapter key for filtering guidelines
        chapter = ChapterRepository(db).get_by_id(chapter_id)
        chapter_key = f"chapter-{chapter.chapter_number}"

        # Count guidelines
        guidelines = (
            db.query(TeachingGuideline)
            .filter(
                TeachingGuideline.book_id == book_id,
                TeachingGuideline.chapter_key == chapter_key,
                TeachingGuideline.review_status == "APPROVED",
            )
            .order_by(TeachingGuideline.topic_sequence)
            .all()
        )
        logger.info(f"  Found {len(guidelines)} guidelines to generate explanations for")

        if not guidelines:
            logger.warning("  No guidelines found! Did sync complete successfully?")
            return False

        # Acquire job lock
        job_service = ChapterJobService(db)
        job_id = job_service.acquire_lock(
            book_id=book_id,
            chapter_id=chapter_id,
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            total_items=len(guidelines),
        )
        job_service.start_job(job_id)
        logger.info(f"  Job started: {job_id}")

        # Delete existing explanations (force mode)
        repo = ExplanationRepository(db)
        deleted = repo.delete_by_chapter(book_id, chapter_key)
        if deleted:
            logger.info(f"  Deleted {deleted} existing explanation variants")

        service = ExplanationGeneratorService(db, llm_service)

        generated = 0
        failed = 0
        errors = []

        for i, guideline in enumerate(guidelines, 1):
            topic = guideline.topic_title or guideline.topic
            logger.info(f"  [{i}/{len(guidelines)}] Generating for: {topic}")

            try:
                job_service.update_progress(
                    job_id, current_item=topic, completed=generated, failed=failed
                )

                results = service.generate_for_guideline(guideline)
                if results:
                    generated += 1
                    logger.info(f"    OK — {len(results)} variants")
                else:
                    failed += 1
                    errors.append(f"{topic}: no variants passed validation")
                    logger.warning(f"    WARN — no variants passed validation")

            except Exception as e:
                failed += 1
                errors.append(f"{topic}: {str(e)}")
                logger.error(f"    FAILED: {e}")

                # Refresh DB session after potential timeout
                try:
                    db.close()
                except Exception:
                    pass
                db = get_db_session()
                service = ExplanationGeneratorService(db, llm_service)
                job_service = ChapterJobService(db)

        # Release lock
        try:
            final_status = "completed" if failed == 0 else "completed_with_errors"
            db2 = get_db_session()
            ChapterJobService(db2).release_lock(job_id, status=final_status)
            db2.close()
        except Exception as e:
            logger.warning(f"  Could not release job lock: {e}")

        logger.info(f"  Explanations: {generated} generated, {failed} failed")
        if errors:
            for err in errors:
                logger.warning(f"    {err}")

        return failed == 0
    finally:
        try:
            db.close()
        except Exception:
            pass


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Chapter reprocessing pipeline")
    parser.add_argument(
        "--step", default="all",
        help="Step to run: 1 (OCR), 2 (topics), 3 (sync), 4 (explanations), all"
    )
    args = parser.parse_args()

    start_time = time.time()
    logger.info("=" * 60)
    logger.info("CHAPTER 1 REPROCESSING PIPELINE")
    logger.info("=" * 60)

    # Find book and chapter
    db = get_db_session()
    try:
        book_id, chapter_id, book, chapter = find_chapter(db)
    finally:
        db.close()

    steps = args.step

    try:
        if steps in ("all", "1"):
            ok = step1_regenerate_ocr(book_id, chapter_id)
            if not ok and steps == "all":
                logger.warning("OCR had failures, continuing anyway...")

        if steps in ("all", "2"):
            ok = step2_reprocess_topics(book_id, chapter_id)
            if not ok and steps == "all":
                logger.warning("Topic extraction had issues, continuing with sync...")

        if steps in ("all", "3"):
            ok = step3_sync_topics(book_id, chapter_id)
            if not ok and steps == "all":
                logger.warning("Sync had errors, continuing with explanations...")

        if steps in ("all", "4"):
            ok = step4_generate_explanations(book_id, chapter_id)

        elapsed = time.time() - start_time
        logger.info("=" * 60)
        logger.info(f"PIPELINE COMPLETE — elapsed: {elapsed/60:.1f} minutes")
        logger.info("=" * 60)

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error("=" * 60)
        logger.error(f"PIPELINE FAILED at {elapsed/60:.1f} minutes: {e}")
        logger.error("=" * 60)
        logger.error(f"To retry from the failed step, run:")
        logger.error(f"  python scripts/reprocess_chapter_pipeline.py --step <N>")
        raise


if __name__ == "__main__":
    main()
