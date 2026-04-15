"""
OCR Service — provider-aware text extraction from images.

Supports two providers:
- "openai": Uses OpenAI Vision API (Chat Completions with image_url).
- "claude_code": Uses the Claude Code CLI via ClaudeCodeAdapter, which lets
  Claude "see" the image through its Read tool.

Provider is REQUIRED and must match the llm_config DB entry that drives the
caller (e.g. "ocr" or "book_ingestion_v2"). Passing provider + model_id keeps
the contract from CLAUDE.md: "never silently switch away from claude_code".
"""
import base64
import logging
import tempfile
from pathlib import Path
from typing import Optional
from openai import OpenAI
from config import get_settings

logger = logging.getLogger(__name__)


class OCRService:
    """Provider-aware OCR. Branches between OpenAI Vision and Claude Code CLI."""

    def __init__(self, *, provider: str, model: str):
        """
        Args:
            provider: One of "openai", "claude_code". Must match llm_config DB entry.
            model: Model id ("gpt-4o", "claude-code", …). Used for logging +
                   passed to the OpenAI Chat Completions API when provider is openai.
        """
        self.provider = provider
        self.model = model
        self.max_tokens = 4096

        if provider == "openai":
            settings = get_settings()
            self.client = OpenAI(api_key=settings.openai_api_key)
            self.claude_code_adapter = None
        elif provider == "claude_code":
            from shared.services.claude_code_adapter import ClaudeCodeAdapter
            self.client = None
            # OCR vision call is short — 5 min timeout is plenty.
            self.claude_code_adapter = ClaudeCodeAdapter(timeout=300)
        else:
            raise ValueError(
                f"OCR does not support provider '{provider}'. "
                f"Supported: 'openai', 'claude_code'."
            )

        logger.info(f"OCR service initialized: provider={provider} model={model}")

    def encode_image_to_base64(self, image_path: str) -> str:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        try:
            with open(image_path, 'rb') as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to encode image: {e}")
            raise IOError(f"Failed to read image file: {e}")

    def encode_bytes_to_base64(self, image_bytes: bytes) -> str:
        return base64.b64encode(image_bytes).decode('utf-8')

    def extract_text_from_image(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        prompt: Optional[str] = None,
    ) -> str:
        """Extract text from an image. Routes to the configured provider."""
        if not image_path and not image_bytes:
            raise ValueError("Either image_path or image_bytes must be provided")

        if prompt is None:
            prompt = (Path(__file__).parent.parent / "prompts" / "ocr_default.txt").read_text()

        if self.provider == "claude_code":
            return self._extract_via_claude_code(image_path, image_bytes, prompt)
        return self._extract_via_openai(image_path, image_bytes, prompt)

    def _extract_via_openai(
        self,
        image_path: Optional[str],
        image_bytes: Optional[bytes],
        prompt: str,
    ) -> str:
        import time
        import json
        start_time = time.time()

        if image_path:
            base64_image = self.encode_image_to_base64(image_path)
        else:
            base64_image = self.encode_bytes_to_base64(image_bytes)

        logger.info(json.dumps({
            "step": "OCR",
            "status": "starting",
            "input": {"provider": "openai", "model": self.model, "image_b64_size": len(base64_image)}
        }))

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{base64_image}"},
                        },
                    ],
                }],
                max_completion_tokens=self.max_tokens,
            )
            extracted_text = response.choices[0].message.content

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(json.dumps({
                "step": "OCR",
                "status": "complete",
                "output": {"chars_extracted": len(extracted_text)},
                "duration_ms": duration_ms,
            }))
            return extracted_text
        except Exception as e:
            logger.error(f"OCR (openai) failed: {e}", exc_info=True)
            raise Exception(f"OCR extraction failed: {str(e)}")

    def _extract_via_claude_code(
        self,
        image_path: Optional[str],
        image_bytes: Optional[bytes],
        prompt: str,
    ) -> str:
        """Claude Code CLI reads the image file from disk via its Read tool.

        If only bytes are provided we write them to a temp PNG so the CLI
        subprocess can access it. We clean up the temp file afterward.
        """
        import time
        import json
        start_time = time.time()

        tmp_path = None
        try:
            if image_bytes and not image_path:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(image_bytes)
                    tmp_path = tmp.name
                    image_path = tmp_path

            logger.info(json.dumps({
                "step": "OCR",
                "status": "starting",
                "input": {"provider": "claude_code", "model": self.model, "image_path": image_path},
            }))

            extracted_text = self.claude_code_adapter.call_vision_sync(
                prompt=prompt,
                image_path=image_path,
            )

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(json.dumps({
                "step": "OCR",
                "status": "complete",
                "output": {"chars_extracted": len(extracted_text)},
                "duration_ms": duration_ms,
            }))
            return extracted_text
        except Exception as e:
            logger.error(f"OCR (claude_code) failed: {e}", exc_info=True)
            raise Exception(f"OCR extraction failed: {str(e)}")
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    def extract_text_with_retry(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        max_retries: int = 2,
    ) -> str:
        """Call extract_text_from_image with simple retry."""
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                return self.extract_text_from_image(
                    image_path=image_path, image_bytes=image_bytes
                )
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(f"OCR attempt {attempt + 1} failed, retrying... Error: {e}")
                else:
                    logger.error(f"All {max_retries + 1} OCR attempts failed")
        raise Exception(f"OCR failed after {max_retries + 1} attempts: {last_error}")


# Global OCR service instance — cached on (provider, model).
_ocr_service: Optional[OCRService] = None


def get_ocr_service(*, provider: str, model: str) -> OCRService:
    """Get or create the global OCR service, cached per (provider, model) pair."""
    global _ocr_service
    if (
        _ocr_service is None
        or _ocr_service.provider != provider
        or _ocr_service.model != model
    ):
        _ocr_service = OCRService(provider=provider, model=model)
    return _ocr_service


def reset_ocr_service():
    """Reset the global OCR service (useful for testing)."""
    global _ocr_service
    _ocr_service = None
