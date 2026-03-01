"""Profile API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession

from database import get_db
from auth.services.profile_service import ProfileService
from auth.middleware.auth_middleware import get_current_user
from auth.models.schemas import (
    UserProfileResponse,
    UpdateProfileRequest,
    ChangePasswordRequest,
    ChangePasswordResponse,
)

router = APIRouter(prefix="/profile", tags=["profile"])


def _user_to_response(user) -> UserProfileResponse:
    """Convert a User ORM object to a UserProfileResponse."""
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        phone=user.phone,
        name=user.name,
        preferred_name=user.preferred_name,
        age=user.age,
        grade=user.grade,
        board=user.board,
        school_name=user.school_name,
        about_me=user.about_me,
        text_language_preference=user.text_language_preference or 'en',
        audio_language_preference=user.audio_language_preference or 'en',
        onboarding_complete=user.onboarding_complete,
        auth_provider=user.auth_provider,
    )


@router.get("", response_model=UserProfileResponse)
async def get_profile(current_user=Depends(get_current_user)):
    """Get the current user's profile."""
    return _user_to_response(current_user)


@router.put("", response_model=UserProfileResponse)
async def update_profile(
    request: UpdateProfileRequest,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Update the current user's profile."""
    service = ProfileService(db)
    user = service.update_profile(
        user_id=current_user.id,
        name=request.name,
        preferred_name=request.preferred_name,
        age=request.age,
        grade=request.grade,
        board=request.board,
        school_name=request.school_name,
        about_me=request.about_me,
        text_language_preference=request.text_language_preference,
        audio_language_preference=request.audio_language_preference,
    )
    return _user_to_response(user)


@router.put("/password", response_model=ChangePasswordResponse)
async def change_password(
    request: ChangePasswordRequest,
    raw_request: Request,
    current_user=Depends(get_current_user),
):
    """
    Change password for email-based users.
    Proxies to Cognito's ChangePassword API.
    """
    if current_user.auth_provider != "email":
        raise HTTPException(
            status_code=400,
            detail="Password change is only available for email-based accounts."
        )

    # Extract raw access token from the Authorization header
    auth_header = raw_request.headers.get("authorization", "")
    access_token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""

    if not access_token:
        raise HTTPException(status_code=401, detail="Access token required")

    import boto3
    from config import get_settings
    client = boto3.client("cognito-idp", region_name=get_settings().cognito_region)
    try:
        client.change_password(
            PreviousPassword=request.previous_password,
            ProposedPassword=request.proposed_password,
            AccessToken=access_token,
        )
        return ChangePasswordResponse(success=True, message="Password changed successfully.")
    except client.exceptions.NotAuthorizedException:
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    except client.exceptions.InvalidPasswordException as e:
        raise HTTPException(status_code=400, detail=f"New password does not meet requirements: {e}")
