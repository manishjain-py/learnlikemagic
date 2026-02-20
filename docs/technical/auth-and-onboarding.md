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
(email/phone/Google)
    │
    v
Get ID Token + Access Token
    │
    v
POST /auth/sync ────────────────────►  Verify token with Cognito
(Authorization: Bearer <idToken>)       Create/update User record
    │                                   Return UserProfile
    v
Store user + token in AuthContext
Set token on API client
```

### Auth Provider: AWS Cognito

- Client-side Cognito SDK (`amazon-cognito-identity-js`)
- User Pool with email/phone/Google OAuth support
- Tokens managed client-side (localStorage)
- Backend verifies tokens and syncs user records

---

## Auth Flows

### Email/Password

1. **Signup**: Client calls `CognitoUser.signUp()` → email verification required
2. **Verify**: `CognitoUser.confirmRegistration(code)` → account activated
3. **Login**: `CognitoUser.authenticateUser()` → get ID + Access tokens
4. **Sync**: `POST /auth/sync` with ID token → backend creates/updates `User` row

### Phone/OTP

1. **Provision**: `POST /auth/phone/provision` → backend creates Cognito user server-side (needed because client-side signUp can't skip required attributes)
2. **Initiate auth**: Cognito custom auth challenge → sends OTP via SMS
3. **Verify OTP**: `CognitoUser.sendCustomChallengeAnswer(code)` → authenticated
4. **Sync**: `POST /auth/sync`

### Google OAuth

1. **Redirect**: Navigate to Cognito hosted UI with Google provider
2. **Callback**: `/auth/callback` receives authorization code
3. **Exchange**: POST to Cognito `/oauth2/token` endpoint for tokens
4. **Manual session**: Tokens written to localStorage (Cognito SDK can't handle OAuth code exchange natively)
5. **Sync**: `POST /auth/sync`

### Session Restore

On app mount:
1. `userPool.getCurrentUser()` checks for cached session
2. `user.getSession()` validates token expiry
3. If valid: `syncUser()` re-fetches profile from backend

---

## User API Endpoints

### Auth (`/auth`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/sync` | Verify Cognito token, create/update User, return UserProfile |
| `POST` | `/auth/phone/provision` | Create Cognito user for phone auth (server-side) |

### Profile (`/profile`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/profile` | Required | Get current user profile |
| `PUT` | `/profile` | Required | Update profile fields |

---

## Onboarding API

The onboarding wizard sends `PUT /profile` after each step with just that field's data:

| Step | Payload |
|------|---------|
| Name | `{"name": "..."}` |
| Age | `{"age": 12}` |
| Grade | `{"grade": 7}` |
| Board | `{"board": "CBSE"}` |
| About | `{"about_me": "..."}` |
| Done | `{"onboarding_complete": true}` |

Partial progress is preserved server-side. The `onboarding_complete` flag is set on the final step.

---

## User Model

**Table:** `users` (SQLAlchemy: `shared/models/entities.py`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR | Primary key |
| `cognito_sub` | VARCHAR | Cognito user ID (unique) |
| `email` | VARCHAR | Email address (nullable) |
| `phone` | VARCHAR | Phone number (nullable) |
| `auth_provider` | VARCHAR | `email`, `phone`, or `google` |
| `name` | VARCHAR | Display name |
| `age` | INT | Student age |
| `grade` | INT | School grade |
| `board` | VARCHAR | Education board |
| `school_name` | VARCHAR | School name |
| `about_me` | TEXT | Self-description |
| `is_active` | BOOL | Account active flag |
| `onboarding_complete` | BOOL | Onboarding wizard completed |
| `created_at` | DATETIME | Account creation timestamp |
| `updated_at` | DATETIME | Last update timestamp |

---

## Frontend Auth Components

### AuthContext (`contexts/AuthContext.tsx`)

Global auth state provider. Exposes:

**State:** `user`, `token`, `isAuthenticated`, `isLoading`, `needsOnboarding`

**Methods:** `loginWithEmail`, `signupWithEmail`, `confirmSignUp`, `resendConfirmationCode`, `sendOTP`, `verifyOTP`, `loginWithGoogle`, `completeOAuthLogin`, `logout`, `refreshProfile`

### Route Guards

| Component | Purpose |
|-----------|---------|
| `ProtectedRoute` | Redirects to `/login` if not authenticated |
| `OnboardingGuard` | Redirects to `/onboarding` if `onboarding_complete === false` |

### Token Management

- Access token stored in module-level variable in `api.ts`
- Set via `setToken()` after authentication
- Attached as `Authorization: Bearer <token>` on all API calls
- Cognito tokens stored in localStorage by the SDK for session restore

---

## Key Files

| File | Purpose |
|------|---------|
| `llm-frontend/src/contexts/AuthContext.tsx` | Global auth state, all auth flows |
| `llm-frontend/src/components/ProtectedRoute.tsx` | Auth route guard |
| `llm-frontend/src/components/OnboardingGuard.tsx` | Onboarding route guard |
| `llm-frontend/src/pages/LoginPage.tsx` | Auth method selection |
| `llm-frontend/src/pages/EmailLoginPage.tsx` | Email/password login |
| `llm-frontend/src/pages/PhoneLoginPage.tsx` | Phone number entry |
| `llm-frontend/src/pages/OTPVerifyPage.tsx` | OTP verification |
| `llm-frontend/src/pages/EmailSignupPage.tsx` | Email signup |
| `llm-frontend/src/pages/EmailVerifyPage.tsx` | Email verification |
| `llm-frontend/src/pages/ForgotPasswordPage.tsx` | Password reset |
| `llm-frontend/src/pages/OnboardingFlow.tsx` | Onboarding wizard |
| `llm-frontend/src/pages/ProfilePage.tsx` | Profile management |
| `llm-frontend/src/config/cognito.ts` | Cognito configuration |
| `llm-backend/shared/models/entities.py` | User model |
