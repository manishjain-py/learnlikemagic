"""Constants and enums for Book Ingestion V2 pipeline."""
from enum import Enum


# Processing configuration
CHUNK_SIZE = 3                    # Pages per chunk
CHUNK_STRIDE = 3                  # Non-overlapping (stride == size)
CHUNK_MAX_RETRIES = 3             # Retries per chunk on LLM failure
HEARTBEAT_STALE_THRESHOLD = 1800  # Seconds (30 minutes — LLM calls with Opus + high effort can take 10+ min)
PENDING_STALE_THRESHOLD = 300     # Seconds (5 minutes)

# LLM config component key
LLM_CONFIG_KEY = "book_ingestion_v2"


class ChapterStatus(str, Enum):
    TOC_DEFINED = "toc_defined"
    UPLOAD_IN_PROGRESS = "upload_in_progress"
    UPLOAD_COMPLETE = "upload_complete"
    TOPIC_EXTRACTION = "topic_extraction"
    CHAPTER_FINALIZING = "chapter_finalizing"
    CHAPTER_COMPLETED = "chapter_completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class V2JobType(str, Enum):
    OCR = "v2_ocr"
    TOPIC_EXTRACTION = "v2_topic_extraction"
    REFINALIZATION = "v2_refinalization"
    EXPLANATION_GENERATION = "v2_explanation_generation"
    VISUAL_ENRICHMENT = "v2_visual_enrichment"
    AUDIO_GENERATION = "v2_audio_generation"
    REFRESHER_GENERATION = "v2_refresher_generation"
    CHECK_IN_ENRICHMENT = "v2_check_in_enrichment"
    PRACTICE_BANK_GENERATION = "v2_practice_bank_generation"


class V2JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class OCRStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TopicStatus(str, Enum):
    DRAFT = "draft"
    CONSOLIDATED = "consolidated"
    FINAL = "final"
    APPROVED = "approved"


# Planning deviation thresholds
PLANNING_DEVIATION_THRESHOLD = 0.30
PLANNING_DEVIATION_MIN_COUNT = 3
