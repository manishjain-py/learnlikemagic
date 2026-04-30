# Frontend Map

Last audited: 2026-03-21
Code baseline: `main@e0c0338`

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
- `/learn/:subject/:chapter`
- `/learn/:subject/:chapter/:topic`
- `/learn/:subject/:chapter/:topic/exam-review/:sessionId`
- `/learn/:subject/:chapter/:topic/teach/:sessionId`
- `/learn/:subject/:chapter/:topic/exam/:sessionId`
- `/learn/:subject/:chapter/:topic/clarify/:sessionId`
- `/session/:sessionId` (backward compat)
- `/profile`
- `/profile/enrichment`
- `/history`
- `/report-card`
- `/` redirects to `/learn`

### Admin routes (currently no route-level auth guard)
- `/admin` renders AdminHome landing page
- `/admin/books` redirects to `/admin/books-v2`
- `/admin/books-v2`
- `/admin/books-v2/new`
- `/admin/books-v2/:id`
- `/admin/evaluation`
- `/admin/docs`
- `/admin/llm-config`
- `/admin/test-scenarios`
- `/admin/feature-flags`

## Auth Flow
1. Cognito login/signup/OTP/OAuth completes client-side
2. Frontend posts ID token to `/auth/sync`
3. Backend returns profile; access token cached for API calls
4. `api.ts` sends bearer token for authenticated requests
5. `401` in `api.ts` redirects to `/login`

## API Surface In Frontend Code
- Student API: `src/api.ts`
- Admin API (evaluation, docs, llm-config, feature-flags, test-scenarios): `src/features/admin/api/adminApi.ts`
- Admin API (book ingestion V2): `src/features/admin/api/adminApiV2.ts`

## Main UI Domains
- Learning flow: subject -> chapter -> topic -> mode -> chat
- Profile, enrichment, and onboarding
- Session history and report card
- Admin book ingestion V2 workflow
- Admin evaluation dashboard
- Admin docs/test scenario browsers
- Admin LLM config and feature flag management
- Admin Pixi.js PoC playground
- Devtools drawer (agent logs/session state)

## E2E Coupling
UI route/test-id changes should be reflected in `e2e/scenarios.json` because scenarios are data-driven and executed dynamically.
