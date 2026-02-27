"""
Admin API routes for book ingestion.

Provides endpoints for book CRUD, page upload, and guideline management.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db

logger = logging.getLogger(__name__)
from book_ingestion.models.schemas import (
    CreateBookRequest,
    BookResponse,
    BookListResponse,
    BookDetailResponse

)
from book_ingestion.services.book_service import BookService


# Create router with /admin prefix (will be added in main.py)
router = APIRouter(prefix="/admin", tags=["admin"])


# ===== Book Management Endpoints =====

@router.post("/books", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
def create_book(request: CreateBookRequest, db: Session = Depends(get_db)):
    """
    Create a new book.

    Args:
        request: Book creation request
        db: Database session

    Returns:
        Created book response

    Raises:
        HTTPException: If book creation fails
    """
    try:
        service = BookService(db)
        return service.create_book(request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create book: {str(e)}"
        )


@router.get("/books", response_model=BookListResponse)
def list_books(
    country: Optional[str] = None,
    board: Optional[str] = None,
    grade: Optional[int] = None,
    subject: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    List books with optional filters.

    Args:
        country: Filter by country
        board: Filter by board
        grade: Filter by grade
        subject: Filter by subject
        limit: Maximum results (default: 100)
        offset: Pagination offset (default: 0)
        db: Database session

    Returns:
        List of books with total count
    """
    try:
        service = BookService(db)
        return service.list_books(
            country=country,
            board=board,
            grade=grade,
            subject=subject,
            limit=limit,
            offset=offset
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list books: {str(e)}"
        )


@router.get("/books/{book_id}", response_model=BookDetailResponse)
def get_book(book_id: str, db: Session = Depends(get_db)):
    """
    Get detailed book information including pages.

    Args:
        book_id: Book identifier
        db: Database session

    Returns:
        Detailed book response

    Raises:
        HTTPException: If book not found
    """
    try:
        service = BookService(db)
        book = service.get_book_detail(book_id)

        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book not found: {book_id}"
            )

        return book
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get book: {str(e)}"
        )





@router.delete("/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_book(book_id: str, db: Session = Depends(get_db)):
    """
    Delete book and all associated files.

    Args:
        book_id: Book identifier
        db: Database session

    Returns:
        No content

    Raises:
        HTTPException: If book not found
    """
    try:
        service = BookService(db)
        success = service.delete_book(book_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book not found: {book_id}"
            )

        return None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete book: {str(e)}"
        )


# ===== Page Management Endpoints =====

from fastapi import UploadFile, File
from book_ingestion.models.schemas import PageUploadResponse, PageApproveResponse
from book_ingestion.services.page_service import PageService


@router.post("/books/{book_id}/pages", response_model=PageUploadResponse)
async def upload_page(
    book_id: str,
    image: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload a page image for a book.

    The system will:
    1. Validate the image
    2. Upload to S3
    3. Perform OCR using OpenAI Vision API
    4. Return the page for review

    Args:
        book_id: Book identifier
        image: Image file (PNG, JPG, JPEG, TIFF, WebP)
        db: Database session

    Returns:
        PageUploadResponse with OCR text and presigned image URL

    Raises:
        HTTPException: If upload or OCR fails
    """
    try:
        # Block single-page upload during bulk OCR to prevent metadata.json conflicts
        from book_ingestion.services.job_lock_service import JobLockService
        job_lock = JobLockService(db)
        active_ocr = job_lock.get_latest_job(book_id, job_type="ocr_batch")
        if active_ocr and active_ocr["status"] in ("pending", "running"):
            raise HTTPException(
                status_code=409,
                detail="Bulk OCR job in progress. Wait for completion before uploading individual pages."
            )

        # Read image data
        image_data = await image.read()

        # Process upload
        service = PageService(db)
        return service.upload_page(book_id, image_data, image.filename)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload page: {str(e)}"
        )


@router.put("/books/{book_id}/pages/{page_num}/approve", response_model=PageApproveResponse)
def approve_page(
    book_id: str,
    page_num: int,
    db: Session = Depends(get_db)
):
    """
    Approve a page after reviewing OCR output.

    Args:
        book_id: Book identifier
        page_num: Page number to approve
        db: Database session

    Returns:
        PageApproveResponse with updated status

    Raises:
        HTTPException: If page not found or already approved
    """
    try:
        service = PageService(db)
        return service.approve_page(book_id, page_num)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve page: {str(e)}"
        )


@router.delete("/books/{book_id}/pages/{page_num}", status_code=status.HTTP_204_NO_CONTENT)
def delete_page(
    book_id: str,
    page_num: int,
    db: Session = Depends(get_db)
):
    """
    Delete (reject) a page to allow re-upload.

    Args:
        book_id: Book identifier
        page_num: Page number to delete
        db: Database session

    Returns:
        No content

    Raises:
        HTTPException: If page not found
    """
    try:
        service = PageService(db)
        success = service.delete_page(book_id, page_num)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Page {page_num} not found"
            )

        return None

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete page: {str(e)}"
        )


@router.get("/books/{book_id}/pages/{page_num}")
def get_page(
    book_id: str,
    page_num: int,
    db: Session = Depends(get_db)
):
    """
    Get page details with presigned URLs for image and text.

    Args:
        book_id: Book identifier
        page_num: Page number
        db: Database session

    Returns:
        Page details with presigned URLs and OCR text

    Raises:
        HTTPException: If page not found
    """
    try:
        service = PageService(db)
        return service.get_page_with_urls(book_id, page_num)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get page: {str(e)}"
        )


# ===== Guideline Management Endpoints (Phase 6) =====

from book_ingestion.services.guideline_extraction_orchestrator import GuidelineExtractionOrchestrator

from book_ingestion.utils.s3_client import S3Client
from openai import OpenAI
from pydantic import BaseModel
from typing import List, Literal


class GenerateGuidelinesRequest(BaseModel):
    """Request to generate guidelines for a book"""
    start_page: Optional[int] = 1
    end_page: Optional[int] = None
    auto_sync_to_db: bool = False
    resume: bool = False  # Auto-resume from last failure point


class GenerateGuidelinesStartResponse(BaseModel):
    """Response from starting guideline generation (background job)."""
    job_id: Optional[str] = None
    status: str
    start_page: int = 0
    end_page: int = 0
    total_pages: int = 0
    message: str


# Keep old response model for backward compatibility with tests
class GenerateGuidelinesResponse(BaseModel):
    """Response from guideline generation (legacy sync mode)"""
    book_id: str
    status: str
    pages_processed: int
    subtopics_created: int
    subtopics_merged: Optional[int] = 0
    subtopics_finalized: int
    duplicates_merged: Optional[int] = 0
    errors: List[str]
    warnings: List[str]


class GuidelineSubtopicResponse(BaseModel):
    """Response for a single subtopic guideline"""
    topic_key: str
    topic_title: str
    subtopic_key: str
    subtopic_title: str
    status: str
    source_page_start: int
    source_page_end: int
    version: int
    guidelines: str


class GuidelinesListResponse(BaseModel):
    """Response with list of all guidelines for a book"""
    book_id: str
    total_subtopics: int
    guidelines: List[GuidelineSubtopicResponse]
    processed_pages: List[int] = []  # Pages that have been processed (from page_index.json)


@router.post("/books/{book_id}/generate-guidelines", response_model=GenerateGuidelinesStartResponse)
def generate_guidelines(
    book_id: str,
    request: GenerateGuidelinesRequest,
    db: Session = Depends(get_db),
):
    """
    Start guideline generation as a background job.
    Returns immediately with job_id. Poll GET /books/{book_id}/jobs/latest for progress.
    """
    from book_ingestion.services.job_lock_service import JobLockService, JobLockError
    from book_ingestion.services.background_task_runner import run_in_background
    from book_ingestion.services.guideline_extraction_orchestrator import run_extraction_background

    try:
        # Validate book exists
        book_service = BookService(db)
        book = book_service.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail=f"Book not found: {book_id}")

        # Load total_pages from S3 metadata
        s3_client = S3Client()
        try:
            metadata = s3_client.download_json(f"books/{book_id}/metadata.json")
            total_pages = metadata.get("total_pages", 0)
        except Exception:
            total_pages = 0

        if total_pages == 0:
            raise HTTPException(status_code=400, detail="No pages uploaded for this book")

        start_page = request.start_page or 1
        end_page = request.end_page or total_pages

        # Handle resume
        if request.resume:
            job_lock_svc = JobLockService(db)
            latest = job_lock_svc.get_latest_job(book_id, job_type="extraction")
            if latest and latest["last_completed_item"]:
                start_page = latest["last_completed_item"] + 1
                if start_page > end_page:
                    return GenerateGuidelinesStartResponse(
                        job_id=None,
                        status="already_complete",
                        message="All pages already processed",
                    )

        total_to_process = end_page - start_page + 1

        # Acquire job lock (409 if already running)
        job_lock_svc = JobLockService(db)
        try:
            job_id = job_lock_svc.acquire_lock(
                book_id, job_type="extraction", total_items=total_to_process
            )
        except JobLockError as e:
            raise HTTPException(status_code=409, detail=str(e))

        # Read model config
        from shared.services.llm_config_service import LLMConfigService
        ingestion_config = LLMConfigService(db).get_config("book_ingestion")

        book_metadata = {
            "grade": book.grade,
            "subject": book.subject,
            "board": book.board,
            "total_pages": total_pages,
        }

        # Launch background task
        run_in_background(
            run_extraction_background,
            job_id=job_id,
            book_id=book_id,
            book_metadata=book_metadata,
            start_page=start_page,
            end_page=end_page,
            model=ingestion_config["model_id"],
        )

        return GenerateGuidelinesStartResponse(
            job_id=job_id,
            status="started",
            start_page=start_page,
            end_page=end_page,
            total_pages=total_to_process,
            message=f"Guideline generation started for pages {start_page}-{end_page}",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start guideline generation: {str(e)}"
        )


class FinalizeRequest(BaseModel):
    """Request to finalize and consolidate guidelines"""
    auto_sync_to_db: bool = False


class FinalizeStartResponse(BaseModel):
    """Response from starting finalization (background job)."""
    job_id: str
    status: str
    message: str


# Keep old response model for backward compatibility
class FinalizeResponse(BaseModel):
    """Response from finalization (legacy sync mode)"""
    book_id: str
    status: str
    subtopics_finalized: int
    subtopics_renamed: int
    duplicates_merged: int
    message: str


@router.post("/books/{book_id}/finalize", response_model=FinalizeStartResponse)
def finalize_guidelines(
    book_id: str,
    request: FinalizeRequest,
    db: Session = Depends(get_db),
):
    """
    Start guideline finalization as a background job.
    Returns immediately with job_id. Poll GET /books/{book_id}/jobs/latest for progress.
    """
    from book_ingestion.services.job_lock_service import JobLockService, JobLockError
    from book_ingestion.services.background_task_runner import run_in_background
    from book_ingestion.services.guideline_extraction_orchestrator import run_finalization_background

    try:
        # Validate book exists
        book_service = BookService(db)
        book = book_service.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail=f"Book not found: {book_id}")

        book_metadata = {
            "grade": book.grade,
            "subject": book.subject,
            "board": book.board,
            "country": book.country,
        }

        # Acquire job lock (409 if already running)
        job_lock_svc = JobLockService(db)
        try:
            job_id = job_lock_svc.acquire_lock(
                book_id, job_type="finalization", total_items=1
            )
        except JobLockError as e:
            raise HTTPException(status_code=409, detail=str(e))

        # Read model config
        from shared.services.llm_config_service import LLMConfigService
        ingestion_config = LLMConfigService(db).get_config("book_ingestion")

        # Launch background task
        run_in_background(
            run_finalization_background,
            job_id=job_id,
            book_id=book_id,
            book_metadata=book_metadata,
            model=ingestion_config["model_id"],
            auto_sync_to_db=request.auto_sync_to_db,
        )

        return FinalizeStartResponse(
            job_id=job_id,
            status="started",
            message="Finalization started in background",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start finalization: {str(e)}"
        )


@router.get("/books/{book_id}/guidelines", response_model=GuidelinesListResponse)
def get_guidelines(book_id: str, db: Session = Depends(get_db)):
    """
    Get all generated guidelines for a book.

    Args:
        book_id: Book identifier
        db: Database session

    Returns:
        List of all subtopic guidelines

    Raises:
        HTTPException: If book not found
    """
    try:
        # Verify book exists
        book_service = BookService(db)
        book = book_service.get_book(book_id)

        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book not found: {book_id}"
            )

        # Load guidelines index from S3
        s3_client = S3Client()
        from book_ingestion.services.index_management_service import IndexManagementService

        index_mgr = IndexManagementService(s3_client)

        # Load page index (tracks which pages have been processed)
        processed_pages: List[int] = []
        try:
            page_index = index_mgr.load_page_index(book_id)
            processed_pages = sorted(page_index.pages.keys())
        except FileNotFoundError:
            pass  # No pages processed yet

        try:
            index = index_mgr.load_index(book_id)
        except FileNotFoundError:
            # No guidelines generated yet
            return GuidelinesListResponse(
                book_id=book_id,
                total_subtopics=0,
                guidelines=[],
                processed_pages=processed_pages
            )

        # Load all shards (V2 only)
        guidelines = []
        from book_ingestion.models.guideline_models import SubtopicShard

        for topic_entry in index.topics:
            for subtopic_entry in topic_entry.subtopics:
                # Load V2 shard
                shard_key = (
                    f"books/{book_id}/guidelines/topics/{topic_entry.topic_key}/"
                    f"subtopics/{subtopic_entry.subtopic_key}.latest.json"
                )

                try:
                    shard_data = s3_client.download_json(shard_key)
                    shard = SubtopicShard(**shard_data)

                    # V2 response with single guidelines field
                    # Note: status comes from index (subtopic_entry), not shard
                    # because shard.status was removed per GAP-001
                    guidelines.append(GuidelineSubtopicResponse(
                        topic_key=shard.topic_key,
                        topic_title=shard.topic_title,
                        subtopic_key=shard.subtopic_key,
                        subtopic_title=shard.subtopic_title,
                        status=subtopic_entry.status,  # From index, not shard
                        source_page_start=shard.source_page_start,
                        source_page_end=shard.source_page_end,
                        version=shard.version,

                        # V2: Single comprehensive guidelines field
                        guidelines=shard.guidelines
                    ))

                except Exception as e:
                    # Log error but continue
                    logger.error(f"Failed to load shard {shard_key}: {str(e)}")
                    continue

        return GuidelinesListResponse(
            book_id=book_id,
            total_subtopics=len(guidelines),
            guidelines=guidelines,
            processed_pages=processed_pages
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get guidelines: {str(e)}"
        )


@router.get("/books/{book_id}/guidelines/{topic_key}/{subtopic_key}", response_model=GuidelineSubtopicResponse)
def get_guideline(
    book_id: str,
    topic_key: str,
    subtopic_key: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific subtopic guideline.

    Args:
        book_id: Book identifier
        topic_key: Topic key (slugified)
        subtopic_key: Subtopic key (slugified)
        db: Database session

    Returns:
        Subtopic guideline details

    Raises:
        HTTPException: If book or guideline not found
    """
    try:
        # Verify book exists
        book_service = BookService(db)
        book = book_service.get_book(book_id)

        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book not found: {book_id}"
            )

        # Load index to get status (status is tracked in index, not shard per GAP-001)
        s3_client = S3Client()
        from book_ingestion.services.index_management_service import IndexManagementService
        index_mgr = IndexManagementService(s3_client)

        try:
            index = index_mgr.load_index(book_id)
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No guidelines found for book: {book_id}"
            )

        # Find the subtopic entry in index to get status
        subtopic_status = "open"  # default
        for topic_entry in index.topics:
            if topic_entry.topic_key == topic_key:
                for subtopic_entry in topic_entry.subtopics:
                    if subtopic_entry.subtopic_key == subtopic_key:
                        subtopic_status = subtopic_entry.status
                        break
                break

        # Load shard
        shard_key = (
            f"books/{book_id}/guidelines/topics/{topic_key}/"
            f"subtopics/{subtopic_key}.latest.json"
        )

        try:
            from book_ingestion.models.guideline_models import SubtopicShard
            shard_data = s3_client.download_json(shard_key)
            shard = SubtopicShard(**shard_data)

            # V2 response with single guidelines field
            # Status comes from index (not shard) per GAP-001
            return GuidelineSubtopicResponse(
                topic_key=shard.topic_key,
                topic_title=shard.topic_title,
                subtopic_key=shard.subtopic_key,
                subtopic_title=shard.subtopic_title,
                status=subtopic_status,  # From index, not shard
                source_page_start=shard.source_page_start,
                source_page_end=shard.source_page_end,
                version=shard.version,
                guidelines=shard.guidelines
            )

        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Guideline not found: {topic_key}/{subtopic_key}"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get guideline: {str(e)}"
        )


@router.put("/books/{book_id}/guidelines/approve")
async def approve_guidelines(book_id: str, db: Session = Depends(get_db)):
    """
    Approve all final guidelines and sync to database.

    Args:
        book_id: Book identifier
        db: Database session

    Returns:
        Number of guidelines synced

    Raises:
        HTTPException: If book not found or sync fails
    """
    try:
        # Verify book exists
        book_service = BookService(db)
        book = book_service.get_book(book_id)

        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book not found: {book_id}"
            )

        # Load guidelines index
        s3_client = S3Client()
        from book_ingestion.services.index_management_service import IndexManagementService
        from book_ingestion.services.db_sync_service import DBSyncService
        from book_ingestion.models.guideline_models import SubtopicShard

        index_mgr = IndexManagementService(s3_client)
        db_sync = DBSyncService(db)

        try:
            index = index_mgr.load_index(book_id)
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No guidelines found for book: {book_id}"
            )

        # STEP 1: Approve all non-final guidelines (change status to "final" in index)
        # Note: Status is tracked in the index only (per GAP-001), not in shards
        approved_count = 0
        for topic_entry in index.topics:
            for subtopic_entry in topic_entry.subtopics:
                try:
                    # Check if already final (status is in index, not shard)
                    if subtopic_entry.status != "final":
                        # Update index status to "final"
                        index = index_mgr.update_subtopic_status(
                            index=index,
                            topic_key=topic_entry.topic_key,
                            subtopic_key=subtopic_entry.subtopic_key,
                            new_status="final"
                        )
                        approved_count += 1
                        logger.info(
                            f"Approved {topic_entry.topic_key}/{subtopic_entry.subtopic_key}"
                        )

                except Exception as e:
                    logger.error(
                        f"Failed to approve {topic_entry.topic_key}/{subtopic_entry.subtopic_key}: {str(e)}"
                    )
                    # Continue with next subtopic

        # Save updated index (always save if we made changes OR if index was out of sync)
        index_mgr.save_index(index, create_snapshot=True)

        # STEP 2: Sync all final shards to database
        synced_count = 0

        for topic_entry in index.topics:
            for subtopic_entry in topic_entry.subtopics:
                if subtopic_entry.status == "final":
                    # Load shard
                    shard_key = (
                        f"books/{book_id}/guidelines/topics/{topic_entry.topic_key}/"
                        f"subtopics/{subtopic_entry.subtopic_key}.latest.json"
                    )

                    try:
                        shard_data = s3_client.download_json(shard_key)
                        shard = SubtopicShard(**shard_data)

                        # Sync to database
                        guideline_id = db_sync.sync_shard(
                            shard=shard,
                            book_id=book_id,
                            grade=book.grade,
                            subject=book.subject,
                            board=book.board,
                            country=book.country
                        )

                        logger.info(f"Successfully synced guideline {guideline_id}: {topic_entry.topic_key}/{subtopic_entry.subtopic_key}")
                        synced_count += 1

                    except Exception as e:
                        import traceback
                        logger.error(
                            f"Failed to sync {topic_entry.topic_key}/{subtopic_entry.subtopic_key}: {str(e)}"
                        )
                        traceback.print_exc()
                        # Continue with next shard

        return {
            "book_id": book_id,
            "status": "approved",
            "approved_count": approved_count,
            "synced_count": synced_count,
            "message": f"Approved {approved_count} guidelines and synced {synced_count} to database"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve guidelines: {str(e)}"
        )


@router.delete("/books/{book_id}/guidelines", status_code=status.HTTP_204_NO_CONTENT)
async def reject_guidelines(book_id: str, db: Session = Depends(get_db)):
    """
    Reject (delete) all generated guidelines to allow regeneration.

    Args:
        book_id: Book identifier
        db: Database session

    Returns:
        No content

    Raises:
        HTTPException: If book not found
    """
    try:
        # Verify book exists
        book_service = BookService(db)
        book = book_service.get_book(book_id)

        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book not found: {book_id}"
            )

        # Delete guidelines directory from S3
        s3_client = S3Client()
        guidelines_prefix = f"books/{book_id}/guidelines/"

        try:
            # Delete all files under guidelines/ prefix
            # Note: This is a simplified implementation
            # A production version should use s3_client.delete_prefix()
            logger.info(f"Deleting guidelines for book {book_id} (prefix: {guidelines_prefix})")
            # TODO: Implement s3_client.delete_prefix() method
            # For now, just log the action

        except Exception as e:
            logger.error(f"Failed to delete guidelines: {str(e)}")

        return None

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reject guidelines: {str(e)}"
        )


# ===== Job Status Polling Endpoints =====

class JobStatusResponse(BaseModel):
    """
    Response for job status polling.

    Contract (must stay in sync with frontend JobStatus type):
    - job_type: one of 'extraction', 'finalization', 'ocr_batch'
    - status: one of 'pending', 'running', 'completed', 'failed'
    - completed_items / failed_items: always integers (0 when null in DB)
    - progress_detail: JSON string with shape {"page_errors": {...}, "stats": {...}}
    - error_message: set whenever status == 'failed'; null otherwise
    - completed_at: set whenever status in ('completed', 'failed'); null otherwise
    """
    job_id: str
    book_id: str
    job_type: Literal['extraction', 'finalization', 'ocr_batch']
    status: Literal['pending', 'running', 'completed', 'failed']
    total_items: Optional[int] = None
    completed_items: int = 0
    failed_items: int = 0
    current_item: Optional[int] = None
    last_completed_item: Optional[int] = None
    progress_detail: Optional[str] = None
    heartbeat_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


@router.get("/books/{book_id}/jobs/latest")
def get_latest_job(
    book_id: str,
    job_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Get the latest job for a book. Used by frontend to:
    - Detect if a job is running when page loads
    - Poll for progress during active jobs
    - Show failure details for resume
    """
    from book_ingestion.services.job_lock_service import JobLockService

    job_lock = JobLockService(db)
    result = job_lock.get_latest_job(book_id, job_type)
    if not result:
        return None
    return JobStatusResponse(**result)


@router.get("/books/{book_id}/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    book_id: str,
    job_id: str,
    db: Session = Depends(get_db),
):
    """Get specific job status."""
    from book_ingestion.services.job_lock_service import JobLockService

    job_lock = JobLockService(db)
    result = job_lock.get_job(job_id)
    if not result or result["book_id"] != book_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(**result)


# ===== Bulk Upload Endpoints =====

MAX_BULK_UPLOAD_FILES = 200


class BulkUploadResponse(BaseModel):
    """Response from bulk page upload."""
    job_id: str
    pages_uploaded: List[int]
    total_pages: int
    status: str
    message: str


@router.post("/books/{book_id}/pages/bulk", response_model=BulkUploadResponse)
async def bulk_upload_pages(
    book_id: str,
    images: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload multiple page images at once.
    Images are streamed to S3 as raw files (no conversion in request path).
    Image conversion + OCR runs in the background.

    Ordering guarantee: lock is acquired BEFORE any S3 writes.
    If the lock fails (409), no side effects have occurred.
    """
    from book_ingestion.services.job_lock_service import JobLockService, JobLockError
    from book_ingestion.services.background_task_runner import run_in_background
    from book_ingestion.services.page_service import PageService, run_bulk_ocr_background

    try:
        # Validate book exists
        book_service = BookService(db)
        book = book_service.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail=f"Book not found: {book_id}")

        if not images:
            raise HTTPException(status_code=400, detail="No images provided")

        if len(images) > MAX_BULK_UPLOAD_FILES:
            raise HTTPException(
                status_code=400,
                detail=f"Max {MAX_BULK_UPLOAD_FILES} files per upload"
            )

        page_service = PageService(db)

        # Lightweight validation only (metadata, not content)
        for img in images:
            page_service._validate_image_metadata(img.filename, img.size)

        # Acquire job lock BEFORE any S3 writes.
        # If another job is running, we fail fast with 409 — no orphaned S3 files.
        job_lock = JobLockService(db)
        try:
            job_id = job_lock.acquire_lock(
                book_id, job_type="ocr_batch", total_items=len(images)
            )
        except JobLockError as e:
            raise HTTPException(status_code=409, detail=str(e))

        # Sort files by filename for consistent page ordering
        sorted_images = sorted(images, key=lambda f: f.filename or "")

        # Stream raw files to S3 one at a time (no conversion, no OCR).
        # Lock is already held, so these writes are associated with a tracked job.
        page_numbers = []
        try:
            for img in sorted_images:
                data = await img.read()
                page_num = page_service.upload_raw_image(book_id, data, img.filename)
                page_numbers.append(page_num)
                del data  # Free memory immediately
        except Exception as upload_err:
            # S3 upload failed mid-batch: mark job as failed so it doesn't stay pending
            job_lock.release_lock(job_id, status='failed', error=f"Upload failed: {upload_err}")
            raise

        # Update job with actual page count (may differ if some uploads were skipped)
        # Now launch background thread for conversion + OCR
        run_in_background(
            run_bulk_ocr_background,
            job_id=job_id,
            book_id=book_id,
            page_numbers=page_numbers,
        )

        return BulkUploadResponse(
            job_id=job_id,
            pages_uploaded=page_numbers,
            total_pages=len(page_numbers),
            status="processing",
            message=f"Uploaded {len(page_numbers)} raw images. Conversion + OCR processing in background.",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk upload pages: {str(e)}"
        )


@router.post("/books/{book_id}/pages/{page_num}/retry-ocr")
def retry_page_ocr(
    book_id: str,
    page_num: int,
    db: Session = Depends(get_db),
):
    """
    Retry OCR for a single page that previously failed.
    Runs synchronously since it's a single page (~10s).
    """
    from book_ingestion.services.page_service import PageService

    try:
        service = PageService(db)
        result = service.retry_page_ocr(book_id, page_num)
        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OCR retry failed: {str(e)}"
        )
