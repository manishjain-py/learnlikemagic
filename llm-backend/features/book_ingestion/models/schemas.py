"""Pydantic schemas for book ingestion API."""
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


# ===== Book Schemas =====

class CreateBookRequest(BaseModel):
    """Request to create a new book."""
    title: str = Field(..., min_length=1, max_length=255)
    author: Optional[str] = None
    edition: Optional[str] = None
    edition_year: Optional[int] = Field(None, ge=1900, le=2100)
    country: str = Field(..., min_length=1)
    board: str = Field(..., min_length=1)
    grade: int = Field(..., ge=1, le=12)
    subject: str = Field(..., min_length=1)


class BookResponse(BaseModel):
    """Response with book details."""
    id: str
    title: str
    author: Optional[str]
    edition: Optional[str]
    edition_year: Optional[int]
    country: str
    board: str
    grade: int
    subject: str
    cover_image_s3_key: Optional[str]
    s3_prefix: str
    status: str
    created_at: datetime
    updated_at: datetime
    created_by: str

    class Config:
        from_attributes = True  # Pydantic v2 (was orm_mode in v1)


class BookListResponse(BaseModel):
    """Response with list of books."""
    books: List[BookResponse]
    total: int


class UpdateBookStatusRequest(BaseModel):
    """Request to update book status."""
    status: str = Field(..., pattern="^(draft|uploading_pages|pages_complete|generating_guidelines|guidelines_pending_review|approved)$")


# ===== Page Schemas =====

class PageInfo(BaseModel):
    """Information about a book page."""
    page_num: int
    image_s3_key: str
    text_s3_key: str
    status: str  # pending_review, approved
    approved_at: Optional[datetime] = None


class PageUploadResponse(BaseModel):
    """Response after uploading a page."""
    page_num: int
    image_url: str
    ocr_text: str
    status: str


class PageApproveResponse(BaseModel):
    """Response after approving a page."""
    page_num: int
    status: str


# ===== Guideline Schemas =====

class GuidelineMetadata(BaseModel):
    """Metadata for a subtopic guideline."""
    learning_objectives: List[str] = Field(default_factory=list)
    depth_level: str = "intermediate"
    prerequisites: List[str] = Field(default_factory=list)
    common_misconceptions: List[str] = Field(default_factory=list)
    scaffolding_strategies: List[str] = Field(default_factory=list)
    assessment_criteria: Dict[str, str] = Field(default_factory=dict)


class SubtopicGuideline(BaseModel):
    """Guideline for a specific subtopic."""
    subtopic: str
    guideline: str
    metadata: GuidelineMetadata
    source_pages: List[int]


class TopicGuideline(BaseModel):
    """Guidelines for a topic with subtopics."""
    topic: str
    subtopics: List[SubtopicGuideline]


class GuidelineJSON(BaseModel):
    """Complete guideline.json structure."""
    book_id: str
    book_metadata: Dict[str, Any]
    topics: List[TopicGuideline]


class GuidelineResponse(BaseModel):
    """Response with guideline details."""
    book_id: str
    status: str
    guideline: GuidelineJSON
    generated_at: Optional[datetime]


class GuidelineApproveResponse(BaseModel):
    """Response after approving a guideline."""
    message: str
    teaching_guidelines_created: int


class GuidelineRejectRequest(BaseModel):
    """Request to reject a guideline."""
    reason: str


# ===== Detailed Book Response (with pages) =====

class BookDetailResponse(BaseModel):
    """Detailed book response with pages."""
    id: str
    title: str
    author: Optional[str]
    edition: Optional[str]
    edition_year: Optional[int]
    country: str
    board: str
    grade: int
    subject: str
    status: str
    pages: List[PageInfo]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
