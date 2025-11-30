"""
OCR Service using OpenAI Vision API.

Extracts comprehensive text from book page images.
"""
import base64
import logging
from pathlib import Path
from typing import Optional
from openai import OpenAI
from config import get_settings

logger = logging.getLogger(__name__)


class OCRService:
    """
    OCR service using OpenAI Vision API.

    Provides high-quality text extraction from textbook page images,
    including drawings, diagrams, formulas, and captions.
    """

    def __init__(self):
        """
        Initialize OCR service with OpenAI client.

        Uses settings from config (OPENAI_API_KEY).
        """
        settings = get_settings()
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = "gpt-4o-mini"  # Vision-capable model, cost-effective
        self.max_tokens = 4096

        logger.info(f"OCR service initialized with model: {self.model}")

    def encode_image_to_base64(self, image_path: str) -> str:
        """
        Encode image file to base64 string.

        Args:
            image_path: Path to image file

        Returns:
            Base64-encoded image string

        Raises:
            FileNotFoundError: If image file doesn't exist
            IOError: If image cannot be read
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        try:
            with open(image_path, 'rb') as image_file:
                encoded = base64.b64encode(image_file.read()).decode('utf-8')
                logger.debug(f"Encoded image to base64: {image_path}")
                return encoded
        except Exception as e:
            logger.error(f"Failed to encode image: {e}")
            raise IOError(f"Failed to read image file: {e}")

    def encode_bytes_to_base64(self, image_bytes: bytes) -> str:
        """
        Encode image bytes to base64 string.

        Args:
            image_bytes: Image data as bytes

        Returns:
            Base64-encoded image string
        """
        return base64.b64encode(image_bytes).decode('utf-8')

    def extract_text_from_image(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None
    ) -> str:
        """
        Extract complete text from textbook page image using OpenAI Vision API.

        Extracts all text, drawings, images, formulas, captions, and visual elements
        from a book page.

        Args:
            image_path: Path to image file (provide either this or image_bytes)
            image_bytes: Image data as bytes (provide either this or image_path)

        Returns:
            Complete interpretation of the book page as text

        Raises:
            ValueError: If neither image_path nor image_bytes provided
            Exception: If OCR fails
        """
        if not image_path and not image_bytes:
            raise ValueError("Either image_path or image_bytes must be provided")

        try:
            import time
            import json
            start_time = time.time()

            # Encode image to base64
            if image_path:
                base64_image = self.encode_image_to_base64(image_path)
            else:
                base64_image = self.encode_bytes_to_base64(image_bytes)

            logger.info(json.dumps({
                "step": "OCR",
                "status": "starting",
                "input": {"model": self.model, "image_b64_size": len(base64_image)}
            }))

            # Detailed interpretation prompt
            prompt_text = """I have a book page image that I need you to interpret completely.

Please read this image and give me each and everything that's present in this book page image.
Give the complete interpretation in form of text - even the drawings and any images in this book page.

Please provide:
- All titles and headings
- All body text and paragraphs
- Descriptions of all images, diagrams, and illustrations
- Labels and captions
- Any equations, formulas, or special formatting
- Page numbers and footers
- Any other visual elements

Format the output clearly with appropriate structure and formatting."""

            # Create the API request
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        },
                    ],
                }],
                max_tokens=self.max_tokens
            )

            # Extract text from response
            extracted_text = response.choices[0].message.content
            
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(json.dumps({
                "step": "OCR",
                "status": "complete",
                "output": {"chars_extracted": len(extracted_text)},
                "duration_ms": duration_ms
            }))

            return extracted_text

        except Exception as e:
            logger.error(f"OCR failed: {e}", exc_info=True)
            raise Exception(f"OCR extraction failed: {str(e)}")

    def extract_text_with_retry(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        max_retries: int = 2
    ) -> str:
        """
        Extract text with automatic retry on failure.

        Args:
            image_path: Path to image file
            image_bytes: Image data as bytes
            max_retries: Maximum number of retry attempts

        Returns:
            Extracted text

        Raises:
            Exception: If all retry attempts fail
        """
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                return self.extract_text_from_image(
                    image_path=image_path,
                    image_bytes=image_bytes
                )
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(f"OCR attempt {attempt + 1} failed, retrying... Error: {e}")
                else:
                    logger.error(f"All {max_retries + 1} OCR attempts failed")

        raise Exception(f"OCR failed after {max_retries + 1} attempts: {last_error}")


# Global OCR service instance
_ocr_service: Optional[OCRService] = None


def get_ocr_service() -> OCRService:
    """
    Get or create the global OCR service instance.

    Returns:
        OCRService: OCR service instance
    """
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = OCRService()
    return _ocr_service


def reset_ocr_service():
    """Reset the global OCR service (useful for testing)."""
    global _ocr_service
    _ocr_service = None
