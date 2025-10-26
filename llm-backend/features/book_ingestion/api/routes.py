"""
Admin API routes for book ingestion.

Provides endpoints for book CRUD, page upload, and guideline management.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from features.book_ingestion.models.schemas import (
    CreateBookRequest,
    BookResponse,
    BookListResponse,
    BookDetailResponse,
    UpdateBookStatusRequest
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
    status: Optional[str] = None,
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
        status: Filter by status
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
            status=status,
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


@router.put("/books/{book_id}/status", response_model=BookResponse)
def update_book_status(
    book_id: str,
    request: UpdateBookStatusRequest,
    db: Session = Depends(get_db)
):
    """
    Update book status.

    Args:
        book_id: Book identifier
        request: Status update request
        db: Database session

    Returns:
        Updated book response

    Raises:
        HTTPException: If book not found or status transition invalid
    """
    try:
        service = BookService(db)
        book = service.update_book_status(book_id, request.status)

        if not book:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book not found: {book_id}"
            )

        return book
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update book status: {str(e)}"
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


# ===== Guideline Management Endpoints (placeholder for Phase 6) =====

# Will be implemented in Phase 6:
# - POST /admin/books/{book_id}/generate-guidelines - Trigger generation
# - GET /admin/books/{book_id}/guidelines - Get generated guideline
# - PUT /admin/books/{book_id}/guidelines/approve - Approve guideline
# - PUT /admin/books/{book_id}/guidelines/reject - Reject guideline
