"""API routes for issue reporting and management."""
import logging
from typing import Optional, List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from database import get_db
from auth.middleware.auth_middleware import get_current_user, get_optional_user
from shared.services.issue_service import IssueService

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────

class InterpretRequest(BaseModel):
    user_input: str
    has_screenshots: bool = False
    previous_interpretation: Optional[str] = None
    refinement_input: Optional[str] = None

class InterpretResponse(BaseModel):
    title: str
    description: str

class CreateIssueRequest(BaseModel):
    title: str
    description: str
    original_input: str
    screenshot_s3_keys: Optional[List[str]] = None

class IssueResponse(BaseModel):
    id: str
    user_id: Optional[str]
    reporter_name: Optional[str]
    title: str
    description: str
    original_input: Optional[str]
    screenshot_s3_keys: Optional[list]
    status: str
    created_at: str
    updated_at: str

class IssueListResponse(BaseModel):
    issues: List[IssueResponse]
    total: int

class UpdateStatusRequest(BaseModel):
    status: str

class ScreenshotUploadResponse(BaseModel):
    s3_key: str


def _issue_to_response(issue) -> IssueResponse:
    return IssueResponse(
        id=issue.id,
        user_id=issue.user_id,
        reporter_name=issue.reporter_name,
        title=issue.title,
        description=issue.description,
        original_input=issue.original_input,
        screenshot_s3_keys=issue.screenshot_s3_keys,
        status=issue.status,
        created_at=issue.created_at.isoformat() if issue.created_at else "",
        updated_at=issue.updated_at.isoformat() if issue.updated_at else "",
    )


# ── User-facing endpoints ────────────────────────────────────

@router.post("/issues/interpret", response_model=InterpretResponse)
async def interpret_issue(
    request: InterpretRequest,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Send user input to LLM to interpret the issue in app context."""
    service = IssueService(db)
    result = service.interpret(
        user_input=request.user_input,
        has_screenshots=request.has_screenshots,
        previous_interpretation=request.previous_interpretation,
        refinement_input=request.refinement_input,
    )
    return InterpretResponse(**result)


@router.post("/issues/upload-screenshot", response_model=ScreenshotUploadResponse)
async def upload_screenshot(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Upload a screenshot for an issue report. Returns S3 key."""
    service = IssueService(db)
    file_bytes = await file.read()
    # Use a temp ID for the upload path — will be grouped under a draft folder
    draft_id = str(uuid4())
    s3_key = service.upload_screenshot(
        issue_id=draft_id,
        file_bytes=file_bytes,
        filename=file.filename or "screenshot.png",
        content_type=file.content_type or "image/png",
    )
    return ScreenshotUploadResponse(s3_key=s3_key)


@router.post("/issues", response_model=IssueResponse, status_code=status.HTTP_201_CREATED)
async def create_issue(
    request: CreateIssueRequest,
    current_user=Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Create a confirmed issue after user accepts the LLM interpretation."""
    service = IssueService(db)
    issue = service.create_issue(
        title=request.title,
        description=request.description,
        original_input=request.original_input,
        screenshot_s3_keys=request.screenshot_s3_keys,
        user_id=current_user.id,
    )
    return _issue_to_response(issue)


# ── Admin endpoints ──────────────────────────────────────────

@router.get("/issues", response_model=IssueListResponse)
async def list_issues(
    status_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: DBSession = Depends(get_db),
):
    """List all issues with optional status filter."""
    service = IssueService(db)
    result = service.list_issues(status=status_filter, limit=limit, offset=offset)
    return IssueListResponse(
        issues=[_issue_to_response(i) for i in result["issues"]],
        total=result["total"],
    )


@router.get("/issues/{issue_id}", response_model=IssueResponse)
async def get_issue(
    issue_id: str,
    db: DBSession = Depends(get_db),
):
    """Get a single issue by ID."""
    service = IssueService(db)
    issue = service.get_issue(issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return _issue_to_response(issue)


@router.patch("/issues/{issue_id}/status", response_model=IssueResponse)
async def update_issue_status(
    issue_id: str,
    request: UpdateStatusRequest,
    db: DBSession = Depends(get_db),
):
    """Update issue status (open, in_progress, closed)."""
    service = IssueService(db)
    try:
        issue = service.update_status(issue_id, request.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    return _issue_to_response(issue)


@router.get("/issues/{issue_id}/screenshots/{s3_key:path}")
async def get_screenshot_url(
    issue_id: str,
    s3_key: str,
    db: DBSession = Depends(get_db),
):
    """Get a presigned URL for a screenshot."""
    service = IssueService(db)
    url = service.get_screenshot_url(s3_key)
    return {"url": url}
