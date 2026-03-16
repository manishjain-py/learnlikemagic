"""Pydantic models for V2 processing pipeline internal data structures."""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class ChunkWindow(BaseModel):
    """Definition of a processing chunk."""
    chunk_index: int
    pages: List[int]                    # Absolute page numbers in this chunk
    previous_page: Optional[int] = None  # Page n-1 for context


class TopicAccumulator(BaseModel):
    """Running state for a single topic during extraction."""
    topic_key: str
    topic_title: str
    guidelines: str
    source_page_start: int
    source_page_end: int


class RunningState(BaseModel):
    """Accumulator state between chunks."""
    chapter_summary_so_far: str = ""
    topic_guidelines_map: Dict[str, TopicAccumulator] = {}  # topic_key → accumulator


class PlannedTopic(BaseModel):
    """A single topic from the chapter-level planning phase."""
    topic_key: str
    title: str
    description: str
    page_start: int
    page_end: int
    sequence_order: int
    grouping_rationale: str
    dependency_notes: str = ""


class ChapterTopicPlan(BaseModel):
    """Full output from the chapter-level planning phase."""
    topics: List[PlannedTopic]
    chapter_overview: str
    planning_rationale: str


class ChunkInput(BaseModel):
    """Full input for a chunk processing call."""
    book_metadata: Dict[str, Any]
    chapter_metadata: Dict[str, Any]
    current_pages: List[Dict[str, Any]]  # [{page_number, text}]
    previous_page_context: Optional[str] = None
    chapter_summary_so_far: str
    topics_so_far: List[TopicAccumulator]


# ───── LLM Output Schemas ─────

class TopicUpdate(BaseModel):
    """Single topic detected/updated in a chunk."""
    topic_key: str
    topic_title: str
    is_new: bool = False  # Legacy field — kept for backward compat with unguided mode
    topic_assignment: str = ""  # "planned" or "unplanned" — used in guided mode
    guidelines_for_this_chunk: str
    reasoning: str
    unplanned_justification: str = ""


class ChunkExtractionOutput(BaseModel):
    """LLM output for a single chunk."""
    updated_chapter_summary: str
    topics: List[TopicUpdate]


class MergeAction(BaseModel):
    """Instruction to merge two topics during consolidation."""
    merge_from: str         # topic_key to absorb
    merge_into: str         # topic_key to keep
    reasoning: str


class TopicFinalUpdate(BaseModel):
    """Final update for a topic during consolidation."""
    original_key: str
    new_key: str
    new_title: str
    summary: str            # 20-40 word summary
    sequence_order: int     # 1-based teaching order
    name_change_reasoning: str


class ConsolidationDeviation(BaseModel):
    """Tracks a deviation from the planned topic structure."""
    deviation_type: str  # "split", "merge", "unplanned_ratified", "unplanned_merged"
    topic_key: str
    affected_target_key: str = ""
    reasoning: str


class ConsolidationOutput(BaseModel):
    """LLM output for chapter finalization."""
    chapter_display_name: str
    final_chapter_summary: str
    merge_actions: List[MergeAction]
    topic_updates: List[TopicFinalUpdate]
    deviations: List[ConsolidationDeviation] = []


class TopicCurriculumContext(BaseModel):
    """Curriculum context for a single topic."""
    topic_key: str
    prior_topics_context: str


class CurriculumContextOutput(BaseModel):
    """LLM output for curriculum context generation."""
    contexts: List[TopicCurriculumContext]


class FinalizationResult(BaseModel):
    """Return type from finalize() — includes status determination."""
    consolidation: ConsolidationOutput
    final_status: str  # "chapter_completed" or "needs_review"
    deviation_ratio: float
    deviation_count: int
