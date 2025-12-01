"""
Admin API endpoints for reviewing and managing Phase 6 extracted guidelines.

These endpoints allow the admin UI to:
1. List all books with guideline extraction status
2. View extracted topics and subtopics for a book
3. Retrieve complete guideline details for a subtopic
4. Review and approve/reject guidelines
5. Edit and update guidelines
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Body
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

from database import get_db
from models.database import TeachingGuideline
from features.book_ingestion.models.database import Book
from features.book_ingestion.utils.s3_client import S3Client
from features.book_ingestion.models.guideline_models import (
    SubtopicShard,
    GuidelinesIndex,
    PageIndex
)

router = APIRouter(prefix="/admin/guidelines", tags=["Admin - Guidelines"])


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class BookGuidelineStatus(BaseModel):
    """Status of guideline extraction for a book"""
    book_id: str
    title: str
    grade: Optional[int]
    subject: Optional[str]
    total_pages: int
    pages_processed: int
    extraction_status: str = Field(
        description="Status: not_started, in_progress, completed, failed"
    )
    topics_count: int
    subtopics_count: int
    subtopics_approved: int
    last_updated: Optional[datetime]


class TopicSummary(BaseModel):
    """Summary of a topic with its subtopics"""
    topic_key: str
    topic_title: str
    subtopics: List[Dict[str, Any]]  # List of SubtopicIndexEntry


class SubtopicGuideline(BaseModel):
    """Complete guideline for a subtopic"""
    book_id: str
    topic_key: str
    topic_title: str
    subtopic_key: str
    subtopic_title: str

    # Page information
    source_page_start: int
    source_page_end: int
    source_pages: List[int]
    page_range: str

    # Status and metadata
    status: str
    confidence: Optional[float]
    version: int
    last_updated: datetime

    # Educational content
    teaching_description: Optional[str]
    objectives: List[str]
    examples: List[str]
    misconceptions: List[str]
    assessments: List[Dict[str, Any]]

    # Evidence
    evidence_summary: Optional[str]


class GuidelineUpdateRequest(BaseModel):
    """Request to update a guideline"""
    teaching_description: Optional[str] = None
    objectives: Optional[List[str]] = None
    examples: Optional[List[str]] = None
    misconceptions: Optional[List[str]] = None
    assessments: Optional[List[Dict[str, Any]]] = None
    status: Optional[str] = None


class ApprovalRequest(BaseModel):
    """Request to approve/reject a guideline"""
    approved: bool
    reviewer_notes: Optional[str] = None


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/books", response_model=List[BookGuidelineStatus])
async def list_books_with_guidelines(
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by extraction status")
):
    """
    List all books with their guideline extraction status.

    Returns summary information including:
    - Book metadata
    - Extraction progress (pages processed)
    - Number of topics/subtopics extracted
    - Approval status
    """
    s3 = S3Client()

    # Get all books
    query = db.query(Book)
    if status:
        query = query.filter(Book.status == status)

    books = query.all()

    result = []
    for book in books:
        # Try to load guideline index from S3
        topics_count = 0
        subtopics_count = 0
        subtopics_approved = 0
        last_updated = None
        extraction_status = "not_started"

        try:
            index_key = f"books/{book.id}/guidelines/index.json"
            index_data = s3.download_json(index_key)
            index = GuidelinesIndex(**index_data)

            topics_count = len(index.topics)
            subtopics_count = sum(len(topic.subtopics) for topic in index.topics)
            # ISSUE-001: Count approved from DB
            subtopics_approved = db.query(TeachingGuideline).filter(
                TeachingGuideline.book_id == book.id,
                TeachingGuideline.review_status == "APPROVED"
            ).count()
            last_updated = index.last_updated
            extraction_status = "completed" if subtopics_count > 0 else "in_progress"

        except Exception:
            # Index doesn't exist or failed to load
            extraction_status = "not_started"

        # Get page count from page index if available
        total_pages = 0
        pages_processed = 0
        try:
            page_index_key = f"books/{book.id}/guidelines/page_index.json"
            page_index_data = s3.download_json(page_index_key)
            page_index_obj = PageIndex(**page_index_data)
            pages_processed = len(page_index_obj.pages)
            total_pages = pages_processed  # Assume all uploaded pages are processed
        except Exception:
            # Page index doesn't exist yet
            pass

        result.append(BookGuidelineStatus(
            book_id=book.id,
            title=book.title or book.id,
            grade=book.grade,
            subject=book.subject,
            total_pages=total_pages,
            pages_processed=pages_processed,
            extraction_status=extraction_status,
            topics_count=topics_count,
            subtopics_count=subtopics_count,
            subtopics_approved=subtopics_approved,
            last_updated=last_updated
        ))

    return result


@router.get("/books/{book_id}/topics", response_model=List[TopicSummary])
async def get_book_topics(
    book_id: str,
    db: Session = Depends(get_db)
):
    """
    Get all topics and subtopics for a book.

    Returns the guideline index showing:
    - All topics extracted
    - Subtopics within each topic
    - Status and page ranges for each subtopic
    """
    # Verify book exists
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Load index from S3
    s3 = S3Client()
    try:
        index_key = f"books/{book_id}/guidelines/index.json"
        index_data = s3.download_json(index_key)
        index = GuidelinesIndex(**index_data)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Guidelines not found for book {book_id}: {str(e)}"
        )

    # Convert to response format
    result = []
    for topic in index.topics:
        result.append(TopicSummary(
            topic_key=topic.topic_key,
            topic_title=topic.topic_title,
            subtopics=[subtopic.model_dump() for subtopic in topic.subtopics]
        ))

    return result


@router.get("/books/{book_id}/subtopics/{subtopic_key}")
async def get_subtopic_guideline(
    book_id: str,
    subtopic_key: str,
    topic_key: str = Query(..., description="Topic key for the subtopic"),
    db: Session = Depends(get_db)
):
    """
    Get complete guideline details for a specific subtopic.

    Returns full educational content including:
    - Teaching description
    - Learning objectives
    - Examples
    - Common misconceptions
    - Assessment questions
    - Page assignments
    - Status and confidence
    """
    # Verify book exists
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Load shard from S3
    s3 = S3Client()
    try:
        shard_key = (
            f"books/{book_id}/guidelines/topics/{topic_key}/subtopics/"
            f"{subtopic_key}.latest.json"
        )
        shard_data = s3.download_json(shard_key)
        shard = SubtopicShard(**shard_data)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Subtopic guideline not found: {str(e)}"
        )

    # Convert lists to simple format (they may be Pydantic models or dicts)
    def to_list(items):
        result = []
        for item in items:
            if hasattr(item, 'model_dump'):
                result.append(item.model_dump())
            elif isinstance(item, dict):
                result.append(item)
            else:
                result.append(str(item))
        return result

    # Convert to response format
    # Convert to response format
    return {
        "book_id": book_id,
        "topic_key": shard.topic_key,
        "topic_title": shard.topic_title,
        "subtopic_key": shard.subtopic_key,
        "subtopic_title": shard.subtopic_title,
        "source_page_start": shard.source_page_start,
        "source_page_end": shard.source_page_end,
        "guidelines": shard.guidelines,  # V2: Single field
        "version": shard.version
    }


@router.put("/books/{book_id}/subtopics/{subtopic_key}")
async def update_subtopic_guideline(
    book_id: str,
    subtopic_key: str,
    topic_key: str = Query(..., description="Topic key for the subtopic"),
    update: GuidelineUpdateRequest = ...,
    db: Session = Depends(get_db)
):
    """
    [DISABLED FOR MVP]
    Manual editing is not supported in MVP.
    To change guidelines, re-run extraction and finalize.
    """
    raise HTTPException(
        status_code=501,  # Not Implemented
        detail="Manual editing disabled for MVP. Use regeneration instead."
    )


# Old approval endpoint removed (BUG-004, ISSUE-003)
# Use POST /{guideline_id}/approve instead


@router.get("/books/{book_id}/page-assignments", response_model=Dict[str, Dict[str, Any]])
async def get_page_assignments(
    book_id: str,
    db: Session = Depends(get_db)
):
    """
    Get page-to-subtopic assignments for a book.

    Returns a mapping of page numbers to their assigned subtopics,
    useful for displaying in a page-by-page review interface.
    """
    # Verify book exists
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Load page index from S3
    s3 = S3Client()
    try:
        page_index_key = f"books/{book_id}/guidelines/page_index.json"
        page_index_data = s3.download_json(page_index_key)
        page_index = PageIndex(**page_index_data)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Page assignments not found: {str(e)}"
        )

    # Convert to simple dict format
    result = {}
    for page_num, assignment in page_index.pages.items():
        result[str(page_num)] = {
            "topic_key": assignment.topic_key,
            "subtopic_key": assignment.subtopic_key,
            "confidence": float(assignment.confidence)
        }

    return result


@router.post("/books/{book_id}/extract")
async def extract_guidelines_for_pages(
    book_id: str,
    start_page: int = Query(..., ge=1, description="First page to process"),
    end_page: int = Query(..., ge=1, description="Last page to process"),
    db: Session = Depends(get_db)
):
    """
    Run guideline extraction on a specific page range.

    - Updates the SAME S3 topic/subtopic map (incremental)
    - Can be run multiple times with different ranges
    - Does NOT sync to DB (use finalize-and-sync for that)
    """
    # Validate book exists
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(404, "Book not found")

    # Check for active job
    from features.book_ingestion.services.job_lock_service import JobLockService, JobLockError
    job_service = JobLockService(db)
    try:
        job_id = job_service.acquire_lock(book_id, "extraction")
    except JobLockError as e:
        raise HTTPException(409, str(e))

    try:
        # Initialize orchestrator
        from features.book_ingestion.services.guideline_extraction_orchestrator import GuidelineExtractionOrchestrator
        s3 = S3Client()
        orchestrator = GuidelineExtractionOrchestrator(
            s3_client=s3,
            db_session=db
        )

        # Get page count from S3 metadata
        total_pages = 100 # Default fallback
        try:
            page_index_key = f"books/{book_id}/guidelines/page_index.json"
            page_index_data = s3.download_json(page_index_key)
            page_index_obj = PageIndex(**page_index_data)
            total_pages = len(page_index_obj.pages)
        except Exception:
            pass

        book_metadata = {
            "grade": book.grade,
            "subject": book.subject,
            "board": book.board,
            "total_pages": total_pages
        }

        # Run extraction
        result = orchestrator.extract_guidelines_for_book(
            book_id=book_id,
            book_metadata=book_metadata,
            start_page=start_page,
            end_page=end_page,
            auto_sync_to_db=False  # Never auto-sync
        )

        job_service.release_lock(job_id, 'completed')

        return {
            "status": "completed",
            "pages_processed": result["pages_processed"],
            "subtopics_created": result["subtopics_created"],
            "subtopics_merged": result["subtopics_merged"],
            "message": "Extraction complete. Run finalize-and-sync to publish."
        }

    except Exception as e:
        job_service.release_lock(job_id, 'failed', str(e))
        raise HTTPException(500, f"Extraction failed: {e}")


@router.post("/books/{book_id}/finalize")
async def finalize_book_guidelines(
    book_id: str,
    auto_sync: bool = Query(False, description="Auto-sync to DB after finalization"),
    db: Session = Depends(get_db)
):
    """
    Finalize and consolidate guidelines for a book.
    
    Triggers:
    1. Finalization of all open topics
    2. Deduplication and merging
    3. Optional sync to database
    """
    # Verify book exists
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Initialize orchestrator
    from features.book_ingestion.services.guideline_extraction_orchestrator import GuidelineExtractionOrchestrator
    s3 = S3Client()
    orchestrator = GuidelineExtractionOrchestrator(
        s3_client=s3,
        db_session=db
    )

    # Check for active job
    from features.book_ingestion.services.job_lock_service import JobLockService, JobLockError
    job_service = JobLockService(db)
    try:
        job_id = job_service.acquire_lock(book_id, "finalization")
    except JobLockError as e:
        raise HTTPException(409, str(e))

    try:
        # Get page count from S3 metadata
        total_pages = 100 # Default fallback
        try:
            page_index_key = f"books/{book_id}/guidelines/page_index.json"
            page_index_data = s3.download_json(page_index_key)
            page_index_obj = PageIndex(**page_index_data)
            total_pages = len(page_index_obj.pages)
        except Exception:
            pass

        book_metadata = {
            "grade": book.grade,
            "subject": book.subject,
            "board": book.board,
            "total_pages": total_pages
        }
        
        result = orchestrator.finalize_book(
            book_id=book_id,
            book_metadata=book_metadata,
            auto_sync_to_db=auto_sync
        )
        
        job_service.release_lock(job_id, 'completed')
        
        return result
        
    except Exception as e:
        job_service.release_lock(job_id, 'failed', str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Finalization failed: {str(e)}"
        )


@router.post("/books/{book_id}/sync-to-database")
async def sync_guidelines_to_database(
    book_id: str,
    status_filter: str = Query("final", description="Only sync guidelines with this status"),
    db: Session = Depends(get_db)
):
    """
    Sync approved guidelines from S3 to the database.

    This makes the guidelines available via the standard API
    for teacher-facing applications.

    CRITICAL: This is a full snapshot sync. It will:
    1. DELETE all existing guidelines for this book from the DB.
    2. INSERT all guidelines from S3 as new rows.
    3. Reset all review statuses to "TO_BE_REVIEWED".
    """
    # Verify book exists
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Use DBSyncService to sync
    from features.book_ingestion.services.db_sync_service import DBSyncService

    sync_service = DBSyncService(db)

    try:
        # Get book metadata
        book_metadata = {
            "grade": book.grade,
            "subject": book.subject,
            "board": book.board,
            "country": "India"
        }

        synced_count = sync_service.sync_book_guidelines(
            book_id=book_id,
            s3_client=S3Client(),
            book_metadata=book_metadata
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync guidelines: {str(e)}"
        )

    return {
        "message": f"Successfully synced {synced_count['synced_count']} guidelines to database (statuses reset)",
        "book_id": book_id,
        "stats": synced_count
    }

@router.get("/review")
async def list_all_guidelines_for_review(
    country: Optional[str] = Query(None, description="Filter by country"),
    board: Optional[str] = Query(None, description="Filter by board"),
    grade: Optional[int] = Query(None, description="Filter by grade"),
    subject: Optional[str] = Query(None, description="Filter by subject"),
    status: Optional[str] = Query(None, description="Filter by review status (TO_BE_REVIEWED, APPROVED)"),
    db: Session = Depends(get_db)
):
    """
    List all teaching guidelines for review with optional filters.
    Returns guidelines with country, board, grade, subject info.
    """
    query = db.query(TeachingGuideline)

    if country:
        query = query.filter(TeachingGuideline.country == country)
    if board:
        query = query.filter(TeachingGuideline.board == board)
    if grade:
        query = query.filter(TeachingGuideline.grade == grade)
    if subject:
        query = query.filter(TeachingGuideline.subject == subject)
    if status:
        query = query.filter(TeachingGuideline.review_status == status)

    # Order by review_status (TO_BE_REVIEWED first), then by subject, topic
    guidelines = query.order_by(
        TeachingGuideline.review_status.desc(),
        TeachingGuideline.subject,
        TeachingGuideline.topic,
        TeachingGuideline.subtopic
    ).all()

    return [
        {
            "id": g.id,
            "country": g.country,
            "board": g.board,
            "grade": g.grade,
            "subject": g.subject,
            "topic": g.topic,
            "subtopic": g.subtopic,
            "guideline": g.guideline,
            "review_status": g.review_status,
            "updated_at": g.updated_at or g.created_at
        }
        for g in guidelines
    ]


@router.get("/review/filters")
async def get_guideline_filter_options(db: Session = Depends(get_db)):
    """
    Get available filter options for guidelines review.
    Returns distinct values for country, board, grade, subject.
    """
    from sqlalchemy import distinct

    countries = [r[0] for r in db.query(distinct(TeachingGuideline.country)).all() if r[0]]
    boards = [r[0] for r in db.query(distinct(TeachingGuideline.board)).all() if r[0]]
    grades = sorted([r[0] for r in db.query(distinct(TeachingGuideline.grade)).all() if r[0]])
    subjects = [r[0] for r in db.query(distinct(TeachingGuideline.subject)).all() if r[0]]

    # Get counts by status
    total = db.query(TeachingGuideline).count()
    pending = db.query(TeachingGuideline).filter(TeachingGuideline.review_status == "TO_BE_REVIEWED").count()
    approved = db.query(TeachingGuideline).filter(TeachingGuideline.review_status == "APPROVED").count()

    return {
        "countries": countries,
        "boards": boards,
        "grades": grades,
        "subjects": subjects,
        "counts": {
            "total": total,
            "pending": pending,
            "approved": approved
        }
    }


@router.get("/books/{book_id}/review")
async def review_book_guidelines(
    book_id: str,
    status: Optional[str] = Query(None, description="Filter by review status (TO_BE_REVIEWED, APPROVED)"),
    db: Session = Depends(get_db)
):
    """
    List guidelines from the database for review (by book).
    """
    query = db.query(TeachingGuideline).filter(TeachingGuideline.book_id == book_id)

    if status:
        query = query.filter(TeachingGuideline.review_status == status)

    guidelines = query.all()

    return [
        {
            "id": g.id,
            "topic": g.topic,
            "subtopic": g.subtopic,
            "guideline": g.guideline,
            "review_status": g.review_status,
            "updated_at": g.created_at
        }
        for g in guidelines
    ]


@router.post("/{guideline_id}/approve")
async def approve_guideline(
    guideline_id: str,
    approved: bool = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    """
    Approve or reject a guideline in the database.
    """
    guideline = db.query(TeachingGuideline).filter(TeachingGuideline.id == guideline_id).first()
    if not guideline:
        raise HTTPException(status_code=404, detail="Guideline not found")
        
    guideline.review_status = "APPROVED" if approved else "TO_BE_REVIEWED"
    db.commit()
    
    return {
        "id": guideline.id,
        "review_status": guideline.review_status
    }
