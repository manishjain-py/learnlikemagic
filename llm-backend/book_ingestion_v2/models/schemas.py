"""Pydantic API request/response models for Book Ingestion V2."""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel


# ───── Book Management ─────

class CreateBookV2Request(BaseModel):
    title: str
    author: Optional[str] = None
    edition: Optional[str] = None
    edition_year: Optional[int] = None
    country: str
    board: str
    grade: int
    subject: str


class BookV2Response(BaseModel):
    id: str
    title: str
    author: Optional[str] = None
    edition: Optional[str] = None
    edition_year: Optional[int] = None
    country: str
    board: str
    grade: int
    subject: str
    pipeline_version: int = 2
    chapter_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None


class BookV2ListResponse(BaseModel):
    books: List[BookV2Response]
    total: int


# ───── TOC Management ─────

class TOCEntry(BaseModel):
    chapter_number: int
    chapter_title: str
    start_page: int
    end_page: int
    notes: Optional[str] = None


class SaveTOCRequest(BaseModel):
    chapters: List[TOCEntry]


class TOCExtractionResponse(BaseModel):
    chapters: List[TOCEntry]
    raw_ocr_text: str


# ───── Chapter ─────

class ChapterResponse(BaseModel):
    id: str
    chapter_number: int
    chapter_title: str
    start_page: int
    end_page: int
    notes: Optional[str] = None
    display_name: Optional[str] = None
    summary: Optional[str] = None
    status: str
    total_pages: int
    uploaded_page_count: int
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TOCResponse(BaseModel):
    book_id: str
    chapters: List[ChapterResponse]


class BookV2DetailResponse(BaseModel):
    id: str
    title: str
    author: Optional[str] = None
    edition: Optional[str] = None
    edition_year: Optional[int] = None
    country: str
    board: str
    grade: int
    subject: str
    pipeline_version: int = 2
    chapters: List[ChapterResponse]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ───── Pages ─────

class PageResponse(BaseModel):
    id: str
    page_number: int
    chapter_id: str
    image_s3_key: Optional[str] = None
    text_s3_key: Optional[str] = None
    ocr_status: str
    ocr_error: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    ocr_completed_at: Optional[datetime] = None


class BulkUploadResponse(BaseModel):
    uploaded: int
    failed: int
    pages: List[PageResponse]
    errors: List[str]


class PageDetailResponse(BaseModel):
    id: str
    page_number: int
    chapter_id: str
    image_url: Optional[str] = None
    ocr_text: Optional[str] = None
    ocr_status: str
    ocr_error: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    ocr_completed_at: Optional[datetime] = None


class ChapterPagesResponse(BaseModel):
    chapter_id: str
    total_pages: int
    uploaded_count: int
    pages: List[PageResponse]


# ───── Processing Jobs ─────

class ProcessingJobResponse(BaseModel):
    job_id: str
    chapter_id: str
    job_type: str
    status: str
    total_items: Optional[int] = None
    completed_items: int = 0
    failed_items: int = 0
    current_item: Optional[str] = None
    last_completed_item: Optional[str] = None
    progress_detail: Optional[Dict[str, Any]] = None
    model_provider: Optional[str] = None
    model_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class StartProcessingRequest(BaseModel):
    resume: bool = False


class ReprocessRequest(BaseModel):
    pass


class RefinalizeRequest(BaseModel):
    pass


# ───── Topics ─────

class ChapterTopicResponse(BaseModel):
    id: str
    topic_key: str
    topic_title: str
    guidelines: str
    summary: Optional[str] = None
    source_page_start: Optional[int] = None
    source_page_end: Optional[int] = None
    sequence_order: Optional[int] = None
    status: str
    version: int = 1
    prior_topics_context: Optional[str] = None
    topic_assignment: Optional[str] = None


class ChapterTopicsResponse(BaseModel):
    chapter_id: str
    topics: List[ChapterTopicResponse]
    total: int


# ───── Sync ─────

class SyncResponse(BaseModel):
    synced_chapters: int
    synced_topics: int
    errors: List[str]


# ───── Explanation Generation ─────

class ExplanationGenerationResponse(BaseModel):
    generated: int           # topics with explanations successfully generated
    skipped: int             # topics that already had explanations
    failed: int              # topics where generation errored
    errors: List[str]        # per-topic error messages


# ───── Explanation Status & Detail ─────

class TopicExplanationStatus(BaseModel):
    guideline_id: str
    topic_title: str
    topic_key: Optional[str] = None
    variant_count: int


class ChapterExplanationStatusResponse(BaseModel):
    chapter_id: str
    chapter_key: str
    topics: List[TopicExplanationStatus]


class ExplanationVariantResponse(BaseModel):
    id: str
    variant_key: str
    variant_label: str
    cards_json: List[Dict[str, Any]]
    summary_json: Optional[Dict[str, Any]] = None
    generator_model: Optional[str] = None
    created_at: Optional[datetime] = None


class TopicExplanationsDetailResponse(BaseModel):
    guideline_id: str
    topic_title: str
    topic_key: Optional[str] = None
    variants: List[ExplanationVariantResponse]


class DeleteExplanationsResponse(BaseModel):
    deleted_count: int


# ───── Results ─────

class ChapterResultSummary(BaseModel):
    chapter_id: str
    chapter_number: int
    chapter_title: str
    display_name: Optional[str] = None
    status: str
    topic_count: int


class BookResultsResponse(BaseModel):
    book_id: str
    title: str
    chapters: List[ChapterResultSummary]
    total_topics: int
