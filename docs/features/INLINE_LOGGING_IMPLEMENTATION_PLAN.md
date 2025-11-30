# Comprehensive Inline Logging Implementation Plan

## Executive Summary

This plan consolidates all logging in the application to use **inline structured JSON logging** via Python's standard `logging` module. This replaces the custom `AgentLoggingService` and ensures consistent observability across both pipelines:

1. **Book Ingestion Pipeline** (book upload → guidelines generation → DB sync)
2. **Tutor Workflow** (planner → executor → evaluator agents)

---

## Current Architecture Analysis

### What Exists Today

| Component | Current Logging | Issues |
|-----------|-----------------|--------|
| `main.py` | `logging.basicConfig()` with text format | Not JSON structured |
| Book Ingestion Services | Inconsistent `logger.info()` calls | Missing input/output/timing |
| `AgentLoggingService` | Custom file-based (JSONL + TXT) | Separate system, not stdout |
| Tutor Agents (`BaseAgent`) | Uses `AgentLoggingService` | File-based, not inline |
| `/sessions/{id}/logs` API | Reads from files | Depends on `AgentLoggingService` |
| LLM calls | Minimal logging | No timing/cost tracking |

### Files Using `AgentLoggingService` (to be refactored)

| File | Usage | Impact |
|------|-------|--------|
| `services/agent_logging_service.py` | Service definition | **DELETE** |
| `services/__init__.py` | Exports `AgentLoggingService` | Remove export |
| `agents/base.py:47` | Injected into all agents | Remove dependency |
| `workflows/tutor_workflow.py:49,162,271` | Builds workflow with logging | Remove param |
| `adapters/workflow_adapter.py:14,48` | Creates `AgentLoggingService` | Remove |
| `api/routes/logs.py:31,36` | Uses for log retrieval | **Deprecate API** |
| `test_evaluator_accuracy.py` | Test file | Update tests |
| `visualize_graph.py` | Utility script | Update |
| `tests/integration/test_tutor_workflow.py` | Integration test | Update |

---

## Target Architecture

### Unified Logging Pattern

Every significant operation logs with this 3-phase pattern:

```
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 1: BEFORE (step starting)                                    │
│  {"step": "X", "status": "starting", "input": {...}}               │
├─────────────────────────────────────────────────────────────────────┤
│  PHASE 2: DURING (optional, for long operations)                    │
│  {"step": "X", "status": "processing", "progress": {...}}          │
├─────────────────────────────────────────────────────────────────────┤
│  PHASE 3: AFTER (step complete)                                     │
│  {"step": "X", "status": "complete", "output": {...}, "duration_ms"}│
└─────────────────────────────────────────────────────────────────────┘
```

### JSON Log Schema

```json
{
  "timestamp": "2025-01-15T10:23:45.123Z",
  "level": "INFO",
  "logger": "services.ocr_service",
  "step": "OCR",
  "status": "complete",
  "book_id": "math-g3-ncert",
  "page": 1,
  "session_id": "abc-123",
  "input": {"model": "gpt-4o-mini", "image_size": 1645432},
  "output": {"chars_extracted": 3421},
  "duration_ms": 5333
}
```

---

## Implementation Phases

### Phase 1: Logging Infrastructure (main.py)

**File:** `llm-backend/main.py`

**Changes:**
1. Add JSON formatter class
2. Add configuration toggle for JSON vs text format
3. Update `logging.basicConfig()` to use JSON formatter

```python
# New code to add to main.py
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    """Format log records as JSON for structured logging."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
        }

        # Check if message is already JSON (our structured logs)
        msg = record.getMessage()
        try:
            msg_data = json.loads(msg)
            log_entry.update(msg_data)
        except (json.JSONDecodeError, TypeError):
            log_entry["message"] = msg

        return json.dumps(log_entry)

# Update basicConfig
log_format = settings.log_format  # "json" or "text"
if log_format == "json":
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        handlers=[handler]
    )
else:
    # Keep existing text format for development
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
```

**File:** `llm-backend/config.py`

**Add:**
```python
log_format: str = Field(
    default="json",
    description="Logging format: 'json' for structured, 'text' for human-readable"
)
```

---

### Phase 2: Book Ingestion Pipeline Services

#### 2.1 PageService (`services/page_service.py`)

**Method: `upload_page()`**
```python
def upload_page(self, book_id: str, image_data: bytes, filename: str) -> PageUploadResponse:
    import time
    start_time = time.time()

    # BEFORE
    logger.info(json.dumps({
        "step": "PAGE_UPLOAD",
        "status": "starting",
        "book_id": book_id,
        "input": {"filename": filename, "size_bytes": len(image_data)}
    }))

    # ... existing validation code ...

    # Log image conversion
    image_bytes = self._convert_to_png(image_data)
    logger.info(json.dumps({
        "step": "IMAGE_CONVERT",
        "status": "complete",
        "book_id": book_id,
        "output": {"format": "PNG", "size_bytes": len(image_bytes)}
    }))

    # Log OCR step (OCRService logs internally)
    ocr_text = self.ocr_service.extract_text_with_retry(image_bytes=image_bytes)

    # AFTER
    duration_ms = int((time.time() - start_time) * 1000)
    logger.info(json.dumps({
        "step": "PAGE_UPLOAD",
        "status": "complete",
        "book_id": book_id,
        "output": {"page_num": page_num, "ocr_chars": len(ocr_text)},
        "duration_ms": duration_ms
    }))
```

#### 2.2 OCRService (`services/ocr_service.py`)

**Method: `extract_text_from_image()`**
```python
def extract_text_from_image(self, image_path=None, image_bytes=None) -> str:
    import time
    start_time = time.time()

    # BEFORE
    logger.info(json.dumps({
        "step": "OCR",
        "status": "starting",
        "input": {"model": self.model, "image_b64_size": len(base64_image)}
    }))

    # ... existing API call ...

    # AFTER
    duration_ms = int((time.time() - start_time) * 1000)
    logger.info(json.dumps({
        "step": "OCR",
        "status": "complete",
        "output": {"chars_extracted": len(extracted_text)},
        "duration_ms": duration_ms
    }))
```

#### 2.3 GuidelineExtractionOrchestrator (`services/guideline_extraction_orchestrator.py`)

Full step-by-step logging for:
- `extract_guidelines_for_book()` - book-level start/complete
- `process_page()` - page-level with sub-steps:
  - LOAD_OCR
  - MINISUMMARY (delegated to MinisummaryService)
  - CONTEXT_PACK
  - BOUNDARY_DETECT (delegated to BoundaryDetectionService)
  - SHARD_CREATE or GUIDELINE_MERGE
  - SHARD_SAVE
  - INDEX_UPDATE

#### 2.4 BoundaryDetectionService (`services/boundary_detection_service.py`)

- Add timing and input/output logging
- **Remove** `_log_boundary_decision()` file-based logging

#### 2.5 MinisummaryService (`services/minisummary_service.py`)

- Add timing for LLM call
- Log input text length, output word count

#### 2.6 GuidelineMergeService (`services/guideline_merge_service.py`)

- Add timing for LLM call
- Log existing/new/merged lengths

#### 2.7 ContextPackService (`services/context_pack_service.py`)

- Log context composition (open topics, recent summaries)

#### 2.8 DBSyncService (`services/db_sync_service.py`)

- Log each shard sync operation

#### 2.9 TopicNameRefinementService (`services/topic_name_refinement_service.py`)

- Add timing for LLM call
- Log old → new name changes

#### 2.10 TopicDeduplicationService (`services/topic_deduplication_service.py`)

- Add timing for LLM call
- Log duplicate pair count

---

### Phase 3: Tutor Workflow (Replace AgentLoggingService)

#### 3.1 Delete AgentLoggingService

1. **DELETE** `services/agent_logging_service.py`
2. **UPDATE** `services/__init__.py` - remove export

#### 3.2 Refactor BaseAgent (`agents/base.py`)

Remove `logging_service` dependency, add inline JSON logging:

```python
def execute(self, state: SimplifiedState) -> SimplifiedState:
    import time
    import json
    start_time = time.time()

    session_id = state.get("session_id", "unknown")

    # BEFORE
    logger.info(json.dumps({
        "step": f"AGENT_{self.agent_name.upper()}",
        "status": "starting",
        "session_id": session_id,
        "agent": self.agent_name
    }))

    try:
        updated_state, output, reasoning, input_summary = self.execute_internal(state)

        duration_ms = int((time.time() - start_time) * 1000)

        # AFTER
        logger.info(json.dumps({
            "step": f"AGENT_{self.agent_name.upper()}",
            "status": "complete",
            "session_id": session_id,
            "agent": self.agent_name,
            "input_summary": input_summary,
            "output": output,
            "reasoning": reasoning[:500] if reasoning else None,
            "duration_ms": duration_ms
        }))

        return updated_state

    except Exception as e:
        # Error logging
        ...
```

#### 3.3 Update Workflow Files

- `workflows/tutor_workflow.py` - remove logging_service parameter
- `adapters/workflow_adapter.py` - remove AgentLoggingService creation

#### 3.4 Update LLMService (`services/llm_service.py`)

Add timing to all LLM calls (call_gpt_4o, call_gpt_5_1, call_gemini)

#### 3.5 Deprecate Logs API (`api/routes/logs.py`)

Return empty results with deprecation notice.

---

### Phase 4: API Routes Cleanup

**File:** `features/book_ingestion/api/routes.py`

1. Fix inline imports - move `import logging` to top
2. Add endpoint-level logging for key operations

---

## Implementation Checklist

### Phase 1: Infrastructure
- [ ] Add `JSONFormatter` class to `main.py`
- [ ] Add `log_format` to `config.py`
- [ ] Update `logging.basicConfig()` to use JSON formatter

### Phase 2: Book Ingestion Services
- [ ] `page_service.py` - upload_page, approve_page, delete_page
- [ ] `ocr_service.py` - extract_text_from_image, extract_text_with_retry
- [ ] `guideline_extraction_orchestrator.py` - all methods
- [ ] `boundary_detection_service.py` - detect (remove file logging)
- [ ] `minisummary_service.py` - generate
- [ ] `guideline_merge_service.py` - merge
- [ ] `context_pack_service.py` - build
- [ ] `db_sync_service.py` - sync_shard, sync_book_guidelines
- [ ] `topic_name_refinement_service.py` - refine_names
- [ ] `topic_deduplication_service.py` - deduplicate
- [ ] `index_management_service.py` - enhance existing logging

### Phase 3: Tutor Workflow
- [ ] Delete `services/agent_logging_service.py`
- [ ] Update `services/__init__.py`
- [ ] Refactor `agents/base.py` - remove logging_service dependency
- [ ] Update `agents/planner_agent.py` - remove logging_service
- [ ] Update `agents/executor_agent.py` - remove logging_service
- [ ] Update `agents/evaluator_agent.py` - remove logging_service
- [ ] Update `workflows/tutor_workflow.py` - remove logging_service
- [ ] Update `adapters/workflow_adapter.py` - remove logging_service
- [ ] Update `services/llm_service.py` - add timing logs
- [ ] Deprecate `api/routes/logs.py` endpoints

### Phase 4: Cleanup
- [ ] Fix `routes.py` inline imports
- [ ] Add API endpoint logging
- [ ] Update test files
- [ ] Update `visualize_graph.py`

### Phase 5: Testing
- [ ] Run book ingestion workflow end-to-end
- [ ] Verify JSON logs in console
- [ ] Run tutor workflow end-to-end
- [ ] Verify agent logs appear correctly
- [ ] Test with `LOG_FORMAT=text` for human-readable output

---

## Example Console Output (After Implementation)

### Book Ingestion Flow
```json
{"timestamp":"2025-01-15T10:23:45.123Z","level":"INFO","logger":"page_service","step":"PAGE_UPLOAD","status":"starting","book_id":"math-g3","input":{"filename":"p1.png","size_bytes":2456789}}
{"timestamp":"2025-01-15T10:23:46.234Z","level":"INFO","logger":"page_service","step":"IMAGE_CONVERT","status":"complete","book_id":"math-g3","output":{"format":"PNG","size_bytes":1234567}}
{"timestamp":"2025-01-15T10:23:46.345Z","level":"INFO","logger":"ocr_service","step":"OCR","status":"starting","input":{"model":"gpt-4o-mini","image_b64_size":1645432}}
{"timestamp":"2025-01-15T10:23:51.456Z","level":"INFO","logger":"ocr_service","step":"OCR","status":"complete","output":{"chars_extracted":3421},"duration_ms":5111}
{"timestamp":"2025-01-15T10:23:51.567Z","level":"INFO","logger":"page_service","step":"PAGE_UPLOAD","status":"complete","book_id":"math-g3","output":{"page_num":1,"ocr_chars":3421},"duration_ms":6444}
```

### Tutor Workflow
```json
{"timestamp":"2025-01-15T11:00:00.123Z","level":"INFO","logger":"agents.base","step":"AGENT_PLANNER","status":"starting","session_id":"abc-123","agent":"planner"}
{"timestamp":"2025-01-15T11:00:05.234Z","level":"INFO","logger":"llm_service","step":"LLM_CALL","status":"complete","output":{"model":"gpt-4o","response_len":2345},"duration_ms":5111}
{"timestamp":"2025-01-15T11:00:05.345Z","level":"INFO","logger":"agents.base","step":"AGENT_PLANNER","status":"complete","session_id":"abc-123","agent":"planner","input_summary":"Plan for fractions lesson","duration_ms":5222}
```

---

## Decisions Made

1. **Logs API**: Deprecated (returns empty results)
2. **File persistence**: Not needed (stdout only)
3. **Format toggle**: `LOG_FORMAT=json` (default) or `LOG_FORMAT=text`
