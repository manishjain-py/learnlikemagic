"""
Pydantic models for Phase 6: Guideline Extraction

All JSON schemas for the sharded guideline extraction pipeline.
Follows Single Responsibility Principle - each model represents one JSON schema.
"""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


# ============================================================================
# ASSESSMENT MODELS
# ============================================================================

class Assessment(BaseModel):
    """Single assessment item with difficulty level"""
    level: Literal["basic", "proficient", "advanced"] = Field(
        description="Difficulty level of the assessment"
    )
    prompt: str = Field(description="Question or problem statement")
    answer: str = Field(description="Expected answer or solution")


# ============================================================================
# SUBTOPIC SHARD MODELS
# ============================================================================

class SubtopicShard(BaseModel):
    """
    Subtopic Shard - Simplified with single guidelines field.

    Stores complete teaching guidelines for a subtopic in natural language text.
    """

    # Identifiers
    topic_key: str = Field(..., description="Slugified topic identifier (lowercase)")
    topic_title: str = Field(..., description="Human-readable topic name")
    subtopic_key: str = Field(..., description="Slugified subtopic identifier (lowercase)")
    subtopic_title: str = Field(..., description="Human-readable subtopic name")

    # Page range
    source_page_start: int = Field(..., description="First page of this subtopic")
    source_page_end: int = Field(..., description="Last page of this subtopic")

    # Status
    status: Literal["open", "stable", "final"] = Field(
        default="open",
        description="open=actively growing, stable=no updates for 5 pages, final=book ended or explicitly finalized"
    )

    # Single guidelines field
    guidelines: str = Field(
        ...,
        description="Complete teaching guidelines in natural language text. Includes objectives, examples, teaching strategies, misconceptions, and assessments."
    )

    # Metadata
    version: int = Field(default=1, description="Shard version for tracking updates")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ============================================================================
# INDEX MODELS
# ============================================================================

class SubtopicIndexEntry(BaseModel):
    """Single subtopic entry in the index"""
    model_config = {"validate_assignment": False}

    subtopic_key: str
    subtopic_title: str
    status: Literal["open", "stable", "final", "needs_review"]
    page_range: str = Field(description="e.g., '2-6' or '7-?'")


class TopicIndexEntry(BaseModel):
    """Single topic entry in the index"""
    topic_key: str
    topic_title: str
    subtopics: List[SubtopicIndexEntry] = Field(default_factory=list)


class GuidelinesIndex(BaseModel):
    """Central index of all topics and subtopics"""
    model_config = {"validate_assignment": False}

    book_id: str
    topics: List[TopicIndexEntry] = Field(default_factory=list)
    version: int = 1
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class PageAssignment(BaseModel):
    """Assignment of a page to a topic/subtopic"""
    topic_key: str
    subtopic_key: str
    confidence: float = Field(ge=0.0, le=1.0)


class PageIndex(BaseModel):
    """Mapping of pages to their assigned subtopics"""
    model_config = {"validate_assignment": False}

    book_id: str
    pages: Dict[int, PageAssignment] = Field(
        default_factory=dict,
        description="Page number → assignment"
    )
    version: int = 1
    last_updated: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# CONTEXT PACK MODELS
# ============================================================================

class RecentPageSummary(BaseModel):
    """Summary of a recent page"""
    page: int
    summary: str = Field(max_length=1000)  # Increased for detailed summaries (~150 words)


class OpenSubtopicInfo(BaseModel):
    """Info about an open subtopic with guidelines text"""
    subtopic_key: str
    subtopic_title: str
    page_start: int
    page_end: int
    guidelines: str = Field(description="Full guidelines text for context")


class OpenTopicInfo(BaseModel):
    """Information about an open topic"""
    topic_key: str
    topic_title: str
    open_subtopics: List[OpenSubtopicInfo] = Field(default_factory=list)


class ToCHints(BaseModel):
    """Table of contents hints (simplified for MVP v1)"""
    current_chapter: Optional[str] = None
    next_section_candidate: Optional[str] = None


class ContextPack(BaseModel):
    """Compact context for LLM (replaces passing all previous pages)"""
    book_id: str
    current_page: int

    book_metadata: Dict[str, Any] = Field(
        description="Grade, subject, board, etc."
    )

    open_topics: List[OpenTopicInfo] = Field(
        default_factory=list,
        description="Currently active topics with open subtopics"
    )

    recent_page_summaries: List[RecentPageSummary] = Field(
        default_factory=list,
        description="Last 5 page summaries for continuity"
    )

    toc_hints: ToCHints = Field(
        default_factory=ToCHints,
        description="Table of contents hints"
    )


# ============================================================================
# LLM RESPONSE MODELS
# ============================================================================

class BoundaryDecision(BaseModel):
    """
    Boundary Detection Output - Simplified.

    LLM determines if page continues existing topic or starts new one,
    and extracts guidelines in the same call.
    """

    is_new_topic: bool = Field(
        ...,
        description="True if this page starts a new topic/subtopic, False if it continues an existing one"
    )

    topic_name: str = Field(
        ...,
        description="Topic name (lowercase, kebab-case). MUST exactly match existing topic if is_new_topic=False"
    )

    subtopic_name: str = Field(
        ...,
        description="Subtopic name (lowercase, kebab-case). MUST exactly match existing subtopic if is_new_topic=False"
    )

    page_guidelines: str = Field(
        ...,
        description="Complete teaching guidelines extracted from this page. Natural language text covering objectives, examples, teaching strategies, misconceptions, and assessments."
    )

    reasoning: str = Field(
        ...,
        description="Detailed reasoning behind the boundary detection decision, explaining why this is/isn't a new topic."
    )


class TopicNameRefinement(BaseModel):
    """LLM response for refined topic/subtopic names"""
    topic_title: str = Field(description="Refined topic title")
    topic_key: str = Field(description="Refined topic key (slug)")
    subtopic_title: str = Field(description="Refined subtopic title")
    subtopic_key: str = Field(description="Refined subtopic key (slug)")
    reasoning: str = Field(description="Brief explanation of changes")


class MinisummaryResponse(BaseModel):
    """Response from minisummary generation"""
    summary: str = Field(
        max_length=500,
        description="Extractive summary (≤60 words)"
    )


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def slugify(text: str) -> str:
    """
    Convert text to slugified format (kebab-case)

    Examples:
        "Adding Like Fractions" → "adding-like-fractions"
        "Fractions" → "fractions"
    """
    import re
    # Lowercase, replace spaces/underscores with hyphens, remove special chars
    text = text.lower()
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'[^\w\-]', '', text)
    text = re.sub(r'\-+', '-', text)  # Multiple hyphens → single
    return text.strip('-')


def deslugify(slug: str) -> str:
    """
    Convert slugified text back to title case

    Examples:
        "adding-like-fractions" → "Adding Like Fractions"
        "fractions" → "Fractions"
    """
    return ' '.join(word.capitalize() for word in slug.split('-'))
