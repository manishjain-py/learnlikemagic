## PR Review: Pre-Computed Explanations (PRD + Impl Plan + Principles)

### Summary

This is a **documentation-only PR** — 3 new markdown files (PRD, implementation plan, explanation principles), 1,475 additions, 0 deletions, **zero code changes**. No regression risk to the running application.

---

### Functional Correctness: ✅ Strong

I verified the implementation plan's assumptions against the actual codebase. All references are accurate:

- **`create_new_session()` flow** — correctly identifies the `generate_welcome_message()` LLM call as the skip target, and correctly notes that `first_turn` is a plain dict (not Pydantic)
- **`SessionState` model** — `start_explanation()`, `advance_step()`, `concepts_covered_set`, `current_step` all exist as described
- **`ExplanationPhase` state machine** — correctly describes `not_started → opening → explaining → informal_check → complete`
- **`_apply_state_updates()` / `_handle_explanation_phase()`** — orchestrator methods exist and work as described
- **`TeachingGuideline` entity** — table name, `prior_topics_context` field, relationship structure all match
- **`TopicSyncService.sync_chapter()`** — signature and `SyncResponse` model match
- **Master tutor prompt** — `{prior_topics_context_section}` placeholder and `PromptTemplate.render()` pattern confirmed
- **Frontend `Turn` interface** — exists in `api.ts`, extensible with optional fields as proposed
- **Repository pattern** — `shared/repositories/` directory pattern matches (TeachingGuidelineRepository, etc.)
- **Migration pattern** — `db.py` `migrate()` function and `_LLM_CONFIG_SEEDS` list match

---

### Regression Risk: ✅ None

This PR adds 3 new documentation files in `docs/`. No code, no config, no schema changes. Zero risk of breaking anything.

---

### Design Observations (for when this gets implemented)

**1. Re-sync cascade delete is the biggest operational risk.**  
Sync deletes/recreates guideline rows → cascade wipes all explanations → if regeneration fails, topics silently downgrade from instant cards to dynamic tutoring. The plan mitigates this well with `SyncResponse.explanation_errors` and a standalone backfill endpoint, but this should be the most carefully tested path.

**2. `asyncio.run()` inside `complete_card_phase()` fallback path.**  
Section 4.9 calls `asyncio.run(self.orchestrator.generate_welcome_message(state))` for the dynamic fallback. This mirrors the existing pattern in `create_new_session()`, but worth noting that nested `asyncio.run()` calls can fail if an event loop is already running (e.g., under an async web server). The existing code has the same pattern, so this is a pre-existing concern, not new.

**3. `_advance_past_explanation_steps()` assumes explain steps are contiguous at the start.**  
The while-loop breaks on the first non-explain step. If a study plan ever interleaves explain/check steps, this would stop early. Currently study plans always front-load explain steps, so this is fine for v1.

**4. No `card_idx` tracking persisted on card navigation.**  
Card navigation (next/prev) updates `currentCardIdx` in React state only. If the user refreshes mid-card, the replay endpoint reads `card_phase.current_card_idx` from session state — but that value is only updated on variant switches and phase completion, not on each card advance. The user would restart from card 0 on refresh. Minor UX issue; could persist card index via a lightweight API call on each advance.

**5. `student_shows_prior_knowledge` gap is well-acknowledged.**  
The PRD explicitly calls out that prior knowledge detection doesn't apply during card phase. This is an acceptable v1 trade-off since the check-understanding phase catches it quickly.

**6. Study plan annotation deferred — good call.**  
Section 4.12 correctly defers the `explanation_source: "pre_computed"` annotation from the PRD. The session service handles routing without it. Less coupling, fewer changes.

---

### Quality of the Documentation

The three documents are well-structured:
- **PRD** is clear on what/why/what-not, with explicit non-goals and fallback behavior
- **Impl plan** is unusually thorough — includes side-effect audits, migration details, cascade delete recovery, session replay handling, and explicit "what this replaces vs. does not replace" sections
- **Principles doc** is concise and practical (12 guidelines, each actionable)

---

### Verdict

**Approve.** Documentation-only PR with no regression risk. The impl plan is technically sound against the current codebase. The design observations above are suggestions for the implementation phase, not blockers for merging this PR.
