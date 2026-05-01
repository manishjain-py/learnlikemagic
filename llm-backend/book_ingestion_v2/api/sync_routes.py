"""API routes for V2 sync, results, and explanation generation."""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from book_ingestion_v2.constants import V2JobType
from book_ingestion_v2.models.schemas import (
    SyncResponse,
    ProcessingJobResponse,
    BookResultsResponse,
    ChapterResultSummary,
    ChapterExplanationStatusResponse,
    TopicExplanationStatus,
    TopicExplanationsDetailResponse,
    ExplanationVariantResponse,
    DeleteExplanationsResponse,
    ChapterGuidelineStatusResponse,
    GuidelineStatusItem,
    GuidelineDetailResponse,
    UpdateGuidelineRequest,
    ChapterVisualStatusResponse,
    TopicVisualStatus,
    ChapterCheckInStatusResponse,
    TopicCheckInStatus,
    ChapterPracticeBankStatusResponse,
    TopicPracticeBankStatus,
    PracticeBankDetailResponse,
    PracticeBankQuestionItem,
    TopicPipelineStatusResponse,
    ChapterPipelineSummaryResponse,
    FanOutJobResponse,
    RunPipelineRequest,
    RunPipelineResponse,
    RunChapterPipelineAllRequest,
    RunChapterPipelineAllResponse,
)
from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
from book_ingestion_v2.repositories.topic_repository import TopicRepository
from book_ingestion_v2.services.topic_sync_service import TopicSyncService
from book_ingestion_v2.services.book_v2_service import BookV2Service
from book_ingestion_v2.services.chapter_job_service import ChapterJobService, ChapterJobLockError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/v2/books/{book_id}", tags=["Book Ingestion V2 - Sync"])


def _resolve_approved_guidelines(
    db: Session,
    *,
    book_id: str,
    chapter_id: Optional[str],
) -> list:
    """Return APPROVED TeachingGuidelines in scope.

    Raises HTTPException(404) if `chapter_id` is given but the chapter
    does not belong to this book.
    """
    from shared.models.entities import TeachingGuideline

    query = db.query(TeachingGuideline).filter(
        TeachingGuideline.book_id == book_id,
        TeachingGuideline.review_status == "APPROVED",
    )
    if chapter_id:
        chapter = ChapterRepository(db).get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chapter {chapter_id} not found in book {book_id}",
            )
        chapter_key = f"chapter-{chapter.chapter_number}"
        query = query.filter(TeachingGuideline.chapter_key == chapter_key)
    return query.order_by(TeachingGuideline.topic_sequence).all()


def _resolve_single_guideline(db: Session, *, book_id: str, guideline_id: str):
    """Return a TeachingGuideline or raise HTTPException(404)."""
    from shared.models.entities import TeachingGuideline

    guideline = db.query(TeachingGuideline).filter(
        TeachingGuideline.id == guideline_id,
        TeachingGuideline.book_id == book_id,
    ).first()
    if not guideline:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Guideline {guideline_id} not found in book {book_id}",
        )
    return guideline


def _fan_out(
    db: Session,
    *,
    launcher,
    book_id: str,
    chapter_id: Optional[str],
    guideline_id: Optional[str],
    launcher_kwargs: Optional[dict] = None,
) -> FanOutJobResponse:
    """Launch a post-sync stage job per guideline in scope.

    - `guideline_id` given → single launcher call (launched=1).
      Raises ChapterJobLockError (→ 409 at route boundary) if the topic
      already has an active job — callers that need that signal
      (per-stage admin pages) get it.
    - Otherwise → one launcher per APPROVED guideline in the resolved
      scope. Topics that already have an active job are recorded in
      `skipped_guidelines` instead of aborting the whole batch.
    """
    launcher_kwargs = launcher_kwargs or {}
    job_ids: list[str] = []
    skipped: list[str] = []

    if guideline_id:
        guideline = _resolve_single_guideline(db, book_id=book_id, guideline_id=guideline_id)
        resolved_chapter_id = _chapter_id_for_guideline(db, book_id, guideline)
        job_id = launcher(
            db,
            book_id=book_id,
            chapter_id=resolved_chapter_id,
            guideline_id=guideline.id,
            **launcher_kwargs,
        )
        job_ids.append(job_id)
        return FanOutJobResponse(launched=len(job_ids), job_ids=job_ids, skipped_guidelines=skipped)

    guidelines = _resolve_approved_guidelines(db, book_id=book_id, chapter_id=chapter_id)
    for g in guidelines:
        try:
            job_id = launcher(
                db,
                book_id=book_id,
                chapter_id=_chapter_id_for_guideline(db, book_id, g),
                guideline_id=g.id,
                **launcher_kwargs,
            )
            job_ids.append(job_id)
        except ChapterJobLockError:
            skipped.append(g.id)
    return FanOutJobResponse(launched=len(job_ids), job_ids=job_ids, skipped_guidelines=skipped)


def _resolve_lookup_scope(
    db: Session,
    *,
    book_id: str,
    chapter_id: Optional[str],
    guideline_id: Optional[str],
) -> tuple[str, Optional[str]]:
    """Map (book_id, chapter_id, guideline_id) → (lookup_chapter_id, lookup_guideline_id).

    Used by `get_latest_*_job` endpoints to query `ChapterJobService.get_latest_job`.
    - If `guideline_id` given, resolve the real chapter_id from the guideline's
      chapter_key and filter by native `guideline_id`.
    - Else, use the given `chapter_id` (or fall back to `book_id` for book-wide lookups).
    """
    if guideline_id:
        guideline = _resolve_single_guideline(db, book_id=book_id, guideline_id=guideline_id)
        resolved_chapter_id = _chapter_id_for_guideline(db, book_id, guideline)
        # Historical rows may have chapter_id = guideline_id (pre-migration).
        # Use the guideline_id as the fallback chapter_id lookup when the real
        # chapter_id can't be resolved, so historical rows stay visible.
        effective = resolved_chapter_id or guideline_id
        return effective, guideline_id
    return (chapter_id or book_id), None


def _chapter_id_for_guideline(db: Session, book_id: str, guideline) -> str:
    """Resolve the BookChapter.id for a guideline (joined via chapter_key)."""
    from book_ingestion_v2.models.database import BookChapter

    if not guideline.chapter_key:
        return ""
    try:
        chapter_num = int(guideline.chapter_key.split("-", 1)[1])
    except (IndexError, ValueError):
        return ""
    chapter = db.query(BookChapter).filter(
        BookChapter.book_id == book_id,
        BookChapter.chapter_number == chapter_num,
    ).first()
    return chapter.id if chapter else ""


@router.post("/sync", response_model=SyncResponse)
def sync_book(book_id: str, db: Session = Depends(get_db)):
    """Sync all completed chapters to teaching_guidelines."""
    try:
        service = TopicSyncService(db)
        return service.sync_book(book_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post("/chapters/{chapter_id}/sync", response_model=SyncResponse)
def sync_chapter(book_id: str, chapter_id: str, db: Session = Depends(get_db)):
    """Sync a single chapter to teaching_guidelines."""
    try:
        service = TopicSyncService(db)
        return service.sync_chapter(book_id, chapter_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/results", response_model=BookResultsResponse)
def get_book_results(book_id: str, db: Session = Depends(get_db)):
    """Book-level results overview with all chapters."""
    try:
        book_service = BookV2Service(db)
        book = book_service.get_book(book_id)
        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"V2 book not found: {book_id}",
            )

        chapter_repo = ChapterRepository(db)
        topic_repo = TopicRepository(db)
        chapters = chapter_repo.get_by_book_id(book_id)

        chapter_summaries = []
        total_topics = 0
        for ch in chapters:
            topic_count = topic_repo.count_by_chapter(ch.id)
            total_topics += topic_count
            chapter_summaries.append(
                ChapterResultSummary(
                    chapter_id=ch.id,
                    chapter_number=ch.chapter_number,
                    chapter_title=ch.chapter_title,
                    display_name=ch.display_name,
                    status=ch.status,
                    topic_count=topic_count,
                )
            )

        return BookResultsResponse(
            book_id=book_id,
            title=book.title,
            chapters=chapter_summaries,
            total_topics=total_topics,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post(
    "/chapters/{chapter_id}/run-pipeline-all",
    response_model=RunChapterPipelineAllResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_chapter_pipeline_all_route(
    book_id: str,
    chapter_id: str,
    body: RunChapterPipelineAllRequest,
    db: Session = Depends(get_db),
):
    """Run the 6-stage pipeline for every APPROVED topic in a chapter.

    Bounded parallelism (default 4 topics at once). Fully-done topics are
    skipped unless `skip_done=false`. A per-topic failure does NOT halt
    other topics.
    """
    import threading
    from book_ingestion_v2.services.topic_pipeline_orchestrator import (
        run_chapter_pipeline_all as _run_chapter_all,
    )
    from book_ingestion_v2.services.topic_pipeline_status_service import (
        TopicPipelineStatusService,
    )
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    ChapterJobService(db).reap_stale_post_sync_jobs(chapter_id)

    # Quick planning pass: figure out how many topics are queued.
    try:
        svc = TopicPipelineStatusService(db)
        summary = svc.get_chapter_summary(book_id, chapter_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

    max_parallel = body.max_parallel
    if max_parallel is None:
        from config import get_settings
        try:
            max_parallel = int(getattr(get_settings(), "topic_pipeline_max_parallel_topics", 4))
        except Exception:
            max_parallel = 4

    # Determine planned queue size (topics whose pipeline needs anything done).
    queued: list[str] = []
    skipped: list[str] = []
    for t in summary.topics:
        if body.skip_done and t.is_fully_done:
            skipped.append(t.topic_key)
        else:
            queued.append(t.topic_key)

    session_factory = _build_session_factory()
    chapter_run_id_holder: dict[str, str] = {}

    def _kickoff():
        try:
            result = _run_chapter_all(
                session_factory,
                book_id=book_id,
                chapter_id=chapter_id,
                quality_level=body.quality_level,
                force=False,
                skip_done=body.skip_done,
                max_parallel=max_parallel or 4,
            )
            chapter_run_id_holder["id"] = result.get("chapter_run_id", "")
        except Exception as e:
            logger.error(f"Chapter-wide runner crashed: {e}", exc_info=True)

    import uuid as _uuid
    chapter_run_id = str(_uuid.uuid4())
    chapter_run_id_holder["id"] = chapter_run_id

    threading.Thread(target=_kickoff, daemon=True).start()

    return RunChapterPipelineAllResponse(
        chapter_run_id=chapter_run_id,
        topics_queued=len(queued),
        skipped_topics=skipped,
    )


@router.post(
    "/chapters/{chapter_id}/topics/{topic_key}/run-pipeline",
    response_model=RunPipelineResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_topic_pipeline(
    book_id: str,
    chapter_id: str,
    topic_key: str,
    body: RunPipelineRequest,
    db: Session = Depends(get_db),
):
    """Run the 6-stage post-sync pipeline for one topic.

    Computes which stages are not done (or all if `force`), launches the
    orchestrator in a daemon thread, and returns 202 immediately with the
    pipeline_run_id and list of stages that will run.

    Each sub-stage acquires its own per-topic lock. A concurrent second
    super-button press fails fast at the sub-stage lock (409).
    """
    import threading
    from book_ingestion_v2.services.topic_pipeline_status_service import (
        TopicPipelineStatusService,
    )
    from book_ingestion_v2.services.topic_pipeline_orchestrator import (
        TopicPipelineOrchestrator,
        stages_to_run_from_status,
    )
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    # Reap stale post-sync jobs up-front so the status snapshot reflects
    # reality. Without this, a stale orphaned job appears `running` and
    # `stages_to_run_from_status` would skip it — then the first launcher
    # reaps it silently via `acquire_lock`, stranding that stage outside
    # the run set.
    ChapterJobService(db).reap_stale_post_sync_jobs(chapter_id)

    try:
        svc = TopicPipelineStatusService(db)
        status_resp = svc.get_pipeline_status(book_id, chapter_id, topic_key)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    stages = stages_to_run_from_status(status_resp.stages, force=body.force)
    if not stages:
        return RunPipelineResponse(
            pipeline_run_id="",
            stages_to_run=[],
            message="All stages already done.",
        )

    orchestrator = TopicPipelineOrchestrator(
        _build_session_factory(),
        book_id=book_id,
        chapter_id=chapter_id,
        guideline_id=status_resp.guideline_id,
        quality_level=body.quality_level,
        force=body.force,
    )

    def _run():
        try:
            orchestrator.run(stages)
        except Exception as e:
            logger.error(
                f"Orchestrator {orchestrator.pipeline_run_id} crashed: {e}",
                exc_info=True,
            )

    threading.Thread(target=_run, daemon=True).start()

    return RunPipelineResponse(
        pipeline_run_id=orchestrator.pipeline_run_id,
        stages_to_run=list(stages),
    )


def _build_session_factory():
    """Session factory for orchestrator stage threads."""
    from database import get_db_manager
    manager = get_db_manager()
    return manager.session_factory


@router.get(
    "/chapters/{chapter_id}/pipeline-summary",
    response_model=ChapterPipelineSummaryResponse,
)
def get_chapter_pipeline_summary(
    book_id: str,
    chapter_id: str,
    db: Session = Depends(get_db),
):
    """Aggregate per-topic pipeline status for one chapter.

    Powers the BookV2Detail chapter summary chip ("12 topics · 8 done · 3 partial · 1 not started").
    """
    from book_ingestion_v2.services.topic_pipeline_status_service import (
        TopicPipelineStatusService,
    )
    try:
        svc = TopicPipelineStatusService(db)
        return svc.get_chapter_summary(book_id, chapter_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Chapter pipeline summary failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get(
    "/chapters/{chapter_id}/topics/{topic_key}/pipeline",
    response_model=TopicPipelineStatusResponse,
)
def get_topic_pipeline(
    book_id: str,
    chapter_id: str,
    topic_key: str,
    db: Session = Depends(get_db),
):
    """Consolidated 6-stage pipeline status for one topic.

    Reads all existing artifacts (explanations, visuals, check-ins,
    practice questions, audio-review job history, audio_url on cards)
    and computes per-stage state for the admin Topic Pipeline Dashboard.
    """
    from book_ingestion_v2.services.topic_pipeline_status_service import (
        TopicPipelineStatusService,
    )
    try:
        svc = TopicPipelineStatusService(db)
        return svc.get_pipeline_status(book_id, chapter_id, topic_key)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Topic pipeline status failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post("/generate-explanations", response_model=FanOutJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_explanations(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope generation"),
    guideline_id: Optional[str] = Query(None, description="Optional guideline_id for single-topic generation"),
    force: bool = Query(False, description="Delete existing explanations before regenerating"),
    mode: str = Query("generate", description="'generate' or 'refine_only'"),
    review_rounds: int = Query(1, ge=0, le=5, description="Number of review-refine rounds"),
    db: Session = Depends(get_db),
):
    """Generate/regenerate pre-computed explanations for synced guidelines.

    Launches one background job per guideline and returns 202 immediately.
    Scoping: guideline_id (single topic) > chapter_id (fan-out across chapter)
    > book-wide (fan-out across whole book).
    mode=generate: full generation pipeline (skips existing unless force=true).
    mode=refine_only: takes existing cards and runs review-refine rounds.
    """
    from book_ingestion_v2.services.stage_launchers import launch_explanation_job

    try:
        return _fan_out(
            db,
            launcher=launch_explanation_job,
            book_id=book_id,
            chapter_id=chapter_id,
            guideline_id=guideline_id,
            launcher_kwargs={
                "force": force,
                "mode": mode,
                "review_rounds": review_rounds,
            },
        )
    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Explanation generation failed for book {book_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/explanation-jobs/latest", response_model=ProcessingJobResponse)
def get_latest_explanation_job(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Chapter ID (omit for book-wide job)"),
    guideline_id: Optional[str] = Query(None, description="Guideline ID for single-topic job"),
    db: Session = Depends(get_db),
):
    """Get the latest explanation generation job for a topic, chapter, or book."""
    try:
        lookup_chapter_id, lookup_guideline_id = _resolve_lookup_scope(
            db, book_id=book_id, chapter_id=chapter_id, guideline_id=guideline_id,
        )
        job_service = ChapterJobService(db)
        result = job_service.get_latest_job(
            lookup_chapter_id,
            job_type=V2JobType.EXPLANATION_GENERATION.value,
            guideline_id=lookup_guideline_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No explanation generation jobs found",
            )
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/audio-review-jobs/latest", response_model=ProcessingJobResponse)
def get_latest_audio_review_job(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Chapter ID (omit for book-wide job)"),
    guideline_id: Optional[str] = Query(None, description="Guideline ID for single-topic job"),
    db: Session = Depends(get_db),
):
    """Latest audio text review job for a topic, chapter, or book.

    Uses the existing ChapterJobService.get_latest_job (which already supports
    optional job_type filtering + stale detection). No new service method.
    """
    try:
        lookup_chapter_id, lookup_guideline_id = _resolve_lookup_scope(
            db, book_id=book_id, chapter_id=chapter_id, guideline_id=guideline_id,
        )
        job_service = ChapterJobService(db)
        result = job_service.get_latest_job(
            lookup_chapter_id,
            job_type=V2JobType.AUDIO_TEXT_REVIEW.value,
            guideline_id=lookup_guideline_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No audio text review jobs found",
            )
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/explanation-jobs/{job_id}/stages")
def get_job_stage_snapshots(
    book_id: str,
    job_id: str,
    guideline_id: Optional[str] = Query(None, description="Filter stages by guideline_id"),
    db: Session = Depends(get_db),
):
    """Get stage-by-stage snapshots for an explanation generation job."""
    job_service = ChapterJobService(db)
    snapshots = job_service.get_stage_snapshots(job_id, guideline_id=guideline_id)
    return {"job_id": job_id, "snapshots": snapshots}


@router.get("/explanation-status", response_model=ChapterExplanationStatusResponse)
def get_explanation_status(
    book_id: str,
    chapter_id: str = Query(..., description="Chapter ID to get explanation status for"),
    db: Session = Depends(get_db),
):
    """Get per-topic explanation variant counts for a chapter."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.explanation_repository import ExplanationRepository

    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chapter {chapter_id} not found in book {book_id}",
            )
        chapter_key = f"chapter-{chapter.chapter_number}"

        repo = ExplanationRepository(db)
        counts = repo.get_variant_counts_for_chapter(book_id, chapter_key)

        # Get all guidelines for this chapter to list even those without explanations
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

        topics = [
            TopicExplanationStatus(
                guideline_id=g.id,
                topic_title=g.topic_title or g.topic,
                topic_key=g.topic_key,
                variant_count=counts.get(g.id, 0),
            )
            for g in guidelines
        ]

        return ChapterExplanationStatusResponse(
            chapter_id=chapter_id,
            chapter_key=chapter_key,
            topics=topics,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/explanations", response_model=TopicExplanationsDetailResponse)
def get_topic_explanations(
    book_id: str,
    guideline_id: str = Query(..., description="Guideline ID to get explanations for"),
    db: Session = Depends(get_db),
):
    """Get all explanation variants with full card data for a topic."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.explanation_repository import ExplanationRepository

    try:
        guideline = db.query(TeachingGuideline).filter(
            TeachingGuideline.id == guideline_id,
            TeachingGuideline.book_id == book_id,
        ).first()
        if not guideline:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Guideline {guideline_id} not found in book {book_id}",
            )

        repo = ExplanationRepository(db)
        explanations = repo.get_by_guideline_id(guideline_id)

        variants = [
            ExplanationVariantResponse(
                id=e.id,
                variant_key=e.variant_key,
                variant_label=e.variant_label,
                cards_json=e.cards_json,
                summary_json=e.summary_json,
                generator_model=e.generator_model,
                created_at=e.created_at,
            )
            for e in explanations
        ]

        return TopicExplanationsDetailResponse(
            guideline_id=guideline_id,
            topic_title=guideline.topic_title or guideline.topic,
            topic_key=guideline.topic_key,
            variants=variants,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.delete("/explanations", response_model=DeleteExplanationsResponse)
def delete_explanations(
    book_id: str,
    guideline_id: Optional[str] = Query(None, description="Delete explanations for a specific topic"),
    chapter_id: Optional[str] = Query(None, description="Delete explanations for all topics in a chapter"),
    db: Session = Depends(get_db),
):
    """Delete explanation variants for a topic or chapter."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.explanation_repository import ExplanationRepository

    try:
        if not guideline_id and not chapter_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must specify either guideline_id or chapter_id",
            )

        repo = ExplanationRepository(db)

        if guideline_id:
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
                TeachingGuideline.book_id == book_id,
            ).first()
            if not guideline:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Guideline {guideline_id} not found in book {book_id}",
                )
            count = repo.delete_by_guideline_id(guideline_id)
        else:
            chapter_repo = ChapterRepository(db)
            chapter = chapter_repo.get_by_id(chapter_id)
            if not chapter or chapter.book_id != book_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Chapter {chapter_id} not found in book {book_id}",
                )
            chapter_key = f"chapter-{chapter.chapter_number}"
            count = repo.delete_by_chapter(book_id, chapter_key)

        return DeleteExplanationsResponse(deleted_count=count)

    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post("/generate-visuals", response_model=FanOutJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_visuals(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope enrichment"),
    guideline_id: Optional[str] = Query(None, description="Optional guideline_id for single-topic enrichment"),
    force: bool = Query(False, description="Re-generate visuals even if cards already have them"),
    review_rounds: int = Query(1, ge=0, le=5, description="Number of review-refine rounds over the generated PixiJS code"),
    db: Session = Depends(get_db),
):
    """Generate pre-computed PixiJS visuals for explanation cards.

    Launches one background job per guideline. Requires explanations to exist.
    Scoping: guideline_id (single topic) > chapter_id (fan-out) > book-wide.
    """
    from book_ingestion_v2.services.stage_launchers import launch_visual_job

    try:
        return _fan_out(
            db,
            launcher=launch_visual_job,
            book_id=book_id,
            chapter_id=chapter_id,
            guideline_id=guideline_id,
            launcher_kwargs={"force": force, "review_rounds": review_rounds},
        )
    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Visual enrichment failed for book {book_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post("/generate-audio", response_model=FanOutJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_audio(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope generation"),
    guideline_id: Optional[str] = Query(None, description="Optional guideline_id for single-topic generation"),
    confirm_skip_review: bool = Query(
        False,
        description="Skip soft guardrail that requires a prior audio text review job for this scope",
    ),
    db: Session = Depends(get_db),
):
    """Generate pre-computed TTS audio for explanation card lines and upload to S3.

    Launches one background job per guideline. Requires explanations to exist.
    Idempotent — skips lines that already have audio_url.
    Scoping: guideline_id (single topic) > chapter_id (fan-out) > book-wide.

    Soft guardrail: if no completed audio_text_review job exists for the
    resolved scope and confirm_skip_review is False, returns HTTP 409 with
    detail={"code":"no_audio_review","requires_confirmation":true,...}. For
    fan-out (chapter/book-wide), the guardrail checks at the scope level:
    we inspect the most recent audio review job in the chapter. The per-topic
    launcher still acquires its own topic-scoped lock.
    """
    from book_ingestion_v2.services.stage_launchers import launch_audio_synthesis_job

    try:
        # Soft guardrail — single-topic uses guideline_id filter, scope-wide uses chapter_id.
        if not confirm_skip_review:
            job_service = ChapterJobService(db)
            if guideline_id:
                _g = _resolve_single_guideline(db, book_id=book_id, guideline_id=guideline_id)
                guardrail_chapter_id = _chapter_id_for_guideline(db, book_id, _g)
                latest_review = job_service.get_latest_job(
                    guardrail_chapter_id,
                    job_type=V2JobType.AUDIO_TEXT_REVIEW.value,
                    guideline_id=guideline_id,
                )
            else:
                guardrail_chapter_id = chapter_id or ""
                latest_review = job_service.get_latest_job(
                    guardrail_chapter_id,
                    job_type=V2JobType.AUDIO_TEXT_REVIEW.value,
                ) if guardrail_chapter_id else None

            guardrail_code: Optional[str] = None
            guardrail_message: Optional[str] = None
            if latest_review is None:
                guardrail_code = "no_audio_review"
                guardrail_message = (
                    "No audio text review has run for this scope. "
                    "MP3s will be synthesized on unreviewed text. Proceed anyway?"
                )
            elif latest_review.status == "failed":
                guardrail_code = "audio_review_failed"
                guardrail_message = (
                    "The most recent audio text review failed — you can retry "
                    "the review, or proceed with audio generation on unreviewed "
                    "text. Proceed anyway?"
                )
            elif latest_review.status in ("pending", "running"):
                guardrail_code = "audio_review_in_progress"
                guardrail_message = (
                    f"An audio text review is currently {latest_review.status}. "
                    "Wait for it to finish, or proceed anyway on unreviewed text?"
                )

            if guardrail_message:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": guardrail_code,
                        "message": guardrail_message,
                        "requires_confirmation": True,
                        "review_status": latest_review.status if latest_review else None,
                    },
                )

        return _fan_out(
            db,
            launcher=launch_audio_synthesis_job,
            book_id=book_id,
            chapter_id=chapter_id,
            guideline_id=guideline_id,
        )

    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Audio generation failed for book {book_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


def _run_audio_generation(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", force_str: str = "False",
):
    """Background task for variant A explanation TTS audio generation.

    Synthesizes audio for `topic_explanations.cards_json` only — Baatcheet
    dialogue audio lives in the parallel `baatcheet_audio_synthesis` stage.

    `force_str == "True"` overwrites lines that already have an `audio_url`
    — used by the dashboard's "Re-run" affordance so a TTS-config change
    (e.g. voice swap, pre-synth text fix) propagates to topics that already
    have audio.
    """
    import json as _json
    from shared.models.entities import TeachingGuideline, TopicExplanation
    from book_ingestion_v2.services.audio_generation_service import (
        AudioGenerationService,
        TTSProviderError,
    )
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService
    from sqlalchemy.orm import attributes

    force = force_str.lower() == "true"
    job_service = ChapterJobService(db)
    audio_svc = AudioGenerationService(db=db)

    try:
        # Build list of guidelines to process
        if guideline_id:
            guidelines = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
            ).all()
        else:
            query = db.query(TeachingGuideline).filter(
                TeachingGuideline.book_id == book_id,
                TeachingGuideline.review_status == "APPROVED",
            )
            if chapter_id:
                from shared.repositories.chapter_repository import ChapterRepository
                chapter = ChapterRepository(db).get_by_id(chapter_id)
                if chapter:
                    chapter_key = f"chapter-{chapter.chapter_number}"
                    query = query.filter(TeachingGuideline.chapter_key == chapter_key)
            guidelines = query.all()

        completed = 0
        failed = 0
        errors: list[str] = []

        for guideline in guidelines:
            topic = guideline.topic_title or guideline.topic
            job_service.update_progress(job_id, current_item=topic, completed=completed, failed=failed)

            explanations = db.query(TopicExplanation).filter(
                TopicExplanation.guideline_id == guideline.id,
            ).all()

            topic_had_failure = False
            for explanation in explanations:
                try:
                    updated_cards = audio_svc.generate_for_topic_explanation(
                        explanation, force=force,
                    )
                    if updated_cards is not None:
                        explanation.cards_json = updated_cards
                        attributes.flag_modified(explanation, "cards_json")
                        db.commit()
                except TTSProviderError:
                    # Provider outage — bail the whole job rather than
                    # power through every remaining guideline. The outer
                    # except marks job=failed; admin retries when EL is
                    # healthy. Plan §error handling: fail the synthesis
                    # stage, no fallback.
                    db.rollback()
                    raise
                except Exception as e:
                    logger.error(f"Audio generation failed for {guideline.id}/{explanation.variant_key}: {e}")
                    db.rollback()
                    topic_had_failure = True
                    errors.append(f"{topic} ({explanation.variant_key}): {e}")

            if topic_had_failure:
                failed += 1
            else:
                completed += 1

        job_service.update_progress(
            job_id, current_item=None, completed=completed, failed=failed,
            detail=_json.dumps({"generated": completed, "failed": failed, "errors": errors[:10]}),
        )
        final_status = "completed" if failed == 0 else "completed_with_errors"
        job_service.release_lock(job_id, status=final_status)

    except Exception as e:
        logger.error(f"Audio generation job {job_id} failed: {e}")
        job_service.release_lock(job_id, status="failed", error=str(e))


# ─────────────────────────── Audio Text Review ────────────────────────────


@router.post(
    "/generate-audio-review",
    response_model=FanOutJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_audio_review(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope review"),
    guideline_id: Optional[str] = Query(None, description="Optional guideline_id for single-topic review"),
    language: Optional[str] = Query(
        None,
        description="Override language for reviewer (en|hi|hinglish). Defaults to 'en'.",
    ),
    db: Session = Depends(get_db),
):
    """Review audio text strings on explanation + check-in cards. Applies surgical revisions.

    Launches one background job per guideline. Requires explanations to exist.
    Clears audio_url on revised lines so next /generate-audio run re-synthesizes only those.
    Scoping: guideline_id (single topic) > chapter_id (fan-out) > book-wide.
    """
    from book_ingestion_v2.services.stage_launchers import launch_audio_review_job

    try:
        return _fan_out(
            db,
            launcher=launch_audio_review_job,
            book_id=book_id,
            chapter_id=chapter_id,
            guideline_id=guideline_id,
            launcher_kwargs={"language": language},
        )

    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Audio text review failed for book {book_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


def _run_audio_text_review(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", language: str = "", force_str: str = "False",
):
    """Background task — builds LLMService from DB config (same pattern as
    check-in enrichment) and injects it into AudioTextReviewService.

    `force_str == "True"` clears every `audio_url` on the variant up front
    so a downstream `audio_synthesis` run regenerates the full clip set,
    not just the lines this review pass happens to revise.
    """
    import json as _json
    from config import get_settings
    from shared.models.entities import TeachingGuideline
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.audio_text_review_service import (
        AudioTextReviewService, DEFAULT_LANGUAGE,
    )
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    force = force_str.lower() == "true"
    job_service = ChapterJobService(db)
    try:
        settings = get_settings()

        llm_config_svc = LLMConfigService(db)
        try:
            config = llm_config_svc.get_config("audio_text_review")
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

        service = AudioTextReviewService(
            db, llm_service, language=language or DEFAULT_LANGUAGE,
        )

        if guideline_id:
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
            ).first()
            if not guideline:
                result = {"completed": 0, "failed": 1, "errors": ["guideline not found"]}
            else:
                topic = guideline.topic_title or guideline.topic
                job_service.update_progress(
                    job_id, current_item=topic, completed=0, failed=0,
                )
                heartbeat_fn = lambda: job_service.update_progress(
                    job_id, current_item=topic, completed=0, failed=0,
                )
                stage_collector: list = []
                per_guideline = service.review_guideline(
                    guideline,
                    heartbeat_fn=heartbeat_fn,
                    stage_collector=stage_collector,
                    force=force,
                )
                if stage_collector:
                    try:
                        job_service.append_stage_snapshots(job_id, stage_collector)
                    except Exception as snap_err:
                        logger.warning(
                            f"append_stage_snapshots failed for job {job_id}: {snap_err}"
                        )
                result = {
                    "completed": 0 if per_guideline["failed"] else 1,
                    "failed": per_guideline["failed"],
                    "errors": per_guideline["errors"][:10],
                    "cards_reviewed": per_guideline["cards_reviewed"],
                    "cards_revised": per_guideline["cards_revised"],
                }
        else:
            result = service.review_chapter(
                book_id, chapter_id or None,
                job_service=job_service, job_id=job_id,
                force=force,
            )

        final_status = (
            "completed" if result.get("failed", 0) == 0 else "completed_with_errors"
        )
        job_service.update_progress(
            job_id,
            completed=result.get("completed", 0),
            failed=result.get("failed", 0),
            detail=_json.dumps(result),
        )
        job_service.release_lock(job_id, status=final_status)

    except Exception as e:
        logger.error(f"Audio text review job {job_id} failed: {e}")
        job_service.release_lock(job_id, status="failed", error=str(e))


def _run_explanation_generation(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", force_str: str = "False",
    mode: str = "generate", review_rounds_str: str = "1",
):
    """Background task for explanation generation or refine-only."""
    import json as _json
    from config import get_settings
    from shared.models.entities import TeachingGuideline
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.explanation_generator_service import ExplanationGeneratorService
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    force = force_str.lower() == "true"
    review_rounds = int(review_rounds_str)

    settings = get_settings()
    config = LLMConfigService(db).get_config("explanation_generator")
    llm_service = LLMService(
        api_key=settings.openai_api_key,
        provider=config["provider"],
        model_id=config["model_id"],
        reasoning_effort=config["reasoning_effort"],
        gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
        anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
    )

    job_service = ChapterJobService(db)
    service = ExplanationGeneratorService(db, llm_service)

    try:
        if guideline_id:
            # Single-topic
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
            ).first()
            if not guideline:
                raise ValueError(f"Guideline {guideline_id} not found")

            topic = guideline.topic_title or guideline.topic
            job_service.update_progress(job_id, current_item=topic, completed=0, failed=0)

            stage_collector = []

            if mode == "refine_only":
                results = service.refine_only_for_guideline(
                    guideline, review_rounds=review_rounds, stage_collector=stage_collector,
                )
            else:
                if force:
                    service.repo.delete_by_guideline_id(guideline_id)
                results = service.generate_for_guideline(
                    guideline, review_rounds=review_rounds, stage_collector=stage_collector,
                    force=force,
                )

            if stage_collector:
                job_service.append_stage_snapshots(job_id, stage_collector)

            generated = 1 if results else 0
            failed = 0 if results else 1
            errors = [] if results else [f"{topic}: no output"]

            job_service.update_progress(
                job_id, current_item=None, completed=generated, failed=failed,
                detail=_json.dumps({
                    "generated": generated, "skipped": 0, "failed": failed, "errors": errors,
                }),
            )
            final_status = "completed" if failed == 0 else "completed_with_errors"
        else:
            # Chapter or book-wide
            if mode == "refine_only":
                result = service.refine_only_for_chapter(
                    book_id,
                    chapter_id=chapter_id or None,
                    review_rounds=review_rounds,
                    job_service=job_service,
                    job_id=job_id,
                )
            else:
                result = service.generate_for_chapter(
                    book_id,
                    chapter_id=chapter_id or None,
                    job_service=job_service,
                    job_id=job_id,
                    force=force,
                    review_rounds=review_rounds,
                )

            for error in result.get("errors", []):
                logger.warning(f"Explanation generation failed: {error}")

            final_status = "completed" if result["failed"] == 0 else "completed_with_errors"

        job_service.release_lock(job_id, status=final_status)

    except Exception:
        raise  # run_in_background_v2 handles marking the job as failed


def _run_visual_enrichment(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", force_str: str = "False", review_rounds_str: str = "1",
):
    """Background task for visual enrichment of explanation cards."""
    import json as _json
    from config import get_settings
    from shared.models.entities import TeachingGuideline
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.animation_enrichment_service import AnimationEnrichmentService
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    force = force_str.lower() == "true"
    review_rounds = int(review_rounds_str)

    settings = get_settings()

    # Decision+spec LLM (can be lighter model)
    config = LLMConfigService(db).get_config("animation_enrichment")
    llm_service = LLMService(
        api_key=settings.openai_api_key,
        provider=config["provider"],
        model_id=config["model_id"],
        reasoning_effort=config["reasoning_effort"],
        gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
        anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
    )

    # Code generation LLM (heavier model for reliable code)
    code_config = LLMConfigService(db).get_config("animation_code_gen")
    code_llm = LLMService(
        api_key=settings.openai_api_key,
        provider=code_config["provider"],
        model_id=code_config["model_id"],
        gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
        anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
    )

    job_service = ChapterJobService(db)
    service = AnimationEnrichmentService(db, llm_service, code_gen_llm=code_llm)

    try:
        if guideline_id:
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
            ).first()
            if not guideline:
                raise ValueError(f"Guideline {guideline_id} not found")

            topic = guideline.topic_title or guideline.topic
            job_service.update_progress(job_id, current_item=topic, completed=0, failed=0)

            heartbeat_fn = lambda: job_service.update_progress(
                job_id, current_item=topic, completed=0, failed=0,
            )
            stage_collector = []
            result = service.enrich_guideline(
                guideline, force=force, heartbeat_fn=heartbeat_fn,
                review_rounds=review_rounds, stage_collector=stage_collector,
            )
            if stage_collector:
                job_service.append_stage_snapshots(job_id, stage_collector)

            job_service.update_progress(
                job_id, current_item=None,
                completed=result["enriched"], failed=result["failed"],
                detail=_json.dumps(result),
            )
            final_status = "completed" if result["failed"] == 0 else "completed_with_errors"
        else:
            result = service.enrich_chapter(
                book_id,
                chapter_id=chapter_id or None,
                force=force,
                job_service=job_service,
                job_id=job_id,
                review_rounds=review_rounds,
            )

            for error in result.get("errors", []):
                logger.warning(f"Visual enrichment error: {error}")

            final_status = "completed" if result["failed"] == 0 else "completed_with_errors"

        job_service.release_lock(job_id, status=final_status)

    except Exception:
        raise


# ═══════════════════════════════════════════════════════════════════════════
# Guidelines Admin Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/guideline-status", response_model=ChapterGuidelineStatusResponse)
def get_guideline_status(
    book_id: str,
    chapter_id: str = Query(..., description="Chapter ID"),
    db: Session = Depends(get_db),
):
    """Per-topic guideline status for a chapter."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.explanation_repository import ExplanationRepository

    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")
        chapter_key = f"chapter-{chapter.chapter_number}"

        guidelines = (
            db.query(TeachingGuideline)
            .filter(
                TeachingGuideline.book_id == book_id,
                TeachingGuideline.chapter_key == chapter_key,
            )
            .order_by(TeachingGuideline.topic_sequence)
            .all()
        )

        repo = ExplanationRepository(db)
        expl_counts = repo.get_variant_counts_for_chapter(book_id, chapter_key)

        items = [
            GuidelineStatusItem(
                guideline_id=g.id,
                topic_title=g.topic_title or g.topic,
                topic_key=g.topic_key,
                review_status=g.review_status or "TO_BE_REVIEWED",
                guideline_preview=(g.guideline[:200] + "...") if g.guideline and len(g.guideline) > 200 else g.guideline,
                has_explanations=expl_counts.get(g.id, 0) > 0,
                source_page_start=g.source_page_start,
                source_page_end=g.source_page_end,
            )
            for g in guidelines
        ]

        return ChapterGuidelineStatusResponse(
            chapter_id=chapter_id, chapter_key=chapter_key, guidelines=items,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/guidelines/{guideline_id}", response_model=GuidelineDetailResponse)
def get_guideline_detail(
    book_id: str,
    guideline_id: str,
    db: Session = Depends(get_db),
):
    """Full guideline detail for a single topic."""
    from shared.models.entities import TeachingGuideline
    import json as _json

    guideline = db.query(TeachingGuideline).filter(
        TeachingGuideline.id == guideline_id,
        TeachingGuideline.book_id == book_id,
    ).first()
    if not guideline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guideline not found")

    meta = None
    if guideline.metadata_json:
        try:
            meta = _json.loads(guideline.metadata_json) if isinstance(guideline.metadata_json, str) else guideline.metadata_json
        except Exception:
            meta = None

    return GuidelineDetailResponse(
        id=guideline.id,
        topic_title=guideline.topic_title or guideline.topic,
        topic_key=guideline.topic_key,
        chapter_key=guideline.chapter_key,
        guideline=guideline.guideline,
        review_status=guideline.review_status or "TO_BE_REVIEWED",
        source_page_start=guideline.source_page_start,
        source_page_end=guideline.source_page_end,
        metadata_json=meta,
        topic_summary=guideline.topic_summary,
        updated_at=guideline.updated_at,
    )


@router.put("/guidelines/{guideline_id}", response_model=GuidelineDetailResponse)
def update_guideline(
    book_id: str,
    guideline_id: str,
    body: UpdateGuidelineRequest,
    db: Session = Depends(get_db),
):
    """Update a guideline's text or review status."""
    from shared.models.entities import TeachingGuideline
    from datetime import datetime

    guideline = db.query(TeachingGuideline).filter(
        TeachingGuideline.id == guideline_id,
        TeachingGuideline.book_id == book_id,
    ).first()
    if not guideline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guideline not found")

    if body.guideline is not None:
        guideline.guideline = body.guideline
    if body.review_status is not None:
        guideline.review_status = body.review_status
        if body.review_status == "APPROVED":
            guideline.reviewed_at = datetime.utcnow()

    guideline.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(guideline)

    return get_guideline_detail(book_id, guideline_id, db)


# ═══════════════════════════════════════════════════════════════════════════
# Visual Enrichment Admin Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/visual-status", response_model=ChapterVisualStatusResponse)
def get_visual_status(
    book_id: str,
    chapter_id: str = Query(..., description="Chapter ID"),
    db: Session = Depends(get_db),
):
    """Per-topic visual enrichment counts for a chapter."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.explanation_repository import ExplanationRepository

    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")
        chapter_key = f"chapter-{chapter.chapter_number}"

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

        repo = ExplanationRepository(db)
        topics = []
        for g in guidelines:
            explanations = repo.get_by_guideline_id(g.id)
            total_cards = 0
            cards_with_visuals = 0
            layout_warning_count = 0
            for expl in explanations:
                cards = expl.cards_json or []
                total_cards += len(cards)
                for c in cards:
                    visual = c.get("visual_explanation")
                    if isinstance(visual, dict) and visual.get("pixi_code"):
                        cards_with_visuals += 1
                        if visual.get("layout_warning") is True:
                            layout_warning_count += 1
            topics.append(TopicVisualStatus(
                guideline_id=g.id,
                topic_title=g.topic_title or g.topic,
                topic_key=g.topic_key,
                total_cards=total_cards,
                cards_with_visuals=cards_with_visuals,
                layout_warning_count=layout_warning_count,
                has_explanations=len(explanations) > 0,
            ))

        return ChapterVisualStatusResponse(
            chapter_id=chapter_id, chapter_key=chapter_key, topics=topics,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.delete("/guidelines/{guideline_id}")
def delete_guideline(
    book_id: str,
    guideline_id: str,
    db: Session = Depends(get_db),
):
    """Delete a single teaching guideline and its explanations."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.explanation_repository import ExplanationRepository

    guideline = db.query(TeachingGuideline).filter(
        TeachingGuideline.id == guideline_id,
        TeachingGuideline.book_id == book_id,
    ).first()
    if not guideline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guideline not found")

    # Delete associated explanations first
    expl_count = ExplanationRepository(db).delete_by_guideline_id(guideline_id)
    db.delete(guideline)
    db.commit()

    return {"deleted_guideline": guideline_id, "deleted_explanations": expl_count}


@router.delete("/visuals")
def delete_visuals(
    book_id: str,
    guideline_id: str = Query(..., description="Guideline ID to strip visuals from"),
    db: Session = Depends(get_db),
):
    """Strip visual_explanation from all cards for a topic's explanations."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.explanation_repository import ExplanationRepository

    guideline = db.query(TeachingGuideline).filter(
        TeachingGuideline.id == guideline_id,
        TeachingGuideline.book_id == book_id,
    ).first()
    if not guideline:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guideline not found")

    repo = ExplanationRepository(db)
    explanations = repo.get_by_guideline_id(guideline_id)
    stripped = 0
    for expl in explanations:
        cards = expl.cards_json or []
        changed = False
        for card in cards:
            if "visual_explanation" in card:
                del card["visual_explanation"]
                changed = True
                stripped += 1
        if changed:
            from sqlalchemy.orm.attributes import flag_modified
            expl.cards_json = cards
            flag_modified(expl, "cards_json")
    db.commit()

    return {"guideline_id": guideline_id, "visuals_stripped": stripped}


@router.get("/visual-jobs/{job_id}/stages")
def get_visual_job_stage_snapshots(
    book_id: str,
    job_id: str,
    guideline_id: Optional[str] = Query(None, description="Filter stages by guideline_id"),
    db: Session = Depends(get_db),
):
    """Get per-card per-round PixiJS snapshots for a visual enrichment job."""
    job_service = ChapterJobService(db)
    snapshots = job_service.get_stage_snapshots(job_id, guideline_id=guideline_id)
    return {"job_id": job_id, "snapshots": snapshots}


@router.get("/visual-jobs/latest", response_model=ProcessingJobResponse)
def get_latest_visual_job(
    book_id: str,
    chapter_id: Optional[str] = Query(None),
    guideline_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Latest visual enrichment job for a topic, chapter, or book."""
    try:
        lookup_chapter_id, lookup_guideline_id = _resolve_lookup_scope(
            db, book_id=book_id, chapter_id=chapter_id, guideline_id=guideline_id,
        )
        job_service = ChapterJobService(db)
        result = job_service.get_latest_job(
            lookup_chapter_id,
            job_type=V2JobType.VISUAL_ENRICHMENT.value,
            guideline_id=lookup_guideline_id,
        )
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No visual enrichment jobs found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Check-In Enrichment Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/generate-check-ins", response_model=FanOutJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_check_ins(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope enrichment"),
    guideline_id: Optional[str] = Query(None, description="Optional guideline_id for single-topic enrichment"),
    force: bool = Query(False, description="Re-generate check-ins even if they already exist"),
    review_rounds: int = Query(1, ge=0, le=5, description="Accuracy review-refine rounds after initial generation (0 disables)"),
    db: Session = Depends(get_db),
):
    """Generate interactive check-in cards for explanation cards.

    Launches one background job per guideline. Requires explanations to exist.
    Scoping: guideline_id (single topic) > chapter_id (fan-out) > book-wide.
    review_rounds controls the accuracy review-refine loop (0-5, default 1).
    """
    from book_ingestion_v2.services.stage_launchers import launch_check_in_job

    try:
        return _fan_out(
            db,
            launcher=launch_check_in_job,
            book_id=book_id,
            chapter_id=chapter_id,
            guideline_id=guideline_id,
            launcher_kwargs={"force": force, "review_rounds": review_rounds},
        )
    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Check-in enrichment failed for book {book_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/check-in-status", response_model=ChapterCheckInStatusResponse)
def get_check_in_status(
    book_id: str,
    chapter_id: str = Query(..., description="Chapter ID"),
    db: Session = Depends(get_db),
):
    """Per-topic check-in enrichment counts for a chapter."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.explanation_repository import ExplanationRepository

    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")
        chapter_key = f"chapter-{chapter.chapter_number}"

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

        repo = ExplanationRepository(db)
        topics = []
        for g in guidelines:
            explanations = repo.get_by_guideline_id(g.id)
            total_cards = 0
            cards_with_check_ins = 0
            for expl in explanations:
                cards = expl.cards_json or []
                total_cards += len(cards)
                cards_with_check_ins += sum(
                    1 for c in cards if c.get("card_type") == "check_in"
                )
            topics.append(TopicCheckInStatus(
                guideline_id=g.id,
                topic_title=g.topic_title or g.topic,
                topic_key=g.topic_key,
                total_cards=total_cards,
                cards_with_check_ins=cards_with_check_ins,
                has_explanations=len(explanations) > 0,
            ))

        return ChapterCheckInStatusResponse(
            chapter_id=chapter_id, chapter_key=chapter_key, topics=topics,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/check-in-jobs/latest", response_model=ProcessingJobResponse)
def get_latest_check_in_job(
    book_id: str,
    chapter_id: Optional[str] = Query(None),
    guideline_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Latest check-in enrichment job for a topic, chapter, or book."""
    try:
        lookup_chapter_id, lookup_guideline_id = _resolve_lookup_scope(
            db, book_id=book_id, chapter_id=chapter_id, guideline_id=guideline_id,
        )
        job_service = ChapterJobService(db)
        result = job_service.get_latest_job(
            lookup_chapter_id,
            job_type=V2JobType.CHECK_IN_ENRICHMENT.value,
            guideline_id=lookup_guideline_id,
        )
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No check-in enrichment jobs found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


def _run_check_in_enrichment(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", force_str: str = "False", review_rounds_str: str = "1",
):
    """Background task for check-in enrichment of explanation cards."""
    import json as _json
    from config import get_settings
    from shared.models.entities import TeachingGuideline
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.check_in_enrichment_service import CheckInEnrichmentService
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    force = force_str.lower() == "true"
    try:
        review_rounds = int(review_rounds_str)
    except (TypeError, ValueError):
        review_rounds = 1

    settings = get_settings()

    # LLM config — fallback to explanation_generator
    llm_config_svc = LLMConfigService(db)
    try:
        config = llm_config_svc.get_config("check_in_enrichment")
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

    job_service = ChapterJobService(db)
    service = CheckInEnrichmentService(db, llm_service)

    if guideline_id:
        guideline = db.query(TeachingGuideline).filter(
            TeachingGuideline.id == guideline_id,
        ).first()
        if not guideline:
            raise ValueError(f"Guideline {guideline_id} not found")

        topic = guideline.topic_title or guideline.topic
        job_service.update_progress(job_id, current_item=topic, completed=0, failed=0)

        heartbeat_fn = lambda: job_service.update_progress(
            job_id, current_item=topic, completed=0, failed=0,
        )
        result = service.enrich_guideline(
            guideline, force=force, review_rounds=review_rounds, heartbeat_fn=heartbeat_fn,
        )

        job_service.update_progress(
            job_id, current_item=None,
            completed=result["enriched"], failed=result["failed"],
            detail=_json.dumps(result),
        )
        final_status = "completed" if result["failed"] == 0 else "completed_with_errors"
    else:
        result = service.enrich_chapter(
            book_id,
            chapter_id=chapter_id or None,
            force=force,
            review_rounds=review_rounds,
            job_service=job_service,
            job_id=job_id,
        )

        for error in result.get("errors", []):
            logger.warning(f"Check-in enrichment error: {error}")

        final_status = "completed" if result["failed"] == 0 else "completed_with_errors"

    job_service.release_lock(job_id, status=final_status)


# ═══════════════════════════════════════════════════════════════════════════
# Practice Bank Generation Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/generate-practice-banks", response_model=FanOutJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_practice_banks(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope generation"),
    guideline_id: Optional[str] = Query(None, description="Optional guideline_id for single-topic generation"),
    force: bool = Query(False, description="Re-generate bank even if questions already exist"),
    review_rounds: int = Query(1, ge=0, le=5, description="Correctness review-refine rounds after initial generation (0 disables)"),
    db: Session = Depends(get_db),
):
    """Generate offline practice question banks for each approved topic.

    Launches one background job per guideline. Requires explanations to exist
    (the generator prompt consumes variant-A cards for concept grounding).
    Scoping: guideline_id (single topic) > chapter_id (fan-out) > book-wide.
    review_rounds controls the correctness review-refine loop (0-5, default 1).
    """
    from book_ingestion_v2.services.stage_launchers import launch_practice_bank_job

    try:
        return _fan_out(
            db,
            launcher=launch_practice_bank_job,
            book_id=book_id,
            chapter_id=chapter_id,
            guideline_id=guideline_id,
            launcher_kwargs={"force": force, "review_rounds": review_rounds},
        )
    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Practice bank generation failed for book {book_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/practice-bank-status", response_model=ChapterPracticeBankStatusResponse)
def get_practice_bank_status(
    book_id: str,
    chapter_id: str = Query(..., description="Chapter ID"),
    db: Session = Depends(get_db),
):
    """Per-topic practice-bank question counts for a chapter."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.explanation_repository import ExplanationRepository
    from shared.repositories.practice_question_repository import PracticeQuestionRepository

    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")
        chapter_key = f"chapter-{chapter.chapter_number}"

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

        expl_repo = ExplanationRepository(db)
        q_repo = PracticeQuestionRepository(db)
        counts = q_repo.counts_by_guidelines([g.id for g in guidelines])
        topics = []
        for g in guidelines:
            explanations = expl_repo.get_by_guideline_id(g.id)
            topics.append(TopicPracticeBankStatus(
                guideline_id=g.id,
                topic_title=g.topic_title or g.topic,
                topic_key=g.topic_key,
                question_count=counts.get(g.id, 0),
                has_explanations=len(explanations) > 0,
            ))

        return ChapterPracticeBankStatusResponse(
            chapter_id=chapter_id, chapter_key=chapter_key, topics=topics,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/practice-bank-jobs/latest", response_model=ProcessingJobResponse)
def get_latest_practice_bank_job(
    book_id: str,
    chapter_id: Optional[str] = Query(None),
    guideline_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Latest practice bank generation job for a topic, chapter, or book."""
    try:
        lookup_chapter_id, lookup_guideline_id = _resolve_lookup_scope(
            db, book_id=book_id, chapter_id=chapter_id, guideline_id=guideline_id,
        )
        job_service = ChapterJobService(db)
        result = job_service.get_latest_job(
            lookup_chapter_id,
            job_type=V2JobType.PRACTICE_BANK_GENERATION.value,
            guideline_id=lookup_guideline_id,
        )
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No practice bank generation jobs found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/practice-banks/{guideline_id}", response_model=PracticeBankDetailResponse)
def get_practice_bank(
    book_id: str,
    guideline_id: str,
    db: Session = Depends(get_db),
):
    """Full practice bank for a topic — admin viewer. Returns all questions."""
    from shared.models.entities import TeachingGuideline
    from shared.repositories.practice_question_repository import PracticeQuestionRepository

    try:
        guideline = db.query(TeachingGuideline).filter(
            TeachingGuideline.id == guideline_id,
            TeachingGuideline.book_id == book_id,
        ).first()
        if not guideline:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Guideline {guideline_id} not found in book {book_id}",
            )

        repo = PracticeQuestionRepository(db)
        questions = repo.list_by_guideline(guideline_id)

        items = [
            PracticeBankQuestionItem(
                id=q.id,
                format=q.format,
                difficulty=q.difficulty,
                concept_tag=q.concept_tag,
                question_json=q.question_json or {},
                generator_model=q.generator_model,
                created_at=q.created_at,
            )
            for q in questions
        ]

        return PracticeBankDetailResponse(
            guideline_id=guideline_id,
            topic_title=guideline.topic_title or guideline.topic,
            question_count=len(items),
            questions=items,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


def _run_practice_bank_generation(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", force_str: str = "False", review_rounds_str: str = "1",
):
    """Background task for practice bank generation."""
    import json as _json
    from config import get_settings
    from shared.models.entities import TeachingGuideline
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.practice_bank_generator_service import PracticeBankGeneratorService
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    force = force_str.lower() == "true"
    try:
        review_rounds = int(review_rounds_str)
    except (TypeError, ValueError):
        review_rounds = 1

    settings = get_settings()

    # LLM config — fallback to explanation_generator
    llm_config_svc = LLMConfigService(db)
    try:
        config = llm_config_svc.get_config("practice_bank_generator")
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

    job_service = ChapterJobService(db)
    service = PracticeBankGeneratorService(db, llm_service)

    if guideline_id:
        guideline = db.query(TeachingGuideline).filter(
            TeachingGuideline.id == guideline_id,
        ).first()
        if not guideline:
            raise ValueError(f"Guideline {guideline_id} not found")

        topic = guideline.topic_title or guideline.topic
        job_service.update_progress(job_id, current_item=topic, completed=0, failed=0)

        heartbeat_fn = lambda: job_service.update_progress(
            job_id, current_item=topic, completed=0, failed=0,
        )
        result = service.enrich_guideline(
            guideline, force=force, review_rounds=review_rounds, heartbeat_fn=heartbeat_fn,
        )

        job_service.update_progress(
            job_id, current_item=None,
            completed=result["generated"], failed=result["failed"],
            detail=_json.dumps(result),
        )
        final_status = "completed" if result["failed"] == 0 else "completed_with_errors"
    else:
        result = service.enrich_chapter(
            book_id,
            chapter_id=chapter_id or None,
            force=force,
            review_rounds=review_rounds,
            job_service=job_service,
            job_id=job_id,
        )

        for error in result.get("errors", []):
            logger.warning(f"Practice bank generation error: {error}")

        final_status = "completed" if result["failed"] == 0 else "completed_with_errors"

    job_service.release_lock(job_id, status=final_status)


# ═══════════════════════════════════════════════════════════════════════════
# Refresher Topic Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/refresher/generate", response_model=ProcessingJobResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_refresher(
    book_id: str,
    chapter_id: str,
    db: Session = Depends(get_db),
):
    """Generate prerequisite refresher topic for a chapter.

    Launches a background job and returns 202 immediately.
    """
    from book_ingestion_v2.api.processing_routes import run_in_background_v2
    from shared.models.entities import TeachingGuideline

    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chapter {chapter_id} not found in book {book_id}",
            )

        # Chapter must have synced topics (non-refresher guidelines)
        chapter_key = f"chapter-{chapter.chapter_number}"
        topic_count = db.query(TeachingGuideline).filter(
            TeachingGuideline.book_id == book_id,
            TeachingGuideline.chapter_key == chapter_key,
            TeachingGuideline.topic_key != "get-ready",
        ).count()
        if topic_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chapter has no synced topics. Sync the chapter first.",
            )

        job_service = ChapterJobService(db)
        job_id = job_service.acquire_lock(
            book_id=book_id,
            chapter_id=chapter_id,
            job_type=V2JobType.REFRESHER_GENERATION.value,
            total_items=1,
        )

        run_in_background_v2(
            _run_refresher_generation, job_id, book_id, chapter_id,
        )

        return job_service.get_job(job_id)

    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Refresher generation failed for book {book_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/refresher-jobs/latest", response_model=ProcessingJobResponse)
def get_latest_refresher_job(
    book_id: str,
    chapter_id: str = Query(..., description="Chapter ID"),
    db: Session = Depends(get_db),
):
    """Latest refresher generation job for a chapter."""
    try:
        job_service = ChapterJobService(db)
        result = job_service.get_latest_job(
            chapter_id, job_type=V2JobType.REFRESHER_GENERATION.value,
        )
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No refresher generation jobs found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/landing")
def get_chapter_landing(
    book_id: str,
    chapter_id: str,
    db: Session = Depends(get_db),
):
    """Chapter landing page data: summary + prerequisite concepts."""
    import json as _json
    from shared.models.entities import TeachingGuideline

    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chapter {chapter_id} not found in book {book_id}",
            )

        chapter_key = f"chapter-{chapter.chapter_number}"

        # Check for refresher guideline
        refresher = db.query(TeachingGuideline).filter(
            TeachingGuideline.book_id == book_id,
            TeachingGuideline.chapter_key == chapter_key,
            TeachingGuideline.topic_key == "get-ready",
        ).first()

        prerequisite_concepts = []
        refresher_guideline_id = None
        if refresher:
            refresher_guideline_id = refresher.id
            if refresher.metadata_json:
                try:
                    meta = _json.loads(refresher.metadata_json) if isinstance(refresher.metadata_json, str) else refresher.metadata_json
                    prerequisite_concepts = meta.get("prerequisite_concepts", [])
                except Exception:
                    pass

        return {
            "chapter_summary": chapter.summary,
            "prerequisite_concepts": prerequisite_concepts,
            "refresher_guideline_id": refresher_guideline_id,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("sync route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


def _run_refresher_generation(
    db: Session, job_id: str, book_id: str, chapter_id: str,
):
    """Background task for refresher topic generation."""
    from config import get_settings
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.refresher_topic_generator_service import RefresherTopicGeneratorService
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService
    from book_ingestion_v2.repositories.chapter_repository import ChapterRepository

    settings = get_settings()
    config = LLMConfigService(db).get_config("explanation_generator")
    llm_service = LLMService(
        api_key=settings.openai_api_key,
        provider=config["provider"],
        model_id=config["model_id"],
        reasoning_effort=config["reasoning_effort"],
        gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
        anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
    )

    job_service = ChapterJobService(db)
    service = RefresherTopicGeneratorService(db, llm_service)

    try:
        chapter_repo = ChapterRepository(db)
        chapter = chapter_repo.get_by_id(chapter_id)
        chapter_key = f"chapter-{chapter.chapter_number}"

        job_service.update_progress(job_id, current_item=f"Refresher for {chapter.chapter_title}", completed=0, failed=0)

        guideline_id = service.generate_for_chapter(book_id, chapter_key)

        if guideline_id:
            job_service.update_progress(job_id, current_item=None, completed=1, failed=0)
            final_status = "completed"
        else:
            job_service.update_progress(job_id, current_item=None, completed=0, failed=0,
                                        detail='{"skipped": true, "reason": "No prerequisites needed"}')
            final_status = "completed"

        job_service.release_lock(job_id, status=final_status)

    except Exception:
        raise  # run_in_background_v2 handles marking the job as failed


# ─────────────────────────── Baatcheet (Stage 5b/5c) ──────────────────────


@router.post(
    "/generate-baatcheet-dialogue",
    response_model=FanOutJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_baatcheet_dialogue(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope generation"),
    guideline_id: Optional[str] = Query(None, description="Optional guideline_id for single-topic generation"),
    force: bool = Query(False, description="Regenerate even if a dialogue already exists"),
    review_rounds: int = Query(1, ge=0, le=5),
    db: Session = Depends(get_db),
):
    """Stage 5b — generate the Baatcheet dialogue.

    Requires variant A explanations to exist. Scoping: guideline_id (single
    topic) > chapter_id (fan-out) > book-wide.
    """
    from book_ingestion_v2.services.stage_launchers import launch_baatcheet_dialogue_job

    try:
        return _fan_out(
            db,
            launcher=launch_baatcheet_dialogue_job,
            book_id=book_id,
            chapter_id=chapter_id,
            guideline_id=guideline_id,
            launcher_kwargs={"force": force, "review_rounds": review_rounds},
        )
    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Baatcheet dialogue gen failed for book {book_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post(
    "/generate-baatcheet-visuals",
    response_model=FanOutJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_baatcheet_visuals(
    book_id: str,
    chapter_id: Optional[str] = Query(None, description="Optional chapter_id to scope enrichment"),
    guideline_id: Optional[str] = Query(None, description="Optional guideline_id for single-topic enrichment"),
    force: bool = Query(False, description="Regenerate visuals even where they already exist"),
    db: Session = Depends(get_db),
):
    """Stage 5c — fill PixiJS visuals on the Baatcheet dialogue's `visual` cards."""
    from book_ingestion_v2.services.stage_launchers import launch_baatcheet_visual_job

    try:
        return _fan_out(
            db,
            launcher=launch_baatcheet_visual_job,
            book_id=book_id,
            chapter_id=chapter_id,
            guideline_id=guideline_id,
            launcher_kwargs={"force": force},
        )
    except ChapterJobLockError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Baatcheet visual gen failed for book {book_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


def _run_baatcheet_dialogue_generation(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", force_str: str = "False",
    review_rounds_str: str = "1",
):
    """Background task — Stage 5b dialogue generation."""
    import json as _json
    from config import get_settings
    from shared.models.entities import TeachingGuideline
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
        BaatcheetDialogueGeneratorService,
        DialogueValidationError,
    )
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    force = force_str.lower() == "true"
    review_rounds = int(review_rounds_str)
    job_service = ChapterJobService(db)

    try:
        settings = get_settings()
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

        service = BaatcheetDialogueGeneratorService(db, llm_service)

        if guideline_id:
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
            ).first()
            if not guideline:
                raise ValueError(f"Guideline {guideline_id} not found")

            topic = guideline.topic_title or guideline.topic
            job_service.update_progress(job_id, current_item=topic, completed=0, failed=0)

            stage_collector: list = []
            try:
                dialogue = service.generate_for_guideline(
                    guideline,
                    review_rounds=review_rounds,
                    stage_collector=stage_collector,
                    force=force,
                )
                completed = 1 if dialogue else 0
                failed = 0 if dialogue else 1
                errors = [] if dialogue else [f"{topic}: dialogue not produced"]
            except DialogueValidationError as e:
                completed = 0
                failed = 1
                errors = [f"{topic}: validators rejected after refine ({e})"]
            except Exception as e:
                completed = 0
                failed = 1
                errors = [f"{topic}: {e}"]

            if stage_collector:
                try:
                    job_service.append_stage_snapshots(job_id, stage_collector)
                except Exception as e:
                    logger.warning(f"append_stage_snapshots failed for job {job_id}: {e}")

            job_service.update_progress(
                job_id, current_item=None, completed=completed, failed=failed,
                detail=_json.dumps({
                    "completed": completed, "failed": failed, "errors": errors,
                }),
            )
            final_status = "completed" if failed == 0 else "completed_with_errors"
        else:
            from shared.models.entities import TeachingGuideline as TG
            query = db.query(TG).filter(
                TG.book_id == book_id,
                TG.review_status == "APPROVED",
            )
            if chapter_id:
                from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
                chapter = ChapterRepository(db).get_by_id(chapter_id)
                if chapter:
                    query = query.filter(TG.chapter_key == f"chapter-{chapter.chapter_number}")
            guidelines = query.order_by(TG.topic_sequence).all()
            completed = 0
            failed = 0
            errors: list[str] = []
            for g in guidelines:
                try:
                    service.generate_for_guideline(
                        g, review_rounds=review_rounds, force=force,
                    )
                    completed += 1
                except Exception as e:
                    failed += 1
                    errors.append(f"{g.topic_title or g.topic}: {e}")
            job_service.update_progress(
                job_id, current_item=None, completed=completed, failed=failed,
                detail=_json.dumps({
                    "completed": completed, "failed": failed, "errors": errors[:10],
                }),
            )
            final_status = "completed" if failed == 0 else "completed_with_errors"

        job_service.release_lock(job_id, status=final_status)

    except Exception as e:
        logger.error(f"Baatcheet dialogue gen job {job_id} failed: {e}")
        job_service.release_lock(job_id, status="failed", error=str(e))


def _run_baatcheet_visual_enrichment(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", force_str: str = "False",
):
    """Background task — Stage 5c PixiJS visuals on dialogue cards."""
    import json as _json
    from config import get_settings
    from shared.models.entities import TeachingGuideline
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.baatcheet_visual_enrichment_service import (
        BaatcheetVisualEnrichmentService,
    )
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    force = force_str.lower() == "true"
    job_service = ChapterJobService(db)

    try:
        settings = get_settings()
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

        service = BaatcheetVisualEnrichmentService(db, llm_service)

        if guideline_id:
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
            ).first()
            if not guideline:
                raise ValueError(f"Guideline {guideline_id} not found")

            topic = guideline.topic_title or guideline.topic
            job_service.update_progress(job_id, current_item=topic, completed=0, failed=0)

            heartbeat_fn = lambda: job_service.update_progress(
                job_id, current_item=topic, completed=0, failed=0,
            )
            stage_collector: list = []
            per = service.enrich_guideline(
                guideline, force=force,
                heartbeat_fn=heartbeat_fn, stage_collector=stage_collector,
            )

            if stage_collector:
                try:
                    job_service.append_stage_snapshots(job_id, stage_collector)
                except Exception as e:
                    logger.warning(f"append_stage_snapshots failed for job {job_id}: {e}")

            completed = 1 if per["failed"] == 0 else 0
            failed = per["failed"]
            job_service.update_progress(
                job_id, current_item=None, completed=completed, failed=failed,
                detail=_json.dumps(per),
            )
            final_status = "completed" if failed == 0 else "completed_with_errors"
        else:
            result = service.enrich_chapter(
                book_id, chapter_id=chapter_id or None,
                force=force, job_service=job_service, job_id=job_id,
            )
            final_status = (
                "completed" if result.get("failed", 0) == 0 else "completed_with_errors"
            )

        job_service.release_lock(job_id, status=final_status)

    except Exception as e:
        logger.error(f"Baatcheet visual enrichment job {job_id} failed: {e}")
        job_service.release_lock(job_id, status="failed", error=str(e))


def _run_baatcheet_audio_review(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", language: str = "", force_str: str = "False",
):
    """Background task — audio text review against topic_dialogues.

    Now a first-class DAG stage (sibling of `audio_review` for variant A).
    `force_str == "True"` clears every dialogue `audio_url` up front so the
    cascaded `baatcheet_audio_synthesis` regenerates the full clip set.
    """
    import json as _json
    from config import get_settings
    from shared.models.entities import TeachingGuideline
    from shared.services.llm_config_service import LLMConfigService
    from shared.services.llm_service import LLMService
    from book_ingestion_v2.services.baatcheet_audio_review_service import (
        BaatcheetAudioReviewService,
    )
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService

    force = force_str.lower() == "true"
    job_service = ChapterJobService(db)
    try:
        settings = get_settings()
        llm_config_svc = LLMConfigService(db)
        try:
            config = llm_config_svc.get_config("audio_text_review")
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

        service = BaatcheetAudioReviewService(db, llm_service, language=language or "en")

        if guideline_id:
            guideline = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
            ).first()
            if not guideline:
                raise ValueError(f"Guideline {guideline_id} not found")
            result = service.review_guideline(guideline, force=force)
            completed = 1 if result.get("failed", 0) == 0 else 0
            failed = result.get("failed", 0)
        else:
            from shared.models.entities import TeachingGuideline as TG
            query = db.query(TG).filter(
                TG.book_id == book_id,
                TG.review_status == "APPROVED",
            )
            if chapter_id:
                from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
                chapter = ChapterRepository(db).get_by_id(chapter_id)
                if chapter:
                    query = query.filter(TG.chapter_key == f"chapter-{chapter.chapter_number}")
            guidelines = query.all()
            completed = 0
            failed = 0
            agg = {"cards_reviewed": 0, "cards_revised": 0, "errors": []}
            for g in guidelines:
                try:
                    res = service.review_guideline(g, force=force)
                    agg["cards_reviewed"] += res.get("cards_reviewed", 0)
                    agg["cards_revised"] += res.get("cards_revised", 0)
                    if res.get("failed", 0):
                        failed += 1
                        agg["errors"].extend(res.get("errors", [])[:3])
                    else:
                        completed += 1
                except Exception as e:
                    failed += 1
                    agg["errors"].append(f"{g.topic_title or g.topic}: {e}")
            result = agg

        job_service.update_progress(
            job_id, current_item=None, completed=completed, failed=failed,
            detail=_json.dumps(result),
        )
        final_status = "completed" if failed == 0 else "completed_with_errors"
        job_service.release_lock(job_id, status=final_status)

    except Exception as e:
        logger.error(f"Baatcheet audio review job {job_id} failed: {e}")
        job_service.release_lock(job_id, status="failed", error=str(e))


def _run_baatcheet_audio_generation(
    db: Session, job_id: str, book_id: str, chapter_id: str,
    guideline_id: str = "", force_str: str = "False",
):
    """Background task for Baatcheet dialogue TTS audio generation.

    Synthesizes audio for `topic_dialogues.cards_json` only — variant A
    explanation audio lives in the parallel `audio_synthesis` stage.

    `force_str == "True"` overwrites lines that already have an
    `audio_url`. S3 keys are deterministic so writes overwrite cleanly at
    the same URL — no orphan cleanup needed.
    """
    import json as _json
    from shared.models.entities import TeachingGuideline, TopicDialogue
    from book_ingestion_v2.services.audio_generation_service import (
        AudioGenerationService,
        TTSProviderError,
    )
    from book_ingestion_v2.services.chapter_job_service import ChapterJobService
    from sqlalchemy.orm import attributes

    force = force_str.lower() == "true"
    job_service = ChapterJobService(db)
    audio_svc = AudioGenerationService(db=db)

    try:
        if guideline_id:
            guidelines = db.query(TeachingGuideline).filter(
                TeachingGuideline.id == guideline_id,
            ).all()
        else:
            query = db.query(TeachingGuideline).filter(
                TeachingGuideline.book_id == book_id,
                TeachingGuideline.review_status == "APPROVED",
            )
            if chapter_id:
                from shared.repositories.chapter_repository import ChapterRepository
                chapter = ChapterRepository(db).get_by_id(chapter_id)
                if chapter:
                    chapter_key = f"chapter-{chapter.chapter_number}"
                    query = query.filter(TeachingGuideline.chapter_key == chapter_key)
            guidelines = query.all()

        completed = 0
        failed = 0
        errors: list[str] = []

        for guideline in guidelines:
            topic = guideline.topic_title or guideline.topic
            job_service.update_progress(
                job_id, current_item=topic, completed=completed, failed=failed,
            )

            dialogue = db.query(TopicDialogue).filter(
                TopicDialogue.guideline_id == guideline.id,
            ).first()
            if dialogue is None:
                # No dialogue for this guideline — silently skip; not an error.
                continue

            try:
                updated_cards = audio_svc.generate_for_topic_dialogue(
                    dialogue, force=force,
                )
                if updated_cards is not None:
                    dialogue.cards_json = updated_cards
                    attributes.flag_modified(dialogue, "cards_json")
                    db.commit()
                completed += 1
            except TTSProviderError:
                # Provider outage — fail the whole job. See parallel
                # comment in generate_audio_for_chapter (variant A path).
                db.rollback()
                raise
            except Exception as e:
                logger.error(
                    f"Dialogue audio failed for guideline={guideline.id}: {e}"
                )
                db.rollback()
                failed += 1
                errors.append(f"{topic} (dialogue): {e}")

        job_service.update_progress(
            job_id, current_item=None, completed=completed, failed=failed,
            detail=_json.dumps({
                "generated": completed, "failed": failed, "errors": errors[:10],
            }),
        )
        final_status = "completed" if failed == 0 else "completed_with_errors"
        job_service.release_lock(job_id, status=final_status)

    except Exception as e:
        logger.error(f"Baatcheet audio generation job {job_id} failed: {e}")
        job_service.release_lock(job_id, status="failed", error=str(e))
