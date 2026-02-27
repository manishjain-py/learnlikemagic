# Frontend Map

Last audited: 2026-02-26
Code baseline: `main@973d1ea`

## Stack
- React 18 + TypeScript + Vite
- Router: `react-router-dom`
- Auth: AWS Cognito JS SDK

## Route Tree

### Public routes
- `/login`
- `/login/email`
- `/login/phone`
- `/login/phone/verify`
- `/signup/email`
- `/signup/email/verify`
- `/forgot-password`
- `/auth/callback`

### Protected student routes
- `/onboarding`
- `/learn`
- `/learn/:subject`
- `/learn/:subject/:topic`
- `/learn/:subject/:topic/:subtopic`
- `/session/:sessionId`
- `/profile`
- `/history`
- `/scorecard`
- `/report-card`
- `/` redirects to `/learn`

### Admin routes (currently no route-level auth guard)
- `/admin/books`
- `/admin/books/new`
- `/admin/books/:id`
- `/admin/guidelines`
- `/admin/evaluation`
- `/admin/docs`
- `/admin/llm-config`
- `/admin/test-scenarios`

## Auth Flow
1. Cognito login/signup/OTP/OAuth completes client-side
2. Frontend posts ID token to `/auth/sync`
3. Backend returns profile; access token cached for API calls
4. `api.ts` sends bearer token for authenticated requests
5. `401` in `api.ts` redirects to `/login`

## API Surface In Frontend Code
- Student API: `src/api.ts`
- Admin API: `src/features/admin/api/adminApi.ts`
- Devtools API: `src/features/devtools/api/devToolsApi.ts`

## Main UI Domains
- Learning flow: subject -> topic -> subtopic -> mode -> chat
- Profile and onboarding
- Session history and scorecard
- Admin ingestion workflow
- Admin guideline review and study plan generation
- Admin evaluation dashboard
- Admin docs/test scenario browsers
- Devtools drawer (agent logs/session state)

## E2E Coupling
UI route/test-id changes should be reflected in `e2e/scenarios.json` because scenarios are data-driven and executed dynamically.
