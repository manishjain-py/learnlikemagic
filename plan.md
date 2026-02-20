# Plan: Centralize LLM Model Configuration

## Goal
Single admin screen → DB-persisted config → components read from DB at runtime. No env vars, no hardcoded models. One source of truth.

## Components to configure (6 logical components)

| Component Key | Description | Current Model | Current Source |
|---|---|---|---|
| `tutor` | Main tutoring pipeline (safety + master tutor + welcome) | gpt-5.2 / claude-opus-4-6 | env var `tutor_llm_provider` → method name |
| `book_ingestion` | All 9+1 book ingestion services | gpt-4o-mini | hardcoded `self.model` in each service |
| `study_plan_generator` | Study plan creation | gpt-5.2 | `call_gpt_5_2()` method name |
| `study_plan_reviewer` | Study plan review + improvement | gpt-4o | `call_gpt_4o()` method name |
| `eval_evaluator` | Evaluation judge | gpt-5.2 / claude-opus-4-6 | `evaluation/config.py` fields |
| `eval_simulator` | Student simulator for evals | gpt-4o / claude-opus-4-6 | `evaluation/config.py` fields |

---

## Step 1: DB table + entity model

**File: `llm-backend/shared/models/entities.py`** — Add `LLMConfig` model:
```python
class LLMConfig(Base):
    __tablename__ = "llm_config"
    component_key = Column(String, primary_key=True)  # e.g. "tutor"
    provider = Column(String, nullable=False)           # "openai", "anthropic", "google"
    model_id = Column(String, nullable=False)           # "gpt-5.2", "claude-opus-4-6", etc.
    description = Column(String, nullable=True)         # Human-readable description
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String, nullable=True)          # Who last changed it
```

**File: `llm-backend/db.py`** — Add seed logic in `migrate()` to insert default rows (matching current behavior) if table is empty. This ensures first-time setup works without manual config.

## Step 2: Repository + Service (backend)

**File: `llm-backend/shared/repositories/llm_config_repository.py`** (new):
- `get_all() -> list[LLMConfig]`
- `get_by_key(component_key) -> LLMConfig | None`
- `upsert(component_key, provider, model_id, updated_by) -> LLMConfig`

**File: `llm-backend/shared/services/llm_config_service.py`** (new):
- Wraps the repository
- `get_config(component_key) -> dict` — returns `{provider, model_id}`, falls back to hardcoded default if row missing (safety net only)
- `get_all_configs() -> list[dict]`
- `update_config(component_key, provider, model_id, updated_by) -> dict`
- No in-memory caching needed: FastAPI creates services per-request, so each request hits DB (one fast SELECT). WebSocket connections read config at connection start, which is the right behavior (don't change model mid-session).

## Step 3: Admin API endpoints

**File: `llm-backend/shared/api/llm_config.py`** (new):
- `GET /api/admin/llm-config` — returns all 6 configs
- `PUT /api/admin/llm-config/{component_key}` — update provider + model for a component
- Also returns available models per provider for the UI dropdown:
  ```
  GET /api/admin/llm-config/options → {
    "openai": ["gpt-5.2", "gpt-5.1", "gpt-4o", "gpt-4o-mini"],
    "anthropic": ["claude-opus-4-6", "claude-haiku-4-5-20251001"],
    "google": ["gemini-3-pro-preview"]
  }
  ```

**File: `llm-backend/main.py`** — Register the new router.

## Step 4: Refactor LLMService — add generic `call()` method

**File: `llm-backend/shared/services/llm_service.py`**:

Add a new `call()` method that takes `provider` and `model` as parameters and routes accordingly:
```python
def call(self, provider: str, model: str, prompt: str,
         reasoning_effort="none", json_mode=True,
         json_schema=None, schema_name="response") -> Dict[str, Any]:
    if provider in ("anthropic", "anthropic-haiku"):
        # Use anthropic adapter with the specified model
        ...
    elif provider == "google":
        return self.call_gemini(prompt, model_name=model, ...)
    else:
        # OpenAI - route to Responses API or Chat Completions based on model
        if model in ("gpt-5.2", "gpt-5.1"):
            # Use Responses API
            ...
        else:
            # Use Chat Completions API (gpt-4o, gpt-4o-mini)
            ...
```

The existing `call_gpt_5_2()`, `call_gpt_4o()`, etc. remain as-is for backward compatibility during the transition — they'll be called only by the new `call()` method internally. No external callers should use them once refactoring is done.

**File: `llm-backend/shared/services/anthropic_adapter.py`**:
- Allow `call_sync()` / `call_async()` to accept an optional `model` override parameter so we can pass the model from config without reconstructing the adapter.

## Step 5: Refactor each component to read from config

### 5a. Tutor workflow
**Files: `session_service.py`, `sessions.py` (websocket)**

Currently:
```python
settings = get_settings()
self.llm_service = LLMService(
    api_key=settings.openai_api_key, ...,
    provider=settings.resolved_tutor_provider,
)
```

After:
```python
from shared.services.llm_config_service import LLMConfigService
config_service = LLMConfigService(db)
tutor_config = config_service.get_config("tutor")
# Pass provider from DB config, not from env var
self.llm_service = LLMService(
    api_key=settings.openai_api_key, ...,
    provider=tutor_config["provider"],
)
```

**Files: `base_agent.py`, `orchestrator.py`**

These call `self.llm.call_gpt_5_2(...)`. Change to:
```python
self.llm.call(
    provider=self.llm.provider,
    model=self.llm.model,  # set during LLMService construction from DB config
    prompt=prompt, ...
)
```

The simplest approach: store the model_id on LLMService itself during construction, so components don't need to know about config service. LLMService already has `self.provider`; we add `self.model_id` and use it in the generic `call()`.

### 5b. Book ingestion (9 services)
**Files: All services in `book_ingestion/services/`**

Currently each has `self.model = "gpt-4o-mini"`.

After: Accept `model` as constructor parameter with no default, and the orchestrator passes it from config.

**File: `book_ingestion/services/guideline_extraction_orchestrator.py`**:
```python
def __init__(self, s3_client, openai_client, db_session, llm_config_service=None):
    config = llm_config_service.get_config("book_ingestion") if llm_config_service else {"model_id": "gpt-4o-mini"}
    model = config["model_id"]
    self.minisummary = MinisummaryService(openai_client, model=model)
    self.boundary_detector = BoundaryDetectionService(openai_client, model=model)
    # ... etc for all services
```

**File: `book_ingestion/api/routes.py`** — pass `LLMConfigService` to the orchestrator.

### 5c. Study plans
**Files: `study_plans/services/generator_service.py`, `reviewer_service.py`, `orchestrator.py`**

Generator currently calls `self.llm_service.call_gpt_5_2(...)`. Change to `self.llm_service.call(provider, model, ...)` where provider/model come from config.

Approach: `StudyPlanOrchestrator` receives config service, looks up `study_plan_generator` and `study_plan_reviewer` configs, passes them to the respective services.

**File: `study_plans/api/admin.py`** — pass config service into the orchestrator.

### 5d. Evaluation pipeline
**File: `evaluation/config.py`**

`EvalConfig` currently has `evaluator_model`, `simulator_model`, etc. as hardcoded defaults.

Change: Add a classmethod `from_db(db_session)` that reads `eval_evaluator` and `eval_simulator` configs from DB and populates the fields. The CLI entry point (`run_evaluation.py`) uses this.

## Step 6: Clean up old config

**File: `config.py`**:
- Mark `tutor_llm_provider`, `ingestion_llm_provider`, `app_llm_provider`, `llm_model` as deprecated
- Keep env vars for API keys only (those stay in env, not DB — secrets shouldn't be in DB)
- Remove `resolved_tutor_provider` property

## Step 7: Frontend admin page

**File: `llm-frontend/src/features/admin/pages/LLMConfigPage.tsx`** (new):
- Table showing all 6 components with their current provider + model
- Each row has a provider dropdown and model dropdown (model options change based on provider)
- Save button per row (or save all)
- Show `updated_at` and `updated_by` for audit trail
- Toast/notification on successful save

**File: `llm-frontend/src/features/admin/api/adminApi.ts`** — add API functions:
- `getLLMConfigs()`
- `updateLLMConfig(componentKey, provider, modelId)`
- `getLLMConfigOptions()`

**File: `llm-frontend/src/features/admin/types/index.ts`** — add types

**File: `llm-frontend/src/App.tsx`** — add route: `/admin/llm-config`

**File: `llm-frontend/src/features/admin/pages/BooksDashboard.tsx`** (or shared nav) — add nav link to LLM Config page

---

## Execution Order
1. **Step 1** — DB table + entity (foundation)
2. **Step 2** — Repository + service (backend plumbing)
3. **Step 3** — Admin API endpoints (can test via curl)
4. **Step 4** — Refactor LLMService with generic `call()` method
5. **Step 5a** — Refactor tutor to use DB config
6. **Step 5b** — Refactor book ingestion to use DB config
7. **Step 5c** — Refactor study plans to use DB config
8. **Step 5d** — Refactor evaluation to use DB config
9. **Step 6** — Clean up old env var config
10. **Step 7** — Frontend admin page
11. **Run tests** — ensure existing tests pass, fix any broken ones

## Key Design Decisions

- **API keys stay in env vars** — they're secrets, not config. DB stores only component→provider→model mapping.
- **No caching** — per-request DB read is fast enough (single row SELECT). Avoids cache invalidation complexity.
- **Seed defaults on migration** — so the system works out-of-box without admin intervention.
- **Generic `call()` method** — routes to the right API (Responses vs Chat Completions vs Anthropic) based on provider+model. Existing methods become internal.
- **Model on LLMService** — store `model_id` on the service instance so downstream code (agents, orchestrators) doesn't need config service access.
