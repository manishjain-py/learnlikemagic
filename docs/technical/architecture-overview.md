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
│  Shared: llm_service, anthropic_adapter, models, utils          │
└────────────────────────────┬────────────────────────────────────┘
                             │ SQLAlchemy
┌────────────────────────────▼────────────────────────────────────┐
│  Database (Aurora Serverless v2 PostgreSQL)                      │
│  Tables: users, sessions, events, contents,                     │
│          teaching_guidelines, study_plans, books, book_jobs,     │
│          book_guidelines                                        │
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
| OpenAI | LLM provider (GPT-5.2) | Structured outputs, Responses API, reasoning models |
| Anthropic | LLM provider (Claude) | Multi-provider flexibility, extended thinking capability |

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
├── tutor/                # Runtime tutoring sessions
├── book_ingestion/       # Book upload & guideline extraction
├── study_plans/          # Study plan generation
├── evaluation/           # Session evaluation pipeline
├── shared/               # Cross-module utilities
├── api/                  # Root API (health, curriculum)
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
| health | `/health` | Health checks |
| curriculum | `/curriculum` | Curriculum hierarchy API |
| sessions | `/sessions` | Session management, scorecard |
| evaluation | `/evaluation` | Evaluation pipeline |
| admin books | `/admin/books` | Book ingestion admin |
| admin guidelines | `/admin/guidelines` | Guidelines admin |
| auth | `/auth` | Auth sync, phone provision |
| profile | `/profile` | User profile CRUD |

---

## Frontend Structure

```
llm-frontend/src/
├── App.tsx               # Root component + routing
├── TutorApp.tsx          # Main tutor UI (chat + topic selection)
├── api.ts                # API client
├── pages/                # Route-level pages
│   ├── LoginPage.tsx, EmailLoginPage.tsx, PhoneLoginPage.tsx
│   ├── OTPVerifyPage.tsx, EmailSignupPage.tsx, EmailVerifyPage.tsx
│   ├── ForgotPasswordPage.tsx
│   ├── OnboardingFlow.tsx
│   ├── ProfilePage.tsx
│   ├── SessionHistoryPage.tsx
│   └── ScorecardPage.tsx
├── contexts/
│   └── AuthContext.tsx    # Global auth state (Cognito SDK)
├── components/
│   └── ProtectedRoute.tsx, OnboardingGuard.tsx
├── features/
│   ├── admin/            # Admin pages + components
│   └── devtools/         # Debug tools
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
| `/auth/callback` | OAuth callback | Public | Google OAuth callback |
| `/` | TutorApp | Protected + Onboarding | Main tutoring interface |
| `/profile` | ProfilePage | Protected | Profile management |
| `/history` | SessionHistoryPage | Protected | Past sessions |
| `/scorecard` | ScorecardPage | Protected | Student scorecard |
| `/onboarding` | OnboardingFlow | Protected | First-time setup |
| `/admin/*` | Admin pages | Unprotected | Admin tools |

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

The backend supports multiple LLM providers via an adapter pattern:

| Provider | Config Value | Models | Usage |
|----------|-------------|--------|-------|
| OpenAI | `openai` | GPT-5.2 (fallback: GPT-5.1, GPT-4o) | Default tutor + ingestion |
| Anthropic | `anthropic` | Claude Opus 4.6 | Tutor + evaluation |
| Anthropic Haiku | `anthropic-haiku` | Claude Haiku 4.5 | Fast/cheap tutor |

### Provider Switching

Set via environment variable:
- `APP_LLM_PROVIDER` — Tutor provider (`openai`, `anthropic`, `anthropic-haiku`)
- `EVAL_LLM_PROVIDER` — Evaluator provider (defaults to `anthropic`)

### Key Provider Files

| File | Purpose |
|------|---------|
| `shared/services/llm_service.py` | OpenAI wrapper with structured output, retry, fallback |
| `shared/services/anthropic_adapter.py` | Claude adapter using thinking + tool_use for structured output |
| `config.py` | `resolved_tutor_provider` property for provider selection |

### Provider Features

- **Structured output**: OpenAI uses `json_schema` (strict); Anthropic uses thinking + tool_use
- **Reasoning levels**: none, low, medium, high, xhigh (mapped to thinking budgets for Claude)
- **Retry**: 3 attempts with exponential backoff
- **Schema conversion**: `make_schema_strict()` converts Pydantic models to OpenAI strict schema format

---

## Configuration

Centralized via Pydantic `BaseSettings` in `config.py`. Reads from `.env` file + environment variables.

| Group | Key Settings |
|-------|-------------|
| Database | `database_url`, `db_pool_size` (5), `db_max_overflow` (10) |
| LLM | `openai_api_key`, `anthropic_api_key`, `tutor_llm_provider` |
| AWS | `aws_region`, `aws_s3_bucket` |
| Cognito | `cognito_user_pool_id`, `cognito_app_client_id` |
| Logging | `log_level` (INFO), `log_format` (json/text) |
| App | `environment` (development/staging/production) |

Required at startup: `OPENAI_API_KEY` and `DATABASE_URL`.
