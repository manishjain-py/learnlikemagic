# Auth & Onboarding — Technical

Authentication architecture, Cognito integration, user management APIs, enrichment, and personality derivation.

---

## Auth Architecture

```
Frontend (Cognito SDK)                  Backend (FastAPI)
─────────────────────                   ──────────────────
User signs in
    │
    v
Cognito Auth
(email/Google)
    │
    v
Get ID Token + Access Token
    │
    v
POST /auth/sync ────────────────────►  Verify ID token with Cognito JWKS
(Authorization: Bearer <idToken>)       Create/update User record
    │                                   Return UserProfile
    v
Store user + token in AuthContext
Set access token on API client
    │
    v
All subsequent API calls ───────────►  Verify access token via get_current_user
(Authorization: Bearer <accessToken>)   Resolve User from cognito_sub claim
```

### Auth Provider: AWS Cognito

- Client-side Cognito SDK (`amazon-cognito-identity-js`)
- User Pool with email/phone/Google OAuth support
- Tokens managed client-side (localStorage by Cognito SDK for session restore)
- Access token also stored in module-level variable in `api.ts` for API calls
- Backend verifies tokens using JWKS (JSON Web Key Set) from Cognito
- JWKS keys are cached for 1 hour with refresh-on-miss for key rotation

---

## Auth Flows

### Email/Password

1. **Signup**: Client calls `CognitoUser.signUp()` with email + name attributes → email verification required
2. **Verify**: `CognitoUser.confirmRegistration(code)` → account activated
3. **Auto-login**: `loginWithEmail(email, password)` is called immediately after verification (password is passed via React Router state)
4. **Login**: `CognitoUser.authenticateUser()` → get ID + Access tokens
5. **Sync**: `POST /auth/sync` with ID token → backend creates/updates `User` row, returns `UserProfile`

### Phone/OTP

Phone auth infrastructure exists in the backend (`POST /auth/phone/provision` endpoint, `provision_phone_user` in AuthService) and frontend (`sendOTP`, `verifyOTP` in AuthContext), but the phone login button is currently disabled on the `LoginPage` UI with a "coming soon" label.

When enabled, the flow works as:

1. **Provision**: `POST /auth/phone/provision` → backend creates Cognito user server-side via admin API (needed because client-side signUp can't skip required email/name schema attributes; uses a placeholder email `phone_{digits}@placeholder.local`). Idempotent — silently skips if user already exists. Also sets a random permanent password to move the user out of `FORCE_CHANGE_PASSWORD` state.
2. **Initiate auth**: `CognitoUser.initiateAuth()` → Cognito custom auth challenge → sends OTP via SMS
3. **Verify OTP**: `CognitoUser.sendCustomChallengeAnswer(code)` → authenticated (pending user stored in module-level `pendingCognitoUser` variable)
4. **Sync**: `POST /auth/sync`

### Google OAuth

1. **Redirect**: Navigate to Cognito hosted UI with `identity_provider=Google` and `scope=openid+email+profile`
2. **Callback**: `/auth/callback` route renders `OAuthCallbackPage` which receives authorization code. A 500ms delay is applied before processing to ensure the Cognito SDK has time to settle.
3. **Exchange**: POST to Cognito `/oauth2/token` endpoint for tokens (using `application/x-www-form-urlencoded` content type)
4. **Manual session**: Tokens written to localStorage under Cognito SDK key format (`CognitoIdentityServiceProvider.<clientId>.<username>.*`) so `getCurrentUser()` works for session restore. The username is extracted from the ID token's `cognito:username` claim (falling back to `sub`).
5. **Sync**: `POST /auth/sync`

### Forgot Password

Handled entirely client-side via Cognito SDK. `ForgotPasswordPage` creates its own `CognitoUserPool` and `CognitoUser` instances directly (not through AuthContext):
1. `CognitoUser.forgotPassword()` → sends reset code to email
2. `CognitoUser.confirmPassword(code, newPassword)` → password updated
3. On success, shows a confirmation screen with a "Go to Login" button (navigates to `/login/email`)

### Change Password

Backend-only endpoint (no frontend UI yet):
1. `PUT /profile/password` with `{previous_password, proposed_password}`
2. Only available for email-based accounts (`auth_provider == "email"`)
3. Proxies to Cognito's `change_password` API using the caller's access token

### Session Restore

On app mount:
1. `userPool.getCurrentUser()` checks for cached session in localStorage
2. `user.getSession()` validates token expiry
3. If valid: `syncUser(idToken, accessToken)` re-syncs profile from backend via `POST /auth/sync`
4. If Cognito is not configured (no UserPoolId/ClientId), loading completes immediately with no user

---

## User API Endpoints

### Auth (`/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/auth/sync` | ID Token | Verify Cognito ID token, create/update User, return UserProfile |
| `POST` | `/auth/phone/provision` | None | Create Cognito user for phone auth (server-side admin API) |
| `DELETE` | `/auth/admin/user?cognito_sub=<sub>` | None | Delete user from both DB and Cognito (admin/dev cleanup) |

### Profile (`/profile`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/profile` | Access Token | Get current user profile |
| `PUT` | `/profile` | Access Token | Update profile fields (partial update). Also triggers personality regeneration if enrichment data exists and personality-triggering fields changed (name, preferred_name, age, grade, board). |
| `PUT` | `/profile/password` | Access Token | Change password (email accounts only) |

### Enrichment (`/profile/enrichment` and `/profile/personality`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/profile/enrichment` | Access Token | Get kid's enrichment profile (returns empty object if none exists) |
| `PUT` | `/profile/enrichment` | Access Token | Create/update enrichment profile (partial update). Triggers async personality regeneration if data changed. |
| `GET` | `/profile/personality` | Access Token | Get latest derived personality + status |
| `POST` | `/profile/personality/regenerate` | Access Token | Force personality regeneration (requires existing enrichment data) |

---

## Onboarding API

The onboarding wizard sends `PUT /profile` after each step with just that field's data:

| Step | Payload |
|------|---------|
| Name | `{"name": "..."}` |
| Preferred Name | `{"preferred_name": "..."}` |
| Age | `{"age": 12}` |
| Grade | `{"grade": 7}` |
| Board | `{"board": "CBSE"}` |
| About | `{"about_me": "..."}` |

**Auto-completion**: The `ProfileService.update_profile()` method automatically sets `onboarding_complete = true` when all four required fields (name, age, grade, board) are filled. The frontend does not explicitly send `onboarding_complete` — it is derived server-side.

Partial progress is preserved server-side. If the user closes mid-onboarding, the `OnboardingFlow` component pre-fills fields from the existing user profile.

---

## Auth Provider Detection

The `auth_provider` field (`email`, `phone`, or `google`) is derived server-side from Cognito token claims to prevent spoofing. Logic in `AuthService._derive_auth_provider()`:

1. Check for `identities` claim with `providerName="Google"` → `"google"`
2. Check for `phone_number_verified=true` or username starting with `+` → `"phone"`
3. Default → `"email"`

---

## User Model

**Table:** `users` (SQLAlchemy: `shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (UUID) |
| `cognito_sub` | VARCHAR | Cognito user ID (unique, indexed) |
| `email` | VARCHAR | Email address (unique, nullable, indexed) |
| `phone` | VARCHAR | Phone number (unique, nullable) |
| `auth_provider` | VARCHAR | `email`, `phone`, or `google` |
| `name` | VARCHAR | Full display name |
| `preferred_name` | VARCHAR | How the tutor greets the student (e.g., first name or nickname) |
| `age` | INT | Student age |
| `grade` | INT | School grade |
| `board` | VARCHAR | Education board |
| `school_name` | VARCHAR | School name |
| `about_me` | TEXT | Self-description |
| `text_language_preference` | VARCHAR | Language for text responses (`en`, `hi`, `hinglish`) |
| `audio_language_preference` | VARCHAR | Language for audio responses (`en`, `hi`, `hinglish`) |
| `focus_mode` | BOOL | Full-screen audio mode for younger students (default false) |
| `is_active` | BOOL | Account active flag (default true) |
| `onboarding_complete` | BOOL | Onboarding wizard completed (auto-set by ProfileService) |
| `created_at` | DATETIME | Account creation timestamp |
| `updated_at` | DATETIME | Last update timestamp (auto-updated) |
| `last_login_at` | DATETIME | Last login timestamp (updated on each sync) |

## Enrichment Model

**Table:** `kid_enrichment_profiles` (SQLAlchemy: `shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (UUID) |
| `user_id` | VARCHAR | FK to `users.id` (unique — one per user) |
| `interests` | JSONB | Array of interest strings |
| `learning_styles` | JSONB | Array of learning style values |
| `motivations` | JSONB | Array of motivation values |
| `growth_areas` | JSONB | Array of growth area strings |
| `parent_notes` | TEXT | Free-text notes from parent (max 1000 chars) |
| `attention_span` | VARCHAR | `short`, `medium`, or `long` |
| `pace_preference` | VARCHAR | `slow`, `balanced`, or `fast` |
| `created_at` | DATETIME | Creation timestamp |
| `updated_at` | DATETIME | Last update timestamp |

## Personality Model

**Table:** `kid_personalities` (SQLAlchemy: `shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (UUID) |
| `user_id` | VARCHAR | FK to `users.id` (multiple versions per user) |
| `personality_json` | JSONB | LLM-derived personality (teaching_approach, example_themes, encouragement_strategy, growth_focus) |
| `tutor_brief` | TEXT | Compact text summary for tutor prompt injection |
| `status` | VARCHAR | `generating`, `ready`, or `failed` |
| `inputs_hash` | VARCHAR | SHA256 hash of inputs used for generation (deduplication) |
| `generator_model` | VARCHAR | LLM model used for generation |
| `version` | INT | Version number (latest = active) |
| `created_at` | DATETIME | Creation timestamp |

---

## Enrichment & Personality Flow

```
Parent fills enrichment form
    │
    v
PUT /profile/enrichment
    │
    v
EnrichmentService.update_profile()
    ├── Upsert enrichment data
    ├── Compute inputs_hash (SHA256 of enrichment + basic profile fields)
    └── Compare hash with latest personality
            │
            v (if changed and has data)
        Background task: _debounced_regenerate()
            ├── Sleep 5s (debounce)
            ├── Re-check hash (skip if parent saved again)
            └── PersonalityService.generate_personality()
                    ├── Create KidPersonality row (status=generating)
                    ├── Call LLM with enrichment + profile data
                    ├── Parse personality_json + tutor_brief
                    └── Update status to ready (or failed)
```

**Profile update trigger**: When `PUT /profile` changes personality-triggering fields (`name`, `preferred_name`, `age`, `grade`, `board`), it also triggers personality regeneration if enrichment data exists and the hash changed.

**Debounce**: The `_debounced_regenerate` background task sleeps 5 seconds before regenerating. If the parent saves again within that window, the hash changes and the earlier task becomes a no-op (the newer task handles it).

**Frontend polling**: When personality status is `generating`, the `EnrichmentPage` polls `GET /profile/personality` every 5 seconds until the status changes.

---

## Frontend Auth Components

### AuthContext (`contexts/AuthContext.tsx`)

Global auth state provider. Exposes:

**State:** `user`, `token`, `isAuthenticated`, `isLoading`, `needsOnboarding`

**Methods:** `loginWithEmail`, `signupWithEmail`, `confirmSignUp`, `resendConfirmationCode`, `sendOTP`, `verifyOTP`, `loginWithGoogle`, `completeOAuthLogin`, `logout`, `refreshProfile`

**Internal:** `syncUser(idToken, accessToken)` — calls `POST /auth/sync` with ID token, stores access token in state and `api.ts` module via `setAccessToken()`

**UserProfile interface** includes: `id`, `email`, `phone`, `name`, `preferred_name`, `age`, `grade`, `board`, `school_name`, `about_me`, `text_language_preference`, `audio_language_preference`, `focus_mode`, `onboarding_complete`, `auth_provider`

### Route Guards

| Component | Purpose |
|-----------|---------|
| `ProtectedRoute` | Shows loading spinner during auth check, redirects to `/login` if not authenticated (preserves original location in state) |
| `OnboardingGuard` | Redirects to `/onboarding` if `onboarding_complete === false` |

**Post-login navigation**: All auth flows (`loginWithEmail`, `verifyOTP`, `confirmSignUp`+auto-login, `completeOAuthLogin`) navigate to `/` after success. The root route redirects to `/learn`, where `OnboardingGuard` sends new users to `/onboarding` if they haven't completed it. After onboarding, `handleFinish` also navigates to `/`, completing the cycle.

**Guard usage per route:**

| Route | `ProtectedRoute` | `OnboardingGuard` | Notes |
|-------|:-:|:-:|-------|
| `/learn` (+ nested child routes) | Yes | Yes | Wrapped in `AppShell` which provides header with user menu. Child routes: `/learn` (`SubjectSelect`), `/learn/:subject` (`ChapterSelect`), `/learn/:subject/:chapter` (`TopicSelect`), `/learn/:subject/:chapter/:topic` (`ModeSelectPage`), `/learn/:subject/:chapter/:topic/exam-review/:sessionId` (`ExamReviewPage`) |
| `/learn/:subject/:chapter/:topic/teach/:sessionId` | Yes | Yes | Teach-mode chat session (outside `AppShell`, own nav) |
| `/learn/:subject/:chapter/:topic/exam/:sessionId` | Yes | Yes | Exam-mode chat session (outside `AppShell`, own nav) |
| `/learn/:subject/:chapter/:topic/clarify/:sessionId` | Yes | Yes | Clarify-mode chat session (outside `AppShell`, own nav) |
| `/session/:sessionId` | Yes | Yes | Legacy session URL (backward compat) |
| `/onboarding` | Yes | No | Must be authenticated but onboarding is in progress |
| `/profile` | Yes | Yes | Wrapped in `AppShell` with `OnboardingGuard` |
| `/profile/enrichment` | Yes | Yes | Enrichment form for parents |
| `/history` | Yes | Yes | Session history |
| `/report-card` | Yes | Yes | Report card |
| `/login/*`, `/signup/*`, `/forgot-password`, `/auth/callback` | No | No | Public auth routes |
| `/admin/*` | No | No | Admin routes (no auth required currently) |

### AppShell

The `AppShell` component (`components/AppShell.tsx`) provides the shared layout for all post-onboarding authenticated routes. It includes:

- A top navigation bar with a home button, app logo/name, and user menu
- User menu dropdown with: Profile, My Sessions, My Report Card, Log Out
- An `<Outlet />` for rendering child routes

All routes under `AppShell` are wrapped in both `ProtectedRoute` and `OnboardingGuard`.

### Token Management

- Access token stored in module-level `_accessToken` variable in `api.ts`
- Set via `setAccessToken()` after authentication; read via `getAccessToken()` (both exported)
- Attached as `Authorization: Bearer <token>` on all API calls via `apiFetch()`
- Cleared on logout via `setAccessToken(null)`
- Cognito tokens stored in localStorage by the SDK for session restore (`CognitoIdentityServiceProvider.<clientId>.*`)
- **401 auto-redirect**: `apiFetch()` intercepts 401 responses and redirects the browser to `/login`. This covers token expiry without explicit refresh logic. The `transcribeAudio` function handles 401 separately since it uses raw `fetch` (not `apiFetch`) due to `FormData` content type requirements.

### Student Profile Derivation

The `useStudentProfile` hook (`hooks/useStudentProfile.ts`) bridges auth/profile data into the learning flow. It reads from `AuthContext` and provides:

| Field | Source | Default |
|-------|--------|---------|
| `country` | Hardcoded | `"India"` |
| `board` | `user.board` | `"CBSE"` |
| `grade` | `user.grade` | `3` |
| `studentId` | `user.id` | `"s1"` |
| `studentName` | `user.preferred_name` or `user.name` | `""` |

### Auth Middleware (Backend)

| Dependency | Purpose |
|-----------|---------|
| `get_current_user` | Validates access token, returns User from DB. Raises 401 if unauthenticated. |
| `get_optional_user` | Same as above but returns `None` instead of 401 for unauthenticated requests. Used by endpoints that support both authenticated and anonymous access (e.g., tutor sessions, transcription). |

**Token verification** (`_verify_cognito_token`):
- Fetches JWKS from Cognito, caches for 1 hour
- On key-not-found, force-refreshes JWKS (handles key rotation)
- Validates issuer, audience/client_id, token_use claim
- ID tokens validated with `aud` = app client ID (`at_hash` verification is skipped since tokens are validated independently)
- Access tokens validated with `client_id` claim (no `aud` in Cognito access tokens; `verify_aud` disabled in decode, `client_id` checked manually)
- If Cognito is not configured (no `cognito_user_pool_id`), raises 401 immediately

---

## Key Files

### Frontend

| File | Purpose |
|------|---------|
| `llm-frontend/src/contexts/AuthContext.tsx` | Global auth state, all auth flows, syncUser |
| `llm-frontend/src/components/ProtectedRoute.tsx` | Auth route guard |
| `llm-frontend/src/components/OnboardingGuard.tsx` | Onboarding route guard |
| `llm-frontend/src/components/AppShell.tsx` | Shared layout with nav bar and user menu for authenticated routes |
| `llm-frontend/src/pages/LoginPage.tsx` | Auth method selection (email, Google active; phone disabled) |
| `llm-frontend/src/pages/EmailLoginPage.tsx` | Email/password login form |
| `llm-frontend/src/pages/PhoneLoginPage.tsx` | Phone number entry with country code selector |
| `llm-frontend/src/pages/OTPVerifyPage.tsx` | 6-digit OTP verification with auto-submit |
| `llm-frontend/src/pages/EmailSignupPage.tsx` | Email signup with inline password rules |
| `llm-frontend/src/pages/EmailVerifyPage.tsx` | Email verification code entry with auto-login |
| `llm-frontend/src/pages/ForgotPasswordPage.tsx` | Two-step password reset (send code, set new password) |
| `llm-frontend/src/pages/OAuthCallbackPage.tsx` | Google OAuth redirect handler, token exchange, error display with retry |
| `llm-frontend/src/pages/OnboardingFlow.tsx` | Onboarding wizard (6 steps + done screen: name, preferred name, age, grade, board, about) |
| `llm-frontend/src/pages/ProfilePage.tsx` | Profile & Settings: view/edit profile, language prefs, focus mode, enrichment CTA |
| `llm-frontend/src/pages/EnrichmentPage.tsx` | Enrichment form (4 chip sections + open textbox + session preferences) with personality card |
| `llm-frontend/src/config/auth.ts` | Cognito configuration (env vars) |
| `llm-frontend/src/api.ts` | API client with access token management and enrichment/personality API functions |
| `llm-frontend/src/hooks/useStudentProfile.ts` | Derives student profile (board, grade, country, preferred name) from AuthContext for learn flow |
| `llm-frontend/src/components/enrichment/SectionCard.tsx` | Collapsible section card for enrichment form |
| `llm-frontend/src/components/enrichment/ChipSelector.tsx` | Multi-select chip selector with optional custom input |
| `llm-frontend/src/components/enrichment/SessionPreferences.tsx` | Attention span + pace preference selectors |

### Backend

| File | Purpose |
|------|---------|
| `llm-backend/auth/api/auth_routes.py` | `/auth/sync`, `/auth/phone/provision`, `/auth/admin/user` endpoints |
| `llm-backend/auth/api/profile_routes.py` | `/profile` GET, PUT, and `/profile/password` endpoints. PUT also triggers personality regen. |
| `llm-backend/auth/api/enrichment_routes.py` | `/profile/enrichment` GET/PUT, `/profile/personality` GET, `/profile/personality/regenerate` POST |
| `llm-backend/auth/services/auth_service.py` | User sync, phone provisioning, auth provider detection, user deletion |
| `llm-backend/auth/services/profile_service.py` | Profile updates (including preferred_name, language prefs, focus_mode), auto-completion of onboarding |
| `llm-backend/auth/services/enrichment_service.py` | Enrichment profile CRUD, inputs hash computation, personality trigger logic |
| `llm-backend/auth/services/personality_service.py` | LLM-based personality generation from enrichment + profile data |
| `llm-backend/auth/repositories/user_repository.py` | User CRUD operations |
| `llm-backend/auth/repositories/enrichment_repository.py` | KidEnrichmentProfile CRUD with upsert |
| `llm-backend/auth/repositories/personality_repository.py` | KidPersonality CRUD (versioned, latest = active) |
| `llm-backend/auth/middleware/auth_middleware.py` | JWT verification, JWKS caching, `get_current_user`/`get_optional_user` |
| `llm-backend/auth/models/schemas.py` | Pydantic models: UserProfileResponse, UpdateProfileRequest, ChangePasswordRequest, ChangePasswordResponse |
| `llm-backend/auth/models/enrichment_schemas.py` | Pydantic models: EnrichmentProfileRequest/Response, EnrichmentUpdateResponse, PersonalityResponse |
| `llm-backend/shared/models/entities.py` | User, KidEnrichmentProfile, KidPersonality SQLAlchemy models |

---

## Configuration

### Frontend Environment Variables

| Variable | Purpose |
|----------|---------|
| `VITE_COGNITO_USER_POOL_ID` | Cognito User Pool ID |
| `VITE_COGNITO_APP_CLIENT_ID` | Cognito App Client ID |
| `VITE_COGNITO_REGION` | AWS region (default: `us-east-1`) |
| `VITE_COGNITO_DOMAIN` | Cognito hosted UI domain prefix (for Google OAuth redirect) |
| `VITE_GOOGLE_CLIENT_ID` | Google OAuth client ID (configured in `auth.ts` but Google login routes through Cognito hosted UI) |
| `VITE_API_URL` | Backend API base URL (default: `http://localhost:8000`) |

### Backend Settings (via `config.py`)

| Setting | Purpose |
|---------|---------|
| `cognito_user_pool_id` | For JWKS URL construction and admin API calls |
| `cognito_app_client_id` | For token audience/client_id validation |
| `cognito_region` | AWS region for Cognito endpoints |
