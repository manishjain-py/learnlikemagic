# Backend API And Flow

Last audited: 2026-02-27
Code baseline: `claude/update-ai-agent-files-ulEgH@212063c`

## Boot Sequence
1. `main.py` validates required settings (`OPENAI_API_KEY`, `DATABASE_URL`)
2. Logging initialized (json or text)
3. FastAPI app + CORS middleware created
4. Routers mounted
5. Startup DB health check executed

## Router Inventory (Current)

### Health + model config snapshot
- `GET /`
- `GET /health`
- `GET /health/db`
- `GET /config/models`

### Curriculum
- `GET /curriculum`

### Session REST
- `GET /sessions`
- `GET /sessions/history`
- `GET /sessions/stats`
- `GET /sessions/report-card`
- `GET /sessions/subtopic-progress`
- `GET /sessions/resumable?guideline_id=...`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/summary`
- `GET /sessions/{session_id}/replay`
- `GET /sessions/{session_id}/agent-logs`
- `POST /sessions`
- `POST /sessions/{session_id}/step`
- `POST /sessions/{session_id}/pause`
- `POST /sessions/{session_id}/resume`
- `POST /sessions/{session_id}/end-clarify`
- `POST /sessions/{session_id}/end-exam`

### Session WebSocket
- `WS /sessions/ws/{session_id}`

### Audio transcription
- `POST /transcribe`

### Auth/profile
- `POST /auth/sync`
- `POST /auth/phone/provision`
- `DELETE /auth/admin/user`
- `GET /profile`
- `PUT /profile`
- `PUT /profile/password`

### Book ingestion admin (`/admin`)
- `POST /admin/books`
- `GET /admin/books`
- `GET /admin/books/{book_id}`
- `DELETE /admin/books/{book_id}`
- `POST /admin/books/{book_id}/pages`
- `PUT /admin/books/{book_id}/pages/{page_num}/approve`
- `DELETE /admin/books/{book_id}/pages/{page_num}`
- `GET /admin/books/{book_id}/pages/{page_num}`
- `POST /admin/books/{book_id}/generate-guidelines`
- `POST /admin/books/{book_id}/finalize`
- `GET /admin/books/{book_id}/guidelines`
- `GET /admin/books/{book_id}/guidelines/{topic_key}/{subtopic_key}`
- `PUT /admin/books/{book_id}/guidelines/approve`
- `DELETE /admin/books/{book_id}/guidelines`
- `GET /admin/books/{book_id}/jobs/latest`
- `GET /admin/books/{book_id}/jobs/{job_id}`
- `POST /admin/books/{book_id}/pages/bulk`
- `POST /admin/books/{book_id}/pages/{page_num}/retry-ocr`

### Guideline review + study plans (`/admin/guidelines`)
- `GET /admin/guidelines/books`
- `GET /admin/guidelines/books/{book_id}/topics`
- `GET /admin/guidelines/books/{book_id}/subtopics/{subtopic_key}`
- `PUT /admin/guidelines/books/{book_id}/subtopics/{subtopic_key}`
- `GET /admin/guidelines/books/{book_id}/page-assignments`
- `POST /admin/guidelines/books/{book_id}/extract`
- `POST /admin/guidelines/books/{book_id}/finalize`
- `POST /admin/guidelines/books/{book_id}/sync-to-database`
- `GET /admin/guidelines/review`
- `GET /admin/guidelines/review/filters`
- `GET /admin/guidelines/books/{book_id}/review`
- `POST /admin/guidelines/{guideline_id}/approve`
- `DELETE /admin/guidelines/{guideline_id}`
- `POST /admin/guidelines/{guideline_id}/generate-study-plan`
- `GET /admin/guidelines/{guideline_id}/study-plan`
- `POST /admin/guidelines/bulk-generate-study-plans`

### Evaluation
- `POST /api/evaluation/start`
- `POST /api/evaluation/evaluate-session`
- `GET /api/evaluation/status`
- `GET /api/evaluation/runs`
- `GET /api/evaluation/runs/{run_id}`
- `POST /api/evaluation/runs/{run_id}/retry-evaluation`

### Docs + scenario browser
- `GET /api/docs`
- `GET /api/docs/{category}/{filename}`
- `GET /api/test-scenarios`
- `GET /api/test-scenarios/{slug}`
- `GET /api/test-scenarios/{slug}/screenshots/{scenario_id}`

### LLM config admin
- `GET /api/admin/llm-config`
- `PUT /api/admin/llm-config/{component_key}`
- `GET /api/admin/llm-config/options`

## Tutoring Runtime Flow
1. Session creation (`SessionService.create_new_session`) resolves guideline + optional study plan + user context
2. Orchestrator turn cycle:
   - safety gate
   - mode routing (teach_me / clarify_doubts / exam)
   - master tutor call
   - state transition application
3. State persisted with optimistic locking (`state_version`)
4. Event log records turn metadata
5. WS flow uses separate version-checked write helper

## LLM Provider Architecture
- Source of truth: `llm_config` table
- Access layer: `LLMConfigService`
- Runtime dispatch: `shared/services/llm_service.py`
- Provider/model can differ per component (tutor, ingestion, evaluator, simulator, study plan roles)

## Session Persistence Model
- Canonical serialized state: `sessions.state_json`
- Query/summary helpers: `mode`, `is_paused`, `exam_score`, `exam_total`, `guideline_id`, `state_version`
- Scorecard/report-card computed from persisted session state

## Auth/Security Notes
- Access token required for user-owned resources
- Optional auth used on some legacy-compatible endpoints (`get_optional_user`)
- WS ownership enforced for user-bound sessions; token passed via query parameter
- Cognito JWKS is cached and refreshed on key miss
