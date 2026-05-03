# Docs Update Changelog — 2026-05-03

Run via `/update-all-docs`. 7 parallel sub-agents.

## Updated Docs

| Doc | Key Changes |
|-----|-------------|
| `docs/functional/app-overview.md` | Topic DAG: 8→10 stages (added baatcheet_audio_review, baatcheet_audio_synthesis). |
| `docs/technical/architecture-overview.md` | Added TTS Provider System section. Added `tts config` router, `/admin/tts-config` route, `TTSConfigPage`. Updated `book_ingestion_v2/stages/` to list all 10 stages. Frontend hooks expanded (audioController, useCheckInAudio, usePersonalizedAudio). Annotated `shared/types/emotion.py`. |
| `docs/functional/learning-session.md` | Removed defunct Mid-Session Feedback section (`session_feedback` table dropped on startup). Added "Adjusting the Experience" section (per-card simplify, explain differently, Clarify questions). |
| `docs/technical/learning-session.md` | Clarified TutorTurnOutput intent values (legacy teach_me + clarify variants). Added `mastery_signal` enum. Clarified `/card-progress` finalization (3 distinct methods). Fixed architecture diagram (moved `/card-action`, `/simplify-card` to Explain column). |
| `docs/functional/evaluation.md` | No changes (already current). |
| `docs/technical/evaluation.md` | Corrected `anthropic-haiku` provider description (works via DB config; only CLI default-constructed `EvalConfig` misroutes). |
| `docs/functional/scorecard.md` | Clarified empty state triggered by zero sessions (practice-only also hidden). Refined practice-only topic note. |
| `docs/technical/scorecard.md` | Fixed `TopicSelect.tsx` badge logic (`coverage === 0` = not_started, `>= 80` = completed). Corrected `ModeSelection.tsx` (receives `practiceAvailable` as prop). Added practice-only inconsistency caveat. |
| `docs/functional/book-guidelines.md` | Pipeline 8→10 stages. Removed "opt-in safety valve" framing for Baatcheet audio review (now default cascade). Updated TTS provider story (ElevenLabs v3 default; emotion tags; new voices: Orus + Leda). Documented practice plans. |
| `docs/technical/book-guidelines.md` | Stage breakdown for new `baatcheet_audio_review` and `baatcheet_audio_synthesis`. TTS config service. Voice IDs and retry knobs. Check-in activity types: 6→11. V2JobType: 13→14. New launchers and `_run_baatcheet_audio_generation` background task. `practice_plan_generator` template. Frontend admin pages: LLMConfigPage, TTSConfigPage. |
| `docs/functional/auth-and-onboarding.md` | Onboarding step 2: preferred-name pre-fill happens "if blank". Step 6 title corrected ("Tell us about yourself!"). |
| `docs/technical/auth-and-onboarding.md` | About step PUT skipped silently when text empty. |
| `docs/technical/dev-workflow.md` | Added `ELEVENLABS_API_KEY` and `TTS_PROVIDER` to optional `.env` vars. |
| `docs/technical/deployment.md` | App Runner health check path: `/health`→`/`. Added ElevenLabs (conditional secret + IAM). Secret count: 3-4→3-5. Clarified Gemini is plaintext env var (not secret-ARN). Updated `terraform.tfvars.example` description. Added missing TF variables. |
| `docs/technical/database.md` | No changes (29 helpers, all entities, seeds verified). |

## Newly Created Docs

None. All gaps fit cleanly inside existing docs.

## Coverage Matrix

| Module / Feature | Functional Doc | Technical Doc |
|------------------|----------------|---------------|
| App overview, routes, tech stack | `app-overview.md` | `architecture-overview.md` |
| Tutor (Teach Me, Clarify, Baatcheet) | `learning-session.md` | `learning-session.md` |
| Evaluation (personas, judge, dashboard) | `evaluation.md` | `evaluation.md` |
| Scorecard / progress | `scorecard.md` | `scorecard.md` |
| Let's Practice | `practice-mode.md` | `practice-mode.md` |
| Book ingestion + study plans | `book-guidelines.md` | `book-guidelines.md` |
| Auth, signup, onboarding, profile | `auth-and-onboarding.md` | `auth-and-onboarding.md` |
| Local dev / testing | N/A (dev-only) | `dev-workflow.md` |
| Deployment / infra | N/A (ops-only) | `deployment.md` |
| Database schema | N/A (internal) | `database.md` |
| LLM provider config | covered in app-overview | `architecture-overview.md` (LLM Provider System) |
| TTS provider config | covered in app-overview / book-guidelines | `architecture-overview.md` (TTS Provider System), `book-guidelines.md` |
| Feature flags admin | covered in app-overview | `architecture-overview.md` |
| Issue reporting + admin | covered in app-overview | `architecture-overview.md` |
| Auto-research | N/A (admin-only) | `auto-research/overview.md` |
| LLM prompts catalog | N/A | `llm-prompts.md` |
| Agent context files | N/A | `ai-agent-files.md` |

## Deferred / Out of Scope

- No deferred items. Coverage matrix complete; all major modules mapped.

## Master Index

`docs/DOCUMENTATION_GUIDELINES.md` already lists all current docs. No changes needed (no new files, no renames).
