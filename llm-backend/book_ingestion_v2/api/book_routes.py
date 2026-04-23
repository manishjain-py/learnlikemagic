"""API routes for V2 book management."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db

logger = logging.getLogger(__name__)
from book_ingestion_v2.models.schemas import (
    CreateBookV2Request,
    BookV2Response,
    BookV2ListResponse,
    BookV2DetailResponse,
)
from book_ingestion_v2.services.book_v2_service import BookV2Service

router = APIRouter(prefix="/admin/v2/books", tags=["Book Ingestion V2"])


@router.post("", response_model=BookV2Response, status_code=status.HTTP_201_CREATED)
def create_book(request: CreateBookV2Request, db: Session = Depends(get_db)):
    """Create a new V2 book with pipeline_version=2."""
    try:
        service = BookV2Service(db)
        return service.create_book(request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("book route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("", response_model=BookV2ListResponse)
def list_books(
    country: str = Query(None),
    board: str = Query(None),
    grade: int = Query(None),
    subject: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List V2 books with optional filters."""
    try:
        service = BookV2Service(db)
        return service.list_books(
            country=country, board=board, grade=grade, subject=subject,
            limit=limit, offset=offset,
        )
    except Exception:
        logger.exception("book route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/{book_id}", response_model=BookV2DetailResponse)
def get_book(book_id: str, db: Session = Depends(get_db)):
    """Get V2 book with chapters summary."""
    try:
        service = BookV2Service(db)
        result = service.get_book_detail(book_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"V2 book not found: {book_id}",
            )
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("book route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_book(book_id: str, db: Session = Depends(get_db)):
    """Delete V2 book, all chapters, and all S3 data."""
    try:
        service = BookV2Service(db)
        success = service.delete_book(book_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"V2 book not found: {book_id}",
            )
    except HTTPException:
        raise
    except Exception:
        logger.exception("book route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
