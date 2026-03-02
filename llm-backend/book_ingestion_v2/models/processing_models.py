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
    is_new: bool
    guidelines_for_this_chunk: str
    reasoning: str


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


class ConsolidationOutput(BaseModel):
    """LLM output for chapter finalization."""
    chapter_display_name: str
    final_chapter_summary: str
    merge_actions: List[MergeAction]
    topic_updates: List[TopicFinalUpdate]
