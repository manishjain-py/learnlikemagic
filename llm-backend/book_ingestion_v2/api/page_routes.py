"""API routes for V2 chapter page management."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session

from database import get_db
from book_ingestion_v2.models.schemas import PageResponse, PageDetailResponse, ChapterPagesResponse
from book_ingestion_v2.services.chapter_page_service import ChapterPageService

router = APIRouter(
    prefix="/admin/v2/books/{book_id}/chapters/{chapter_id}/pages",
    tags=["Book Ingestion V2 - Pages"],
)


@router.post("", response_model=PageResponse, status_code=status.HTTP_201_CREATED)
async def upload_page(
    book_id: str,
    chapter_id: str,
    page_number: int = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a single page with inline OCR."""
    try:
        image_data = await image.read()
        service = ChapterPageService(db)
        return service.upload_page(
            book_id=book_id,
            chapter_id=chapter_id,
            page_number=page_number,
            image_data=image_data,
            filename=image.filename or "upload.png",
        )
    except ValueError as e:
        detail = str(e)
        code = status.HTTP_409_CONFLICT if "already exists" in detail else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("", response_model=ChapterPagesResponse)
def list_pages(book_id: str, chapter_id: str, db: Session = Depends(get_db)):
    """List all pages for a chapter."""
    try:
        service = ChapterPageService(db)
        return service.get_chapter_pages(book_id, chapter_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/{page_num}", response_model=PageResponse)
def get_page(book_id: str, chapter_id: str, page_num: int, db: Session = Depends(get_db)):
    """Get page detail."""
    try:
        service = ChapterPageService(db)
        result = service.get_page(book_id, chapter_id, page_num)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Page {page_num} not found",
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/{page_num}/detail", response_model=PageDetailResponse)
def get_page_detail(book_id: str, chapter_id: str, page_num: int, db: Session = Depends(get_db)):
    """Get page detail with presigned image URL and OCR text."""
    try:
        service = ChapterPageService(db)
        result = service.get_page_detail(book_id, chapter_id, page_num)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Page {page_num} not found",
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.delete("/{page_num}", status_code=status.HTTP_204_NO_CONTENT)
def delete_page(book_id: str, chapter_id: str, page_num: int, db: Session = Depends(get_db)):
    """Delete a page."""
    try:
        service = ChapterPageService(db)
        success = service.delete_page(book_id, chapter_id, page_num)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Page {page_num} not found",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/{page_num}/retry-ocr", response_model=PageResponse)
def retry_ocr(book_id: str, chapter_id: str, page_num: int, db: Session = Depends(get_db)):
    """Retry failed OCR for a specific page."""
    try:
        service = ChapterPageService(db)
        return service.retry_ocr(book_id, chapter_id, page_num)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
