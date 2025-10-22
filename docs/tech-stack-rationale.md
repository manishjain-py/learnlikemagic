# 🧩 Tech Stack Rationale – LearnLikeMagic

This document explains **what frameworks, libraries, and cloud services** power the LearnLikeMagic architecture, **why** they are used, and **what makes each of them special**.  
It’s structured by layers: **Backend**, **Frontend**, **Infrastructure & Deployment**, and **Supporting Tools**.

---

## ⚙️ Backend

| Framework / Library | Purpose | Why It’s Popular / Why We Use It |
|----------------------|----------|----------------------------------|
| **FastAPI** | Main web framework for REST APIs | Extremely fast, modern Python 3 syntax, auto-generated Swagger docs, async-ready, great developer experience |
| **Uvicorn** | ASGI server that runs FastAPI | Lightweight and high-performance server, pairs naturally with FastAPI |
| **Pydantic** | Data validation & serialization | Uses Python type hints for validation, clear error handling and schema generation |
| **SQLAlchemy** | ORM for database access | Mature, flexible, database-agnostic ORM; easy migration from SQLite → PostgreSQL |
| **Alembic** *(optional)* | Database migrations for SQLAlchemy | Versioned schema evolution; safe upgrades/downgrades |
| **LangGraph** | LLM agent orchestration framework | Deterministic, graph-based state management for AI agent workflows (e.g., adaptive tutoring logic) |

---

## 🖥️ Frontend

| Framework / Library | Purpose | Why It’s Popular / Why We Use It |
|----------------------|----------|----------------------------------|
| **React** | UI component library | Dominant frontend ecosystem, reusable components, strong community support |
| **TypeScript** | Typed JavaScript | Adds type safety, better refactorability, and IDE auto-complete support |
| **Vite** | Development server & build tool | Lightning-fast hot module reloads (HMR), minimal config, faster builds vs. Webpack |
| **Axios / Fetch API** | HTTP client for API calls | Simplifies REST calls; clean syntax and async support |

---

## ☁️ Infrastructure & Deployment

| Technology | Purpose | Why It’s Popular / Why We Use It |
|-------------|----------|----------------------------------|
| **Docker** | Containerization | Ensures consistent runtime across environments; perfect for CI/CD pipelines and App Runner |
| **AWS App Runner** | Run backend container | Fully managed container platform; autoscaling, HTTPS, and no server management |
| **Amazon ECR** | Container image registry | Secure, private image storage that integrates natively with App Runner |
| **AWS S3** | Static file hosting | Cheap, reliable, and scalable storage for frontend builds |
| **Amazon CloudFront** | Global CDN | Speeds up delivery with edge caching and SSL termination |
| **Aurora Serverless v2 (PostgreSQL)** | Managed relational database | Auto-scaling, pay-per-use PostgreSQL; production-grade without maintenance overhead |
| **AWS Secrets Manager** | Secure credentials storage | Centralized, encrypted secrets (API keys, DB passwords) with rotation support |
| **AWS CloudWatch** | Logging & monitoring | Unified logs and metrics for App Runner, RDS, and other AWS resources |
| **GitHub Actions** | CI/CD automation | Native to GitHub; handles push-to-deploy for frontend & backend |
| **OIDC (GitHub → AWS)** | Secure CI authentication | Removes need for static AWS keys; grants temporary, least-privilege access |
| **Terraform** | Infrastructure as Code | Declarative, version-controlled infra for easy provisioning and teardown |
| **Makefile** | Developer automation | Simplifies repetitive commands: build, deploy, terraform, etc. |

---

## 🧰 Supporting / Utility Tools

| Tool | Purpose | Why It’s Popular / Why We Use It |
|------|----------|----------------------------------|
| **CORS Middleware (FastAPI)** | Allow frontend ↔ backend communication | Required for browser-based API access between domains |
| **OpenAPI / Swagger Docs** | Auto-generated API documentation | Great for quick API testing and collaboration |
| **GitHub OIDC Roles** | Secure AWS deployments | Enables short-lived credentials for CI/CD pipelines |
| **PostgreSQL Client / psycopg2** | Database driver | Standard, well-supported driver for PostgreSQL in Python |

---

## 🧠 Why This Combination Works

- **FastAPI + Uvicorn + Pydantic** → High-performance, type-safe backend foundation with minimal boilerplate.  
- **React + TypeScript + Vite** → Fastest modern frontend workflow for building interactive UIs.  
- **SQLAlchemy + Alembic** → Proven DB abstraction that evolves cleanly with schema versioning.  
- **App Runner + S3 + CloudFront** → 100% managed hosting: autoscaling, HTTPS, and no server upkeep.  
- **Terraform + GitHub Actions + OIDC** → Secure, reproducible, and automated deployments.  
- **Secrets Manager + RDS Serverless** → Enterprise-grade security and scalability with near-zero ops.

This stack strikes the ideal balance between **speed of development**, **operational simplicity**, and **scalability** — making it perfect for solo founders and small teams who want **production reliability** without managing infrastructure.

---

**🏗️ Summary:**  
> LearnLikeMagic’s architecture is built for fast iteration, full automation, and zero-maintenance scalability — combining developer-friendly tools like FastAPI and Vite with AWS’s managed cloud ecosystem.
