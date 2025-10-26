"""
Page service - business logic for page upload and management.

Handles page upload, OCR processing, approval workflow, and metadata management.
"""
import logging
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from PIL import Image
import io

from features.book_ingestion.repositories.book_repository import BookRepository
from features.book_ingestion.services.ocr_service import get_ocr_service
from features.book_ingestion.utils.s3_client import get_s3_client
from features.book_ingestion.models.schemas import (
    PageUploadResponse,
    PageApproveResponse,
    PageInfo
)

logger = logging.getLogger(__name__)

# Supported image formats
SUPPORTED_FORMATS = {'.png', '.jpg', '.jpeg', '.tiff', '.webp'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


class PageService:
    """
    Service for page upload and management operations.

    Handles the complete page lifecycle: upload → OCR → review → approval.
    """

    def __init__(self, db):
        """
        Initialize service with database session.

        Args:
            db: SQLAlchemy session
        """
        self.db = db
        self.book_repository = BookRepository(db)
        self.ocr_service = get_ocr_service()
        self.s3_client = get_s3_client()

    def upload_page(
        self,
        book_id: str,
        image_data: bytes,
        filename: str
    ) -> PageUploadResponse:
        """
        Upload a page image, perform OCR, and prepare for review.

        Workflow:
        1. Validate book exists and status allows page upload
        2. Validate image format and size
        3. Determine next page number
        4. Upload image to S3
        5. Perform OCR
        6. Save OCR text to S3
        7. Update metadata.json
        8. Return response with presigned URLs

        Args:
            book_id: Book identifier
            image_data: Image file bytes
            filename: Original filename

        Returns:
            PageUploadResponse with page details and OCR text

        Raises:
            ValueError: If validation fails
            Exception: If upload or OCR fails
        """
        # Validate book
        book = self.book_repository.get_by_id(book_id)
        if not book:
            raise ValueError(f"Book not found: {book_id}")

        if book.status not in ["draft", "uploading_pages"]:
            raise ValueError(
                f"Cannot upload pages for book in status '{book.status}'. "
                "Book must be in 'draft' or 'uploading_pages' status."
            )

        # Validate image
        self._validate_image(image_data, filename)

        try:
            # Load current metadata
            metadata = self._load_metadata(book_id)

            # Determine next page number
            page_num = self._get_next_page_number(metadata)

            # Upload image to S3
            image_s3_key = f"books/{book_id}/{page_num}.png"
            logger.info(f"Uploading page {page_num} for book {book_id}")

            # Convert to PNG for consistency
            image_bytes = self._convert_to_png(image_data)
            self.s3_client.upload_bytes(image_bytes, image_s3_key, content_type="image/png")

            # Perform OCR
            logger.info(f"Performing OCR on page {page_num}")
            ocr_text = self.ocr_service.extract_text_with_retry(image_bytes=image_bytes)

            # Save OCR text to S3
            text_s3_key = f"books/{book_id}/{page_num}.txt"
            self.s3_client.upload_bytes(
                ocr_text.encode('utf-8'),
                text_s3_key,
                content_type="text/plain"
            )

            # Update metadata
            page_info = {
                "page_num": page_num,
                "image_s3_key": image_s3_key,
                "text_s3_key": text_s3_key,
                "status": "pending_review",
                "uploaded_at": datetime.utcnow().isoformat()
            }

            metadata["pages"].append(page_info)
            metadata["total_pages"] = len(metadata["pages"])
            metadata["last_updated"] = datetime.utcnow().isoformat()

            self.s3_client.update_metadata_json(book_id, metadata)

            # Update book status if this is the first page
            if book.status == "draft":
                self.book_repository.update_status(book_id, "uploading_pages")

            # Generate presigned URL for image
            image_url = self.s3_client.get_presigned_url(image_s3_key, expiration=3600)

            logger.info(f"Successfully uploaded page {page_num} for book {book_id}")

            return PageUploadResponse(
                page_num=page_num,
                image_url=image_url,
                ocr_text=ocr_text,
                status="pending_review"
            )

        except Exception as e:
            logger.error(f"Failed to upload page for book {book_id}: {e}", exc_info=True)
            raise

    def approve_page(self, book_id: str, page_num: int) -> PageApproveResponse:
        """
        Approve a page, marking it as ready for guideline generation.

        Args:
            book_id: Book identifier
            page_num: Page number to approve

        Returns:
            PageApproveResponse with updated status

        Raises:
            ValueError: If book or page not found
        """
        # Validate book
        book = self.book_repository.get_by_id(book_id)
        if not book:
            raise ValueError(f"Book not found: {book_id}")

        # Load metadata
        metadata = self._load_metadata(book_id)

        # Find and update page
        page_found = False
        for page in metadata["pages"]:
            if page["page_num"] == page_num:
                if page["status"] == "approved":
                    raise ValueError(f"Page {page_num} is already approved")

                page["status"] = "approved"
                page["approved_at"] = datetime.utcnow().isoformat()
                page_found = True
                break

        if not page_found:
            raise ValueError(f"Page {page_num} not found for book {book_id}")

        # Save updated metadata
        metadata["last_updated"] = datetime.utcnow().isoformat()
        self.s3_client.update_metadata_json(book_id, metadata)

        logger.info(f"Approved page {page_num} for book {book_id}")

        return PageApproveResponse(
            page_num=page_num,
            status="approved"
        )

    def delete_page(self, book_id: str, page_num: int) -> bool:
        """
        Delete a page (reject), allowing re-upload.

        Args:
            book_id: Book identifier
            page_num: Page number to delete

        Returns:
            True if deleted successfully

        Raises:
            ValueError: If book or page not found
        """
        # Validate book
        book = self.book_repository.get_by_id(book_id)
        if not book:
            raise ValueError(f"Book not found: {book_id}")

        # Load metadata
        metadata = self._load_metadata(book_id)

        # Find and remove page
        page_to_remove = None
        for page in metadata["pages"]:
            if page["page_num"] == page_num:
                page_to_remove = page
                break

        if not page_to_remove:
            raise ValueError(f"Page {page_num} not found for book {book_id}")

        # Delete from S3
        self.s3_client.delete_file(page_to_remove["image_s3_key"])
        self.s3_client.delete_file(page_to_remove["text_s3_key"])

        # Remove from metadata
        metadata["pages"] = [p for p in metadata["pages"] if p["page_num"] != page_num]
        metadata["total_pages"] = len(metadata["pages"])
        metadata["last_updated"] = datetime.utcnow().isoformat()

        self.s3_client.update_metadata_json(book_id, metadata)

        logger.info(f"Deleted page {page_num} for book {book_id}")
        return True

    def get_pages(self, book_id: str) -> List[PageInfo]:
        """
        Get all pages for a book.

        Args:
            book_id: Book identifier

        Returns:
            List of PageInfo objects

        Raises:
            ValueError: If book not found
        """
        book = self.book_repository.get_by_id(book_id)
        if not book:
            raise ValueError(f"Book not found: {book_id}")

        metadata = self._load_metadata(book_id)

        return [
            PageInfo(
                page_num=page["page_num"],
                image_s3_key=page["image_s3_key"],
                text_s3_key=page["text_s3_key"],
                status=page["status"],
                approved_at=page.get("approved_at")
            )
            for page in metadata["pages"]
        ]

    def get_page_with_urls(self, book_id: str, page_num: int) -> Dict[str, Any]:
        """
        Get page details with presigned URLs.

        Args:
            book_id: Book identifier
            page_num: Page number

        Returns:
            Dictionary with page info and presigned URLs

        Raises:
            ValueError: If page not found
        """
        metadata = self._load_metadata(book_id)

        for page in metadata["pages"]:
            if page["page_num"] == page_num:
                return {
                    "page_num": page["page_num"],
                    "status": page["status"],
                    "image_url": self.s3_client.get_presigned_url(page["image_s3_key"]),
                    "text_url": self.s3_client.get_presigned_url(page["text_s3_key"]),
                    "ocr_text": self.s3_client.download_bytes(page["text_s3_key"]).decode('utf-8')
                }

        raise ValueError(f"Page {page_num} not found for book {book_id}")

    def _validate_image(self, image_data: bytes, filename: str):
        """
        Validate image format and size.

        Args:
            image_data: Image bytes
            filename: Original filename

        Raises:
            ValueError: If validation fails
        """
        # Check file size
        if len(image_data) > MAX_FILE_SIZE:
            raise ValueError(
                f"Image file too large: {len(image_data)} bytes. "
                f"Maximum size: {MAX_FILE_SIZE} bytes"
            )

        # Check file extension
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported image format: {ext}. "
                f"Supported formats: {', '.join(SUPPORTED_FORMATS)}"
            )

        # Validate image can be opened
        try:
            image = Image.open(io.BytesIO(image_data))
            image.verify()
        except Exception as e:
            raise ValueError(f"Invalid image file: {e}")

    def _convert_to_png(self, image_data: bytes) -> bytes:
        """
        Convert image to PNG format.

        Args:
            image_data: Image bytes in any supported format

        Returns:
            PNG image bytes
        """
        try:
            image = Image.open(io.BytesIO(image_data))

            # Convert to RGB if necessary (for RGBA, LA, etc.)
            if image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')

            # Save as PNG
            output = io.BytesIO()
            image.save(output, format='PNG')
            return output.getvalue()

        except Exception as e:
            logger.error(f"Failed to convert image to PNG: {e}")
            raise ValueError(f"Image conversion failed: {e}")

    def _load_metadata(self, book_id: str) -> Dict[str, Any]:
        """
        Load metadata.json from S3.

        Args:
            book_id: Book identifier

        Returns:
            Metadata dictionary
        """
        try:
            return self.s3_client.download_json(f"books/{book_id}/metadata.json")
        except Exception as e:
            logger.warning(f"Failed to load metadata for {book_id}, using defaults: {e}")
            return {
                "book_id": book_id,
                "pages": [],
                "total_pages": 0,
                "last_updated": datetime.utcnow().isoformat()
            }

    def _get_next_page_number(self, metadata: Dict[str, Any]) -> int:
        """
        Determine the next page number.

        Args:
            metadata: Book metadata

        Returns:
            Next page number
        """
        if not metadata.get("pages"):
            return 1

        # Get highest page number and add 1
        max_page = max(page["page_num"] for page in metadata["pages"])
        return max_page + 1
