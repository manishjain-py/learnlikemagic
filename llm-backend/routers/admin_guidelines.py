"""
Admin API endpoints for reviewing and managing Phase 6 extracted guidelines.

These endpoints allow the admin UI to:
1. List all books with guideline extraction status
2. View extracted topics and subtopics for a book
3. Retrieve complete guideline details for a subtopic
4. Review and approve/reject guidelines
5. Edit and update guidelines
"""

from fastapi import APIRouter, HTTPException, Depends, Query
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
            subtopics_approved = sum(
                1 for topic in index.topics
                for subtopic in topic.subtopics
                if subtopic.status == "final"
            )
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


@router.get("/books/{book_id}/subtopics/{subtopic_key}", response_model=SubtopicGuideline)
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
    return SubtopicGuideline(
        book_id=shard.book_id,
        topic_key=shard.topic_key,
        topic_title=shard.topic_title,
        subtopic_key=shard.subtopic_key,
        subtopic_title=shard.subtopic_title,
        source_page_start=shard.source_page_start,
        source_page_end=shard.source_page_end,
        source_pages=shard.source_pages,
        page_range=f"{shard.source_page_start}-{shard.source_page_end}",
        status=shard.status,
        confidence=shard.confidence,
        version=shard.version,
        last_updated=datetime.utcnow(),  # Use current time as shard doesn't track this
        teaching_description=shard.teaching_description,
        objectives=to_list(shard.objectives),
        examples=to_list(shard.examples),
        misconceptions=to_list(shard.misconceptions),
        assessments=to_list(shard.assessments),
        evidence_summary=shard.evidence_summary
    )


@router.put("/books/{book_id}/subtopics/{subtopic_key}")
async def update_subtopic_guideline(
    book_id: str,
    subtopic_key: str,
    topic_key: str = Query(..., description="Topic key for the subtopic"),
    update: GuidelineUpdateRequest = ...,
    db: Session = Depends(get_db)
):
    """
    Update a subtopic guideline.

    Allows editing of:
    - Teaching description
    - Learning objectives
    - Examples
    - Misconceptions
    - Assessment questions
    - Status
    """
    # Verify book exists
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Load shard from S3
    s3 = S3Client()
    shard_key = (
        f"books/{book_id}/guidelines/topics/{topic_key}/subtopics/"
        f"{subtopic_key}.latest.json"
    )

    try:
        shard_data = s3.download_json(shard_key)
        shard = SubtopicShard(**shard_data)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Subtopic guideline not found: {str(e)}"
        )

    # Apply updates
    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if hasattr(shard, field):
            setattr(shard, field, value)

    # Increment version and update timestamp
    shard.version += 1
    shard.last_updated = datetime.utcnow()

    # Save back to S3
    try:
        s3.upload_json(data=shard.model_dump(), s3_key=shard_key)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save updated guideline: {str(e)}"
        )

    return {
        "message": "Guideline updated successfully",
        "version": shard.version,
        "updated_at": shard.last_updated
    }


@router.post("/books/{book_id}/subtopics/{subtopic_key}/approve")
async def approve_subtopic_guideline(
    book_id: str,
    subtopic_key: str,
    topic_key: str = Query(..., description="Topic key for the subtopic"),
    approval: ApprovalRequest = ...,
    db: Session = Depends(get_db)
):
    """
    Approve or reject a subtopic guideline.

    When approved:
    - Status changes to "final"
    - Guideline becomes visible to teachers
    - Can be synced to database

    When rejected:
    - Status changes to "needs_review"
    - Reviewer notes are stored
    """
    # Verify book exists
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Load shard from S3
    s3 = S3Client()
    shard_key = (
        f"books/{book_id}/guidelines/topics/{topic_key}/subtopics/"
        f"{subtopic_key}.latest.json"
    )

    try:
        shard_data = s3.download_json(shard_key)
        shard = SubtopicShard(**shard_data)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Subtopic guideline not found: {str(e)}"
        )

    # Update status based on approval
    old_status = shard.status
    if approval.approved:
        shard.status = "final"
    else:
        shard.status = "needs_review"

    # Store reviewer notes in evidence_summary if provided
    if approval.reviewer_notes:
        if shard.evidence_summary:
            shard.evidence_summary += f"\n\nReviewer Notes: {approval.reviewer_notes}"
        else:
            shard.evidence_summary = f"Reviewer Notes: {approval.reviewer_notes}"

    # Increment version and update timestamp
    shard.version += 1
    shard.last_updated = datetime.utcnow()

    # Save back to S3
    try:
        s3.upload_json(data=shard.model_dump(), s3_key=shard_key)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save approval: {str(e)}"
        )

    # Update index to reflect new status
    from features.book_ingestion.services.index_management_service import IndexManagementService
    index_manager = IndexManagementService(s3)
    try:
        index = index_manager.get_or_create_index(book_id)
        index = index_manager.update_subtopic_status(
            index=index,
            topic_key=topic_key,
            subtopic_key=subtopic_key,
            status=shard.status
        )
        index_manager.save_index(index, create_snapshot=True)
    except Exception as e:
        # Log but don't fail - shard is already updated
        print(f"Warning: Failed to update index: {e}")

    return {
        "message": f"Guideline {'approved' if approval.approved else 'rejected'}",
        "status": shard.status,
        "previous_status": old_status,
        "version": shard.version,
        "updated_at": shard.last_updated
    }


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

    Only syncs guidelines with status="final" by default.
    """
    # Verify book exists
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Use DatabaseSyncService to sync
    from features.book_ingestion.services.database_sync_service import DatabaseSyncService

    s3 = S3Client()
    sync_service = DatabaseSyncService(db, s3)

    try:
        synced_count = sync_service.sync_book_guidelines(
            book_id=book_id,
            status_filter=status_filter
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync guidelines: {str(e)}"
        )

    return {
        "message": f"Successfully synced {synced_count} guidelines to database",
        "book_id": book_id,
        "synced_count": synced_count
    }
