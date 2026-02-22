# Architecture Overview

Full-stack architecture, tech stack, and code conventions for LearnLikeMagic.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (React + TypeScript + Vite)                           │
│  S3 + CloudFront                                                │
│  Routes: /, /login, /profile, /scorecard, /admin/*              │
└────────────────────────────┬────────────────────────────────────┘
                             │ REST API + WebSocket
┌────────────────────────────▼────────────────────────────────────┐
│  Backend (FastAPI + Python)                                     │
│  AWS App Runner                                                 │
│                                                                 │
│  Modules: tutor, book_ingestion, study_plans, evaluation, auth  │
│  Shared: llm_service, llm_config_service, anthropic_adapter,    │
│          models, utils, repositories                            │
└────────────────────────────┬────────────────────────────────────┘
                             │ SQLAlchemy
┌────────────────────────────▼────────────────────────────────────┐
│  Database (Aurora Serverless v2 PostgreSQL)                      │
│  Tables: users, sessions, events, contents,                     │
│          teaching_guidelines, study_plans, books, book_jobs,     │
│          book_guidelines, llm_config                            │
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
| OpenAI | LLM provider (GPT-5.2, Whisper) | Structured outputs, Responses API, reasoning models, audio transcription |
| Anthropic | LLM provider (Claude) | Multi-provider flexibility, extended thinking capability |
| Google | LLM provider (Gemini) | Additional provider option for flexibility |

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
├── book_ingestion/       # Book upload & guideline extraction
├── study_plans/          # Study plan generation
├── evaluation/           # Session evaluation pipeline
├── auth/                 # Authentication & user profiles
├── shared/               # Cross-module utilities
├── api/                  # Root-level API (docs endpoint)
├── tests/
├── main.py               # FastAPI app entrypoint
├── config.py             # Pydantic settings
├── db.py                 # Migration CLI
└── database.py           # Connection management
```

Each module follows the same internal structure:

```
<module>/
├── api/              # REST endpoints
├── services/         # Business logic
├── agents/           # LLM-powered actors (AI modules only)
├── orchestration/    # Agent coordination (AI modules only)
├── repositories/     # Database access
├── models/           # Pydantic schemas
└── prompts/          # LLM prompt templates
```

### Routers Registered in `main.py`

| Router | Prefix | Purpose |
|--------|--------|---------|
| health | `/` | Health checks, root endpoint |
| curriculum | `/curriculum` | Curriculum hierarchy API |
| sessions | `/sessions` | Session management, scorecard, WebSocket |
| transcription | `/transcribe` | Audio-to-text via OpenAI Whisper |
| evaluation | `/api/evaluation` | Evaluation pipeline |
| admin books | `/admin/books` | Book ingestion admin |
| admin guidelines | `/admin/guidelines` | Guidelines admin |
| auth | `/auth` | Auth sync (Cognito to local DB) |
| profile | `/profile` | User profile CRUD |
| docs | `/api/docs` | Documentation API for admin viewer |
| llm config | `/api/admin/llm-config` | LLM model configuration admin |

---

## Frontend Structure

```
llm-frontend/src/
├── App.tsx               # Root component + routing
├── TutorApp.tsx          # Main tutor UI (topic selection + chat + modes)
├── api.ts                # API client with auth token handling
├── pages/                # Route-level pages
│   ├── LoginPage.tsx, EmailLoginPage.tsx, PhoneLoginPage.tsx
│   ├── OTPVerifyPage.tsx, EmailSignupPage.tsx, EmailVerifyPage.tsx
│   ├── ForgotPasswordPage.tsx, OAuthCallbackPage.tsx
│   ├── OnboardingFlow.tsx
│   ├── ProfilePage.tsx
│   ├── SessionHistoryPage.tsx
│   └── ScorecardPage.tsx
├── contexts/
│   └── AuthContext.tsx    # Global auth state (Cognito SDK)
├── components/
│   ├── ProtectedRoute.tsx, OnboardingGuard.tsx
│   └── ModeSelection.tsx # Learning mode picker (teach/clarify/exam/resume)
├── features/
│   ├── admin/            # Admin pages + components
│   │   └── pages/
│   │       ├── BooksDashboard.tsx, CreateBook.tsx, BookDetail.tsx
│   │       ├── GuidelinesReview.tsx, EvaluationDashboard.tsx
│   │       ├── DocsViewer.tsx    # In-app documentation browser
│   │       └── LLMConfigPage.tsx # LLM model config admin
│   └── devtools/         # Debug tools (agent logs, guidelines, study plan)
└── config/               # Cognito config, constants
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
| `/` | TutorApp | Protected + Onboarding | Main tutoring interface (topic selection + chat) |
| `/profile` | ProfilePage | Protected | Profile management |
| `/history` | SessionHistoryPage | Protected | Past sessions |
| `/scorecard` | ScorecardPage | Protected | Student scorecard |
| `/report-card` | ScorecardPage | Protected | Alias for scorecard |
| `/onboarding` | OnboardingFlow | Protected | First-time setup |
| `/admin` | (redirect) | Unprotected | Redirects to `/admin/books` |
| `/admin/books` | BooksDashboard | Unprotected | Book management |
| `/admin/books/new` | CreateBook | Unprotected | Create new book |
| `/admin/books/:id` | BookDetail | Unprotected | Book detail + pages |
| `/admin/guidelines` | GuidelinesReview | Unprotected | Guidelines review |
| `/admin/evaluation` | EvaluationDashboard | Unprotected | Evaluation dashboard |
| `/admin/docs` | DocsViewer | Unprotected | Project documentation browser |
| `/admin/llm-config` | LLMConfigPage | Unprotected | LLM provider/model configuration |

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
| OpenAI | `openai` | gpt-5.2, gpt-5.1, gpt-4o, gpt-4o-mini | Tutor, ingestion, transcription (Whisper) |
| Anthropic | `anthropic` | claude-opus-4-6, claude-haiku-4-5-20251001 | Tutor, evaluation |
| Google | `google` | gemini-3-pro-preview | Alternative provider |

### LLM Configuration (DB-Backed)

Each system component (tutor, book_ingestion, evaluator, etc.) has its own row in the `llm_config` DB table specifying which provider and model it uses. This replaced the earlier environment-variable-based provider switching.

- **Admin UI**: `/admin/llm-config` page lets admins change provider + model per component
- **API**: `GET /api/admin/llm-config` lists all configs; `PUT /api/admin/llm-config/{component_key}` updates one
- **No fallbacks**: If a component's config is missing from the DB, the system raises `LLMConfigNotFoundError`

### Key Provider Files

| File | Purpose |
|------|---------|
| `shared/services/llm_service.py` | Centralized LLM call interface; routes to OpenAI, Anthropic, or Gemini based on provider |
| `shared/services/anthropic_adapter.py` | Claude adapter: thinking budgets, tool_use structured output |
| `shared/services/llm_config_service.py` | Reads/writes LLM config from `llm_config` DB table |
| `shared/repositories/llm_config_repository.py` | CRUD for `llm_config` table |
| `shared/api/llm_config_routes.py` | Admin API endpoints for LLM config (list, update, options) |

### Provider Features

- **Structured output**: OpenAI uses `json_schema` (strict mode); Anthropic uses thinking + tool_use
- **Reasoning levels**: none, low, medium, high, xhigh (mapped to thinking budgets for Claude: 0, 5K, 10K, 20K, 40K tokens)
- **Retry**: 3 attempts with exponential backoff for rate limits and timeouts
- **Schema conversion**: `make_schema_strict()` converts Pydantic models to OpenAI strict schema format
- **OpenAI API selection**: gpt-5.2/gpt-5.1 use the Responses API; gpt-4o/gpt-4o-mini use Chat Completions
- **Gemini**: Google Generative AI client with JSON mode support

---

## Configuration

Centralized via Pydantic `BaseSettings` in `config.py`. Reads from `.env` file + environment variables.

| Group | Key Settings |
|-------|-------------|
| Database | `database_url`, `db_pool_size` (5), `db_max_overflow` (10), `db_pool_timeout` (30) |
| LLM API Keys | `openai_api_key`, `anthropic_api_key`, `gemini_api_key` |
| AWS | `aws_region`, `aws_s3_bucket` |
| Cognito | `cognito_user_pool_id`, `cognito_app_client_id`, `cognito_region` |
| Logging | `log_level` (INFO), `log_format` (json/text) |
| App | `environment` (development/staging/production), `api_host`, `api_port` |

**Note:** Provider/model selection is no longer in `config.py`. It is managed via the `llm_config` DB table (see LLM Provider System above). The config file only holds API keys.

Required at startup: `OPENAI_API_KEY` and `DATABASE_URL`.
