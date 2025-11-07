"""
Pydantic models for Phase 6: Guideline Extraction

All JSON schemas for the sharded guideline extraction pipeline.
Follows Single Responsibility Principle - each model represents one JSON schema.
"""

from typing import List, Dict, Any, Optional, Literal, Union
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
# PAGE GUIDELINE MODELS (Provisional)
# ============================================================================

class PageFacts(BaseModel):
    """Extracted facts from a single page"""
    objectives_add: List[str] = Field(
        default_factory=list,
        description="Learning objectives to add"
    )
    examples_add: List[str] = Field(
        default_factory=list,
        description="Worked examples to add"
    )
    misconceptions_add: List[str] = Field(
        default_factory=list,
        description="Common misconceptions to add"
    )
    assessments_add: List[Assessment] = Field(
        default_factory=list,
        description="Assessment items to add"
    )


class DecisionMetadata(BaseModel):
    """Metadata about the boundary decision"""
    continue_score: float = Field(
        ge=0.0, le=1.0,
        description="Confidence that page continues current subtopic"
    )
    new_score: float = Field(
        ge=0.0, le=1.0,
        description="Confidence that page starts new subtopic"
    )
    reasoning: str = Field(
        description="Brief explanation of the decision"
    )


class PageGuideline(BaseModel):
    """Provisional guideline for a single page"""
    book_id: str
    page: int = Field(gt=0, description="Page number (1-indexed)")

    assigned_topic_key: str = Field(description="Slugified topic (e.g., 'fractions')")
    assigned_subtopic_key: str = Field(description="Slugified subtopic (e.g., 'adding-like-fractions')")

    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in the assignment"
    )

    summary: str = Field(
        max_length=500,
        description="Minisummary of the page (≤60 words)"
    )

    facts: PageFacts = Field(description="Extracted structured facts")

    provisional: bool = Field(
        default=True,
        description="Whether this assignment is provisional"
    )

    decision_metadata: DecisionMetadata = Field(
        description="Metadata about the boundary decision"
    )


# ============================================================================
# SUBTOPIC SHARD MODELS (Authoritative)
# ============================================================================

class QualityFlags(BaseModel):
    """Quality validation flags for a subtopic"""
    has_min_objectives: bool = Field(default=False)
    has_misconception: bool = Field(default=False)
    has_assessments: bool = Field(default=False)
    teaching_description_valid: bool = Field(default=False)


class SubtopicShard(BaseModel):
    """Authoritative state for a single subtopic"""
    book_id: str

    topic_key: str = Field(description="Slugified topic identifier")
    subtopic_key: str = Field(description="Slugified subtopic identifier")

    # Human-readable titles
    topic_title: str = Field(description="Human-readable topic name")
    subtopic_title: str = Field(description="Human-readable subtopic name")

    aliases: List[str] = Field(
        default_factory=list,
        description="Alternative names for this subtopic"
    )

    status: Literal["open", "stable", "final", "needs_review"] = Field(
        default="open",
        description="Lifecycle status of the subtopic"
    )

    # Page tracking
    source_page_start: int = Field(gt=0, description="First page number")
    source_page_end: int = Field(gt=0, description="Last page number")
    source_pages: List[int] = Field(
        default_factory=list,
        description="All page numbers (sorted)"
    )

    # Extracted content
    objectives: List[str] = Field(
        default_factory=list,
        description="Learning objectives"
    )
    examples: List[str] = Field(
        default_factory=list,
        description="Worked examples"
    )
    misconceptions: List[str] = Field(
        default_factory=list,
        description="Common misconceptions"
    )
    assessments: List[Assessment] = Field(
        default_factory=list,
        description="Assessment items"
    )

    # Teaching description (generated when stable)
    teaching_description: Optional[str] = Field(
        default=None,
        description="3-6 line teacher-ready description"
    )

    # Comprehensive description (generated when stable)
    description: Optional[str] = Field(
        default=None,
        description="Comprehensive 200-300 word description covering what this topic is, how it's taught, and how it's assessed"
    )

    # Optional longer guideline (future enhancement)
    guideline_text: Optional[str] = Field(
        default=None,
        description="Optional longer prose (250-800 words)"
    )

    evidence_summary: str = Field(
        default="",
        description="Brief summary of content coverage"
    )

    confidence: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="Overall confidence in this subtopic"
    )

    last_updated_page: int = Field(
        default=0,
        description="Last page that updated this shard"
    )

    version: int = Field(
        default=1,
        ge=1,
        description="Version number (increments on each update)"
    )

    quality_flags: QualityFlags = Field(
        default_factory=QualityFlags,
        description="Quality validation flags"
    )

    @field_validator('source_pages')
    @classmethod
    def pages_must_be_sorted(cls, v: List[int]) -> List[int]:
        """Ensure pages are sorted"""
        return sorted(set(v))  # Also deduplicate


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
    summary: str = Field(max_length=500)


class OpenSubtopicInfo(BaseModel):
    """Information about an open subtopic"""
    subtopic_key: str
    subtopic_title: str
    evidence_summary: str
    objectives_count: int = Field(ge=0)
    examples_count: int = Field(ge=0)


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

    open_topics: List[Union[OpenTopicInfo, 'OpenTopicInfoV2']] = Field(
        default_factory=list,
        description="Currently active topics with open subtopics (V1 or V2)"
    )

    recent_page_summaries: List[RecentPageSummary] = Field(
        default_factory=list,
        description="Last 1-2 page summaries for continuity"
    )

    toc_hints: ToCHints = Field(
        default_factory=ToCHints,
        description="Table of contents hints"
    )


# ============================================================================
# LLM RESPONSE MODELS
# ============================================================================

class BoundaryDecision(BaseModel):
    """Response from boundary detection LLM call"""
    decision: Literal["continue", "new"]
    continue_score: float = Field(ge=0.0, le=1.0)
    new_score: float = Field(ge=0.0, le=1.0)

    # If continuing
    continue_subtopic_key: Optional[str] = None

    # If new
    new_subtopic_key: Optional[str] = None
    new_subtopic_title: Optional[str] = None

    reasoning: str = Field(description="Brief explanation")


class MinisummaryResponse(BaseModel):
    """Response from minisummary generation"""
    summary: str = Field(
        max_length=500,
        description="Extractive summary (≤60 words)"
    )


class FactsExtractionResponse(BaseModel):
    """Response from facts extraction LLM call"""
    objectives_add: List[str] = Field(default_factory=list)
    examples_add: List[str] = Field(default_factory=list)
    misconceptions_add: List[str] = Field(default_factory=list)
    assessments_add: List[Assessment] = Field(default_factory=list)


class TeachingDescriptionResponse(BaseModel):
    """Response from teaching description generation"""
    teaching_description: str = Field(
        min_length=100,
        max_length=800,
        description="3-6 line teacher-ready description"
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


# ============================================================================
# V2 MODELS - SIMPLIFIED ARCHITECTURE
# ============================================================================

class SubtopicShardV2(BaseModel):
    """
    V2 SubtopicShard - Simplified with single guidelines field.

    Breaking change from V1:
    - Removed: objectives, examples, misconceptions, assessments,
               teaching_description, description, evidence_summary
    - Added: guidelines (single comprehensive text field)
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

    # Single guidelines field (V2 simplification)
    guidelines: str = Field(
        ...,
        description="Complete teaching guidelines in natural language text. Includes objectives, examples, teaching strategies, misconceptions, and assessments."
    )

    # Metadata
    version: int = Field(default=1, description="Shard version for tracking updates")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class BoundaryDecisionV2(BaseModel):
    """
    V2 Boundary Detection Output - Simplified.

    Breaking change from V1:
    - Removed: decision, continue_score, new_score, continue_subtopic_key,
               new_subtopic_key, new_subtopic_title, reasoning
    - Changed: Single decision + extracted guidelines
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


class OpenSubtopicInfoV2(BaseModel):
    """Info about an open subtopic (V2 with guidelines text)"""
    subtopic_key: str
    subtopic_title: str
    page_start: int
    page_end: int
    guidelines: str = Field(description="Full guidelines text for context")


class OpenTopicInfoV2(BaseModel):
    """Information about an open topic (V2)"""
    topic_key: str
    topic_title: str
    open_subtopics: List[OpenSubtopicInfoV2] = Field(default_factory=list)


class TopicNameRefinement(BaseModel):
    """LLM response for refined topic/subtopic names"""
    topic_title: str = Field(description="Refined topic title")
    topic_key: str = Field(description="Refined topic key (slug)")
    subtopic_title: str = Field(description="Refined subtopic title")
    subtopic_key: str = Field(description="Refined subtopic key (slug)")
    reasoning: str = Field(description="Brief explanation of changes")
