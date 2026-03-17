# Architecture Overview

Full-stack architecture, tech stack, and code conventions for LearnLikeMagic.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (React + TypeScript + Vite)                           │
│  S3 + CloudFront                                                │
│  Routes: /learn/*, /learn/.../teach/:id, /learn/.../exam/:id,   │
│          /learn/.../clarify/:id, /login/*, /profile,            │
│          /report-card, /history, /admin/*                       │
└────────────────────────────┬────────────────────────────────────┘
                             │ REST API + WebSocket
┌────────────────────────────▼────────────────────────────────────┐
│  Backend (FastAPI + Python)                                     │
│  AWS App Runner                                                 │
│                                                                 │
│  Modules: tutor, book_ingestion_v2, study_plans, evaluation,    │
│           auth (+ enrichment, personality)                      │
│  Root API: api/ (docs, test_scenarios, pixi_poc)                 │
│  Shared: llm_service, llm_config_service, feature_flag_service, │
│          anthropic_adapter, claude_code_adapter, ocr_service,   │
│          s3_client, api, models, utils, repositories, prompts   │
└────────────────────────────┬────────────────────────────────────┘
                             │ SQLAlchemy
┌────────────────────────────▼────────────────────────────────────┐
│  Database (Aurora Serverless v2 PostgreSQL)                      │
│  Tables: users, sessions, events, contents,                     │
│          teaching_guidelines, study_plans, books, llm_config,    │
│          feature_flags, session_feedback, kid_enrichment_profiles,│
│          kid_personalities, book_chapters, chapter_pages,        │
│          chapter_processing_jobs, chapter_chunks, chapter_topics,│
│          topic_explanations                                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

### Backend

| Technology | Purpose | Why |
|------------|---------|-----|
| FastAPI | REST API framework | Fast, modern Python, auto Swagger docs, async-ready |
| Uvicorn | ASGI server | Lightweight, high-performance, pairs with FastAPI |
| Pydantic | Data validation | Type hints for validation, clear errors, schema gen |
| SQLAlchemy | ORM | Mature, flexible, database-agnostic |
| OpenAI | LLM provider (GPT-5.4, GPT-5.3, GPT-5.2, Whisper) | Structured outputs, Responses API, reasoning models, audio transcription |
| Anthropic | LLM provider (Claude) | Multi-provider flexibility, extended thinking capability |
| Google | LLM provider (Gemini) + Cloud TTS | Additional provider option, text-to-speech |
| Claude Code | LLM provider via CLI subprocess | Local/admin workflows, no API key needed (uses local Claude Code session) |

### Frontend

| Technology | Purpose | Why |
|------------|---------|-----|
| React | UI components | Dominant ecosystem, reusable components |
| TypeScript | Typed JavaScript | Type safety, better refactoring, IDE support |
| Vite | Dev server & bundler | Fast HMR, minimal config, faster than Webpack |

### Infrastructure

| Technology | Purpose | Why |
|------------|---------|-----|
| Docker | Containerization | Consistent runtime, CI/CD ready |
| AWS App Runner | Backend hosting | Managed containers, autoscaling, HTTPS |
| Amazon ECR | Container registry | Secure, integrates with App Runner |
| S3 + CloudFront | Frontend hosting | Cheap static hosting + global CDN |
| Aurora Serverless v2 | Database | Auto-scaling PostgreSQL, pay-per-use |
| Secrets Manager | Credentials | Encrypted secrets with rotation |
| Terraform | Infrastructure as Code | Declarative, version-controlled infra |
| GitHub Actions + OIDC | CI/CD | Native to GitHub, secure AWS auth without static keys |
| AWS Cognito | Authentication | Managed auth with email/phone/social login support |

---

## Backend Module Structure

```
llm-backend/
├── tutor/                # Runtime tutoring sessions (teach, clarify, exam)
│   ├── api/              # sessions, curriculum, transcription, tts endpoints
│   ├── agents/           # master_tutor, safety, base_agent
│   ├── orchestration/    # orchestrator
│   ├── services/         # session_service, exam_service, report_card_service, topic_adapter, pixi_code_generator
│   ├── models/           # session_state, messages, study_plan, agent_logs
│   ├── prompts/          # master_tutor, exam, clarify_doubts, orchestrator, language_utils, templates
│   └── utils/            # schema_utils, state_utils, prompt_utils
├── book_ingestion_v2/    # Book upload, TOC extraction, chapter processing, topic sync (V2 pipeline)
│   ├── api/              # book_routes, toc_routes, page_routes, processing_routes, sync_routes
│   ├── services/         # book_v2_service, toc_service, toc_extraction_service, chapter_page_service,
│   │                     #   chapter_job_service, chunk_processor_service, topic_extraction_orchestrator,
│   │                     #   chapter_finalization_service, topic_sync_service, chapter_topic_planner_service,
│   │                     #   explanation_generator_service
│   ├── repositories/     # chapter_repository, chapter_page_repository, chunk_repository,
│   │                     #   processing_job_repository, topic_repository
│   ├── models/           # schemas, database, processing_models
│   ├── utils/            # chunk_builder
│   └── prompts/
├── study_plans/          # Study plan generation
│   ├── api/
│   ├── services/         # generator_service, reviewer_service, orchestrator
│   └── models/
├── autoresearch/         # Autonomous experiment pipelines
│   ├── tutor_teaching_quality/
│   │   ├── evaluation/   # Session evaluation pipeline (flat structure)
│   │   │   ├── api.py, evaluator.py, session_runner.py, student_simulator.py
│   │   │   ├── report_generator.py, run_evaluation.py, config.py
│   │   ├── run_experiment.py, email_report.py, program.md, results.tsv
│   ├── book_ingestion_quality/
│   │   ├── evaluation/   # Book ingestion evaluation pipeline
├── auth/                 # Authentication, user profiles, enrichment, personality
│   ├── api/              # auth_routes, profile_routes, enrichment_routes
│   ├── services/         # auth_service, profile_service, enrichment_service, personality_service
│   ├── repositories/     # user_repository, enrichment_repository, personality_repository
│   ├── models/           # schemas, enrichment_schemas
│   ├── middleware/        # auth_middleware
│   └── prompts/          # personality_prompts
├── shared/               # Cross-module utilities
│   ├── api/              # Health checks, LLM config admin, feature flag admin endpoints
│   ├── services/         # LLM service, Anthropic adapter, Claude Code adapter, LLM config service, feature flag service, OCR service
│   ├── repositories/     # Session, event, guideline, book, LLM config, feature flag, explanation repos
│   ├── models/           # Domain models, ORM entities, Pydantic schemas
│   ├── prompts/          # Shared prompt loader
│   └── utils/            # Constants, exceptions, formatting helpers, S3 client
├── api/                  # Root-level API (docs, test scenarios, pixi PoC)
├── scripts/              # Utility scripts
├── tests/
├── main.py               # FastAPI app entrypoint
├── config.py             # Pydantic settings
├── db.py                 # Migration + seed CLI
└── database.py           # Connection management
```

Most modules follow the layered internal structure:

```
<module>/
├── api/              # REST endpoints
├── services/         # Business logic
├── agents/           # LLM-powered actors (AI modules only)
├── orchestration/    # Agent coordination (AI modules only)
├── repositories/     # Database access
├── models/           # Pydantic schemas
├── middleware/       # Request middleware (auth module only)
└── prompts/          # LLM prompt templates
```

**Exception:** The `autoresearch/tutor_teaching_quality/evaluation/` module uses a flat file layout (`api.py`, `evaluator.py`, `session_runner.py`, etc.) rather than subdirectories.

### Routers Registered in `main.py`

| Router | Prefix | Purpose |
|--------|--------|---------|
| health | (none) | Root endpoint, `/health`, `/health/db`, `/config/models` |
| curriculum | `/curriculum` | Curriculum hierarchy API |
| sessions | `/sessions` | Session management, report card, topic progress, exam review, WebSocket |
| transcription | `/transcribe` | Audio-to-text via OpenAI Whisper |
| tts | `/text-to-speech` | Text-to-speech via Google Cloud TTS (English, Hindi, Hinglish) |
| evaluation | `/api/evaluation` | Evaluation pipeline |
| auth | `/auth` | Auth sync (Cognito to local DB) |
| profile | `/profile` | User profile CRUD |
| enrichment | `/profile` | Enrichment profile + personality endpoints (`/profile/enrichment`, `/profile/personality`) |
| docs | `/api/docs` | Documentation API for admin viewer |
| llm config | `/api/admin` | LLM model configuration (`/api/admin/llm-config/*`) |
| feature flags | `/api/admin` | Runtime feature flag management (`/api/admin/feature-flags/*`) |
| test scenarios | `/api/test-scenarios` | E2E test scenario results and screenshots |
| v2 book routes | `/admin/v2/books` | Book CRUD (V2) |
| v2 toc routes | `/admin/v2/books` | Table of contents extraction (V2) |
| v2 page routes | `/admin/v2/books/{id}/chapters/{id}/pages` | Chapter page management (V2) |
| v2 processing routes | `/admin/v2/books/{id}/chapters/{id}` | Chapter processing, topic extraction, jobs (V2) |
| v2 sync routes | `/admin/v2/books/{id}` | Sync processed topics to curriculum + results (V2) |
| pixi poc | `/api/admin/pixi-poc` | Pixi.js code generation from text prompts (PoC) |

---

## Frontend Structure

```
llm-frontend/src/
├── App.tsx               # Root component + routing
├── TutorApp.tsx          # Legacy redirect (→ /learn)
├── api.ts                # API client with auth token handling
├── pages/                # Route-level pages
│   ├── LoginPage.tsx, EmailLoginPage.tsx, PhoneLoginPage.tsx
│   ├── OTPVerifyPage.tsx, EmailSignupPage.tsx, EmailVerifyPage.tsx
│   ├── ForgotPasswordPage.tsx, OAuthCallbackPage.tsx
│   ├── OnboardingFlow.tsx
│   ├── SubjectSelect.tsx     # Subject picker (/learn)
│   ├── ChapterSelect.tsx     # Chapter picker (/learn/:subject)
│   ├── TopicSelect.tsx       # Topic picker (/learn/:subject/:chapter)
│   ├── ModeSelectPage.tsx    # Mode picker (/learn/:subject/:chapter/:topic)
│   ├── ChatSession.tsx       # Chat UI (/learn/.../teach|exam|clarify/:sessionId)
│   ├── ExamReviewPage.tsx    # Post-exam question-by-question review
│   ├── ProfilePage.tsx
│   ├── EnrichmentPage.tsx    # Parent enrichment profile form + personality card
│   ├── SessionHistoryPage.tsx
│   └── ReportCardPage.tsx    # Student report card (coverage %, exam scores)
├── hooks/
│   └── useStudentProfile.ts  # Student profile hook (board, grade, country)
├── contexts/
│   └── AuthContext.tsx    # Global auth state (Cognito SDK)
├── components/
│   ├── AppShell.tsx          # Shared layout for authenticated pages (nav bar, user menu)
│   ├── ProtectedRoute.tsx, OnboardingGuard.tsx
│   ├── ModeSelection.tsx     # Learning mode picker (teach/clarify/exam/resume)
│   ├── VisualExplanation.tsx # Renders LLM-generated Pixi.js visuals in sandboxed iframe
│   ├── ExplanationViewer.tsx # Step-by-step card viewer for pre-computed explanation variants
│   └── enrichment/           # Enrichment form components
│       ├── SectionCard.tsx
│       ├── ChipSelector.tsx
│       └── SessionPreferences.tsx
├── features/
│   ├── admin/            # Admin pages, components, API client, types
│   │   ├── api/
│   │   │   ├── adminApi.ts          # Admin API client (evaluation, docs, LLM config, feature flags, test scenarios)
│   │   │   └── adminApiV2.ts        # Book ingestion V2 API client
│   │   ├── components/
│   │   │   └── AdminLayout.tsx      # Shared admin layout with persistent top nav bar
│   │   ├── pages/
│   │   │   ├── AdminHome.tsx        # Admin dashboard landing page with cards linking to all admin sections
│   │   │   ├── BookV2Dashboard.tsx   # V2 book management dashboard
│   │   │   ├── CreateBookV2.tsx      # Create new book (V2)
│   │   │   ├── BookV2Detail.tsx      # Book detail + chapters (V2)
│   │   │   ├── EvaluationDashboard.tsx
│   │   │   ├── DocsViewer.tsx        # In-app documentation browser
│   │   │   ├── LLMConfigPage.tsx     # LLM model config admin
│   │   │   ├── FeatureFlagsPage.tsx  # Feature flag toggle admin
│   │   │   ├── TestScenariosPage.tsx # E2E test results viewer
│   │   │   └── PixiJsPocPage.tsx    # Pixi.js visual generation PoC
│   │   └── types/
│   │       └── index.ts             # TypeScript types for admin features (eval, LLM config, feature flags)
│   └── devtools/         # Debug tools (shown in chat session)
│       ├── api/devToolsApi.ts         # Dev tools API client
│       ├── components/
│       │   ├── DevToolsDrawer.tsx     # Expandable debug drawer
│       │   ├── AgentLogsPanel.tsx     # Agent execution log viewer
│       │   ├── GuidelinesPanel.tsx    # Active guidelines viewer
│       │   └── StudyPlanPanel.tsx     # Active study plan viewer
│       └── types/index.ts            # Dev tools type definitions
└── config/
    └── auth.ts           # Cognito config
```

### Route Map

| Route | Page | Auth | Purpose |
|-------|------|------|---------|
| `/login` | LoginPage | Public | Auth method selection |
| `/login/email` | EmailLoginPage | Public | Email/password login |
| `/login/phone` | PhoneLoginPage | Public | Phone number entry |
| `/login/phone/verify` | OTPVerifyPage | Public | OTP verification |
| `/signup/email` | EmailSignupPage | Public | Email signup |
| `/signup/email/verify` | EmailVerifyPage | Public | Email verification |
| `/forgot-password` | ForgotPasswordPage | Public | Password reset |
| `/auth/callback` | OAuthCallbackPage | Public | Google OAuth callback |
| `/` | (redirect) | — | Redirects to `/learn` |
| `/learn` | AppShell > SubjectSelect | Protected + Onboarding | Subject picker |
| `/learn/:subject` | AppShell > ChapterSelect | Protected + Onboarding | Chapter picker |
| `/learn/:subject/:chapter` | AppShell > TopicSelect | Protected + Onboarding | Topic picker |
| `/learn/:subject/:chapter/:topic` | AppShell > ModeSelectPage | Protected + Onboarding | Mode picker (teach/clarify/exam/resume) |
| `/learn/:subject/:chapter/:topic/teach/:sessionId` | ChatSession | Protected + Onboarding | Teach Me chat session |
| `/learn/:subject/:chapter/:topic/exam/:sessionId` | ChatSession | Protected + Onboarding | Exam chat session |
| `/learn/:subject/:chapter/:topic/clarify/:sessionId` | ChatSession | Protected + Onboarding | Clarify Doubts chat session |
| `/learn/:subject/:chapter/:topic/exam-review/:sessionId` | AppShell > ExamReviewPage | Protected + Onboarding | Post-exam review with answers |
| `/session/:sessionId` | ChatSession | Protected + Onboarding | Legacy session URL (backward compat) |
| `/profile` | AppShell > ProfilePage | Protected + Onboarding | Profile management |
| `/profile/enrichment` | AppShell > EnrichmentPage | Protected + Onboarding | Parent enrichment profile + personality |
| `/history` | AppShell > SessionHistoryPage | Protected + Onboarding | Past sessions |
| `/report-card` | AppShell > ReportCardPage | Protected + Onboarding | Student report card |
| `/onboarding` | OnboardingFlow | Protected | First-time setup |
| `/admin` | AdminLayout > AdminHome | Unprotected | Admin dashboard landing page with links to all admin sections |
| `/admin/books` | (redirect) | Unprotected | Redirects to `/admin/books-v2` |
| `/admin/books-v2` | AdminLayout > BookV2Dashboard | Unprotected | Book management (V2) |
| `/admin/books-v2/new` | AdminLayout > CreateBookV2 | Unprotected | Create new book (V2) |
| `/admin/books-v2/:id` | AdminLayout > BookV2Detail | Unprotected | Book detail + chapters (V2) |
| `/admin/evaluation` | AdminLayout > EvaluationDashboard | Unprotected | Evaluation dashboard |
| `/admin/docs` | AdminLayout > DocsViewer | Unprotected | Project documentation browser |
| `/admin/llm-config` | AdminLayout > LLMConfigPage | Unprotected | LLM provider/model configuration |
| `/admin/feature-flags` | AdminLayout > FeatureFlagsPage | Unprotected | Toggle runtime feature flags on/off |
| `/admin/test-scenarios` | AdminLayout > TestScenariosPage | Unprotected | E2E test results and screenshots |
| `/admin/pixi-js-poc` | AdminLayout > PixiJsPocPage | Unprotected | Pixi.js visual generation PoC |

---

## Code Conventions

### Backend Layers

```
Request → API → Service → Agent/Orchestration → Repository → Database
```

| Layer | Responsibility | Rules |
|-------|---------------|-------|
| **API** | HTTP endpoints | Routes, request/response handling |
| **Service** | Business logic | Stateless, coordinates repos + agents |
| **Agent** | LLM-powered actor | Has persona, prompt, structured output |
| **Orchestration** | Agent coordination | Defines execution flow, state transitions |
| **Repository** | Data access | CRUD operations, returns domain objects |

### File Naming

| Pattern | Purpose |
|---------|---------|
| `<entity>_repository.py` | Data access |
| `<domain>_service.py` | Business logic |
| `<role>_agent.py` | LLM-powered actor |
| `orchestrator.py` | Agent orchestration |

### Decision Guide

```
Database read/write?      → Repository
LLM-powered with persona? → Agent
Coordinating agents?      → Orchestration
HTTP endpoint?            → API
Everything else?          → Service
```

---

## LLM Provider System

The backend supports multiple LLM providers via an adapter pattern. Provider and model selection is **DB-backed** via the `llm_config` table, managed through the `/admin/llm-config` admin UI.

### Available Providers and Models

| Provider | Config Value | Available Models | Usage |
|----------|-------------|------------------|-------|
| OpenAI | `openai` | gpt-5.4, gpt-5.3-codex, gpt-5.2, gpt-5.1, gpt-4o, gpt-4o-mini | Tutor, ingestion, transcription (Whisper) |
| Anthropic | `anthropic` | claude-opus-4-6, claude-haiku-4-5-20251001 | Tutor, evaluation |
| Google | `google` | gemini-3-pro-preview | Alternative provider |
| Claude Code | `claude_code` | claude-code | Local/admin workflows via CLI subprocess (book ingestion, etc.) |

### LLM Configuration (DB-Backed)

Each system component (tutor, book_ingestion_v2, evaluator, etc.) has its own row in the `llm_config` DB table specifying which provider and model it uses. This replaced the earlier environment-variable-based provider switching.

- **Admin UI**: `/admin/llm-config` page lets admins change provider + model per component
- **API**: `GET /api/admin/llm-config` lists all configs; `PUT /api/admin/llm-config/{component_key}` updates one
- **No fallbacks**: If a component's config is missing from the DB, the system raises `LLMConfigNotFoundError`

### Key Provider Files

| File | Purpose |
|------|---------|
| `shared/services/llm_service.py` | Centralized LLM call interface; routes to OpenAI, Anthropic, Gemini, or Claude Code based on provider |
| `shared/services/anthropic_adapter.py` | Claude adapter: thinking budgets, tool_use structured output, streaming |
| `shared/services/claude_code_adapter.py` | Claude Code CLI adapter: calls `claude` binary as subprocess for local/admin LLM tasks |
| `shared/services/llm_config_service.py` | Reads/writes LLM config from `llm_config` DB table |
| `shared/services/ocr_service.py` | OCR via OpenAI Vision API for textbook page image extraction |
| `shared/repositories/llm_config_repository.py` | CRUD for `llm_config` table |
| `shared/repositories/explanation_repository.py` | CRUD for `topic_explanations` table (pre-computed explanation variants) |
| `shared/api/llm_config_routes.py` | Admin API endpoints for LLM config (list, update, options) |

### Provider Features

- **Structured output**: OpenAI uses `json_schema` (strict mode); Anthropic uses thinking + tool_use
- **Reasoning levels**: none, low, medium, high, xhigh (mapped to thinking budgets for Claude: 0, 5K, 10K, 20K, 40K tokens)
- **Retry**: 3 attempts with exponential backoff for rate limits and timeouts
- **Schema conversion**: `make_schema_strict()` converts Pydantic models to OpenAI strict schema format
- **OpenAI API selection**: gpt-5.4/gpt-5.3-codex/gpt-5.2/gpt-5.1 use the Responses API; gpt-4o/gpt-4o-mini use Chat Completions
- **Streaming**: `call_stream()` yields text chunks via OpenAI Responses API or Chat Completions streaming; Anthropic streams via adapter; Gemini falls back to non-streaming
- **Fast model**: `call_fast()` always uses gpt-4o-mini via Chat Completions for lightweight tasks (translation, safety checks) regardless of provider setting
- **Prompt caching**: Anthropic adapter splits prompts on `---` separator to extract a system portion marked with `cache_control`, reducing latency on repeated calls
- **Gemini**: Google Generative AI client with JSON mode support
- **Claude Code**: Calls the `claude` CLI as a subprocess (`--dangerously-skip-permissions --no-session-persistence --max-turns 1`). Maps reasoning effort to CLI `--effort` flag. Extracts JSON from response text (handles markdown fences and raw JSON). Used for local/admin workflows where the Claude Code CLI is available on the machine

---

## Feature Flag System

Runtime feature toggles stored in the `feature_flags` DB table. Flags are seeded during migration (`db.py`) and managed through the `/admin/feature-flags` admin UI.

- **Admin UI**: `/admin/feature-flags` page lets admins toggle each flag on or off. Changes take effect immediately for new sessions.
- **API**: `GET /api/admin/feature-flags` lists all flags; `PUT /api/admin/feature-flags/{flag_name}` toggles one. Only existing flags can be updated (404 for unknown names).
- **Service**: `FeatureFlagService.is_enabled(flag_name)` returns `True`/`False` — called from backend code to gate features at runtime.
- **Seeded flags**: `show_visuals_in_tutor_flow` (controls Pixi.js visual explanations during tutoring sessions).

### Key Feature Flag Files

| File | Purpose |
|------|---------|
| `shared/services/feature_flag_service.py` | Read/write feature flags from DB; `is_enabled()` check |
| `shared/repositories/feature_flag_repository.py` | CRUD for `feature_flags` table |
| `shared/api/feature_flag_routes.py` | Admin API endpoints (list, toggle) |
| `shared/models/entities.py` (`FeatureFlag`) | ORM entity for `feature_flags` table |
| `db.py` (`_FEATURE_FLAG_SEEDS`) | Default flag seeds applied during migration |

---

## Configuration

Centralized via Pydantic `BaseSettings` in `config.py`. Reads from `.env` file + environment variables.

| Group | Key Settings |
|-------|-------------|
| Database | `database_url`, `db_pool_size` (5), `db_max_overflow` (10), `db_pool_timeout` (30) |
| LLM API Keys | `openai_api_key`, `anthropic_api_key`, `gemini_api_key`, `google_cloud_tts_api_key` |
| AWS | `aws_region`, `aws_s3_bucket` |
| Cognito | `cognito_user_pool_id`, `cognito_app_client_id`, `cognito_region` |
| Logging | `log_level` (INFO), `log_format` (json/text) |
| App | `environment` (development/staging/production), `api_host`, `api_port` |

**Note:** Provider/model selection is no longer in `config.py`. It is managed via the `llm_config` DB table (see LLM Provider System above). The config file only holds API keys.

Required at startup: `OPENAI_API_KEY` and `DATABASE_URL`.
