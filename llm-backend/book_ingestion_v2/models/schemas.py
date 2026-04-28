"""Pydantic API request/response models for Book Ingestion V2."""
from typing import List, Literal, Optional, Dict, Any
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
    refresher_deleted: bool = False


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


# ───── Guideline Status & Detail ─────

class GuidelineStatusItem(BaseModel):
    guideline_id: str
    topic_title: str
    topic_key: Optional[str] = None
    review_status: str
    guideline_preview: Optional[str] = None  # first 200 chars
    has_explanations: bool = False
    source_page_start: Optional[int] = None
    source_page_end: Optional[int] = None

class ChapterGuidelineStatusResponse(BaseModel):
    chapter_id: str
    chapter_key: str
    guidelines: List[GuidelineStatusItem]

class GuidelineDetailResponse(BaseModel):
    id: str
    topic_title: str
    topic_key: Optional[str] = None
    chapter_key: Optional[str] = None
    guideline: str
    review_status: str
    source_page_start: Optional[int] = None
    source_page_end: Optional[int] = None
    metadata_json: Optional[Dict[str, Any]] = None
    topic_summary: Optional[str] = None
    updated_at: Optional[datetime] = None

class UpdateGuidelineRequest(BaseModel):
    guideline: Optional[str] = None
    review_status: Optional[str] = None


# ───── Visual Enrichment Status ─────

class TopicVisualStatus(BaseModel):
    guideline_id: str
    topic_title: str
    topic_key: Optional[str] = None
    total_cards: int
    cards_with_visuals: int
    layout_warning_count: int = 0
    has_explanations: bool = False

class ChapterVisualStatusResponse(BaseModel):
    chapter_id: str
    chapter_key: str
    topics: List[TopicVisualStatus]


# ───── Check-In Enrichment Status ─────

class TopicCheckInStatus(BaseModel):
    guideline_id: str
    topic_title: str
    topic_key: Optional[str] = None
    total_cards: int
    cards_with_check_ins: int
    has_explanations: bool = False

class ChapterCheckInStatusResponse(BaseModel):
    chapter_id: str
    chapter_key: str
    topics: List[TopicCheckInStatus]


# ───── Practice Bank Generation Status ─────

class TopicPracticeBankStatus(BaseModel):
    guideline_id: str
    topic_title: str
    topic_key: Optional[str] = None
    question_count: int
    has_explanations: bool = False

class ChapterPracticeBankStatusResponse(BaseModel):
    chapter_id: str
    chapter_key: str
    topics: List[TopicPracticeBankStatus]


class PracticeBankQuestionItem(BaseModel):
    id: str
    format: str
    difficulty: str
    concept_tag: str
    question_json: Dict[str, Any]
    generator_model: Optional[str] = None
    created_at: datetime

class PracticeBankDetailResponse(BaseModel):
    guideline_id: str
    topic_title: str
    question_count: int
    questions: List[PracticeBankQuestionItem]


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


# ───── Topic Pipeline Dashboard ─────

StageId = Literal[
    "explanations",
    "baatcheet_dialogue",
    "baatcheet_visuals",
    "visuals",
    "check_ins",
    "practice_bank",
    "audio_review",
    "audio_synthesis",
]

StageState = Literal[
    "done",
    "warning",
    "running",
    "ready",
    "blocked",
    "failed",
]

QualityLevel = Literal["fast", "balanced", "thorough"]


class StageStatus(BaseModel):
    stage_id: StageId
    state: StageState
    summary: str
    warnings: List[str] = []
    blocked_by: Optional[StageId] = None
    is_stale: bool = False
    last_job_id: Optional[str] = None
    last_job_status: Optional[str] = None
    last_job_error: Optional[str] = None
    last_job_completed_at: Optional[datetime] = None


class TopicPipelineStatusResponse(BaseModel):
    topic_key: str
    topic_title: str
    guideline_id: str
    chapter_id: str
    chapter_preflight_ok: bool
    pipeline_run_id: Optional[str] = None
    stages: List[StageStatus]


class RunPipelineRequest(BaseModel):
    quality_level: QualityLevel = "balanced"
    force: bool = False


class RunPipelineResponse(BaseModel):
    pipeline_run_id: str
    stages_to_run: List[StageId]
    message: Optional[str] = None


class RunChapterPipelineAllRequest(BaseModel):
    quality_level: QualityLevel = "balanced"
    skip_done: bool = True
    max_parallel: Optional[int] = None


class RunChapterPipelineAllResponse(BaseModel):
    chapter_run_id: str
    topics_queued: int
    skipped_topics: List[str] = []


class StageCountsByState(BaseModel):
    done: int = 0
    warning: int = 0
    running: int = 0
    ready: int = 0
    blocked: int = 0
    failed: int = 0


class ChapterPipelineTopicSummary(BaseModel):
    topic_key: str
    topic_title: str
    guideline_id: str
    stage_counts: StageCountsByState
    is_fully_done: bool


class ChapterPipelineTotals(BaseModel):
    topics_total: int
    topics_fully_done: int
    topics_partial: int
    topics_not_started: int


class ChapterPipelineSummaryResponse(BaseModel):
    chapter_id: str
    topics: List[ChapterPipelineTopicSummary]
    chapter_totals: ChapterPipelineTotals


class FanOutJobResponse(BaseModel):
    launched: int
    job_ids: List[str]
    skipped_guidelines: List[str] = []


# ───── Phase 3 — Topic DAG cascade ─────


class DAGStageDefinition(BaseModel):
    id: str
    scope: str
    label: str
    depends_on: List[str]


class DAGDefinitionResponse(BaseModel):
    stages: List[DAGStageDefinition]


TopicStageRunState = Literal["pending", "running", "done", "failed"]


class TopicDAGStageRow(BaseModel):
    """Per-stage state for the DAG view. Combines the durable
    `topic_stage_runs` row with the DAG topology."""

    stage_id: str
    label: str
    depends_on: List[str]
    state: TopicStageRunState
    is_stale: bool = False
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    last_job_id: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None


class CascadeInfo(BaseModel):
    cascade_id: str
    running: Optional[str] = None
    halted_at: Optional[str] = None
    cancelled: bool = False
    pending: List[str] = []
    started_at: datetime
    stage_results: Dict[str, str] = {}


class TopicDAGResponse(BaseModel):
    guideline_id: str
    stages: List[TopicDAGStageRow]
    cascade: Optional[CascadeInfo] = None


class StartCascadeRequest(BaseModel):
    force: bool = True
    quality_level: QualityLevel = "balanced"


class RunAllCascadeRequest(BaseModel):
    quality_level: QualityLevel = "balanced"


class CascadeKickoffResponse(BaseModel):
    cascade_id: str
    pending: List[str] = []
    running: Optional[str] = None
    message: Optional[str] = None


class CascadeCancelResponse(BaseModel):
    cancelled: bool


CrossDagWarningKind = Literal["chapter_resynced"]


class CrossDagWarning(BaseModel):
    """Phase 6 — surfaced when upstream DAG mutated topic content after
    the cached `explanations` artefacts were generated."""

    kind: CrossDagWarningKind
    message: str
    last_explanations_at: Optional[datetime] = None


class CrossDagWarningsResponse(BaseModel):
    warnings: List[CrossDagWarning] = []
