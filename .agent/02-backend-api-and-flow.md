# Backend API And Flow

Last audited: 2026-03-06
Code baseline: `claude/update-agent-docs-j6oFs@5dbd8b5`

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
- `GET /sessions/topic-progress`
- `GET /sessions/resumable?guideline_id=...`
- `GET /sessions/guideline/{guideline_id}`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/summary`
- `GET /sessions/{session_id}/replay`
- `GET /sessions/{session_id}/exam-review`
- `GET /sessions/{session_id}/agent-logs`
- `POST /sessions`
- `POST /sessions/{session_id}/step`
- `POST /sessions/{session_id}/pause`
- `POST /sessions/{session_id}/resume`
- `POST /sessions/{session_id}/end-clarify`
- `POST /sessions/{session_id}/end-exam`
- `POST /sessions/{session_id}/feedback`

### Session WebSocket
- `WS /sessions/ws/{session_id}`

### Audio transcription
- `POST /transcribe`

### Text-to-speech
- `POST /text-to-speech`

### Auth/profile
- `POST /auth/sync`
- `POST /auth/phone/provision`
- `DELETE /auth/admin/user`
- `GET /profile`
- `PUT /profile`
- `PUT /profile/password`
- `GET /profile/enrichment`
- `PUT /profile/enrichment`
- `GET /profile/personality`
- `POST /profile/personality/regenerate`

### Book ingestion V2 — books (`/admin/v2/books`)
- `POST /admin/v2/books`
- `GET /admin/v2/books`
- `GET /admin/v2/books/{book_id}`
- `DELETE /admin/v2/books/{book_id}`

### Book ingestion V2 — TOC (`/admin/v2/books/{book_id}/toc`)
- `POST /admin/v2/books/{book_id}/toc/extract`
- `POST /admin/v2/books/{book_id}/toc`
- `GET /admin/v2/books/{book_id}/toc`
- `PUT /admin/v2/books/{book_id}/toc/{chapter_id}`
- `DELETE /admin/v2/books/{book_id}/toc/{chapter_id}`

### Book ingestion V2 — pages (`/admin/v2/books/{book_id}/chapters/{chapter_id}/pages`)
- `POST /admin/v2/books/{book_id}/chapters/{chapter_id}/pages`
- `GET /admin/v2/books/{book_id}/chapters/{chapter_id}/pages`
- `GET /admin/v2/books/{book_id}/chapters/{chapter_id}/pages/{page_num}`
- `GET /admin/v2/books/{book_id}/chapters/{chapter_id}/pages/{page_num}/detail`
- `DELETE /admin/v2/books/{book_id}/chapters/{chapter_id}/pages/{page_num}`
- `POST /admin/v2/books/{book_id}/chapters/{chapter_id}/pages/{page_num}/retry-ocr`

### Book ingestion V2 — processing + topics (`/admin/v2/books/{book_id}/chapters/{chapter_id}`)
- `POST /admin/v2/books/{book_id}/chapters/{chapter_id}/process`
- `POST /admin/v2/books/{book_id}/chapters/{chapter_id}/reprocess`
- `POST /admin/v2/books/{book_id}/chapters/{chapter_id}/refinalize`
- `GET /admin/v2/books/{book_id}/chapters/{chapter_id}/jobs/latest`
- `GET /admin/v2/books/{book_id}/chapters/{chapter_id}/jobs/{job_id}`
- `GET /admin/v2/books/{book_id}/chapters/{chapter_id}/topics`
- `GET /admin/v2/books/{book_id}/chapters/{chapter_id}/topics/{topic_key}`

### Book ingestion V2 — sync + results (`/admin/v2/books/{book_id}`)
- `POST /admin/v2/books/{book_id}/sync`
- `POST /admin/v2/books/{book_id}/chapters/{chapter_id}/sync`
- `GET /admin/v2/books/{book_id}/results`

### Evaluation
- `GET /api/evaluation/guidelines`
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
