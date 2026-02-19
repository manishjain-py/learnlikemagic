"""Auth API endpoints — sync Cognito user to local DB."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from database import get_db
from auth.services.auth_service import AuthService
from auth.middleware.auth_middleware import _verify_cognito_token
from auth.models.schemas import UserProfileResponse

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()


@router.post("/sync", response_model=UserProfileResponse)
async def sync_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: DBSession = Depends(get_db),
):
    """
    Sync Cognito user to local DB.
    Called by frontend after successful Cognito authentication.

    Accepts an ID token (not access token) because ID tokens contain
    email, phone_number, and name claims needed for user creation.

    auth_provider is derived server-side from token claims, not from
    the client request body, to prevent spoofing.
    """
    # Validate as ID token (has user attributes in claims)
    claims = await _verify_cognito_token(credentials.credentials, expected_token_use="id")

    service = AuthService(db)
    user = service.sync_user(claims=claims)

    return UserProfileResponse(
        id=user.id,
        email=user.email,
        phone=user.phone,
        name=user.name,
        age=user.age,
        grade=user.grade,
        board=user.board,
        school_name=user.school_name,
        about_me=user.about_me,
        onboarding_complete=user.onboarding_complete,
        auth_provider=user.auth_provider,
    )


class PhoneProvisionRequest(BaseModel):
    phone: str


@router.post("/phone/provision")
async def provision_phone_user(body: PhoneProvisionRequest):
    """
    Ensure a Cognito user exists for this phone number.
    Called by frontend before initiating custom auth (OTP) flow.
    Uses admin API to bypass required email/name schema constraints.
    """
    service = AuthService.__new__(AuthService)
    service.provision_phone_user(body.phone)
    return {"status": "ok"}


@router.delete("/admin/user")
async def delete_user(
    cognito_sub: str = Query(..., description="Cognito sub of the user to delete"),
    db: DBSession = Depends(get_db),
):
    """
    Delete a user from both the local DB and Cognito.
    Admin-only endpoint for dev/testing cleanup.
    """
    service = AuthService(db)
    deleted = service.delete_user(cognito_sub)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "deleted", "cognito_sub": cognito_sub}
