"""API routes for V2 TOC management."""
import logging
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from database import get_db
from book_ingestion_v2.models.schemas import (
    SaveTOCRequest,
    TOCEntry,
    TOCExtractionResponse,
    TOCResponse,
    ChapterResponse,
)
from book_ingestion_v2.services.toc_service import TOCService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/v2/books", tags=["Book Ingestion V2 - TOC"])


@router.post("/{book_id}/toc/extract", response_model=TOCExtractionResponse)
def extract_toc_from_images(
    book_id: str,
    images: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Extract TOC from uploaded page images using OCR + LLM. Does NOT save to DB."""
    try:
        from shared.repositories.book_repository import BookRepository
        from config import get_settings
        from shared.services.llm_config_service import LLMConfigService
        from shared.services.llm_service import LLMService
        from book_ingestion_v2.constants import LLM_CONFIG_KEY
        from book_ingestion_v2.services.toc_extraction_service import TOCExtractionService

        # Validate book exists
        book = BookRepository(db).get_by_id(book_id)
        if not book:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Book not found: {book_id}")
        if getattr(book, "pipeline_version", 1) != 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Book {book_id} is not a V2 book")

        # Build LLM service
        settings = get_settings()
        config = LLMConfigService(db).get_config(LLM_CONFIG_KEY)
        llm_service = LLMService(
            api_key=settings.openai_api_key,
            provider=config["provider"],
            model_id=config["model_id"],
            reasoning_effort=config["reasoning_effort"],
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        )

        # Read image data
        image_data_list = []
        for img in images:
            img.file.seek(0)
            data = img.file.read()
            logger.info(f"Read image '{img.filename}': {len(data)} bytes, content_type={img.content_type}")
            if not data:
                raise ValueError(f"Empty file uploaded: {img.filename}")
            image_data_list.append(data)

        # Extract TOC
        service = TOCExtractionService(
            llm_service=llm_service,
            ocr_provider=config["provider"],
            ocr_model=config["model_id"],
        )
        chapters, raw_ocr_text = service.extract(
            book_id=book_id,
            image_data_list=image_data_list,
            book_title=book.title,
        )

        return TOCExtractionResponse(chapters=chapters, raw_ocr_text=raw_ocr_text)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"TOC extraction failed for book {book_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"TOC extraction failed: {str(e)}",
        )


@router.post("/{book_id}/toc", response_model=TOCResponse, status_code=status.HTTP_201_CREATED)
def save_toc(book_id: str, request: SaveTOCRequest, db: Session = Depends(get_db)):
    """Create or replace the full TOC for a book."""
    try:
        service = TOCService(db)
        return service.save_toc(book_id, request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("toc route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/{book_id}/toc", response_model=TOCResponse)
def get_toc(book_id: str, db: Session = Depends(get_db)):
    """Get all TOC entries for a book."""
    try:
        service = TOCService(db)
        return service.get_toc(book_id)
    except Exception:
        logger.exception("toc route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.put("/{book_id}/toc/{chapter_id}", response_model=ChapterResponse)
def update_chapter(
    book_id: str, chapter_id: str, entry: TOCEntry, db: Session = Depends(get_db)
):
    """Update a single chapter entry. Blocked if pages are uploaded."""
    try:
        service = TOCService(db)
        return service.update_chapter(book_id, chapter_id, entry)
    except ValueError as e:
        detail = str(e)
        code = status.HTTP_409_CONFLICT if "uploaded pages" in detail else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail)
    except HTTPException:
        raise
    except Exception:
        logger.exception("toc route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.delete("/{book_id}/toc/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chapter(book_id: str, chapter_id: str, db: Session = Depends(get_db)):
    """Delete a single chapter. Blocked if pages are uploaded."""
    try:
        service = TOCService(db)
        success = service.delete_chapter(book_id, chapter_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chapter not found: {chapter_id}",
            )
    except ValueError as e:
        detail = str(e)
        code = status.HTTP_409_CONFLICT if "uploaded pages" in detail else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail)
    except HTTPException:
        raise
    except Exception:
        logger.exception("toc route failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
