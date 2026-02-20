Update all project documentation to match the current codebase.

**Instructions:**
1. Read `docs/DOCUMENTATION_GUIDELINES.md` to understand structure and writing rules.
2. Launch the following 7 specialized sub-agents **in parallel** using the Task tool.
   Each agent receives:
   - The writing rules (functional = user POV, no code; technical = developer POV, code paths + APIs)
   - Its assigned doc files to update
   - **Discovery instructions** — directories to explore and patterns to search, NOT hardcoded file lists
   - Instruction to log changes with justification

3. **Agent 1 — App Overview & Architecture**
   - Docs: `docs/functional/app-overview.md`, `docs/technical/architecture-overview.md`
   - Discover:
     - Read the existing docs' "Key Files" sections as a starting point
     - Glob `llm-frontend/src/App.tsx` and `llm-frontend/src/TutorApp.tsx` for routes and main flow
     - Glob `llm-backend/main.py` for registered routers
     - Glob `llm-backend/config.py` for settings
     - Glob `llm-backend/shared/**/*.py` for shared services
     - Grep for `include_router` in `llm-backend/` to find all API routers
     - Grep for `LLM|provider|model` in `llm-backend/config.py` and `llm-backend/shared/services/` for LLM provider details
   - Focus: App purpose, user journey, routes, tech stack, module structure, code conventions, LLM providers

4. **Agent 2 — Learning Session**
   - Docs: `docs/functional/learning-session.md`, `docs/technical/learning-session.md`
   - Discover:
     - Read the existing docs' "Key Files" sections as a starting point
     - Glob `llm-backend/tutor/**/*.py` to find all tutor module files
     - Glob `llm-frontend/src/TutorApp.tsx` for the student-facing UI
     - Grep for `class.*Agent` in `llm-backend/tutor/` for agent definitions
     - Grep for `def process_turn` in `llm-backend/tutor/` for orchestration flow
     - Grep for `MASTER_TUTOR` in `llm-backend/tutor/prompts/` for teaching rules
     - Grep for `SessionState|StudyPlan` in `llm-backend/tutor/models/` for state models
   - Focus: Teaching philosophy, session flow, master tutor architecture, safety agent, WebSocket + REST, state management

5. **Agent 3 — Evaluation**
   - Docs: `docs/functional/evaluation.md`, `docs/technical/evaluation.md`
   - Discover:
     - Read the existing docs' "Key Files" sections as a starting point
     - Glob `llm-backend/evaluation/**/*.py` to find all evaluation module files
     - Glob `llm-backend/evaluation/personas/*.json` to find all persona files
     - Grep for `EvaluationDashboard|evaluation` in `llm-frontend/src/` for frontend components
     - Grep for `dimension|scoring` in `llm-backend/evaluation/` for scoring criteria
   - Focus: Persona simulation, session runner, LLM judge, scoring dimensions, report artifacts, dashboard

6. **Agent 4 — Scorecard**
   - Docs: `docs/functional/scorecard.md`, `docs/technical/scorecard.md`
   - Discover:
     - Read the existing docs' "Key Files" sections as a starting point
     - Grep for `scorecard|Scorecard` in `llm-backend/` and `llm-frontend/src/` to find all scorecard-related files
     - Grep for `def get_scorecard` in `llm-backend/` for the aggregation logic
     - Grep for `subtopic-progress|subtopic_progress` in `llm-backend/` for the lightweight endpoint
   - Focus: Score aggregation, hierarchy, trends, strengths/weaknesses, practice-again flow

7. **Agent 5 — Book & Guidelines**
   - Docs: `docs/functional/book-guidelines.md`, `docs/technical/book-guidelines.md`
   - Discover:
     - Read the existing docs' "Key Files" sections as a starting point
     - Glob `llm-backend/book_ingestion/**/*.py` to find all book ingestion files
     - Glob `llm-backend/study_plans/**/*.py` to find all study plan files
     - Grep for `books|guidelines|BooksDashboard|GuidelinesReview` in `llm-frontend/src/features/admin/` for frontend components
     - Grep for `class.*Service` in `llm-backend/book_ingestion/services/` for all pipeline services
   - Focus: Book upload, OCR, guideline extraction, refinement, DB sync, study plan generation

8. **Agent 6 — Auth & Onboarding**
   - Docs: `docs/functional/auth-and-onboarding.md`, `docs/technical/auth-and-onboarding.md`
   - Discover:
     - Read the existing docs' "Key Files" sections as a starting point
     - Grep for `login|Login|signup|Signup|auth|Auth|onboarding|Onboarding|profile|Profile` in `llm-frontend/src/pages/` to find all auth-related pages
     - Glob `llm-frontend/src/contexts/Auth*.tsx` for auth state management
     - Grep for `ProtectedRoute|OnboardingGuard` in `llm-frontend/src/components/` for route guards
     - Grep for `cognito|Cognito` in `llm-frontend/src/` and `llm-backend/` for Cognito integration
     - Grep for `/auth/|/profile` in `llm-backend/` for backend auth endpoints
   - Focus: Auth methods, Cognito, signup/login flows, onboarding wizard, profile management

9. **Agent 7 — Infrastructure**
   - Docs: `docs/technical/dev-workflow.md`, `docs/technical/deployment.md`, `docs/technical/database.md`
   - Discover:
     - Read the existing docs' "Key Files" sections as a starting point
     - Glob `llm-backend/shared/models/entities.py` for all DB table definitions
     - Glob `llm-backend/db.py` and `llm-backend/database.py` for migration and connection logic
     - Glob `infra/terraform/*.tf` for infrastructure definitions
     - Glob `.github/workflows/*.yml` for CI/CD pipelines
     - Glob `llm-backend/Makefile` for build commands
     - Grep for `class.*Base` in `llm-backend/shared/models/` and `llm-backend/book_ingestion/models/` for all ORM models
   - Focus: Local setup, testing, Terraform deployment, Docker, CI/CD, DB schema, migrations

10. After all agents complete, review `docs/DOCUMENTATION_GUIDELINES.md` — update the master index if any docs were added or renamed.
11. Log all changes in `tmp/DOCS_UPDATE_CHANGELOG.md` (overwrite each run).

**For each agent, use this prompt template:**

```
You are updating LearnLikeMagic documentation. Read the assigned docs and compare against the current code.

Writing rules:
- Functional docs: user perspective, no code, no file paths, no jargon
- Technical docs: developer perspective, code paths, APIs, data flows, key files

Your assigned docs: [list]

Discovery steps (do these FIRST before comparing):
1. Read each assigned doc — note the "Key Files" sections as your starting point
2. Run the discovery searches listed above to find ALL relevant code (files may have moved or new ones added)
3. Read the discovered code files
4. Compare with the docs: identify outdated info, missing features, wrong details, stale file paths
5. Update the docs to match current code — including updating the "Key Files" tables
6. Report what you changed and why
```
