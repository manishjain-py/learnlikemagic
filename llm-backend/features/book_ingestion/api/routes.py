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
from features.book_ingestion.models.schemas import (
    CreateBookRequest,
    BookResponse,
    BookListResponse,
    BookDetailResponse

)
from features.book_ingestion.services.book_service import BookService


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
from features.book_ingestion.models.schemas import PageUploadResponse, PageApproveResponse
from features.book_ingestion.services.page_service import PageService


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

from features.book_ingestion.services.guideline_extraction_orchestrator import GuidelineExtractionOrchestrator

from features.book_ingestion.utils.s3_client import S3Client
from openai import OpenAI
from pydantic import BaseModel
from typing import List


class GenerateGuidelinesRequest(BaseModel):
    """Request to generate guidelines for a book"""
    start_page: Optional[int] = 1
    end_page: Optional[int] = None
    auto_sync_to_db: bool = False


class GenerateGuidelinesResponse(BaseModel):
    """Response from guideline generation"""
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


@router.post("/books/{book_id}/generate-guidelines", response_model=GenerateGuidelinesResponse)
async def generate_guidelines(
    book_id: str,
    request: GenerateGuidelinesRequest,
    db: Session = Depends(get_db)
):
    """
    Generate teaching guidelines for a book.

    This triggers the Phase 6 guideline extraction pipeline:
    1. Process each page (minisummary, boundary detection, facts extraction)
    2. Merge facts into subtopic shards
    3. Detect stable subtopics and generate teaching descriptions
    4. Run quality validation
    5. Optionally sync to database

    Args:
        book_id: Book identifier
        request: Generation request with options
        db: Database session

    Returns:
        Generation results with statistics

    Raises:
        HTTPException: If book not found or generation fails
    """
    try:
        # Get book metadata
        book_service = BookService(db)
        book = book_service.get_book(book_id)

        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book not found: {book_id}"
            )

        # Load total_pages from S3 metadata (page count is stored in S3, not DB)
        s3_client = S3Client()
        try:
            metadata_key = f"books/{book_id}/metadata.json"
            metadata = s3_client.download_json(metadata_key)
            total_pages = metadata.get("total_pages", 0)
        except Exception as e:
            # If metadata.json doesn't exist yet (no pages uploaded), default to 0
            total_pages = 0

        # Build book metadata
        book_metadata = {
            "grade": book.grade,
            "subject": book.subject,
            "board": book.board,
            "total_pages": total_pages
        }

        # Initialize orchestrator
        openai_client = OpenAI()
        orchestrator = GuidelineExtractionOrchestrator(
            s3_client=s3_client,
            openai_client=openai_client,
            db_session=db
        )

        # Extract guidelines
        stats = orchestrator.extract_guidelines_for_book(
            book_id=book_id,
            book_metadata=book_metadata,
            start_page=request.start_page,
            end_page=request.end_page,
            auto_sync_to_db=request.auto_sync_to_db
        )

        return GenerateGuidelinesResponse(
            book_id=book_id,
            status="completed",
            pages_processed=stats["pages_processed"],
            subtopics_created=stats["subtopics_created"],
            subtopics_merged=stats.get("subtopics_merged", 0),
            subtopics_finalized=stats["subtopics_finalized"],
            duplicates_merged=stats.get("duplicates_merged", 0),
            errors=stats["errors"],
            warnings=stats.get("warnings", [])
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate guidelines: {str(e)}"
        )


class FinalizeRequest(BaseModel):
    """Request to finalize and consolidate guidelines"""
    auto_sync_to_db: bool = False


class FinalizeResponse(BaseModel):
    """Response from finalization"""
    book_id: str
    status: str
    subtopics_finalized: int
    subtopics_renamed: int
    duplicates_merged: int
    message: str


@router.post("/books/{book_id}/finalize", response_model=FinalizeResponse)
async def finalize_guidelines(
    book_id: str,
    request: FinalizeRequest,
    db: Session = Depends(get_db)
):
    """
    Finalize and consolidate guidelines for a book.

    This triggers the finalization pipeline:
    1. Mark all open/stable subtopics as final
    2. Refine topic/subtopic names using LLM
    3. Run deduplication to merge similar topics
    4. Optionally sync to database

    Args:
        book_id: Book identifier
        request: Finalization request with options
        db: Database session

    Returns:
        Finalization results with statistics

    Raises:
        HTTPException: If book not found or finalization fails
    """
    try:
        # Get book metadata
        book_service = BookService(db)
        book = book_service.get_book(book_id)

        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book not found: {book_id}"
            )

        # Build book metadata
        book_metadata = {
            "grade": book.grade,
            "subject": book.subject,
            "board": book.board,
            "country": book.country
        }

        # Initialize V2 orchestrator
        s3_client = S3Client()
        openai_client = OpenAI()
        orchestrator = GuidelineExtractionOrchestrator(
            s3_client=s3_client,
            openai_client=openai_client,
            db_session=db
        )

        # Run finalization
        result = orchestrator.finalize_book(
            book_id=book_id,
            book_metadata=book_metadata,
            auto_sync_to_db=request.auto_sync_to_db
        )

        return FinalizeResponse(
            book_id=book_id,
            status="completed",
            subtopics_finalized=result.get("subtopics_finalized", 0),
            subtopics_renamed=result.get("subtopics_renamed", 0),
            duplicates_merged=result.get("duplicates_merged", 0),
            message=f"Successfully finalized {result.get('subtopics_finalized', 0)} subtopics, "
                   f"refined {result.get('subtopics_renamed', 0)} names, "
                   f"merged {result.get('duplicates_merged', 0)} duplicates"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to finalize guidelines: {str(e)}"
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
        from features.book_ingestion.services.index_management_service import IndexManagementService

        index_mgr = IndexManagementService(s3_client)

        try:
            index = index_mgr.load_index(book_id)
        except FileNotFoundError:
            # No guidelines generated yet
            return GuidelinesListResponse(
                book_id=book_id,
                total_subtopics=0,
                guidelines=[]
            )

        # Load all shards (V2 only)
        guidelines = []
        from features.book_ingestion.models.guideline_models import SubtopicShard

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
                    import logging
                    logging.error(f"Failed to load shard {shard_key}: {str(e)}")
                    continue

        return GuidelinesListResponse(
            book_id=book_id,
            total_subtopics=len(guidelines),
            guidelines=guidelines
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

        # Load shard
        s3_client = S3Client()
        shard_key = (
            f"books/{book_id}/guidelines/topics/{topic_key}/"
            f"subtopics/{subtopic_key}.latest.json"
        )

        try:
            from features.book_ingestion.models.guideline_models import SubtopicShard
            shard_data = s3_client.download_json(shard_key)
            shard = SubtopicShard(**shard_data)

            return GuidelineSubtopicResponse(
                topic_key=shard.topic_key,
                topic_title=shard.topic_title,
                subtopic_key=shard.subtopic_key,
                subtopic_title=shard.subtopic_title,
                status=shard.status,
                source_page_start=shard.source_page_start,
                source_page_end=shard.source_page_end,
                objectives=shard.objectives,
                examples=shard.examples,
                misconceptions=shard.misconceptions,
                assessments=[
                    {
                        "level": a.level,
                        "prompt": a.prompt,
                        "answer": a.answer
                    }
                    for a in shard.assessments
                ],
                teaching_description=shard.teaching_description,
                description=shard.description,
                evidence_summary=shard.evidence_summary,
                confidence=shard.confidence,
                quality_score=None,  # Quality score not yet implemented in Phase 6
                version=shard.version
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
        from features.book_ingestion.services.index_management_service import IndexManagementService
        from features.book_ingestion.services.db_sync_service import DBSyncService
        from features.book_ingestion.models.guideline_models import SubtopicShard

        index_mgr = IndexManagementService(s3_client)
        db_sync = DBSyncService(db)

        try:
            index = index_mgr.load_index(book_id)
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No guidelines found for book: {book_id}"
            )

        # STEP 1: Approve all non-final guidelines (change status to "final")
        approved_count = 0
        for topic_entry in index.topics:
            for subtopic_entry in topic_entry.subtopics:
                # Load shard to check its ACTUAL status (index might be out of sync)
                shard_key = (
                    f"books/{book_id}/guidelines/topics/{topic_entry.topic_key}/"
                    f"subtopics/{subtopic_entry.subtopic_key}.latest.json"
                )

                try:
                    shard_data = s3_client.download_json(shard_key)
                    shard = SubtopicShard(**shard_data)

                    # Approve if not already final
                    if shard.status != "final":
                        shard.status = "final"
                        shard.version += 1
                        s3_client.upload_json(data=shard.model_dump(), s3_key=shard_key)

                        # Update index to match
                        index = index_mgr.update_subtopic_status(
                            index=index,
                            topic_key=topic_entry.topic_key,
                            subtopic_key=subtopic_entry.subtopic_key,
                            new_status="final"
                        )

                        approved_count += 1
                    elif subtopic_entry.status != "final":
                        # Shard is final but index isn't - sync the index
                        index = index_mgr.update_subtopic_status(
                            index=index,
                            topic_key=topic_entry.topic_key,
                            subtopic_key=subtopic_entry.subtopic_key,
                            new_status="final"
                        )

                except Exception as e:
                    import logging
                    logging.error(
                        f"Failed to approve {topic_entry.topic_key}/{subtopic_entry.subtopic_key}: {str(e)}"
                    )
                    # Continue with next shard

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
                        import logging
                        import traceback
                        logging.error(
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
            import logging
            logging.info(f"Deleting guidelines for book {book_id} (prefix: {guidelines_prefix})")
            # TODO: Implement s3_client.delete_prefix() method
            # For now, just log the action

        except Exception as e:
            import logging
            logging.error(f"Failed to delete guidelines: {str(e)}")

        return None

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reject guidelines: {str(e)}"
        )
