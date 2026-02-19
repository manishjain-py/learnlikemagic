# Login & User Profile — PRD

**Status:** Draft
**Date:** 2026-02-19
**Module:** Authentication + Student Profile

---

## 1. Problem

Currently, sessions are anonymous (UUID-based, no user identity). This means:
- Students lose session history when they return
- No personalization — grade/board are hardcoded in the frontend
- No way to build a learning profile over time

## 2. Goals

1. Let students **sign up and log in** via phone+OTP, email+password, or Google
2. Let students **build a profile** (age, grade, board, about themselves)
3. Use profile data to **personalize** tutoring sessions and study plans
4. **Persist** session history across devices tied to a user account

---

## 3. Login & Signup

### 3.1 Auth Methods

| Method | Flow |
|--------|------|
| **Phone + OTP** | Enter phone number → receive 6-digit OTP via SMS → verify → logged in |
| **Email + Password** | Enter email + password → verify email via link/code → logged in |
| **Google** | Tap "Continue with Google" → OAuth consent → logged in |

All three methods result in a single unified user account. If a user signs up with phone and later tries Google (same email on Google account), they should be prompted to link accounts.

### 3.2 Auth Screens

| Screen | Elements |
|--------|----------|
| **Welcome** | App logo, tagline, "Continue with Phone", "Continue with Email", "Continue with Google" |
| **Phone Login** | Country code selector, phone input, "Send OTP" button |
| **OTP Verify** | 6-digit OTP input, auto-submit on fill, "Resend OTP" (30s cooldown), back button |
| **Email Signup** | Email input, password input (min 8 chars), "Create Account" button, "Already have an account? Log in" |
| **Email Login** | Email input, password input, "Log In" button, "Forgot password?" |
| **Forgot Password** | Email input → send reset link → new password screen |

### 3.3 Auth Rules

- OTP expires after **5 minutes**
- Max **5 OTP attempts** per phone number per hour
- Passwords: minimum 8 characters
- JWT-based sessions, access token (15 min) + refresh token (30 days)
- Token stored in httpOnly cookie (web) for security
- All authenticated API requests carry `Authorization: Bearer <token>` header
- Logout clears tokens client-side and invalidates refresh token server-side

### 3.4 Auth Provider

**Recommendation: AWS Cognito** — aligns with existing AWS infrastructure (App Runner, Aurora, S3). Cognito handles:
- User pool management
- Phone OTP via Amazon SNS
- Email verification
- Google OAuth federation
- JWT token issuance and validation

Alternative: Firebase Auth (simpler phone OTP setup, but adds a non-AWS dependency).

---

## 4. User (Student) Profile

### 4.1 Profile Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | String | Yes | Display name, collected at signup |
| `age` | Integer | Yes | Used for age-appropriate content and language |
| `grade` | Integer | Yes | Drives curriculum (replaces hardcoded `GRADE`) |
| `board` | Enum | Yes | CBSE, ICSE, State Board, etc. (replaces hardcoded `BOARD`) |
| `school_name` | String | No | Optional context |
| `about_me` | Text | No | Free-form: "I like cricket, I learn better with stories, I'm shy but curious" |

### 4.2 Profile Flow

**Post-signup onboarding (first login only):**

```
Signup complete
  → "What's your name?" (text input)
  → "How old are you?" (number picker)
  → "What grade are you in?" (grade selector: 1-12)
  → "What's your school board?" (dropdown: CBSE, ICSE, State Board, Other)
  → "Tell us about yourself!" (optional, free-form textarea, skip button)
  → Done → Land on tutor home screen
```

- Name, age, grade, board are **required** before the student can use the tutor
- "About me" is **optional** — can be filled later from profile settings
- Profile can be **edited anytime** from a profile/settings page

### 4.3 How Profile Data Is Used

| Field | Used For |
|-------|----------|
| `grade` + `board` | Curriculum selection — determines available subjects, topics, guidelines |
| `age` | Language complexity, tone calibration in tutor prompts |
| `about_me` | Injected into tutor system prompt for personalization (interests, learning style, personality) |
| `name` | Tutor addresses student by name |

### 4.4 Profile Settings Page

Accessible from a user icon/menu in the top nav. Contains:
- View and edit all profile fields
- Change password (for email users)
- Linked accounts (show which auth methods are connected)
- Logout button

---

## 5. Data Model

### 5.1 New Database Tables

```
users
├── id              UUID, PK
├── phone           String, unique, nullable
├── email           String, unique, nullable
├── password_hash   String, nullable (null for Google/phone-only users)
├── google_id       String, unique, nullable
├── auth_provider   Enum: 'phone', 'email', 'google'  (primary signup method)
├── name            String
├── age             Integer
├── grade           Integer
├── board           String
├── school_name     String, nullable
├── about_me        Text, nullable
├── is_active       Boolean, default true
├── created_at      DateTime
├── updated_at      DateTime
└── last_login_at   DateTime
```

> Note: If using AWS Cognito, core auth fields (phone, email, google_id, password_hash) live in Cognito's user pool. The `users` table stores the profile and links to Cognito via `cognito_sub` (Cognito's user UUID) instead of duplicating auth fields.

### 5.2 Schema Changes to Existing Tables

```
sessions (existing)
├── ...existing fields...
└── user_id         UUID, FK → users.id, nullable
                    (nullable to preserve existing anonymous sessions)
```

- New sessions are created with `user_id` set
- `student_json` continues to work but is populated from the user's profile
- Existing anonymous sessions remain untouched

---

## 6. API Endpoints

### 6.1 Auth Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/signup/email` | Email + password signup |
| POST | `/auth/login/email` | Email + password login |
| POST | `/auth/send-otp` | Send OTP to phone number |
| POST | `/auth/verify-otp` | Verify OTP, return tokens |
| POST | `/auth/google` | Exchange Google OAuth token |
| POST | `/auth/refresh` | Refresh access token |
| POST | `/auth/logout` | Invalidate refresh token |
| POST | `/auth/forgot-password` | Send password reset email |
| POST | `/auth/reset-password` | Set new password with reset token |

### 6.2 Profile Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/profile` | Get current user's profile |
| PUT | `/profile` | Update profile fields |
| PUT | `/profile/password` | Change password |

### 6.3 Auth Middleware

- All existing endpoints (sessions, curriculum, etc.) become **authenticated**
- Add `get_current_user` dependency that validates JWT and returns user
- `/health`, `/config/models` remain public
- Admin endpoints get a separate role check (future scope)

---

## 7. Frontend Changes

### 7.1 New Pages/Components

| Component | Purpose |
|-----------|---------|
| `LoginPage` | Welcome screen with auth method buttons |
| `PhoneLoginForm` | Phone number input + OTP flow |
| `EmailLoginForm` | Email/password forms (login + signup) |
| `OnboardingFlow` | Post-signup profile collection wizard |
| `ProfilePage` | View/edit profile settings |
| `AuthProvider` | React context for auth state (user, tokens, login/logout functions) |
| `ProtectedRoute` | Route wrapper that redirects unauthenticated users to login |

### 7.2 Changes to Existing Components

- **`TutorApp.tsx`**: Remove hardcoded `COUNTRY`, `BOARD`, `GRADE` — read from user profile
- **`App.tsx`**: Add auth routes, wrap app in `AuthProvider`, add `ProtectedRoute`
- **`api.ts`**: Attach `Authorization` header to all API calls; handle 401 → redirect to login
- **Nav bar**: Add user avatar/icon → dropdown with "Profile", "Logout"

---

## 8. Integration with Tutor

When a session is created:

1. Backend reads the authenticated user's profile from DB
2. Builds `student` object: `{ id: user.id, grade: user.grade, prefs: { name: user.name, age: user.age, about_me: user.about_me } }`
3. Curriculum is filtered by user's `board` and `grade`
4. `about_me` is injected into the master tutor's system prompt for personalization
5. Session is saved with `user_id` FK for history

---

## 9. Out of Scope (for now)

- Parent/guardian accounts with multi-child profiles
- Role-based access control (admin vs student)
- Social login beyond Google (Apple, Facebook)
- Email-based passwordless (magic link)
- Account deletion / data export (GDPR)
- Profile picture upload

---

## 10. Success Metrics

| Metric | Target |
|--------|--------|
| Signup completion rate | > 80% of users who start signup finish it |
| Profile completion rate | > 90% fill required fields, > 40% fill "about me" |
| Return rate | > 50% of signed-up users return within 7 days |
| Session continuity | Users can see past session history on return |

---

## 11. Owner Setup Checklist

Things **you** need to configure/set up (the code won't handle these):

### AWS Cognito Setup
1. **Create a Cognito User Pool** in AWS Console (us-east-1)
   - Enable phone number as a sign-in attribute
   - Enable email as a sign-in attribute
   - Set password policy: minimum 8 characters
   - Enable self-signup

2. **Configure SMS (for phone OTP)**
   - Set up Amazon SNS for SMS delivery
   - Request SMS spending limit increase if needed (default is $1/month)
   - Set an origination number or sender ID for your region
   - Verify SMS sandbox if in sandbox mode (add test phone numbers)

3. **Configure Email (for verification & password reset)**
   - Use Cognito's default email (limited to 50/day) OR
   - Set up Amazon SES for production email delivery:
     - Verify your domain in SES
     - Move SES out of sandbox mode
     - Configure Cognito to use SES as email provider

4. **Set up Google OAuth**
   - Go to [Google Cloud Console](https://console.cloud.google.com)
   - Create OAuth 2.0 Client ID (Web application type)
   - Set authorized redirect URI to your Cognito domain
   - Add the Google Client ID and Secret to Cognito as an identity provider

5. **Create a Cognito App Client**
   - Generate an app client (no client secret for public SPA)
   - Set callback URLs: `http://localhost:3000` (dev), `https://your-domain.com` (prod)
   - Enable the auth flows: `ALLOW_USER_SRP_AUTH`, `ALLOW_REFRESH_TOKEN_AUTH`

6. **Set a Cognito Domain**
   - Either use Cognito's hosted domain (`your-app.auth.us-east-1.amazoncognito.com`)
   - Or configure a custom domain with ACM certificate

### Environment Variables to Add
```
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_APP_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
COGNITO_REGION=us-east-1
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
```

### Database Migration
- Run the migration script (will be provided) to create the `users` table and add `user_id` column to `sessions`

### DNS / Domain (Optional)
- If you want login on a custom domain, configure Route53 or your DNS provider
