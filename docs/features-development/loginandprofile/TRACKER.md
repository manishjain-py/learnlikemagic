# Login & User Profile — Implementation Tracker

**Branch:** `claude/login-feature-implementation-g0rr9`
**Plan:** [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)
**PRD:** [PRD.md](./PRD.md)

---

## Phase Overview

| Phase | Description | Status | Notes |
|-------|-------------|--------|-------|
| 1 | AWS Cognito + Infrastructure (Terraform) | SKIPPED | Owner manual setup — see [SETUP_GUIDE.md](./SETUP_GUIDE.md) |
| 2 | Backend Auth Module | DONE | JWT middleware, user model, sync endpoint |
| 3 | Backend Profile + Session Linking | DONE | Profile CRUD, user_id on sessions |
| 4 | Frontend Auth Screens | DONE | Login/signup pages, Cognito SDK, AuthContext |
| 5 | Frontend Profile + Onboarding | DONE | Onboarding wizard, profile page, nav updates |
| 6 | Tutor Personalization Integration | DONE | Name/age/about_me in prompts |
| 7 | Session History | DONE | History API + My Sessions page |

---

## Phase 2: Backend Auth Module

| Task | File(s) | Status | Notes |
|------|---------|--------|-------|
| Add `python-jose[cryptography]` to requirements | `llm-backend/requirements.txt` | DONE | |
| Add Cognito config to Settings | `llm-backend/config.py` | DONE | cognito_user_pool_id, cognito_app_client_id, cognito_region |
| Add User ORM model | `llm-backend/shared/models/entities.py` | DONE | All fields from PRD + indexes |
| Add user_id + subject columns to Session model | `llm-backend/shared/models/entities.py` | DONE | FK to users, nullable for backward compat |
| Create auth module directory structure | `llm-backend/auth/` | DONE | api, services, repositories, models, middleware |
| Create auth middleware (JWT validation) | `llm-backend/auth/middleware/auth_middleware.py` | DONE | JWKS caching, access+ID token support, get_current_user + get_optional_user deps |
| Create user repository | `llm-backend/auth/repositories/user_repository.py` | DONE | CRUD, get_by_cognito_sub |
| Create auth service (user sync) | `llm-backend/auth/services/auth_service.py` | DONE | Server-side auth_provider derivation from claims |
| Create auth routes (POST /auth/sync) | `llm-backend/auth/api/auth_routes.py` | DONE | Accepts ID token, creates/updates user |
| Create Pydantic schemas | `llm-backend/auth/models/schemas.py` | DONE | UserProfileResponse, UpdateProfileRequest, ChangePasswordRequest |
| Register auth router in main.py | `llm-backend/main.py` | DONE | |
| Update db.py for migration | `llm-backend/db.py` | DONE | ALTER TABLE sessions for user_id, subject columns |

## Phase 3: Backend Profile + Session Linking

| Task | File(s) | Status | Notes |
|------|---------|--------|-------|
| Create profile service | `llm-backend/auth/services/profile_service.py` | DONE | Auto-marks onboarding_complete when all required fields filled |
| Create profile routes | `llm-backend/auth/api/profile_routes.py` | DONE | GET/PUT /profile, PUT /profile/password |
| Register profile router in main.py | `llm-backend/main.py` | DONE | |
| Modify session creation to link user | `llm-backend/tutor/services/session_service.py` | DONE | user_id + subject persisted |
| Modify session API to inject user | `llm-backend/tutor/api/sessions.py` | DONE | get_optional_user dependency on POST /sessions |
| Build student context from profile | `llm-backend/tutor/services/session_service.py` | DONE | _build_student_context_from_profile method |

## Phase 4: Frontend Auth Screens

| Task | File(s) | Status | Notes |
|------|---------|--------|-------|
| Install amazon-cognito-identity-js | `llm-frontend/package.json` | DONE | |
| Create auth config | `llm-frontend/src/config/auth.ts` | DONE | Env vars for Cognito pool/client/region |
| Create AuthContext | `llm-frontend/src/contexts/AuthContext.tsx` | DONE | Full auth state, login/signup/OTP/OAuth/logout |
| Create ProtectedRoute | `llm-frontend/src/components/ProtectedRoute.tsx` | DONE | |
| Create OnboardingGuard | `llm-frontend/src/components/OnboardingGuard.tsx` | DONE | |
| Create LoginPage (welcome) | `llm-frontend/src/pages/LoginPage.tsx` | DONE | 3 auth method buttons |
| Create PhoneLoginPage | `llm-frontend/src/pages/PhoneLoginPage.tsx` | DONE | Country code + phone |
| Create OTPVerifyPage | `llm-frontend/src/pages/OTPVerifyPage.tsx` | DONE | 6-digit auto-submit |
| Create EmailSignupPage | `llm-frontend/src/pages/EmailSignupPage.tsx` | DONE | |
| Create EmailLoginPage | `llm-frontend/src/pages/EmailLoginPage.tsx` | DONE | |
| Create ForgotPasswordPage | `llm-frontend/src/pages/ForgotPasswordPage.tsx` | DONE | 2-step: send code + reset |
| Create OAuthCallbackPage | `llm-frontend/src/pages/OAuthCallbackPage.tsx` | DONE | Handles Google OAuth redirect |
| Update api.ts with auth headers | `llm-frontend/src/api.ts` | DONE | apiFetch wrapper, setAccessToken, 401 redirect |
| Update App.tsx with auth routes | `llm-frontend/src/App.tsx` | DONE | Full routing with protected/public/admin routes |

## Phase 5: Frontend Profile + Onboarding

| Task | File(s) | Status | Notes |
|------|---------|--------|-------|
| Create OnboardingFlow | `llm-frontend/src/pages/OnboardingFlow.tsx` | DONE | 5 steps: name, age, grade, board, about_me |
| Create ProfilePage | `llm-frontend/src/pages/ProfilePage.tsx` | DONE | Edit mode, change password link, logout |
| Update TutorApp — remove hardcoded values | `llm-frontend/src/TutorApp.tsx` | DONE | Uses user.board, user.grade from profile |
| Update TutorApp — add nav bar with user menu | `llm-frontend/src/TutorApp.tsx` | DONE | Profile, My Sessions, Log Out |

## Phase 6: Tutor Personalization Integration

| Task | File(s) | Status | Notes |
|------|---------|--------|-------|
| Extend StudentContext model | `llm-backend/tutor/models/messages.py` | DONE | student_name, student_age, about_me fields |
| Populate StudentContext from profile | `llm-backend/tutor/services/session_service.py` | DONE | _build_student_context_from_profile |
| Add personalization block to tutor prompt | `llm-backend/tutor/prompts/master_tutor_prompts.py` | DONE | {personalization_block} in system prompt |
| Add _build_personalization_block to MasterTutor | `llm-backend/tutor/agents/master_tutor.py` | DONE | Builds "Student Profile" section for prompt |

## Phase 7: Session History

| Task | File(s) | Status | Notes |
|------|---------|--------|-------|
| Add list_by_user to session repository | `llm-backend/shared/repositories/session_repository.py` | DONE | With subject filter, pagination |
| Add get_user_stats to session repository | `llm-backend/shared/repositories/session_repository.py` | DONE | total_sessions, avg_mastery, topics, total_steps |
| Create session history API endpoints | `llm-backend/tutor/api/sessions.py` | DONE | GET /sessions/history, GET /sessions/stats, GET /sessions/{id}/replay |
| Create SessionHistoryPage | `llm-frontend/src/pages/SessionHistoryPage.tsx` | DONE | Stats grid + session list + pagination |
| Add auth CSS styles | `llm-frontend/src/App.css` | DONE | Full responsive auth/profile/history styles |

---

## Remaining Work (Not Code)

| Item | Owner | Status |
|------|-------|--------|
| Create Cognito User Pool in AWS | Owner | NOT STARTED |
| Configure Google OAuth provider | Owner | NOT STARTED |
| Set environment variables (VITE_COGNITO_*) | Owner | NOT STARTED |
| Run `python db.py --migrate` to create users table | Owner | NOT STARTED |
| Add Terraform for Cognito (optional) | Owner | NOT STARTED |

---

## Session Log

| Date | Session | Work Done |
|------|---------|-----------|
| 2026-02-19 | Session 1 | Full implementation: Phases 2-7 complete. Backend auth module (JWT, user model, sync, profile, session linking, personalization, history API). Frontend auth screens (login, signup, phone OTP, Google OAuth, forgot password), onboarding flow, profile page, session history page. Updated App.tsx routing, TutorApp.tsx with profile data and user menu, api.ts with auth headers. |
