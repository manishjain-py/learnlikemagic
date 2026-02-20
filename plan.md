# Plan: Centralize LLM Model Configuration

## Goal
Single admin screen → DB-persisted config → components read from DB at runtime. No env vars, no hardcoded models. One source of truth.

## Components to configure (6 logical components)

| Component Key | Description | Current Default | Current Source |
|---|---|---|---|
| `tutor` | Tutoring pipeline (safety + master tutor + welcome) | openai / gpt-5.2 | env `TUTOR_LLM_PROVIDER` → `resolved_tutor_provider` |
| `book_ingestion` | All 9 book ingestion services | openai / gpt-4o-mini | hardcoded `self.model` in 9 service files |
| `study_plan_generator` | Study plan creation | openai / gpt-5.2 | hardcoded `call_gpt_5_2()` call |
| `study_plan_reviewer` | Study plan review + improvement | openai / gpt-4o | hardcoded `call_gpt_4o()` call |
| `eval_evaluator` | Evaluation judge | openai / gpt-5.2 | `EvalConfig.evaluator_model` + `EVAL_LLM_PROVIDER` env |
| `eval_simulator` | Student simulator for evals | openai / gpt-4o | `EvalConfig.simulator_model` + `EVAL_LLM_PROVIDER` env |

## Key Design Decisions

- **No fallbacks, no defaults** — if a component's LLM config is missing from DB, it fails immediately with a clear error: `"LLM config not found for component '{key}'. Add it via /admin/llm-config."` This ensures we always know exactly what model every component is using. The `migrate()` seeding ensures this never happens in practice, but if someone adds a new component and forgets to seed it, they'll know immediately.
- **Tutor reads config at session start only** — LLMService is constructed once per WebSocket connection (in `sessions.py:360` and `session_service.py:42`). The model is fixed for the entire session. This is correct — no mid-session model changes.
- **API keys stay in env vars** — secrets don't go in DB. DB stores only component→provider→model.
- **No caching** — tutor reads once at session start; admin endpoints read on each request (fast single-row SELECT).
- **Seed defaults on migration** — `migrate()` seeds all 6 rows. This is the ONLY place defaults exist.
- **Generic `call()` on LLMService** — routes to the right API (Responses vs Chat Completions vs Anthropic vs Gemini) based on provider+model. Old methods become internal.
- **`model_id` stored on LLMService** — downstream code (agents, orchestrators) calls `self.llm.call()` without needing config service access.

---

## Step 1: DB table + entity model

**File: `llm-backend/shared/models/entities.py`** — Add `LLMConfig` model after `StudyPlan`:
```python
class LLMConfig(Base):
    __tablename__ = "llm_config"
    component_key = Column(String, primary_key=True)  # e.g. "tutor"
    provider = Column(String, nullable=False)           # "openai", "anthropic", "google"
    model_id = Column(String, nullable=False)           # "gpt-5.2", "claude-opus-4-6", etc.
    description = Column(String, nullable=True)         # Human-readable description
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String, nullable=True)
```

**File: `llm-backend/db.py`** — Add `_seed_llm_config(db_manager)` function called from `migrate()`:
- Inserts 6 default rows if `llm_config` table is empty
- Defaults match current behavior exactly (openai/gpt-5.2 for tutor, openai/gpt-4o-mini for ingestion, etc.)

---

## Step 2: Repository + Service (backend)

**File: `llm-backend/shared/repositories/llm_config_repository.py`** (new):
```python
class LLMConfigRepository:
    def __init__(self, db: Session): ...
    def get_all(self) -> list[LLMConfig]: ...
    def get_by_key(self, component_key: str) -> LLMConfig | None: ...
    def upsert(self, component_key, provider, model_id, updated_by=None) -> LLMConfig: ...
```

**File: `llm-backend/shared/repositories/__init__.py`** — Export `LLMConfigRepository`.

**File: `llm-backend/shared/services/llm_config_service.py`** (new):
```python
class LLMConfigNotFoundError(Exception):
    """Raised when LLM config is missing for a component."""
    pass

class LLMConfigService:
    def __init__(self, db: Session): ...
    def get_config(self, component_key: str) -> dict:
        """Returns {provider, model_id}. Raises LLMConfigNotFoundError if row missing — NO FALLBACKS."""
        row = self.repo.get_by_key(component_key)
        if not row:
            raise LLMConfigNotFoundError(
                f"LLM config not found for component '{component_key}'. "
                f"Add it via /admin/llm-config or run 'python db.py --migrate' to seed defaults."
            )
        return {"provider": row.provider, "model_id": row.model_id}
    def get_all_configs(self) -> list[dict]: ...
    def update_config(self, component_key, provider, model_id, updated_by=None) -> dict: ...
```

**File: `llm-backend/shared/services/__init__.py`** — Export `LLMConfigService`.

---

## Step 3: Admin API endpoints

**File: `llm-backend/shared/api/llm_config_routes.py`** (new):
- `GET /api/admin/llm-config` — returns all 6 configs with descriptions
- `PUT /api/admin/llm-config/{component_key}` — update provider + model
- `GET /api/admin/llm-config/options` — returns available models per provider:
  ```json
  {
    "openai": ["gpt-5.2", "gpt-5.1", "gpt-4o", "gpt-4o-mini"],
    "anthropic": ["claude-opus-4-6", "claude-haiku-4-5-20251001"],
    "google": ["gemini-3-pro-preview"]
  }
  ```

**File: `llm-backend/main.py`** — Add `from shared.api import llm_config_routes` and `app.include_router(llm_config_routes.router)`.

---

## Step 4: Refactor LLMService — add generic `call()` method

**File: `llm-backend/shared/services/llm_service.py`**:

1. Add required `model_id` parameter to `__init__()`:
   ```python
   def __init__(self, api_key, ..., provider: str, model_id: str):
       self.provider = provider   # REQUIRED — no default
       self.model_id = model_id   # REQUIRED — no default
   ```
   Both `provider` and `model_id` are now required with no defaults. If someone constructs an `LLMService` without them, it fails at the call site.

2. Add generic `call()` method that routes based on provider+model:
   ```python
   def call(self, prompt, reasoning_effort="none", json_mode=True,
            json_schema=None, schema_name="response") -> Dict[str, Any]:
       """Generic LLM call using self.provider and self.model_id."""
       provider = self.provider
       model = self.model_id

       if provider in ("anthropic", "anthropic-haiku"):
           return self.call_anthropic(prompt, reasoning_effort, json_mode, json_schema, schema_name)
       elif provider == "google":
           return self.call_gemini(prompt, model_name=model)
       else:  # openai
           if model in ("gpt-5.2", "gpt-5.1"):
               # Responses API path
               return self._call_responses_api(prompt, model, reasoning_effort, json_mode, json_schema, schema_name)
           else:
               # Chat Completions API path (gpt-4o, gpt-4o-mini)
               return self._call_chat_completions(prompt, model, json_mode=json_mode)
   ```

3. Extract internal methods `_call_responses_api()` and `_call_chat_completions()` from existing `call_gpt_5_2()` and `call_gpt_4o()` so the model name is parameterized.

4. Keep `call_gpt_5_2()`, `call_gpt_4o()`, `call_gpt_5_1()` as thin wrappers calling the internal methods with hardcoded model names — these still work for tests and any code not yet migrated.

**File: `llm-backend/shared/services/anthropic_adapter.py`**:
- Add optional `model` override parameter to `call_sync()` / `call_async()` / `_build_kwargs()`:
  ```python
  def call_sync(self, prompt, ..., model: str = None):
      # If model override provided, use it; else use self.model
  ```

---

## Step 5: Refactor each component to read from config

### 5a. Tutor workflow (reads config at session start — NOT per turn)

**File: `llm-backend/tutor/api/sessions.py`** (line 355-365):
```python
# BEFORE:
settings = get_settings()
llm_service = LLMService(
    api_key=settings.openai_api_key,
    gemini_api_key=..., anthropic_api_key=...,
    provider=settings.resolved_tutor_provider,  # ← env var
)

# AFTER:
settings = get_settings()
from shared.services.llm_config_service import LLMConfigService
config_service = LLMConfigService(db)
tutor_config = config_service.get_config("tutor")
llm_service = LLMService(
    api_key=settings.openai_api_key,
    gemini_api_key=..., anthropic_api_key=...,
    provider=tutor_config["provider"],   # ← DB
    model_id=tutor_config["model_id"],   # ← DB
)
```

**File: `llm-backend/tutor/services/session_service.py`** (line 41-47) — Same change.

**File: `llm-backend/tutor/agents/base_agent.py`** (line 92-96):
```python
# BEFORE:
self.llm.call_gpt_5_2(prompt=..., reasoning_effort=..., json_schema=..., schema_name=...)

# AFTER:
self.llm.call(prompt=..., reasoning_effort=..., json_schema=..., schema_name=...)
```

**File: `llm-backend/tutor/orchestration/orchestrator.py`** (lines 265, 445):
```python
# BEFORE:
self.llm.call_gpt_5_2(prompt=..., ...)

# AFTER:
self.llm.call(prompt=..., ...)
```

### 5b. Book ingestion (9 services)

**Files to change** (each has `self.model = "gpt-4o-mini"`):
1. `book_ingestion/services/minisummary_service.py:44`
2. `book_ingestion/services/boundary_detection_service.py:53`
3. `book_ingestion/services/ocr_service.py:32`
4. `book_ingestion/services/topic_deduplication_service.py:40`
5. `book_ingestion/services/facts_extraction_service.py:43`
6. `book_ingestion/services/teaching_description_generator.py:50`
7. `book_ingestion/services/description_generator.py:55`
8. `book_ingestion/services/topic_name_refinement_service.py:30`
9. `book_ingestion/services/guideline_merge_service.py:36`

Change each to accept `model` as a **required** constructor parameter (no default):
```python
# BEFORE:
def __init__(self, openai_client=None):
    self.client = openai_client or OpenAI()
    self.model = "gpt-4o-mini"

# AFTER:
def __init__(self, openai_client=None, *, model: str):
    self.client = openai_client or OpenAI()
    self.model = model  # NO DEFAULT — must be explicitly passed
```

**File: `book_ingestion/services/guideline_extraction_orchestrator.py`** (line 81-110):
```python
# BEFORE:
def __init__(self, s3_client, openai_client=None, db_session=None):
    self.minisummary = MinisummaryService(self.openai_client)
    self.boundary_detector = BoundaryDetectionService(self.openai_client)
    ...

# AFTER:
def __init__(self, s3_client, openai_client=None, db_session=None, *, model: str):
    self.minisummary = MinisummaryService(self.openai_client, model=model)
    self.boundary_detector = BoundaryDetectionService(self.openai_client, model=model)
    ...  # NO DEFAULT — caller must provide model from DB config
```

**File: `book_ingestion/api/routes.py`** (lines 438-442, 538-541):
```python
# BEFORE:
orchestrator = GuidelineExtractionOrchestrator(s3_client=s3_client, openai_client=openai_client, db_session=db)

# AFTER:
from shared.services.llm_config_service import LLMConfigService
config = LLMConfigService(db).get_config("book_ingestion")
orchestrator = GuidelineExtractionOrchestrator(
    s3_client=s3_client, openai_client=openai_client, db_session=db,
    model=config["model_id"]
)
```

**File: `study_plans/api/admin.py`** (lines 400, 468) — Same pattern for the 2 orchestrator creations in that file.

### 5c. Study plans

**File: `study_plans/services/generator_service.py`** (line 102):
```python
# BEFORE:
response = self.llm_service.call_gpt_5_2(prompt=prompt, reasoning_effort="high", json_schema=..., schema_name=...)

# AFTER:
response = self.llm_service.call(prompt=prompt, reasoning_effort="high", json_schema=..., schema_name=...)
```
The `LLMService` passed to the generator must have `provider` and `model_id` from the `study_plan_generator` DB config.

**File: `study_plans/services/reviewer_service.py`** (line 61):
```python
# BEFORE:
response_text = self.llm_service.call_gpt_4o(prompt=prompt, max_tokens=2048, json_mode=True)

# AFTER:
response_text = self.llm_service.call(prompt=prompt, json_mode=True)
```
The `LLMService` passed to the reviewer must have `provider` and `model_id` from the `study_plan_reviewer` DB config.

**File: `study_plans/services/orchestrator.py`** (line 129):
```python
# BEFORE:
response_text = self.llm_service.call_gpt_4o(prompt=prompt, max_tokens=4096, json_mode=True)

# AFTER:
response_text = self.llm_service.call(prompt=prompt, json_mode=True)
```
Uses the reviewer's LLMService since this is the improve step.

**File: `study_plans/api/admin.py`** (line 113-115):
```python
# BEFORE:
def get_llm_service():
    settings = get_settings()
    return LLMService(api_key=settings.openai_api_key, gemini_api_key=settings.gemini_api_key)

# AFTER:
def get_llm_service(db: Session, component_key: str):
    settings = get_settings()
    config = LLMConfigService(db).get_config(component_key)
    return LLMService(
        api_key=settings.openai_api_key,
        gemini_api_key=settings.gemini_api_key,
        anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        provider=config["provider"],
        model_id=config["model_id"],
    )
```
Generator and reviewer get separate LLMService instances with their own config.

### 5d. Evaluation pipeline

**File: `evaluation/config.py`** — Add `classmethod from_db()`:
```python
@classmethod
def from_db(cls, db_session) -> "EvalConfig":
    """Create EvalConfig with model settings from DB."""
    from shared.services.llm_config_service import LLMConfigService
    config_svc = LLMConfigService(db_session)

    evaluator = config_svc.get_config("eval_evaluator")
    simulator = config_svc.get_config("eval_simulator")

    config = cls()
    config.eval_llm_provider = evaluator["provider"]
    config.evaluator_model = evaluator["model_id"]
    config.anthropic_evaluator_model = evaluator["model_id"]  # unified
    config.simulator_model = simulator["model_id"]
    config.anthropic_simulator_model = simulator["model_id"]  # unified
    return config
```

**File: `evaluation/api.py`** — Use `EvalConfig.from_db(db)` instead of `EvalConfig()`.

**File: `evaluation/run_evaluation.py`** — Use `EvalConfig.from_db(db_session)` at CLI entry point.

---

## Step 6: Remove deprecated config (NOT just mark — actually remove)

### 6a. Remove from `config.py`

**File: `llm-backend/config.py`** — DELETE these fields entirely:
- `llm_model` (line 56-58) — never used by any live code
- `app_llm_provider` (line 60-63) — replaced by DB config
- `tutor_llm_provider` (line 64-67) — replaced by DB config
- `ingestion_llm_provider` (line 68-71) — replaced by DB config
- `resolved_tutor_provider` property (line 112-115) — replaced by DB config

**KEEP** in `config.py`: `openai_api_key`, `gemini_api_key`, `anthropic_api_key` (secrets stay in env vars).

### 6b. Remove from evaluation config

**File: `evaluation/config.py`** — Remove these fields:
- `eval_llm_provider` (line 55-57) — now comes from DB via `from_db()`
- `tutor_llm_provider` (line 65-67) — now comes from DB via `from_db()`
- `anthropic_evaluator_model` (line 60) — unified with `evaluator_model`
- `anthropic_simulator_model` (line 61) — unified with `simulator_model`

### 6c. Update health endpoint

**File: `llm-backend/shared/api/health.py`** (line 20-42):
- `GET /config/models` currently reads from env vars
- Change to read from `LLMConfigService` (via DB)
- This endpoint shows current config in the health check

### 6d. Update all references

These files reference the removed fields and must be updated:

| File | What to change |
|---|---|
| `tutor/api/sessions.py:364` | `settings.resolved_tutor_provider` → DB config (done in step 5a) |
| `tutor/services/session_service.py:46` | `settings.resolved_tutor_provider` → DB config (done in step 5a) |
| `shared/api/health.py:32,39` | `settings.resolved_tutor_provider` / `settings.ingestion_llm_provider` → DB config |
| `evaluation/config.py:66` | `os.environ.get("TUTOR_LLM_PROVIDER")` → DB config |
| `evaluation/config.py:56` | `os.environ.get("EVAL_LLM_PROVIDER")` → DB config |

### 6e. Update tests

| Test file | What to change |
|---|---|
| `tests/unit/test_health_api.py:63,80,94` | `mock_settings.resolved_tutor_provider` / `ingestion_llm_provider` → mock config service |
| `tests/unit/test_shared_api.py:58,73,85,96` | Same pattern |
| `tests/unit/test_session_service.py` (9 occurrences) | `resolved_tutor_provider="openai"` → mock config service |
| `tests/unit/test_evaluation.py:116,119` | `tutor_llm_provider` → DB config |
| `tests/unit/test_base_agent.py:59,134,213,234` | `call_gpt_5_2` → `call` |
| `tests/unit/test_orchestrator.py:213,228,631,636,642,652` | `call_gpt_5_2` → `call` |
| `tests/unit/test_study_plans.py:72,89,96,179,190,203,218` | `call_gpt_5_2` / `call_gpt_4o` → `call` |
| `tests/unit/test_llm_service.py` | Keep existing tests for backward-compat methods, add new tests for `call()` |

---

## Step 7: Frontend admin page

**File: `llm-frontend/src/features/admin/types/index.ts`** — Add types:
```typescript
export interface LLMConfig {
  component_key: string;
  provider: string;
  model_id: string;
  description: string;
  updated_at: string;
  updated_by: string | null;
}

export interface LLMConfigOptions {
  [provider: string]: string[];  // provider → model list
}
```

**File: `llm-frontend/src/features/admin/api/adminApi.ts`** — Add:
```typescript
export async function getLLMConfigs(): Promise<LLMConfig[]> { ... }
export async function updateLLMConfig(componentKey: string, provider: string, modelId: string): Promise<LLMConfig> { ... }
export async function getLLMConfigOptions(): Promise<LLMConfigOptions> { ... }
```

**File: `llm-frontend/src/features/admin/pages/LLMConfigPage.tsx`** (new):
- Table: component | description | provider dropdown | model dropdown | updated | save button
- Provider dropdown changes → model dropdown options update accordingly
- Success/error feedback on save
- Style matches existing admin pages (inline styles, same color palette)

**File: `llm-frontend/src/App.tsx`** (line 100):
- Add `import LLMConfigPage from './features/admin/pages/LLMConfigPage'`
- Add route: `<Route path="/admin/llm-config" element={<LLMConfigPage />} />`

**File: `llm-frontend/src/features/admin/pages/BooksDashboard.tsx`** (around line 87-108):
- Add "LLM Config" nav button alongside existing "Guidelines Review", "Evaluation", "Docs" buttons

---

## Execution Order

1. **Step 1** — DB table + entity + seed defaults
2. **Step 2** — Repository + service
3. **Step 3** — Admin API endpoints (testable via curl)
4. **Step 7** — Frontend admin page (can work immediately with step 3)
5. **Step 4** — Refactor LLMService with generic `call()` + `model_id` parameter
6. **Step 5a** — Tutor: read config at session start from DB
7. **Step 5b** — Book ingestion: pass model from DB config
8. **Step 5c** — Study plans: use DB config for generator + reviewer
9. **Step 5d** — Evaluation: use `EvalConfig.from_db()`
10. **Step 6** — Remove deprecated env var config + update tests
11. **Run tests** — ensure all existing tests pass

## Safety: What prevents breakage

- **Seed on migrate**: `migrate()` seeds all 6 DB rows with current defaults → no behavior change on deploy. This is the ONLY place defaults live.
- **Fail-fast on missing config**: `LLMConfigService.get_config()` raises `LLMConfigNotFoundError` with a clear message if DB row is missing. No silent fallbacks. You'll know immediately if something is misconfigured.
- **Required parameters everywhere**: `LLMService(provider=..., model_id=...)`, book ingestion services `__init__(model=...)`, orchestrators — all require explicit values. No hidden defaults that mask misconfiguration.
- **Old methods kept**: `call_gpt_5_2()`, `call_gpt_4o()` still work as internal methods (used by `call()` internally).
- **Tests updated in same step**: every functional change updates its tests in lock-step.
