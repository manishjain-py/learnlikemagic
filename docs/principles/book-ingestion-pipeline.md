# Principles: Book Ingestion Pipeline

Operational principles for the multi-stage pipeline that turns raw textbook pages into teachable topics.

## Goal: Great Quality Content

Best model, max effort. Best model = quality over cost — always prefer the most capable model, never downgrade for savings. Max effort = trade ingestion speed for output quality, always. These are offline pipelines, can take as long as needed.

## Cost Discipline

Use Claude Code (subprocess) for LLM work — direct API calls are way too expensive at this volume. All LLM calls route through `LLMService`, which dispatches to Claude Code when the admin-configured provider is `claude_code`. Keep the provider set accordingly in prod.

**June 15, 2026 change:** Anthropic splits billing into interactive (subscription) and programmatic (`claude -p` — capped Agent SDK credit at API list prices: $200/mo on Max 20x). Our adapter uses `claude -p`, so ingestion hits the capped pool. If the cap bites, we can do the same thing for a pipeline stage using claude skills.

## 1. Review-Refine with Targeted Critique

Iterative review-refine is the primary quality lever — quality comes from multiple passes, not a single perfect generation. But review rounds must target specific critique facets per component (factual accuracy, prerequisite assumptions, logical flow, format compliance, etc.), not open-ended "improve this."

## 2. Admin Observability and Control

Every stage must be independently observable, triggerable, and retryable by an admin.

## 3. Job Lifecycle and Recovery

Jobs have well-defined lifecycle states. The system auto-detects and recovers from stalled jobs. Concurrent jobs for the same scope are prevented.

## 4. Stage Gating

No stage may start until its prerequisite stages are verifiably complete.

## 5. Stage Re-run Replaces Output

Re-running a stage replaces its output entirely. No versioning of previous results across runs.

---

*Reviewed by Manish on date: 2026-05-27*
