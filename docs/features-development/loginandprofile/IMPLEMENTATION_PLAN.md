# Login & User Profile — Technical Implementation Plan

**Status:** Draft (v2 — updated from PR review)
**Date:** 2026-02-19
**PRD:** [PRD.md](./PRD.md)

---

## Changelog (v2)

Fixes from PR #10 review:

| # | Issue | What Changed |
|---|-------|-------------|
| 1 | Token contract inconsistency | Explicitly distinguish ID token (for `/auth/sync`) vs access token (for all other endpoints). Middleware validates `token_use` claim. Access tokens validate `client_id`; ID tokens validate `aud`. |
| 2 | Path naming mismatch | Split into two routers: `auth_routes.py` (prefix `/auth`) and `profile_routes.py` (prefix `/profile`). Endpoints are now `/auth/sync`, `GET /profile`, `PUT /profile`. |
| 3 | Cognito `name` required | Changed `required = false` in Cognito schema. Phone OTP users won't have a name at signup; it's collected during onboarding (Phase 5). |
| 4 | JWKS cache no TTL | Added 1-hour TTL + refresh-on-kid-miss. If a `kid` isn't found in cache, refetch JWKS once before returning 401. Handles Cognito key rotation without restart. |
| 5 | String boolean columns | Changed `is_active` and `onboarding_complete` from `Column(String)` to `Column(Boolean)`. Removed all `== "true"` string comparisons. |
| 6 | Client-provided `auth_provider` | Removed `auth_provider` from `SyncRequest` body. Added `_derive_auth_provider()` that inspects Cognito token claims (`identities` for Google, `phone_number_verified` for phone, fallback to email). |
| 7 | Brittle subject filter | Added denormalized `subject` column to `sessions` table. Populated at creation from the guideline's subject field. History filtering uses exact column match instead of `goal_json.contains()`. |

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Architecture Decisions](#2-architecture-decisions)
3. [Implementation Phases](#3-implementation-phases)
4. [Phase 1: AWS Cognito + Infrastructure](#phase-1-aws-cognito--infrastructure)
5. [Phase 2: Backend Auth Module](#phase-2-backend-auth-module)
6. [Phase 3: Backend Profile + Session Linking](#phase-3-backend-profile--session-linking)
7. [Phase 4: Frontend Auth Screens](#phase-4-frontend-auth-screens)
8. [Phase 5: Frontend Profile + Onboarding](#phase-5-frontend-profile--onboarding)
9. [Phase 6: Tutor Personalization Integration](#phase-6-tutor-personalization-integration)
10. [Phase 7: Session History](#phase-7-session-history)
11. [Database Migration Strategy](#database-migration-strategy)
12. [Testing Strategy](#testing-strategy)
13. [Rollout Plan](#rollout-plan)
14. [File Index](#file-index)

---

## 1. Current State Analysis

### What exists today

| Area | Current State | Impact |
|------|--------------|--------|
| **Authentication** | None. No auth anywhere in the stack. | All endpoints are public. |
| **User identity** | Anonymous. `student_json` in sessions stores `{id: "s1", grade: 3, prefs: {style, lang}}` — hardcoded in frontend. | No persistence across visits. |
| **Session ownership** | Sessions table has no `user_id`. Sessions keyed by UUID, no way to list "my sessions". | No history, no continuity. |
| **Profile data** | `COUNTRY`, `BOARD`, `GRADE` are constants in `TutorApp.tsx` (lines 49-51). | No personalization. |
| **Frontend routing** | React Router v7 exists in `App.tsx` with routes for `/` (tutor) and `/admin/*`. No auth guards. | Need to add auth routes + protected routes. |
| **Infrastructure** | AWS: App Runner, Aurora PostgreSQL, S3+CloudFront, ECR, Secrets Manager. Terraform modules for each. No Cognito. | Cognito must be added to Terraform. |
| **Backend framework** | FastAPI with Pydantic models, SQLAlchemy ORM, modular structure (API → Service → Repository). | Auth module follows same pattern. |

### Key files that need changes

| File | What Changes |
|------|-------------|
| `llm-backend/shared/models/entities.py` | Add `User` ORM model, add `user_id` FK to `Session` |
| `llm-backend/main.py` | Register auth router, add auth middleware |
| `llm-backend/config.py` | Add Cognito config settings |
| `llm-backend/tutor/services/session_service.py` | Read profile for `student_context`, set `user_id` on sessions |
| `llm-backend/tutor/api/sessions.py` | Inject `current_user` dependency |
| `llm-backend/tutor/prompts/master_tutor_prompts.py` | Inject student name, age, about_me |
| `llm-frontend/src/App.tsx` | Add auth routes, AuthProvider, ProtectedRoute |
| `llm-frontend/src/TutorApp.tsx` | Remove hardcoded COUNTRY/BOARD/GRADE, read from profile |
| `infra/terraform/main.tf` | Add Cognito module |

---

## 2. Architecture Decisions

### AD-1: AWS Cognito as auth provider

**Decision:** Use AWS Cognito User Pools for all authentication.

**Rationale:**
- Already fully on AWS (App Runner, Aurora, S3, CloudFront, Secrets Manager)
- Cognito handles: user pool, phone OTP (via SNS), email verification (via SES), Google OAuth federation, JWT issuance
- No additional vendor dependency (vs Firebase Auth)
- JWT validation can be done server-side with `python-jose` + Cognito JWKS endpoint

**What Cognito manages vs what we manage:**

| Cognito manages | We manage (in our DB) |
|----------------|----------------------|
| Email, phone, password hash | Profile: name, age, grade, board, school_name, about_me |
| Google OAuth linking | `cognito_sub` FK linking Cognito user → our `users` table |
| JWT tokens (access + refresh) | Session ownership (`user_id` on `sessions`) |
| OTP delivery (SNS) | Onboarding flow state |
| Email verification (SES) | Session history queries |

### AD-2: Thin backend auth layer

**Decision:** Backend validates Cognito JWTs but does NOT proxy auth operations. The frontend calls Cognito directly via `amazon-cognito-identity-js` (or AWS Amplify Auth).

**Why:**
- Cognito has a well-supported JS SDK for signup, login, OTP, OAuth
- Eliminates 9 auth endpoints from our backend (signup, login, send-otp, verify-otp, google, refresh, logout, forgot-password, reset-password)
- Backend only needs: (1) JWT validation middleware, (2) a "sync profile" endpoint that creates/updates the `users` row on first login
- Fewer moving parts, fewer things to break

**Revised backend auth endpoints (replaces PRD section 7.1):**

| Method | Path | Token Type | Description |
|--------|------|-----------|-------------|
| POST | `/auth/sync` | **ID token** | Called after Cognito login; creates/updates user row in our DB. Uses ID token because it contains `email`, `phone_number`, `name` claims needed for sync. |
| GET | `/profile` | Access token | Get current user's profile |
| PUT | `/profile` | Access token | Update profile fields |
| PUT | `/profile/password` | Access token | Change password (proxies to Cognito) |

**Token contract (important):**
- **ID token** (`token_use: "id"`): Contains user attributes (email, phone, name). Has `aud` claim = app client ID. Used only for `/auth/sync`.
- **Access token** (`token_use: "access"`): Authorizes API calls. Has `client_id` claim (not `aud`). Used for all other authenticated endpoints.
- The middleware MUST validate `token_use` to ensure the correct token type is used per endpoint.

All other auth operations (signup, login, OTP, Google OAuth, forgot password, token refresh) happen client-side via the Cognito SDK.

### AD-3: Auth module structure

**Decision:** Create a new top-level `auth/` module following the existing codebase conventions.

```
llm-backend/
├── auth/                    # NEW MODULE
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth_routes.py    # /auth/sync (auth operations)
│   │   └── profile_routes.py # /profile, /profile/password (separate router)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py   # JWT validation, user sync
│   │   └── profile_service.py # Profile CRUD
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── user_repository.py # User table CRUD
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py        # Pydantic request/response models
│   └── middleware/
│       ├── __init__.py
│       └── auth_middleware.py # get_current_user dependency
```

**Path mapping (two separate routers to avoid prefix confusion):**

| Router file | Prefix | Endpoints |
|------------|--------|-----------|
| `auth_routes.py` | `/auth` | `POST /auth/sync` |
| `profile_routes.py` | `/profile` | `GET /profile`, `PUT /profile`, `PUT /profile/password` |

### AD-4: Frontend auth approach

**Decision:** Use `amazon-cognito-identity-js` (lightweight, ~50KB) instead of full AWS Amplify (~200KB+).

**Why:**
- We only need auth, not Analytics/Storage/PubSub
- Smaller bundle size
- More control over UX (Amplify's pre-built UI components don't match our UX principles)
- The SDK handles: SRP auth, token refresh, OTP flows, OAuth redirect

### AD-5: Profile-first onboarding

**Decision:** After Cognito signup/login, if the user has no profile in our DB (first login), redirect to onboarding wizard before allowing access to the tutor.

**Flow:**
```
Cognito signup/login → /auth/sync → if no profile → redirect to /onboarding
                                   → if profile exists → redirect to /
```

---

## 3. Implementation Phases

```
Phase 1: AWS Cognito + Infrastructure        (Terraform, no code)
Phase 2: Backend Auth Module                  (JWT middleware, user sync)
Phase 3: Backend Profile + Session Linking    (Profile CRUD, user_id on sessions)
Phase 4: Frontend Auth Screens                (Login, signup, OTP, Google)
Phase 5: Frontend Profile + Onboarding        (Onboarding wizard, profile page)
Phase 6: Tutor Personalization Integration    (Name, age, about_me in prompts)
Phase 7: Session History                      (History API, My Sessions page)
```

Each phase is independently deployable. Phases 2-3 can be developed in parallel with Phase 4-5.

---

## Phase 1: AWS Cognito + Infrastructure

### Goal
Provision Cognito User Pool, configure auth methods, and wire up secrets.

### 1.1 New Terraform module: `infra/terraform/modules/cognito/`

**Files to create:**

#### `modules/cognito/main.tf`

```hcl
resource "aws_cognito_user_pool" "main" {
  name = "${var.project_name}-${var.environment}"

  # Username config — allow email and phone as sign-in
  username_attributes = ["email", "phone_number"]
  auto_verified_attributes = ["email", "phone_number"]

  # Password policy
  password_policy {
    minimum_length    = 8
    require_lowercase = false
    require_numbers   = false
    require_symbols   = false
    require_uppercase = false
  }

  # MFA (OTP via SMS)
  mfa_configuration = "OPTIONAL"
  sms_configuration {
    external_id    = "${var.project_name}-cognito-sms"
    sns_caller_arn = aws_iam_role.cognito_sms.arn
    sns_region     = var.aws_region
  }

  # Email configuration (SES for production)
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"  # Switch to SES for production
  }

  # Schema: name is NOT required at Cognito level because phone OTP signup
  # does not collect a name. Name is collected during our onboarding wizard
  # (Phase 5) and stored in our users table, not in Cognito.
  schema {
    name                = "name"
    attribute_data_type = "String"
    mutable             = true
    required            = false
  }

  # Lambda triggers (future: post-confirmation, pre-sign-up)
  # lambda_config { ... }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
    recovery_mechanism {
      name     = "verified_phone_number"
      priority = 2
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# App client (for frontend)
resource "aws_cognito_user_pool_client" "frontend" {
  name         = "${var.project_name}-frontend"
  user_pool_id = aws_cognito_user_pool.main.id

  # No client secret (public client for SPA)
  generate_secret = false

  # Auth flows
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_CUSTOM_AUTH",
    "ALLOW_USER_PASSWORD_AUTH",
  ]

  # Token validity
  access_token_validity  = 15   # minutes
  id_token_validity      = 15   # minutes
  refresh_token_validity = 30   # days

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  # OAuth for Google
  supported_identity_providers = ["COGNITO", "Google"]
  allowed_oauth_flows          = ["code"]
  allowed_oauth_scopes         = ["email", "openid", "profile"]
  allowed_oauth_flows_user_pool_client = true
  callback_urls = var.callback_urls
  logout_urls   = var.logout_urls
}

# Google identity provider
resource "aws_cognito_identity_provider" "google" {
  user_pool_id  = aws_cognito_user_pool.main.id
  provider_name = "Google"
  provider_type = "Google"

  provider_details = {
    client_id        = var.google_client_id
    client_secret    = var.google_client_secret
    authorize_scopes = "email profile openid"
  }

  attribute_mapping = {
    email    = "email"
    name     = "name"
    username = "sub"
  }
}

# IAM role for Cognito SMS (SNS)
resource "aws_iam_role" "cognito_sms" {
  name = "${var.project_name}-cognito-sms-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "cognito-idp.amazonaws.com" }
      Condition = {
        StringEquals = {
          "sts:ExternalId" = "${var.project_name}-cognito-sms"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "cognito_sms" {
  name = "cognito-sms-publish"
  role = aws_iam_role.cognito_sms.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action   = "sns:Publish"
      Effect   = "Allow"
      Resource = "*"
    }]
  })
}

# Cognito domain (for hosted UI / OAuth redirect)
resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.project_name}-${var.environment}"
  user_pool_id = aws_cognito_user_pool.main.id
}
```

#### `modules/cognito/variables.tf`

```hcl
variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "google_client_id" { type = string }
variable "google_client_secret" { type = string; sensitive = true }
variable "callback_urls" { type = list(string) }
variable "logout_urls" { type = list(string) }
```

#### `modules/cognito/outputs.tf`

```hcl
output "user_pool_id" { value = aws_cognito_user_pool.main.id }
output "user_pool_arn" { value = aws_cognito_user_pool.main.arn }
output "client_id" { value = aws_cognito_user_pool_client.frontend.id }
output "domain" { value = aws_cognito_user_pool_domain.main.domain }
output "endpoint" { value = aws_cognito_user_pool.main.endpoint }
```

### 1.2 Wire into root `main.tf`

Add to `infra/terraform/main.tf`:

```hcl
module "cognito" {
  source = "./modules/cognito"

  project_name         = var.project_name
  environment          = var.environment
  aws_region           = var.aws_region
  google_client_id     = var.google_client_id
  google_client_secret = var.google_client_secret
  callback_urls        = ["https://${module.frontend.cloudfront_domain}/auth/callback", "http://localhost:5173/auth/callback"]
  logout_urls          = ["https://${module.frontend.cloudfront_domain}/login", "http://localhost:5173/login"]
}
```

### 1.3 Pass Cognito config to App Runner

Update `modules/app-runner/main.tf` to pass env vars:
- `COGNITO_USER_POOL_ID`
- `COGNITO_APP_CLIENT_ID`
- `COGNITO_REGION`

Update `modules/frontend/main.tf` to set CloudFront env vars (or build-time vars):
- `VITE_COGNITO_USER_POOL_ID`
- `VITE_COGNITO_APP_CLIENT_ID`
- `VITE_COGNITO_REGION`
- `VITE_COGNITO_DOMAIN`

### 1.4 New Terraform variables

Add to `variables.tf`:
```hcl
variable "google_client_id" { type = string; default = "" }
variable "google_client_secret" { type = string; default = ""; sensitive = true }
```

### 1.5 Google OAuth setup (manual)

Documented in the existing `SETUP_GUIDE.md`:
1. Create Google Cloud project
2. Configure OAuth consent screen
3. Create OAuth 2.0 client ID (Web application)
4. Set authorized redirect URIs to Cognito domain
5. Copy client ID and secret to Terraform variables

---

## Phase 2: Backend Auth Module

### Goal
Add JWT validation middleware and user sync endpoint so the backend can identify authenticated users.

### 2.1 New dependencies

Add to `requirements.txt`:
```
python-jose[cryptography]>=3.3.0
```

### 2.2 Config additions

Add to `config.py` (`Settings` class):

```python
# Cognito Configuration
cognito_user_pool_id: str = Field(
    default="",
    description="AWS Cognito User Pool ID"
)
cognito_app_client_id: str = Field(
    default="",
    description="AWS Cognito App Client ID"
)
cognito_region: str = Field(
    default="us-east-1",
    description="AWS Cognito region"
)
```

### 2.3 Auth middleware: `auth/middleware/auth_middleware.py`

This is the core piece — a FastAPI dependency that validates Cognito JWTs.

```python
"""
JWT validation middleware for AWS Cognito tokens.

Token types:
  - Access token (token_use="access"): Used for all API calls. Has `client_id` claim.
  - ID token (token_use="id"): Used only for /auth/sync. Has `aud` claim + user attributes.

Usage:
    @router.get("/protected")
    def protected_endpoint(current_user: User = Depends(get_current_user)):
        return {"user_id": current_user.id}
"""

import logging
import time
from typing import Optional, Literal
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import httpx

from config import get_settings
from auth.repositories.user_repository import UserRepository
from database import get_db
from sqlalchemy.orm import Session as DBSession

logger = logging.getLogger("auth.middleware")

security = HTTPBearer(auto_error=False)

# JWKS cache with TTL
_jwks_cache: Optional[dict] = None
_jwks_fetched_at: float = 0
JWKS_TTL_SECONDS = 3600  # Re-fetch keys every hour


async def _get_jwks(force_refresh: bool = False) -> dict:
    """
    Fetch and cache Cognito JWKS (JSON Web Key Set).

    Uses a TTL-based cache (1 hour) with refresh-on-miss:
    - Normal: serve from cache if within TTL
    - force_refresh=True: bypass cache (used when kid not found, indicating key rotation)
    """
    global _jwks_cache, _jwks_fetched_at
    now = time.time()

    if _jwks_cache and not force_refresh and (now - _jwks_fetched_at < JWKS_TTL_SECONDS):
        return _jwks_cache

    settings = get_settings()
    jwks_url = (
        f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
        f"{settings.cognito_user_pool_id}/.well-known/jwks.json"
    )

    async with httpx.AsyncClient() as client:
        response = await client.get(jwks_url)
        _jwks_cache = response.json()
        _jwks_fetched_at = now

    logger.info("JWKS cache refreshed")
    return _jwks_cache


async def _verify_cognito_token(
    token: str,
    expected_token_use: Literal["access", "id"] = "access",
) -> dict:
    """
    Verify a Cognito JWT and return claims.

    Args:
        token: The JWT string
        expected_token_use: "access" for API calls, "id" for /auth/sync
    """
    settings = get_settings()
    jwks = await _get_jwks()

    # Decode header to get key ID
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")

    # Find matching key
    key = None
    for k in jwks.get("keys", []):
        if k["kid"] == kid:
            key = k
            break

    # Key not found — might be a key rotation. Refresh JWKS once and retry.
    if not key:
        logger.warning(f"kid '{kid}' not found in JWKS cache, refreshing...")
        jwks = await _get_jwks(force_refresh=True)
        for k in jwks.get("keys", []):
            if k["kid"] == kid:
                key = k
                break

    if not key:
        raise HTTPException(status_code=401, detail="Invalid token: key not found after refresh")

    # Verify token — audience/client_id validation differs by token type
    issuer = f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/{settings.cognito_user_pool_id}"

    try:
        if expected_token_use == "id":
            # ID tokens have `aud` = app client ID
            claims = jwt.decode(
                token, key, algorithms=["RS256"],
                audience=settings.cognito_app_client_id,
                issuer=issuer,
            )
        else:
            # Access tokens have `client_id` (not `aud`) — skip audience check in decode,
            # validate client_id manually after
            claims = jwt.decode(
                token, key, algorithms=["RS256"],
                issuer=issuer,
                options={"verify_aud": False},
            )
            if claims.get("client_id") != settings.cognito_app_client_id:
                raise HTTPException(status_code=401, detail="Invalid token: wrong client_id")
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # Validate token_use claim
    actual_token_use = claims.get("token_use")
    if actual_token_use != expected_token_use:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid token: expected token_use='{expected_token_use}', got '{actual_token_use}'"
        )

    return claims


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: DBSession = Depends(get_db),
):
    """
    FastAPI dependency: extract and validate access token, return User from DB.
    Raises 401 if token is missing or invalid.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    claims = await _verify_cognito_token(credentials.credentials, expected_token_use="access")
    cognito_sub = claims.get("sub")

    if not cognito_sub:
        raise HTTPException(status_code=401, detail="Invalid token: no sub claim")

    # Look up user in our DB
    repo = UserRepository(db)
    user = repo.get_by_cognito_sub(cognito_sub)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found. Call /auth/sync first."
        )

    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: DBSession = Depends(get_db),
):
    """
    Same as get_current_user but returns None instead of 401 for unauthenticated.
    Use for endpoints that work for both authenticated and anonymous users.
    """
    if not credentials:
        return None

    try:
        claims = await _verify_cognito_token(credentials.credentials, expected_token_use="access")
        cognito_sub = claims.get("sub")
        if cognito_sub:
            repo = UserRepository(db)
            return repo.get_by_cognito_sub(cognito_sub)
    except HTTPException:
        pass

    return None
```

### 2.4 User ORM model

Add to `shared/models/entities.py`:

```python
from sqlalchemy import Boolean

class User(Base):
    """User table - stores student profiles linked to Cognito."""
    __tablename__ = "users"

    id = Column(String, primary_key=True)          # UUID
    cognito_sub = Column(String, unique=True, nullable=False)  # Cognito user UUID
    email = Column(String, unique=True, nullable=True)
    phone = Column(String, unique=True, nullable=True)
    auth_provider = Column(String, nullable=False)  # 'email', 'phone', 'google' (derived server-side)
    name = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    grade = Column(Integer, nullable=True)
    board = Column(String, nullable=True)
    school_name = Column(String, nullable=True)
    about_me = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    onboarding_complete = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    sessions = relationship("Session", back_populates="user")

    __table_args__ = (
        Index("idx_cognito_sub", "cognito_sub"),
        Index("idx_user_email", "email"),
    )
```

Add `user_id` FK and denormalized `subject` column to existing `Session` model:

```python
class Session(Base):
    # ... existing fields ...
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    # nullable=True preserves existing anonymous sessions

    # Denormalized subject for efficient filtering in session history.
    # Populated at session creation from goal_json. Avoids brittle
    # substring matching on JSON text (e.g. goal_json.contains("Math")
    # would also match "Mathematics" or unrelated fields).
    subject = Column(String, nullable=True)

    user = relationship("User", back_populates="sessions")
```

### 2.5 User repository: `auth/repositories/user_repository.py`

```python
"""User data access layer."""

from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlalchemy.orm import Session as DBSession
from shared.models.entities import User


class UserRepository:
    """CRUD operations for the users table."""

    def __init__(self, db: DBSession):
        self.db = db

    def get_by_id(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def get_by_cognito_sub(self, cognito_sub: str) -> Optional[User]:
        return self.db.query(User).filter(User.cognito_sub == cognito_sub).first()

    def get_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(User.email == email).first()

    def create(self, cognito_sub: str, email: Optional[str], phone: Optional[str],
               auth_provider: str, name: Optional[str] = None) -> User:
        user = User(
            id=str(uuid4()),
            cognito_sub=cognito_sub,
            email=email,
            phone=phone,
            auth_provider=auth_provider,
            name=name,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            last_login_at=datetime.utcnow(),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_profile(self, user_id: str, **fields) -> Optional[User]:
        user = self.get_by_id(user_id)
        if not user:
            return None
        for key, value in fields.items():
            if hasattr(user, key):
                setattr(user, key, value)
        user.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_last_login(self, user_id: str) -> None:
        user = self.get_by_id(user_id)
        if user:
            user.last_login_at = datetime.utcnow()
            self.db.commit()
```

### 2.6 Auth service: `auth/services/auth_service.py`

```python
"""Auth service — handles user sync from Cognito."""

import logging
from typing import Optional
from sqlalchemy.orm import Session as DBSession
from auth.repositories.user_repository import UserRepository

logger = logging.getLogger("auth.service")


class AuthService:
    """Syncs Cognito users to local DB on first login."""

    def __init__(self, db: DBSession):
        self.db = db
        self.user_repo = UserRepository(db)

    @staticmethod
    def _derive_auth_provider(claims: dict) -> str:
        """
        Derive auth_provider from Cognito token claims (server-side).

        This is NOT taken from the client request body to prevent spoofing.

        Cognito claim inspection:
        - Google federated users have an `identities` claim with providerName="Google"
        - Phone users have `phone_number_verified=true` and cognito:username starts with "+"
        - Email users have `email_verified=true` as default fallback
        """
        # Check for federated identity (Google OAuth)
        identities = claims.get("identities", [])
        if identities:
            provider = identities[0].get("providerName", "")
            if provider == "Google":
                return "google"

        # Check for phone-based signup
        if claims.get("phone_number_verified"):
            return "phone"
        username = claims.get("cognito:username", "")
        if username.startswith("+"):
            return "phone"

        # Default: email
        return "email"

    def sync_user(self, claims: dict):
        """
        Create or update user record after Cognito authentication.
        Called from /auth/sync endpoint with the full decoded ID token claims.
        """
        cognito_sub = claims["sub"]
        email = claims.get("email")
        phone = claims.get("phone_number")
        name = claims.get("name")
        auth_provider = self._derive_auth_provider(claims)

        existing = self.user_repo.get_by_cognito_sub(cognito_sub)

        if existing:
            # Update last login, merge any new data
            self.user_repo.update_last_login(existing.id)
            if email and not existing.email:
                self.user_repo.update_profile(existing.id, email=email)
            if phone and not existing.phone:
                self.user_repo.update_profile(existing.id, phone=phone)
            return existing
        else:
            # First login — create user row
            return self.user_repo.create(
                cognito_sub=cognito_sub,
                email=email,
                phone=phone,
                auth_provider=auth_provider,
                name=name,
            )
```

### 2.7 Auth API routes: `auth/api/auth_routes.py`

```python
"""Auth API endpoints — sync Cognito user to local DB."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel
from typing import Optional

from database import get_db
from auth.services.auth_service import AuthService
from auth.middleware.auth_middleware import _verify_cognito_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()


class UserProfileResponse(BaseModel):
    id: str
    email: Optional[str]
    phone: Optional[str]
    name: Optional[str]
    age: Optional[int]
    grade: Optional[int]
    board: Optional[str]
    school_name: Optional[str]
    about_me: Optional[str]
    onboarding_complete: bool
    auth_provider: str


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
```

### 2.8 Register routers in `main.py`

```python
from auth.api.auth_routes import router as auth_router
from auth.api.profile_routes import router as profile_router

app.include_router(auth_router)      # /auth/sync
app.include_router(profile_router)   # /profile, /profile/password
```

---

## Phase 3: Backend Profile + Session Linking

### Goal
Profile CRUD, onboarding completion tracking, link sessions to users.

### 3.1 Profile service: `auth/services/profile_service.py`

```python
"""Profile management service."""

from typing import Optional
from sqlalchemy.orm import Session as DBSession
from auth.repositories.user_repository import UserRepository


class ProfileService:
    """Business logic for profile operations."""

    def __init__(self, db: DBSession):
        self.db = db
        self.user_repo = UserRepository(db)

    def get_profile(self, user_id: str):
        return self.user_repo.get_by_id(user_id)

    def update_profile(self, user_id: str, name: Optional[str] = None,
                       age: Optional[int] = None, grade: Optional[int] = None,
                       board: Optional[str] = None, school_name: Optional[str] = None,
                       about_me: Optional[str] = None):
        fields = {}
        if name is not None: fields["name"] = name
        if age is not None: fields["age"] = age
        if grade is not None: fields["grade"] = grade
        if board is not None: fields["board"] = board
        if school_name is not None: fields["school_name"] = school_name
        if about_me is not None: fields["about_me"] = about_me

        user = self.user_repo.update_profile(user_id, **fields)

        # Check if onboarding is now complete (all required fields filled)
        if user and user.name and user.age and user.grade and user.board:
            if not user.onboarding_complete:
                self.user_repo.update_profile(user_id, onboarding_complete=True)
                user.onboarding_complete = True

        return user
```

### 3.2 Profile API: `auth/api/profile_routes.py`

Profile endpoints live under their own `/profile` prefix (separate from `/auth`) to keep paths clean and intuitive for frontend developers.

```python
"""Profile API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel
from typing import Optional

from database import get_db
from auth.services.profile_service import ProfileService
from auth.middleware.auth_middleware import get_current_user
from auth.api.auth_routes import UserProfileResponse  # Shared response model

router = APIRouter(prefix="/profile", tags=["profile"])


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    grade: Optional[int] = None
    board: Optional[str] = None
    school_name: Optional[str] = None
    about_me: Optional[str] = None


@router.get("", response_model=UserProfileResponse)
async def get_profile(current_user = Depends(get_current_user)):
    """Get the current user's profile."""
    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        phone=current_user.phone,
        name=current_user.name,
        age=current_user.age,
        grade=current_user.grade,
        board=current_user.board,
        school_name=current_user.school_name,
        about_me=current_user.about_me,
        onboarding_complete=current_user.onboarding_complete,
        auth_provider=current_user.auth_provider,
    )


@router.put("", response_model=UserProfileResponse)
async def update_profile(
    request: UpdateProfileRequest,
    current_user = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Update the current user's profile."""
    service = ProfileService(db)
    user = service.update_profile(
        user_id=current_user.id,
        name=request.name,
        age=request.age,
        grade=request.grade,
        board=request.board,
        school_name=request.school_name,
        about_me=request.about_me,
    )
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
```

### 3.3 Modify session creation to link user

In `tutor/services/session_service.py`, modify `_persist_session`:

```python
def _persist_session(self, session_id, session, request, user_id=None):
    # Extract subject from goal for denormalized column (enables efficient history filtering)
    subject = None
    if hasattr(request.goal, 'syllabus') and request.goal.syllabus:
        # syllabus is e.g. "CBSE-G3", topic is e.g. "Fractions"
        # The actual subject comes from the curriculum selection flow
        pass
    # Prefer reading from the guideline's subject field
    if request.goal.guideline_id:
        guideline = self.guideline_repo.get_guideline_by_id(request.goal.guideline_id)
        if guideline:
            subject = guideline.subject  # e.g. "Mathematics"

    db_record = SessionModel(
        id=session_id,
        student_json=request.student.model_dump_json(),
        goal_json=request.goal.model_dump_json(),
        state_json=session.model_dump_json(),
        mastery=session.overall_mastery,
        step_idx=session.current_step,
        user_id=user_id,    # NEW: link session to user
        subject=subject,    # NEW: denormalized for history filtering
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
```

### 3.4 Modify session API to inject user

In `tutor/api/sessions.py`, add optional user dependency:

```python
from auth.middleware.auth_middleware import get_optional_user

@router.post("", response_model=CreateSessionResponse)
def create_session(
    request: CreateSessionRequest,
    db: DBSession = Depends(get_db),
    current_user = Depends(get_optional_user),  # NEW
):
    service = SessionService(db)
    return service.create_new_session(
        request,
        user_id=current_user.id if current_user else None
    )
```

### 3.5 Build student context from profile

When `current_user` is present, override the request's student data with the profile:

```python
# In SessionService.create_new_session():
if user_id and self.user_repo:
    user = self.user_repo.get_by_id(user_id)
    if user:
        student_context = StudentContext(
            grade=user.grade,
            board=user.board or "CBSE",
            language_level="simple" if user.age and user.age <= 10 else "standard",
        )
```

---

## Phase 4: Frontend Auth Screens

### Goal
Login/signup screens, Cognito SDK integration, auth state management.

### 4.1 New dependencies

```bash
npm install amazon-cognito-identity-js
```

### 4.2 Auth configuration: `src/config/auth.ts`

```typescript
export const cognitoConfig = {
  UserPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
  ClientId: import.meta.env.VITE_COGNITO_APP_CLIENT_ID,
  Region: import.meta.env.VITE_COGNITO_REGION,
  Domain: import.meta.env.VITE_COGNITO_DOMAIN,
};
```

### 4.3 Auth context: `src/contexts/AuthContext.tsx`

```typescript
/**
 * AuthContext — global auth state for the app.
 *
 * Provides:
 * - user: current user profile (or null)
 * - isAuthenticated: boolean
 * - isLoading: boolean (true during initial token check)
 * - login/signup/logout functions
 * - token: current JWT for API calls
 */

interface AuthContextType {
  user: UserProfile | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  needsOnboarding: boolean;
  loginWithEmail: (email: string, password: string) => Promise<void>;
  signupWithEmail: (email: string, password: string) => Promise<void>;
  sendOTP: (phone: string) => Promise<void>;
  verifyOTP: (phone: string, code: string) => Promise<void>;
  loginWithGoogle: () => void;
  logout: () => void;
  refreshProfile: () => Promise<void>;
}
```

**Key behaviors:**
- On mount, check if Cognito session exists (auto-refresh)
- After any login/signup, call `POST /auth/sync` to create/update the user row
- Store user profile in React state
- Expose `token` for API calls
- Track `needsOnboarding` flag

### 4.4 API client updates: `src/api.ts`

Add auth header to all requests:

```typescript
const getAuthHeaders = (): Record<string, string> => {
  const token = getStoredToken(); // from AuthContext or localStorage
  if (token) {
    return { Authorization: `Bearer ${token}` };
  }
  return {};
};

// Update all fetch calls to include auth headers
const apiFetch = async (path: string, options: RequestInit = {}) => {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...options.headers,
    },
  });

  if (response.status === 401) {
    // Token expired — try refresh, then redirect to login
    window.location.href = '/login';
  }

  return response;
};
```

### 4.5 New pages and components

| File | Purpose |
|------|---------|
| `src/pages/LoginPage.tsx` | Welcome screen: logo, tagline, 3 auth buttons |
| `src/pages/PhoneLoginPage.tsx` | Phone number input + country code selector |
| `src/pages/OTPVerifyPage.tsx` | 6-digit OTP input, auto-submit |
| `src/pages/EmailSignupPage.tsx` | Email + password signup form |
| `src/pages/EmailLoginPage.tsx` | Email + password login form |
| `src/pages/ForgotPasswordPage.tsx` | Password reset flow |
| `src/components/ProtectedRoute.tsx` | Route guard — redirects to `/login` if unauthenticated |
| `src/components/OnboardingGuard.tsx` | Route guard — redirects to `/onboarding` if profile incomplete |

### 4.6 Updated routing: `src/App.tsx`

```tsx
function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public auth routes */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/login/phone" element={<PhoneLoginPage />} />
          <Route path="/login/phone/verify" element={<OTPVerifyPage />} />
          <Route path="/login/email" element={<EmailLoginPage />} />
          <Route path="/signup/email" element={<EmailSignupPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/auth/callback" element={<OAuthCallbackPage />} />

          {/* Onboarding (authenticated but profile incomplete) */}
          <Route path="/onboarding" element={
            <ProtectedRoute>
              <OnboardingFlow />
            </ProtectedRoute>
          } />

          {/* Protected routes */}
          <Route path="/" element={
            <ProtectedRoute>
              <OnboardingGuard>
                <TutorApp />
              </OnboardingGuard>
            </ProtectedRoute>
          } />

          <Route path="/profile" element={
            <ProtectedRoute>
              <ProfilePage />
            </ProtectedRoute>
          } />

          <Route path="/history" element={
            <ProtectedRoute>
              <SessionHistoryPage />
            </ProtectedRoute>
          } />

          {/* Admin routes (unchanged for now) */}
          <Route path="/admin/*" element={/* ... existing admin routes */} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
```

### 4.7 UX implementation notes

Per PRD UX principles and `docs/UX_PRINCIPLES.md`:

| Principle | Implementation |
|-----------|---------------|
| One thing per screen | Each auth step is its own route/page |
| Minimal typing | Auto-detect country code (via IP geolocation or browser locale), auto-advance OTP digits, auto-submit on 6th digit |
| Friendly language | "Continue with Phone", not "Phone Authentication". "What's your phone number?" not "Enter phone" |
| Forgiving inputs | Strip spaces/dashes from phone numbers before sending. Inline validation. |
| Fast | Cognito SDK handles token refresh in background. Pre-warm JWKS cache. |
| Mobile-first | Min 44px tap targets, full-width inputs, large buttons, no hover states |
| Warm | Success: "You're all set! Let's start learning." Error: "Hmm, that didn't work. Let's try again." |

---

## Phase 5: Frontend Profile + Onboarding

### Goal
Post-signup wizard to collect name/age/grade/board, profile settings page.

### 5.1 Onboarding flow: `src/pages/OnboardingFlow.tsx`

A multi-step wizard with one question per screen:

```
Step 1: "What's your name?" → text input
Step 2: "How old are you?" → number picker (5-18)
Step 3: "What grade are you in?" → grade selector (1-12)
Step 4: "What's your school board?" → dropdown (CBSE, ICSE, State Board, Other)
Step 5: "Tell us about yourself!" → textarea + prominent "Skip for now" button
Done: "You're all set, {name}! Let's start learning." → redirect to /
```

Each step calls `PUT /profile` individually (not batched) so progress is saved even if the user closes the app mid-onboarding.

### 5.2 Profile settings page: `src/pages/ProfilePage.tsx`

Accessible from user icon in nav bar. Contains:
- View/edit all profile fields (same form as onboarding but editable)
- Linked accounts section (show connected auth methods)
- Change password (email users only, proxied through Cognito SDK)
- Logout button

### 5.3 Nav bar updates

Add to the header in `TutorApp.tsx`:
- User avatar/initial in top-right
- Dropdown menu: "Profile", "My Sessions", "Logout"

### 5.4 Remove hardcoded profile values

In `TutorApp.tsx`, replace:
```typescript
// REMOVE these:
const COUNTRY = 'India';
const BOARD = 'CBSE';
const GRADE = 3;

// REPLACE with:
const { user } = useAuth();
const BOARD = user?.board || 'CBSE';
const GRADE = user?.grade || 3;
const COUNTRY = 'India'; // Keep for now, add to profile later if needed
```

---

## Phase 6: Tutor Personalization Integration

### Goal
Use profile data (name, age, about_me) to personalize tutoring sessions.

### 6.1 Extend `StudentContext` model

In `tutor/models/messages.py`, add fields:

```python
class StudentContext(BaseModel):
    grade: int
    board: str = "CBSE"
    language_level: Literal["simple", "standard", "advanced"] = "simple"
    preferred_examples: list[str] = Field(default_factory=lambda: ["food", "sports", "games"])
    # NEW personalization fields
    student_name: Optional[str] = None
    student_age: Optional[int] = None
    about_me: Optional[str] = None
```

### 6.2 Modify session creation to populate from profile

In `session_service.py`:

```python
def create_new_session(self, request, user_id=None):
    # ... existing code ...

    if user_id:
        user = UserRepository(self.db).get_by_id(user_id)
        if user:
            student_context = StudentContext(
                grade=user.grade or request.student.grade,
                board=user.board or "CBSE",
                language_level="simple" if (user.age and user.age <= 10) else "standard",
                student_name=user.name,
                student_age=user.age,
                about_me=user.about_me,
            )
```

### 6.3 Update master tutor system prompt

In `tutor/prompts/master_tutor_prompts.py`, add personalization block:

```python
MASTER_TUTOR_SYSTEM_PROMPT = PromptTemplate(
    """You are a warm, encouraging tutor teaching a Grade {grade} student.
Use {language_level} language. The student likes examples about: {preferred_examples}.

{personalization_block}

## Topic: {topic_name}
...
"""
)
```

Where `personalization_block` is built as:

```python
def build_personalization_block(ctx: StudentContext) -> str:
    lines = []
    if ctx.student_name:
        lines.append(f"The student's name is {ctx.student_name}. Address them by name.")
    if ctx.student_age:
        lines.append(f"The student is {ctx.student_age} years old.")
    if ctx.about_me:
        lines.append(f"About the student: {ctx.about_me}")
    if not lines:
        return ""
    return "## Student Profile\n" + "\n".join(lines)
```

---

## Phase 7: Session History

### Goal
API and UI for viewing past sessions, aggregated learning stats.

### 7.1 Session history API

Add to `tutor/api/sessions.py` or create a new `auth/api/history.py`:

```python
@router.get("/sessions/history")
def get_session_history(
    subject: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    current_user = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List current user's past sessions, paginated."""
    repo = SessionRepository(db)
    sessions = repo.list_by_user(
        user_id=current_user.id,
        subject=subject,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return {"sessions": sessions, "page": page, "page_size": page_size}
```

### 7.2 Session replay endpoint

```python
@router.get("/sessions/{session_id}/replay")
def get_session_replay(
    session_id: str,
    current_user = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get full conversation replay for a session owned by the current user."""
    repo = SessionRepository(db)
    session = repo.get_by_id(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your session")

    return json.loads(session.state_json)
```

### 7.3 Learning stats endpoint

```python
@router.get("/profile/stats")
def get_learning_stats(
    current_user = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Aggregated learning stats for the current user."""
    repo = SessionRepository(db)
    stats = repo.get_user_stats(current_user.id)
    return stats
```

### 7.4 Repository methods

Add to `shared/repositories/session_repository.py`:

```python
def list_by_user(self, user_id: str, subject: Optional[str] = None,
                 offset: int = 0, limit: int = 20):
    query = self.db.query(Session).filter(Session.user_id == user_id)
    if subject:
        # Use the denormalized subject column — exact match, indexable
        query = query.filter(Session.subject == subject)
    return query.order_by(Session.created_at.desc()).offset(offset).limit(limit).all()

def get_user_stats(self, user_id: str) -> dict:
    from sqlalchemy import func
    sessions = self.db.query(Session).filter(Session.user_id == user_id).all()
    if not sessions:
        return {"total_sessions": 0, "average_mastery": 0, "topics_covered": []}

    total = len(sessions)
    avg_mastery = sum(s.mastery or 0 for s in sessions) / total
    # Use denormalized subject column for distinct topics
    topics = set(s.subject for s in sessions if s.subject)

    return {
        "total_sessions": total,
        "average_mastery": round(avg_mastery, 2),
        "topics_covered": list(topics),
    }
```

### 7.5 Frontend: Session History page

New page `src/pages/SessionHistoryPage.tsx`:
- List view with columns: Subject/Topic, Date, Mastery indicator, Steps
- Click to open detail view (conversation replay)
- "Continue" / "Retry" button on detail view

### 7.6 Frontend: Stats on home/profile

Show aggregated stats (total sessions, topics, average mastery, study streak) on the profile page or home screen.

---

## Database Migration Strategy

### Migration approach

The project uses `db.py --migrate` with `Base.metadata.create_all()` (no Alembic). This approach auto-creates new tables and columns.

### Migration steps

1. **Add `User` model to `entities.py`** — `create_all()` creates the `users` table
2. **Add `user_id` column to `sessions`** — Requires a manual ALTER TABLE since `create_all()` doesn't add columns to existing tables

Manual migration SQL:

```sql
-- Phase 2: Create users table (handled by create_all)

-- Phase 3: Add user_id and subject to sessions (manual, since create_all
-- doesn't add columns to existing tables)
ALTER TABLE sessions ADD COLUMN user_id VARCHAR REFERENCES users(id);
ALTER TABLE sessions ADD COLUMN subject VARCHAR;
CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_subject ON sessions(subject);

-- Backfill subject for existing sessions (one-time)
-- This extracts subject from the linked guideline via goal_json's guideline_id
-- Can be run as a Python script if SQL JSON extraction is too complex
```

### Consider adding Alembic

For this feature and future schema changes, strongly consider adding Alembic for proper migration management:

```bash
pip install alembic
alembic init migrations
```

This is optional but recommended. If not using Alembic, document the manual SQL in a `migrations/` folder.

---

## Testing Strategy

### Backend tests

| Area | Test Type | What to Test |
|------|-----------|-------------|
| JWT middleware | Unit | Valid token → user returned; expired token → 401; missing token → 401; invalid signature → 401 |
| User repository | Unit | Create, get_by_cognito_sub, update_profile |
| Auth service | Unit | sync_user (new user), sync_user (existing user) |
| Profile service | Unit | update_profile, onboarding_complete flag logic |
| Auth API routes | Integration | POST /auth/sync, GET /profile, PUT /profile |
| Session linking | Integration | Create session with user_id, list sessions by user |
| Session history | Integration | Pagination, user-scoping (can't see other users' sessions) |

### Frontend tests

| Area | Test Type | What to Test |
|------|-----------|-------------|
| AuthContext | Unit | Login flow, token storage, auto-refresh |
| ProtectedRoute | Unit | Redirects when unauthenticated |
| OnboardingFlow | Integration | Step progression, form validation, API calls |
| LoginPage | Integration | Auth method buttons, error handling |

### Mocking strategy

- Mock Cognito JWKS endpoint in backend tests using `unittest.mock`
- Mock `amazon-cognito-identity-js` in frontend tests
- Use test JWTs signed with a known test key

---

## Rollout Plan

### Pre-launch checklist

- [ ] Cognito User Pool provisioned via Terraform
- [ ] Google OAuth configured and tested
- [ ] SNS phone OTP tested (requires AWS SNS sandbox exit for production)
- [ ] SES email configured (optional: use Cognito default email for MVP)
- [ ] CORS updated in `main.py` to restrict to actual domains
- [ ] Frontend env vars set in CI/CD (GitHub Actions secrets)
- [ ] Database migration run on production Aurora
- [ ] JWT validation tested with real Cognito tokens
- [ ] Load testing: Cognito token verification latency

### Feature flags / gradual rollout

Since this is a greenfield feature (no existing users), there's no migration of user data. Rollout is binary:

1. **Before launch:** All endpoints remain public, no auth middleware
2. **Launch:** Deploy all phases, enable auth middleware, existing anonymous sessions remain accessible but no new ones created
3. **Post-launch:** Monitor error rates, signup completion rate, onboarding completion rate

### Backward compatibility

- Existing anonymous sessions (no `user_id`) remain in the DB and accessible via direct session ID
- Admin routes (`/admin/*`) remain unauthenticated initially (admin auth is out of scope per PRD)
- The `get_optional_user` dependency allows graceful degradation during transition

---

## File Index

Complete list of new and modified files:

### New files

```
# Infrastructure
infra/terraform/modules/cognito/main.tf
infra/terraform/modules/cognito/variables.tf
infra/terraform/modules/cognito/outputs.tf

# Backend auth module
llm-backend/auth/__init__.py
llm-backend/auth/api/__init__.py
llm-backend/auth/api/auth_routes.py
llm-backend/auth/api/profile_routes.py
llm-backend/auth/services/__init__.py
llm-backend/auth/services/auth_service.py
llm-backend/auth/services/profile_service.py
llm-backend/auth/repositories/__init__.py
llm-backend/auth/repositories/user_repository.py
llm-backend/auth/models/__init__.py
llm-backend/auth/models/schemas.py
llm-backend/auth/middleware/__init__.py
llm-backend/auth/middleware/auth_middleware.py

# Frontend auth
llm-frontend/src/config/auth.ts
llm-frontend/src/contexts/AuthContext.tsx
llm-frontend/src/pages/LoginPage.tsx
llm-frontend/src/pages/PhoneLoginPage.tsx
llm-frontend/src/pages/OTPVerifyPage.tsx
llm-frontend/src/pages/EmailSignupPage.tsx
llm-frontend/src/pages/EmailLoginPage.tsx
llm-frontend/src/pages/ForgotPasswordPage.tsx
llm-frontend/src/pages/OAuthCallbackPage.tsx
llm-frontend/src/pages/OnboardingFlow.tsx
llm-frontend/src/pages/ProfilePage.tsx
llm-frontend/src/pages/SessionHistoryPage.tsx
llm-frontend/src/components/ProtectedRoute.tsx
llm-frontend/src/components/OnboardingGuard.tsx
```

### Modified files

```
# Infrastructure
infra/terraform/main.tf                          # Add cognito module
infra/terraform/variables.tf                     # Add google_client_id/secret vars
infra/terraform/modules/app-runner/main.tf       # Pass Cognito env vars
infra/terraform/modules/app-runner/variables.tf  # Add Cognito vars

# Backend
llm-backend/requirements.txt                     # Add python-jose
llm-backend/config.py                            # Add Cognito settings
llm-backend/main.py                              # Register auth router
llm-backend/shared/models/entities.py            # Add User model, user_id FK on Session
llm-backend/tutor/services/session_service.py    # User-aware session creation
llm-backend/tutor/api/sessions.py                # Inject current_user dependency
llm-backend/tutor/models/messages.py             # Extend StudentContext
llm-backend/tutor/prompts/master_tutor_prompts.py # Personalization block
llm-backend/shared/repositories/session_repository.py  # list_by_user, get_user_stats
llm-backend/db.py                                # Add migration for user_id column

# Frontend
llm-frontend/package.json                        # Add amazon-cognito-identity-js
llm-frontend/src/App.tsx                         # Auth routes, AuthProvider, ProtectedRoute
llm-frontend/src/TutorApp.tsx                    # Remove hardcoded profile, add nav
llm-frontend/src/api.ts                          # Add auth headers, 401 handling
```
