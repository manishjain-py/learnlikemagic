# Documentation Guidelines

How LearnLikeMagic documentation is structured, written, and maintained.

---

## Documentation Structure

```
docs/
├── DOCUMENTATION_GUIDELINES.md       # This file: structure, rules, update process
├── functional/                       # User perspective (no code)
│   ├── app-overview.md               # What the app is, purpose, user journey
│   ├── learning-session.md           # Tutoring experience from student POV
│   ├── evaluation.md                 # Tutor quality testing from admin POV
│   ├── scorecard.md                  # Student progress report
│   ├── book-guidelines.md            # Book ingestion from admin POV
│   └── auth-and-onboarding.md        # Login, signup, onboarding
├── technical/                        # Developer perspective (code, APIs, data flows)
│   ├── architecture-overview.md      # Full-stack architecture, tech stack, conventions
│   ├── learning-session.md           # Tutor pipeline: agents, orchestration, WebSocket
│   ├── evaluation.md                 # Evaluation pipeline: simulator, judge, reports
│   ├── scorecard.md                  # Scorecard service, API, aggregation
│   ├── book-guidelines.md            # Book ingestion, OCR, guideline extraction
│   ├── auth-and-onboarding.md        # Cognito, auth flows, user management
│   ├── dev-workflow.md               # Local setup, testing, git workflow
│   ├── deployment.md                 # AWS infra, Terraform, CI/CD
│   └── database.md                   # Tables, schema, migrations
└── archive/                          # Preserved historical docs
    ├── SESSION_LOG_TUTOR_REWRITE.md
    └── feature-development/          # PRDs, implementation plans, trackers
```

**Functional docs** describe features from the user's perspective. No code, no file paths, no technical jargon. Written as if explaining the product to someone who will use it.

**Technical docs** describe the same features from the developer's perspective. Include architecture diagrams, code paths, API endpoints, data models, and key files.

---

## Master Index

| Doc | Purpose | When to Reference |
|-----|---------|-------------------|
| `docs/DOCUMENTATION_GUIDELINES.md` | Doc structure, writing rules, master index | Understanding doc organization |
| **Functional** | | |
| `docs/functional/app-overview.md` | What the app is, user journey, UX philosophy | App context, onboarding new people |
| `docs/functional/learning-session.md` | Tutoring experience from student POV | Understanding the tutor feature |
| `docs/functional/evaluation.md` | Tutor quality testing from admin POV | Understanding evaluation |
| `docs/functional/scorecard.md` | Student progress report | Understanding scorecard |
| `docs/functional/book-guidelines.md` | Book → guidelines → study plans from admin POV | Understanding content pipeline |
| `docs/functional/auth-and-onboarding.md` | Login, signup, onboarding | Understanding auth flows |
| **Technical** | | |
| `docs/technical/architecture-overview.md` | Full-stack architecture, tech stack, conventions | Code organization, adding new code |
| `docs/technical/learning-session.md` | Tutor pipeline technical details | Working on tutor code |
| `docs/technical/evaluation.md` | Evaluation pipeline technical details | Working on evaluation |
| `docs/technical/scorecard.md` | Scorecard service technical details | Working on scorecard |
| `docs/technical/book-guidelines.md` | Book/guidelines pipeline technical details | Working on content pipeline |
| `docs/technical/auth-and-onboarding.md` | Auth architecture, Cognito, APIs | Working on auth |
| `docs/technical/dev-workflow.md` | Local setup, testing, git workflow | Dev environment, testing |
| `docs/technical/deployment.md` | AWS infra, Terraform, CI/CD | Deploying, debugging prod |
| `docs/technical/database.md` | DB schema, migrations | Database changes |

---

## Writing Principles

1. **Compact** — Say what needs saying, nothing more. No filler, no redundant sections.
2. **Accurate** — Every claim must match the current code. If in doubt, verify before writing.
3. **Easy to scan** — Use tables, bullet lists, and short paragraphs. Avoid walls of text.
4. **One audience per doc** — Functional docs speak to users/admins. Technical docs speak to developers. Never mix.

### Functional Doc Template

Each functional doc follows this structure:
- **What It Is** — One-paragraph overview
- **How It Works** — Step-by-step user flow
- **Key Principles** — Philosophy or design intent (where relevant)
- **Key Details** — Specifics the user should know

No code snippets, file paths, or API references in functional docs.

### Technical Doc Template

Each technical doc follows this structure:
- **Architecture** — Diagram or component overview
- **Key Components** — What each piece does
- **Data Flow** — How data moves through the system
- **API Endpoints** — Method, path, description
- **Key Files** — File path and purpose
- **Configuration** — Environment variables, settings

---

## UX Writing Principles

These principles guide both the app's UI and how functional docs describe the experience. The primary users are **students (kids)**.

| Principle | What It Means |
|-----------|---------------|
| **One thing per screen** | Each screen has one clear purpose. Big, clear buttons. Focused flows. |
| **Minimal typing** | Prefill what you can. Use pickers and selectors over free-text. |
| **Friendly language** | No jargon. Say "What's your name?" not "Enter display name". Write like you're talking to the student. |
| **Forgiving inputs** | Accept messy input gracefully. Inline validation, not error popups. Never make the student feel wrong. |
| **Fast** | No interaction should feel slow. Loading spinners under 2 seconds. |
| **Skippable where possible** | Optional steps have a clear, prominent "Skip for now" button. |
| **Mobile-first** | Design for phone screens first. Big tap targets (min 44px), no tiny links. |
| **Warm and encouraging** | The app feels like a friendly tutor. "You're all set!" not "Account created successfully." |
| **Consistent** | Same patterns everywhere. Predictability builds trust. |
| **Accessible** | Sufficient contrast, readable fonts (min 16px), screen-reader friendly labels. |

**Checklist for any feature:**
- Can a student figure out what to do within 3 seconds?
- Is there only one primary action per screen?
- Is the language something a 10-year-old would understand?
- Does it work well on a phone?
- Are error states helpful and kind?

---

## Keeping Docs Updated

### The Update Skill

Run `/update-all-docs` to automatically update all documentation against the current codebase.

**How it works:**
1. Reads `DOCUMENTATION_GUIDELINES.md` for structure and rules
2. Launches 7 specialized sub-agents in parallel, each responsible for its feature area
3. Each agent reads the relevant code, compares with existing docs, and updates both functional and technical docs
4. Updates the master index if any docs were added or renamed
5. Logs all changes to `tmp/DOCS_UPDATE_CHANGELOG.md`

**When to run:**
- After significant feature changes
- Before a release
- When onboarding a new developer

**Sub-agents:**
1. App Overview & Architecture
2. Learning Session
3. Evaluation
4. Scorecard
5. Book & Guidelines
6. Auth & Onboarding
7. Infrastructure (dev workflow, deployment, database)
