# Docs Update Changelog — 2026-03-21

13 docs updated, 0 new docs created.

---

## Updated Docs

### Agent 1 — App Overview & Architecture

| Doc | Changes |
|-----|---------|
| `docs/functional/app-overview.md` | Added Interactive Questions to Core Features table |
| `docs/technical/architecture-overview.md` | Updated OpenAI models (added GPT-5.1, GPT-5.3-codex); added `exceptions.py` to tutor module, `constants.py` to book_ingestion_v2; added 2 autoresearch pipelines (explanation_quality, session_experience); replaced stale ExplanationViewer.tsx with InteractiveQuestion.tsx; updated fast model to show DB-configurable |

### Agent 2 — Learning Session

| Doc | Changes |
|-----|---------|
| `docs/functional/learning-session.md` | Rewrote card phase flow (v2 plan generation); updated teaching philosophy to match 15 rules (verify-practice-extend, strategy switch, false OK ban); added v2 session progression (check/guided/independent/extend steps); added Interactive Question Formats section; added colored emoji detail |
| `docs/technical/learning-session.md` | Added QuestionFormat model; rewrote card phase architecture (welcome gen, v2 plan, bridge turns); updated 14→15 teaching rules; added card_covered_concepts to SessionState; restructured Study Plan into v1/v2; added 6 pacing directives; rewrote card phase flows; added question_format + card_navigate to WebSocket; added 3 LLM calls; updated 6 Key Files entries |

### Agent 3 — Evaluation

| Doc | Changes |
|-----|---------|
| `docs/functional/evaluation.md` | Updated 5→7 dimensions (Card-to-Session Coherence, Transition Quality); added card phase in simulations |
| `docs/technical/evaluation.md` | Updated pipeline diagram for card phase + 7 dimensions; removed stale retry/provider sections; added card content to simulator; documented card phase in session runner; added 3 root cause categories; unified model config with claude_code provider; updated artifact formats; documented frontend dimension gap |

### Agent 4 — Scorecard

| Doc | Changes |
|-----|---------|
| `docs/functional/scorecard.md` | Removed stale end-of-session report card link |
| `docs/technical/scorecard.md` | Removed ChatSession.tsx end-of-session entry point; clarified list_by_guideline coverage formula |

### Agent 5 — Book & Guidelines

| Doc | Changes |
|-----|---------|
| `docs/functional/book-guidelines.md` | Added bulk OCR; added audio_text for TTS; added teaching_notes; added per-topic and force-regenerate explanation gen; added explanation management; added session plans |
| `docs/technical/book-guidelines.md` | Added bulk OCR API routes; added job_type param; expanded sync_routes with 4 endpoints; added audio_text and teaching_notes fields; added Card Fields subsection; added Session Plan Generator; updated eval config with claude_code; updated pipeline diagram and frontend API |

### Agent 6 — Auth & Onboarding

| Doc | Changes |
|-----|---------|
| `docs/functional/auth-and-onboarding.md` | Removed non-existent Focus Mode toggle from profile |
| `docs/technical/auth-and-onboarding.md` | Clarified people_to_reference as array of {name, context} objects |

### Agent 7 — Infrastructure

| Doc | Changes |
|-----|---------|
| `docs/technical/database.md` | Added 2 LLM config seeds: fast_model (gpt-4o-mini), pixi_code_generator (gpt-5.3-codex) |
| `docs/technical/dev-workflow.md` | No changes needed — verified current |
| `docs/technical/deployment.md` | No changes needed — verified current |

---

## Newly Created Docs

None — all functionality adequately covered by existing docs.

---

## Coverage Matrix

| Feature/Module | Functional Doc | Technical Doc |
|---|---|---|
| App overview & user journey | app-overview.md | architecture-overview.md |
| Learning sessions (tutor) | learning-session.md | learning-session.md |
| Card phase & v2 plans | learning-session.md | learning-session.md |
| Interactive questions | learning-session.md | learning-session.md |
| Evaluation pipeline | evaluation.md | evaluation.md |
| Card-phase evaluation dims | evaluation.md | evaluation.md |
| Scorecard / report card | scorecard.md | scorecard.md |
| Book ingestion & guidelines | book-guidelines.md | book-guidelines.md |
| Explanation cards & TTS | book-guidelines.md | book-guidelines.md |
| Session plan generation | book-guidelines.md | book-guidelines.md |
| Auth & onboarding | auth-and-onboarding.md | auth-and-onboarding.md |
| Dev workflow & testing | N/A (dev-facing) | dev-workflow.md |
| Deployment & infra | N/A (ops-facing) | deployment.md |
| Database schema | N/A (dev-facing) | database.md |
| Autoresearch | N/A (internal) | auto-research/overview.md |
| AI agent files | N/A (internal) | ai-agent-files.md |

No coverage gaps identified.

---

## Deferred Items

None.
