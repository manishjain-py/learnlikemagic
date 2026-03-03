"""
TOC extraction service — OCR images of TOC pages and extract structured chapters via LLM.

Pure read-only pipeline: no DB writes. Returns extracted chapters for admin review.
"""
import io
import json
import logging
from pathlib import Path
from typing import List, Tuple

from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

from shared.services.ocr_service import OCRService
from shared.utils.s3_client import get_s3_client
from shared.services.llm_service import LLMService
from book_ingestion_v2.models.schemas import TOCEntry

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "toc_extraction.txt"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text()

MAX_IMAGES = 5
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB


class TOCExtractionService:
    """Extracts structured TOC from page images using OCR + LLM."""

    def __init__(self, llm_service: LLMService, ocr_model: str):
        self.llm_service = llm_service
        self.ocr_service = OCRService(model=ocr_model)
        self.s3_client = get_s3_client()

    def extract(
        self,
        book_id: str,
        image_data_list: List[bytes],
        book_title: str,
    ) -> Tuple[List[TOCEntry], str]:
        """
        Extract TOC entries from page images.

        Returns (chapters, raw_ocr_text).
        """
        # 1. Validate inputs
        if not image_data_list:
            raise ValueError("At least one TOC image is required")
        if len(image_data_list) > MAX_IMAGES:
            raise ValueError(f"Maximum {MAX_IMAGES} images allowed")
        for i, data in enumerate(image_data_list):
            if len(data) > MAX_IMAGE_SIZE:
                raise ValueError(f"Image {i + 1} exceeds {MAX_IMAGE_SIZE // (1024 * 1024)}MB limit")

        # 2. Convert all images to PNG (OCR service hardcodes image/png MIME type)
        png_images = []
        for i, raw_bytes in enumerate(image_data_list):
            png_bytes = self._convert_to_png(raw_bytes)
            png_images.append(png_bytes)

        # 3. OCR each image
        ocr_texts = []
        for i, png_bytes in enumerate(png_images):
            logger.info(json.dumps({
                "step": "TOC_OCR",
                "status": "starting",
                "details": {"book_id": book_id, "page": i + 1, "size_bytes": len(png_bytes)},
            }))
            text = self.ocr_service.extract_text_with_retry(
                image_bytes=png_bytes, max_retries=2
            )
            ocr_texts.append(text)
            logger.info(json.dumps({
                "step": "TOC_OCR",
                "status": "complete",
                "details": {"book_id": book_id, "page": i + 1, "text_length": len(text)},
            }))

        # 4. Store PNG images to S3 for audit
        for i, png_bytes in enumerate(png_images):
            s3_key = f"books/{book_id}/toc_pages/page_{i + 1}.png"
            self.s3_client.upload_bytes(png_bytes, s3_key, content_type="image/png")

        # 5. Combine OCR texts
        raw_ocr_text = "\n\n--- Page Break ---\n\n".join(ocr_texts)

        # 6. Build prompt and call LLM
        prompt = _PROMPT_TEMPLATE.format(
            book_title=book_title,
            ocr_text=raw_ocr_text,
        )

        logger.info(json.dumps({
            "step": "TOC_LLM_EXTRACTION",
            "status": "starting",
            "details": {"book_id": book_id, "prompt_length": len(prompt)},
        }))

        result = self.llm_service.call(prompt=prompt, json_mode=True)
        output_text = result.get("output_text", "")

        logger.info(json.dumps({
            "step": "TOC_LLM_EXTRACTION",
            "status": "complete",
            "details": {"book_id": book_id, "output_length": len(output_text)},
        }))

        # 7. Parse JSON response
        # Strip markdown code blocks if present
        cleaned = output_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        parsed = json.loads(cleaned)
        raw_chapters = parsed.get("chapters", [])

        # 8. Build TOCEntry list, re-number sequentially
        chapters = []
        for i, ch in enumerate(raw_chapters):
            chapters.append(TOCEntry(
                chapter_number=i + 1,
                chapter_title=ch["chapter_title"],
                start_page=int(ch["start_page"]),
                end_page=int(ch["end_page"]),
                notes=ch.get("notes") or None,
            ))

        # 9. Store extraction result to S3 for debugging
        extraction_result = {
            "book_id": book_id,
            "book_title": book_title,
            "raw_ocr_text": raw_ocr_text,
            "llm_output": output_text,
            "chapters": [ch.model_dump() for ch in chapters],
        }
        s3_key = f"books/{book_id}/toc_pages/extraction_result.json"
        self.s3_client.upload_json(extraction_result, s3_key)

        logger.info(json.dumps({
            "step": "TOC_EXTRACTION_COMPLETE",
            "status": "complete",
            "details": {"book_id": book_id, "chapter_count": len(chapters)},
        }))

        return chapters, raw_ocr_text

    @staticmethod
    def _convert_to_png(image_data: bytes) -> bytes:
        """Convert image bytes (JPEG, WEBP, etc.) to PNG format."""
        try:
            img = Image.open(io.BytesIO(image_data))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            output = io.BytesIO()
            img.save(output, format="PNG")
            return output.getvalue()
        except Exception as e:
            raise ValueError(
                f"Cannot process image ({len(image_data)} bytes). "
                f"Ensure it is a valid PNG, JPEG, or WEBP file. Error: {e}"
            )
