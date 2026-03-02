"""
Chapter page service — page upload with inline OCR, completeness tracking.

Pages are scoped to a chapter via TOC range. OCR runs inline on every upload.
When all pages in range are uploaded and OCR'd, chapter transitions to upload_complete.
"""
import uuid
import logging
import tempfile
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from PIL import Image
import io

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from book_ingestion.utils.s3_client import get_s3_client
from book_ingestion.services.ocr_service import get_ocr_service
from shared.services.llm_config_service import LLMConfigService
from book_ingestion_v2.constants import ChapterStatus, OCRStatus, LLM_CONFIG_KEY
from book_ingestion_v2.models.database import ChapterPage, BookChapter
from book_ingestion_v2.models.schemas import PageResponse, PageDetailResponse, ChapterPagesResponse
from book_ingestion_v2.repositories.chapter_repository import ChapterRepository
from book_ingestion_v2.repositories.chapter_page_repository import ChapterPageRepository

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".tiff", ".webp"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


class ChapterPageService:
    """Service for page upload and management within chapter context."""

    def __init__(self, db: Session):
        self.db = db
        self.chapter_repo = ChapterRepository(db)
        self.page_repo = ChapterPageRepository(db)
        self.s3_client = get_s3_client()

        ingestion_config = LLMConfigService(db).get_config(LLM_CONFIG_KEY)
        self.ocr_service = get_ocr_service(model=ingestion_config["model_id"])

    def upload_page(
        self,
        book_id: str,
        chapter_id: str,
        page_number: int,
        image_data: bytes,
        filename: str,
    ) -> PageResponse:
        """
        Upload a single page with inline OCR.

        1. Validate chapter exists and page_number is in range
        2. Convert to PNG, upload to S3
        3. Run OCR inline
        4. Save text to S3, create DB record
        5. Update chapter completeness
        """
        chapter = self.chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise ValueError(f"Chapter not found: {chapter_id}")

        # Validate page number is in chapter range
        if page_number < chapter.start_page or page_number > chapter.end_page:
            raise ValueError(
                f"Page {page_number} is outside chapter range "
                f"({chapter.start_page}-{chapter.end_page})"
            )

        # Check for duplicate
        existing = self.page_repo.get_by_chapter_and_page_number(chapter_id, page_number)
        if existing:
            raise ValueError(
                f"Page {page_number} already exists in chapter {chapter.chapter_number}. "
                f"Delete it first to re-upload."
            )

        # Validate file
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported format: {ext}. Supported: {SUPPORTED_FORMATS}")
        if len(image_data) > MAX_FILE_SIZE:
            raise ValueError(f"File too large: {len(image_data)} bytes (max {MAX_FILE_SIZE})")

        # Build S3 keys
        ch_num = str(chapter.chapter_number).zfill(2)
        s3_base = f"books/{book_id}/chapters/{ch_num}/pages"
        raw_s3_key = f"{s3_base}/raw/{page_number}{ext}"
        png_s3_key = f"{s3_base}/{page_number}.png"
        text_s3_key = f"{s3_base}/{page_number}.txt"

        # Upload raw image to S3
        self.s3_client.upload_bytes(image_data, raw_s3_key)

        # Convert to PNG
        png_data = self._convert_to_png(image_data)
        self.s3_client.upload_bytes(png_data, png_s3_key)

        # Run OCR inline
        ocr_status = OCRStatus.PENDING.value
        ocr_error = None
        ocr_completed_at = None
        ocr_model = None
        tmp_path = None

        try:
            # Write PNG to temp file for OCR service
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(png_data)
                tmp_path = tmp.name

            ocr_text = self.ocr_service.extract_text_from_image(image_path=tmp_path)
            ocr_model = self.ocr_service.model

            # Upload OCR text to S3
            self.s3_client.upload_bytes(ocr_text.encode("utf-8"), text_s3_key)

            ocr_status = OCRStatus.COMPLETED.value
            ocr_completed_at = datetime.utcnow()
            logger.info(f"OCR completed for page {page_number} in chapter {chapter_id}")
        except Exception as e:
            ocr_status = OCRStatus.FAILED.value
            ocr_error = str(e)
            text_s3_key = None
            logger.warning(f"OCR failed for page {page_number}: {e}")
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

        # Create DB record
        page = ChapterPage(
            id=str(uuid.uuid4()),
            book_id=book_id,
            chapter_id=chapter_id,
            page_number=page_number,
            raw_image_s3_key=raw_s3_key,
            image_s3_key=png_s3_key,
            text_s3_key=text_s3_key,
            ocr_status=ocr_status,
            ocr_error=ocr_error,
            ocr_model=ocr_model,
            uploaded_at=datetime.utcnow(),
            ocr_completed_at=ocr_completed_at,
        )
        try:
            page = self.page_repo.create(page)
        except IntegrityError:
            self.db.rollback()
            raise ValueError(
                f"Page {page_number} already exists in chapter {chapter.chapter_number}. "
                f"Delete it first to re-upload."
            )

        # Update chapter completeness
        self._update_chapter_completeness(chapter)

        return self._to_response(page)

    def delete_page(self, book_id: str, chapter_id: str, page_number: int) -> bool:
        """Delete a page and update chapter completeness."""
        page = self.page_repo.get_by_chapter_and_page_number(chapter_id, page_number)
        if not page or page.book_id != book_id:
            return False

        # Delete S3 files
        for key in [page.raw_image_s3_key, page.image_s3_key, page.text_s3_key]:
            if key:
                try:
                    self.s3_client.delete_file(key)
                except Exception as e:
                    logger.warning(f"Failed to delete S3 file {key}: {e}")

        self.page_repo.delete(page.id)

        # Update chapter completeness
        chapter = self.chapter_repo.get_by_id(chapter_id)
        if chapter:
            self._update_chapter_completeness(chapter)

        return True

    def retry_ocr(self, book_id: str, chapter_id: str, page_number: int) -> PageResponse:
        """Retry failed OCR for a specific page."""
        page = self.page_repo.get_by_chapter_and_page_number(chapter_id, page_number)
        if not page or page.book_id != book_id:
            raise ValueError(f"Page {page_number} not found in chapter {chapter_id}")

        if page.ocr_status != OCRStatus.FAILED.value:
            raise ValueError(f"Page {page_number} OCR is not in failed state")

        if not page.image_s3_key:
            raise ValueError(f"Page {page_number} has no image to OCR")

        # Download PNG from S3 and retry
        chapter = self.chapter_repo.get_by_id(chapter_id)
        ch_num = str(chapter.chapter_number).zfill(2)
        text_s3_key = f"books/{book_id}/chapters/{ch_num}/pages/{page_number}.txt"
        tmp_path = None

        try:
            png_data = self.s3_client.download_bytes(page.image_s3_key)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(png_data)
                tmp_path = tmp.name

            ocr_text = self.ocr_service.extract_text_from_image(image_path=tmp_path)

            self.s3_client.upload_bytes(text_s3_key, ocr_text.encode("utf-8"))

            page.text_s3_key = text_s3_key
            page.ocr_status = OCRStatus.COMPLETED.value
            page.ocr_error = None
            page.ocr_model = self.ocr_service.model
            page.ocr_completed_at = datetime.utcnow()
            self.page_repo.update(page)

            # Re-check chapter completeness
            self._update_chapter_completeness(chapter)

            logger.info(f"OCR retry succeeded for page {page_number}")
        except Exception as e:
            page.ocr_error = str(e)
            self.page_repo.update(page)
            raise ValueError(f"OCR retry failed: {e}")
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

        return self._to_response(page)

    def get_chapter_pages(self, book_id: str, chapter_id: str) -> ChapterPagesResponse:
        """Get all pages for a chapter with completeness info."""
        chapter = self.chapter_repo.get_by_id(chapter_id)
        if not chapter or chapter.book_id != book_id:
            raise ValueError(f"Chapter not found: {chapter_id}")

        pages = self.page_repo.get_by_chapter_id(chapter_id)

        return ChapterPagesResponse(
            chapter_id=chapter_id,
            total_pages=chapter.total_pages,
            uploaded_count=len(pages),
            pages=[self._to_response(p) for p in pages],
        )

    def get_page(
        self, book_id: str, chapter_id: str, page_number: int
    ) -> Optional[PageResponse]:
        """Get a specific page detail."""
        page = self.page_repo.get_by_chapter_and_page_number(chapter_id, page_number)
        if not page or page.book_id != book_id:
            return None
        return self._to_response(page)

    def get_page_detail(
        self, book_id: str, chapter_id: str, page_number: int
    ) -> Optional[PageDetailResponse]:
        """Get page detail with presigned image URL and OCR text content."""
        page = self.page_repo.get_by_chapter_and_page_number(chapter_id, page_number)
        if not page or page.book_id != book_id:
            return None

        # Generate presigned URL for the image
        image_url = None
        if page.image_s3_key:
            try:
                image_url = self.s3_client.get_presigned_url(page.image_s3_key, expiration=3600)
            except Exception as e:
                logger.warning(f"Failed to generate presigned URL for page {page_number}: {e}")

        # Download OCR text from S3
        ocr_text = None
        if page.text_s3_key and page.ocr_status == OCRStatus.COMPLETED.value:
            try:
                text_bytes = self.s3_client.download_bytes(page.text_s3_key)
                ocr_text = text_bytes.decode("utf-8")
            except Exception as e:
                logger.warning(f"Failed to download OCR text for page {page_number}: {e}")

        return PageDetailResponse(
            id=page.id,
            page_number=page.page_number,
            chapter_id=page.chapter_id,
            image_url=image_url,
            ocr_text=ocr_text,
            ocr_status=page.ocr_status,
            ocr_error=page.ocr_error,
            uploaded_at=page.uploaded_at,
            ocr_completed_at=page.ocr_completed_at,
        )

    def _update_chapter_completeness(self, chapter: BookChapter):
        """Update chapter's uploaded_page_count and status based on current pages."""
        uploaded_count = self.page_repo.count_by_chapter(chapter.id)
        ocr_completed_count = self.page_repo.count_ocr_completed(chapter.id)

        chapter.uploaded_page_count = uploaded_count

        # Determine status
        if uploaded_count == 0:
            chapter.status = ChapterStatus.TOC_DEFINED.value
        elif uploaded_count == chapter.total_pages and ocr_completed_count == chapter.total_pages:
            chapter.status = ChapterStatus.UPLOAD_COMPLETE.value
        else:
            chapter.status = ChapterStatus.UPLOAD_IN_PROGRESS.value

        self.chapter_repo.update(chapter)

    def _convert_to_png(self, image_data: bytes) -> bytes:
        """Convert image to PNG format."""
        img = Image.open(io.BytesIO(image_data))
        if img.mode != "RGB":
            img = img.convert("RGB")
        output = io.BytesIO()
        img.save(output, format="PNG")
        return output.getvalue()

    def _to_response(self, page: ChapterPage) -> PageResponse:
        return PageResponse(
            id=page.id,
            page_number=page.page_number,
            chapter_id=page.chapter_id,
            image_s3_key=page.image_s3_key,
            text_s3_key=page.text_s3_key,
            ocr_status=page.ocr_status,
            ocr_error=page.ocr_error,
            uploaded_at=page.uploaded_at,
            ocr_completed_at=page.ocr_completed_at,
        )
