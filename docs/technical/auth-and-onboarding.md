# Auth & Onboarding — Technical

Authentication architecture, Cognito integration, and user management APIs.

---

## Auth Architecture

```
Frontend (Cognito SDK)                  Backend (FastAPI)
─────────────────────                   ──────────────────
User signs in
    │
    v
Cognito Auth
(email/Google; phone disabled)
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
- User Pool with email/Google OAuth support (phone auth disabled on frontend)
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

**Note:** Phone auth is currently disabled on the frontend (login button is disabled with "coming soon" label). The backend provisioning endpoint and Cognito custom auth flow remain implemented but unused.

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
| `PUT` | `/profile` | Access Token | Update profile fields (partial update). Triggers personality regeneration in background if personality-triggering fields change (name, preferred_name, age, grade, board) and enrichment data exists. |
| `PUT` | `/profile/password` | Access Token | Change password (email accounts only) |

### Enrichment (`/profile/enrichment`, `/profile/personality`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/profile/enrichment` | Access Token | Get kid's enrichment profile (returns empty object if none exists) |
| `PUT` | `/profile/enrichment` | Access Token | Create/update enrichment profile. Triggers personality regeneration asynchronously via debounced background task if data changed. |
| `GET` | `/profile/personality` | Access Token | Get latest derived personality + status (`none`, `generating`, `ready`, `failed`) |
| `POST` | `/profile/personality/regenerate` | Access Token | Force regeneration of personality (requires existing enrichment data with at least one section filled) |

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
| `name` | VARCHAR | Display name |
| `preferred_name` | VARCHAR | What the tutor calls the student (nullable) |
| `age` | INT | Student age |
| `grade` | INT | School grade |
| `board` | VARCHAR | Education board |
| `school_name` | VARCHAR | School name |
| `about_me` | TEXT | Self-description |
| `text_language_preference` | VARCHAR | Text language: `en`, `hi`, or `hinglish` (nullable, defaults to `en` in API response) |
| `audio_language_preference` | VARCHAR | Audio language: `en`, `hi`, or `hinglish` (nullable, defaults to `en` in API response) |
| `focus_mode` | BOOL | Full-screen tutor response mode (default true) |
| `is_active` | BOOL | Account active flag (default true) |
| `onboarding_complete` | BOOL | Onboarding wizard completed (auto-set by ProfileService) |
| `created_at` | DATETIME | Account creation timestamp |
| `updated_at` | DATETIME | Last update timestamp (auto-updated) |
| `last_login_at` | DATETIME | Last login timestamp (updated on each sync) |

### Enrichment & Personality Tables

**Table:** `kid_enrichment_profiles` (one per user)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (UUID) |
| `user_id` | VARCHAR | FK to users, unique |
| `interests` | JSONB | Array of interest strings |
| `learning_styles` | JSONB | Array of learning style values |
| `motivations` | JSONB | Array of motivation values |
| `growth_areas` | JSONB | Array of growth area strings |
| `parent_notes` | TEXT | Free-text notes from parent |
| `attention_span` | VARCHAR | `short`, `medium`, or `long` |
| `pace_preference` | VARCHAR | `slow`, `balanced`, or `fast` |
| `created_at` | DATETIME | Creation timestamp |
| `updated_at` | DATETIME | Last update timestamp |

**Table:** `kid_personalities` (multiple per user, latest = active)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key (UUID) |
| `user_id` | VARCHAR | FK to users |
| `personality_json` | JSONB | Derived personality fields: teaching_approach, example_themes, people_to_reference (array of `{name, context}` objects), communication_style, encouragement_strategy, pace_guidance, strength_leverage, growth_focus, things_to_avoid, fun_hooks (10 fields total; tutor_brief stored separately) |
| `tutor_brief` | TEXT | Concise brief for tutor prompt injection |
| `status` | VARCHAR | `generating`, `ready`, or `failed` |
| `inputs_hash` | VARCHAR | Hash of enrichment+profile inputs for change detection |
| `generator_model` | VARCHAR | LLM model used for generation |
| `version` | INT | Version counter per user |
| `created_at` | DATETIME | Creation timestamp |

---

## Frontend Auth Components

### AuthContext (`contexts/AuthContext.tsx`)

Global auth state provider. Exposes:

**State:** `user`, `token`, `isAuthenticated`, `isLoading`, `needsOnboarding`

**UserProfile interface fields:** `id`, `email`, `phone`, `name`, `preferred_name`, `age`, `grade`, `board`, `school_name`, `about_me`, `text_language_preference`, `audio_language_preference`, `focus_mode`, `onboarding_complete`, `auth_provider`

**Methods:** `loginWithEmail`, `signupWithEmail`, `confirmSignUp`, `resendConfirmationCode`, `sendOTP`, `verifyOTP`, `loginWithGoogle`, `completeOAuthLogin`, `logout`, `refreshProfile`

**Internal:** `syncUser(idToken, accessToken)` — calls `POST /auth/sync` with ID token, stores access token in state and `api.ts` module via `setAccessToken()`

### Route Guards

| Component | Purpose |
|-----------|---------|
| `ProtectedRoute` | Shows loading spinner during auth check, redirects to `/login` if not authenticated (preserves original location in state) |
| `OnboardingGuard` | Redirects to `/onboarding` if `onboarding_complete === false` |

**Post-login navigation**: All auth flows (`loginWithEmail`, `verifyOTP`, `confirmSignUp`+auto-login, `completeOAuthLogin`) navigate to `/` after success. The root route redirects to `/learn`, where `OnboardingGuard` sends new users to `/onboarding` if they haven't completed it. After onboarding, `handleFinish` also navigates to `/`, completing the cycle.

**App layout**: Most authenticated routes are wrapped in `AppShell`, which provides a top navigation bar with a home button, logo, and user menu (profile, sessions, report card, logout). `AppShell` uses `<Outlet />` to render child routes.

**Guard usage per route:**

| Route | `ProtectedRoute` | `OnboardingGuard` | Notes |
|-------|:-:|:-:|-------|
| `/learn` (+ nested child routes) | Yes | Yes | Wrapped in `AppShell`. Child routes: `/learn` (SubjectSelect), `/learn/:subject` (ChapterSelect), `/learn/:subject/:chapter` (TopicSelect), `/learn/:subject/:chapter/:topic` (ModeSelectPage), `/learn/:subject/:chapter/:topic/exam-review/:sessionId` (ExamReviewPage) |
| `/learn/:subject/:chapter/:topic/teach/:sessionId` | Yes | Yes | Chat sessions — outside AppShell (own nav-bar) |
| `/learn/:subject/:chapter/:topic/exam/:sessionId` | Yes | Yes | Chat sessions — outside AppShell |
| `/learn/:subject/:chapter/:topic/clarify/:sessionId` | Yes | Yes | Chat sessions — outside AppShell |
| `/session/:sessionId` | Yes | Yes | Backward-compatible old session URL |
| `/profile` | Yes | Yes | Inside AppShell — requires completed onboarding |
| `/profile/enrichment` | Yes | Yes | Inside AppShell — enrichment profile form |
| `/history` | Yes | Yes | Inside AppShell — session history |
| `/report-card` | Yes | Yes | Inside AppShell — progress reports |
| `/onboarding` | Yes | No | Must be authenticated but onboarding is in progress |
| `/login/*`, `/signup/*`, `/forgot-password`, `/auth/callback` | No | No | Public auth routes |
| `/admin/*` | No | No | Admin routes (no auth required currently) |

### Token Management

- Access token stored in module-level `_accessToken` variable in `api.ts`
- Set via `setAccessToken()` after authentication; read via `getAccessToken()` (both exported)
- Attached as `Authorization: Bearer <token>` on all API calls via `apiFetch()`
- Cleared on logout via `setAccessToken(null)`
- Cognito tokens stored in localStorage by the SDK for session restore (`CognitoIdentityServiceProvider.<clientId>.*`)
- **401 auto-redirect**: `apiFetch()` intercepts 401 responses and redirects the browser to `/login`. This covers token expiry without explicit refresh logic. The `transcribeAudio` and `synthesizeSpeech` functions handle 401 separately since they use raw `fetch` (not `apiFetch`) due to content type requirements (FormData and binary blob respectively).

### Student Profile Derivation

The `useStudentProfile` hook (`hooks/useStudentProfile.ts`) bridges auth/profile data into the learning flow. It reads from `AuthContext` and provides:

| Field | Source | Default |
|-------|--------|---------|
| `country` | Hardcoded | `"India"` |
| `board` | `user.board` | `"CBSE"` |
| `grade` | `user.grade` | `3` |
| `studentId` | `user.id` | `"s1"` |
| `studentName` | `user.preferred_name` (fallback: `user.name`) | `""` |

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

## Enrichment & Personality Pipeline

### Data Flow

1. Parent fills enrichment sections on `/profile/enrichment` → `PUT /profile/enrichment`
2. Backend saves enrichment data and computes an `inputs_hash` (hash of all enrichment + profile fields)
3. If data has changed and at least one section has meaningful data, schedules a debounced background task (5s delay)
4. After 5s, re-checks hash to prevent duplicate generation if parent saved again within the window
5. `PersonalityService.generate_personality()` loads LLM config via `LLMConfigService` (component key: `personality_derivation`), builds prompt from `personality_prompts.py`, calls the LLM in JSON mode to produce a structured personality object
6. LLM output has 11 fields: `teaching_approach`, `example_themes`, `people_to_reference`, `communication_style`, `encouragement_strategy`, `pace_guidance`, `strength_leverage`, `growth_focus`, `things_to_avoid`, `fun_hooks`, `tutor_brief`. The `tutor_brief` field is extracted and stored in its own column; the remaining 10 fields are stored as `personality_json`.
7. Result stored in `kid_personalities` with `status=ready`
8. Frontend polls `/profile/personality` every 5s while `status=generating`

Profile updates to personality-triggering fields (name, preferred_name, age, grade, board) also trigger regeneration if an enrichment profile exists.

`POST /profile/personality/regenerate` calls `PersonalityService.force_regenerate()`, which bypasses the hash-based skip check and always creates a new personality version.

### Enrichment Service

- `EnrichmentService.get_profile()` — returns enrichment data + `sections_filled` count + `has_about_me` flag (for migration banner)
- `EnrichmentService.update_profile()` — partial updates, returns `personality_status` and `inputs_hash`
- `EnrichmentService.has_meaningful_data()` — checks if any enrichment data exists: any of the 4 chip sections, parent_notes, attention_span, or pace_preference
- `EnrichmentService.compute_inputs_hash()` — hashes enrichment + user profile fields (name, preferred_name, age, grade, board, about_me) for change detection
- `EnrichmentService.should_regenerate()` — compares new hash with latest personality's `inputs_hash` to detect changes

---

## Key Files

### Frontend

| File | Purpose |
|------|---------|
| `llm-frontend/src/contexts/AuthContext.tsx` | Global auth state, all auth flows, syncUser |
| `llm-frontend/src/components/ProtectedRoute.tsx` | Auth route guard |
| `llm-frontend/src/components/OnboardingGuard.tsx` | Onboarding route guard |
| `llm-frontend/src/components/AppShell.tsx` | App layout with nav bar and user menu (profile, sessions, report card, logout) |
| `llm-frontend/src/pages/LoginPage.tsx` | Auth method selection (email + Google active, phone disabled) |
| `llm-frontend/src/pages/EmailLoginPage.tsx` | Email/password login form |
| `llm-frontend/src/pages/PhoneLoginPage.tsx` | Phone number entry with country code selector |
| `llm-frontend/src/pages/OTPVerifyPage.tsx` | 6-digit OTP verification with auto-submit |
| `llm-frontend/src/pages/EmailSignupPage.tsx` | Email signup with inline password rules |
| `llm-frontend/src/pages/EmailVerifyPage.tsx` | Email verification code entry with auto-login |
| `llm-frontend/src/pages/ForgotPasswordPage.tsx` | Two-step password reset (send code, set new password) |
| `llm-frontend/src/pages/OAuthCallbackPage.tsx` | Google OAuth redirect handler, token exchange, error display with retry |
| `llm-frontend/src/pages/OnboardingFlow.tsx` | Onboarding wizard (6 steps: name, preferred name, age, grade, board, about + done screen) |
| `llm-frontend/src/pages/ProfilePage.tsx` | Profile view/edit with language prefs, focus mode, enrichment CTA |
| `llm-frontend/src/pages/EnrichmentPage.tsx` | Enrichment profile form (interests, learning styles, motivations, challenges, notes, session prefs) + personality card |
| `llm-frontend/src/components/enrichment/SectionCard.tsx` | Collapsible section card for enrichment form |
| `llm-frontend/src/components/enrichment/ChipSelector.tsx` | Multi-select chip selector with custom entry support |
| `llm-frontend/src/components/enrichment/SessionPreferences.tsx` | Attention span and pace preference controls |
| `llm-frontend/src/config/auth.ts` | Cognito configuration (env vars) |
| `llm-frontend/src/api.ts` | API client with access token management, enrichment/personality API functions |
| `llm-frontend/src/hooks/useStudentProfile.ts` | Derives student profile (board, grade, country, preferred_name) from AuthContext for learn flow |

### Backend

| File | Purpose |
|------|---------|
| `llm-backend/auth/api/auth_routes.py` | `/auth/sync`, `/auth/phone/provision`, `/auth/admin/user` endpoints |
| `llm-backend/auth/api/profile_routes.py` | `/profile` GET, PUT, and `/profile/password` endpoints; triggers personality regen on profile field changes |
| `llm-backend/auth/api/enrichment_routes.py` | `/profile/enrichment` GET/PUT, `/profile/personality` GET, `/profile/personality/regenerate` POST; debounced background personality generation |
| `llm-backend/auth/services/auth_service.py` | User sync, phone provisioning, auth provider detection, user deletion |
| `llm-backend/auth/services/profile_service.py` | Profile updates, auto-completion of onboarding |
| `llm-backend/auth/services/enrichment_service.py` | Enrichment profile CRUD, input hashing, meaningful data checks |
| `llm-backend/auth/services/personality_service.py` | LLM-driven personality generation from enrichment + profile data; uses `LLMConfigService` with component key `personality_derivation` |
| `llm-backend/auth/prompts/personality_prompts.py` | Personality derivation prompt template, JSON schema (11 fields), enrichment data formatter |
| `llm-backend/auth/repositories/user_repository.py` | User CRUD operations |
| `llm-backend/auth/repositories/enrichment_repository.py` | KidEnrichmentProfile CRUD |
| `llm-backend/auth/repositories/personality_repository.py` | KidPersonality CRUD (versioned, latest = active) |
| `llm-backend/auth/middleware/auth_middleware.py` | JWT verification, JWKS caching, `get_current_user`/`get_optional_user` |
| `llm-backend/auth/models/schemas.py` | Pydantic request/response models (UserProfileResponse, UpdateProfileRequest, ChangePasswordRequest, ChangePasswordResponse) |
| `llm-backend/auth/models/enrichment_schemas.py` | Pydantic models for enrichment and personality endpoints |
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
