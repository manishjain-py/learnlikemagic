# Tech Stack Rationale

## Backend

| Technology | Purpose | Why |
|------------|---------|-----|
| FastAPI | REST API framework | Fast, modern Python, auto Swagger docs, async-ready |
| Uvicorn | ASGI server | Lightweight, high-performance, pairs with FastAPI |
| Pydantic | Data validation | Type hints for validation, clear errors, schema gen |
| SQLAlchemy | ORM | Mature, flexible, database-agnostic |
| OpenAI | LLM provider (GPT-4o, GPT-5.2) | Structured outputs, Responses API, reasoning models |
| Anthropic | LLM provider (Claude) | Multi-provider flexibility, extended thinking capability |

## Frontend

| Technology | Purpose | Why |
|------------|---------|-----|
| React | UI components | Dominant ecosystem, reusable components |
| TypeScript | Typed JavaScript | Type safety, better refactoring, IDE support |
| Vite | Dev server & bundler | Fast HMR, minimal config, faster than Webpack |

## Infrastructure

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

## Why This Stack

**Backend:** FastAPI + Pydantic = type-safe, high-performance API with minimal boilerplate

**Frontend:** React + TypeScript + Vite = fast dev workflow for interactive UIs

**Infrastructure:** App Runner + S3 + CloudFront = fully managed, autoscaling, zero server maintenance

**DevOps:** Terraform + GitHub Actions + OIDC = secure, reproducible, automated deployments

Optimized for **fast iteration**, **operational simplicity**, and **scalability** without managing infrastructure.
