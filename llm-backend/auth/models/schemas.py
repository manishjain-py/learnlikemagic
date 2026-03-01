"""Pydantic request/response models for auth and profile endpoints."""

from pydantic import BaseModel
from typing import Literal, Optional


class UserProfileResponse(BaseModel):
    """Response model for user profile data."""
    id: str
    email: Optional[str] = None
    phone: Optional[str] = None
    name: Optional[str] = None
    age: Optional[int] = None
    grade: Optional[int] = None
    board: Optional[str] = None
    school_name: Optional[str] = None
    about_me: Optional[str] = None
    text_language_preference: Optional[str] = 'en'
    audio_language_preference: Optional[str] = 'en'
    onboarding_complete: bool
    auth_provider: str


class UpdateProfileRequest(BaseModel):
    """Request model for updating profile fields."""
    name: Optional[str] = None
    age: Optional[int] = None
    grade: Optional[int] = None
    board: Optional[str] = None
    school_name: Optional[str] = None
    about_me: Optional[str] = None
    text_language_preference: Optional[Literal['en', 'hi', 'hinglish']] = None
    audio_language_preference: Optional[Literal['en', 'hi', 'hinglish']] = None


class ChangePasswordRequest(BaseModel):
    """Request model for changing password."""
    previous_password: str
    proposed_password: str


class ChangePasswordResponse(BaseModel):
    """Response model for password change."""
    success: bool
    message: str
