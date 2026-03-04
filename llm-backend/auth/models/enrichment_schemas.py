"""Pydantic request/response models for enrichment and personality endpoints."""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal, Optional


class EnrichmentProfileRequest(BaseModel):
    """Partial update - all fields optional."""
    interests: Optional[list[str]] = None
    learning_styles: Optional[list[str]] = None
    motivations: Optional[list[str]] = None
    growth_areas: Optional[list[str]] = None
    parent_notes: Optional[str] = Field(default=None, max_length=1000)
    attention_span: Optional[Literal["short", "medium", "long"]] = None
    pace_preference: Optional[Literal["slow", "balanced", "fast"]] = None


class EnrichmentProfileResponse(BaseModel):
    """Full profile - nulls for unfilled sections."""
    interests: Optional[list[str]] = None
    learning_styles: Optional[list[str]] = None
    motivations: Optional[list[str]] = None
    growth_areas: Optional[list[str]] = None
    parent_notes: Optional[str] = None
    attention_span: Optional[str] = None
    pace_preference: Optional[str] = None
    personality_status: Optional[str] = None  # generating/ready/failed/none
    sections_filled: int = 0  # 0-4 count for progress indicator
    has_about_me: bool = False  # True if user has about_me but no parent_notes (migration prompt)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EnrichmentUpdateResponse(BaseModel):
    """Minimal response for PUT - frontend already has the data it sent."""
    personality_status: str  # generating/unchanged/none
    sections_filled: int
    inputs_hash: Optional[str] = None  # passed to background task for debounce


class PersonalityResponse(BaseModel):
    personality_json: Optional[dict] = None
    tutor_brief: Optional[str] = None
    status: str  # generating/ready/failed/none
    updated_at: Optional[datetime] = None
