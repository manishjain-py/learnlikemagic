# Code Coverage — Automated Unit Test Generation Pipeline

You are running a measure → prioritize → generate tests → validate → re-measure → report cycle to achieve ≥80% unit test coverage across the backend.

**Reference:** Read `docs/backend-architecture.md` and the existing tests under `llm-backend/tests/` for patterns and conventions.

---

## ENVIRONMENT SETUP

**All Python commands MUST use the project virtual environment.** The venv is at `llm-backend/venv` (NOT `.venv`).

For every `python` or `python -m` command in this pipeline, use:
```bash
cd llm-backend && source venv/bin/activate && python ...
```

Or use the full path: `llm-backend/venv/bin/python`

Do NOT use bare `python` or `python3` — the system Python lacks project dependencies.

---

## AUTOMATION DIRECTIVE

This is a **fully automated pipeline**. The user will NOT be present to review plans, approve decisions, or give go-ahead between steps.

- **Do NOT** use `EnterPlanMode` or `AskUserQuestion` at any point.
- **Do NOT** pause for user confirmation between steps.
- Make all decisions autonomously based on coverage data and architecture knowledge.
- Execute every step end-to-end without stopping.
- If something fails (tests, imports), attempt to fix it yourself and retry. Only stop if you've exhausted reasonable recovery attempts (3 max).
- Log all decisions and rationale to the progress file (Step 0) so the user can review after the fact.

---

## ARCHITECTURE KNOWLEDGE — Component Priority Map

You MUST understand the system architecture to prioritize what to test. Here is the priority map:

### P0 — Critical Runtime (MUST reach 90%+ coverage)
These are the core components that execute during every tutoring session:

| File | Why Critical |
|------|-------------|
| `tutor/orchestration/orchestrator.py` | Central coordinator — Safety → MasterTutor → State Update flow |
| `tutor/services/session_service.py` | Session lifecycle — create, step, summary |
| `tutor/agents/master_tutor.py` | The actual tutor — generates responses, grades, tracks mastery |
| `tutor/agents/safety.py` | Safety gate — blocks harmful content before tutor sees it |
| `tutor/agents/base_agent.py` | Base class — prompt building, LLM call, timeout, schema validation |
| `tutor/models/session_state.py` | Session state — all state transitions, mastery tracking, question lifecycle |
| `tutor/models/messages.py` | DTOs — Message, StudentContext, SessionStateDTO |
| `shared/services/llm_service.py` | LLM abstraction — multi-provider calls, retry logic, structured output |
| `shared/services/anthropic_adapter.py` | Claude API adapter — request/response translation |
| `shared/repositories/session_repository.py` | Session persistence — create, get, update |
| `shared/repositories/event_repository.py` | Event logging — log turns, retrieve history |
| `shared/repositories/guideline_repository.py` | Guideline access — search, get by ID/topic |

### P1 — Business Logic (MUST reach 80%+ coverage)
Supporting logic that shapes tutoring quality:

| File | Why Important |
|------|--------------|
| `tutor/services/topic_adapter.py` | Converts DB guidelines → Topic domain model |
| `shared/models/domain.py` | Core domain objects — Student, Goal, TutorState, GradingResult |
| `shared/models/schemas.py` | API request/response schemas — validation logic |
| `shared/models/entities.py` | ORM models — Session, Event, TeachingGuideline, StudyPlan |
| `shared/utils/exceptions.py` | Custom exceptions — HTTP error conversion |
| `shared/utils/formatting.py` | Conversation formatting, turn extraction (partially tested) |
| `shared/utils/constants.py` | System constants — MAX_STEPS, thresholds |
| `shared/prompts/loader.py` | Prompt template loading and rendering |
| `tutor/prompts/templates.py` | Jinja2 prompt templates |
| `tutor/utils/prompt_utils.py` | Prompt construction helpers |
| `tutor/utils/schema_utils.py` | JSON schema utilities for structured output |
| `tutor/utils/state_utils.py` | State manipulation helpers |
| `study_plans/services/generator_service.py` | Study plan generation via LLM |
| `study_plans/services/reviewer_service.py` | Study plan validation |
| `study_plans/services/orchestrator.py` | Generate → Review loop |

### P2 — Offline Pipeline (target 70%+ coverage)
Book ingestion runs offline, not in the critical tutoring path:

| File | Why |
|------|-----|
| `book_ingestion/services/book_service.py` | Book CRUD operations |
| `book_ingestion/services/ocr_service.py` | Text extraction from images/PDFs |
| `book_ingestion/services/guideline_extraction_orchestrator.py` | Coordinates the full extraction pipeline |
| `book_ingestion/services/boundary_detection_service.py` | Topic boundary detection |
| `book_ingestion/services/topic_deduplication_service.py` | Duplicate topic removal |
| `book_ingestion/services/quality_gates_service.py` | Output quality validation |
| `book_ingestion/services/db_sync_service.py` | Sync extracted data to DB |
| `book_ingestion/repositories/book_repository.py` | Book data access |
| `book_ingestion/repositories/book_guideline_repository.py` | Guideline data access |
| Other `book_ingestion/services/*` | Supporting pipeline stages |

### P3 — Infrastructure (target 60%+ coverage)
Config, startup, API routing — largely tested via integration tests:

| File | Why |
|------|-----|
| `config.py` | Environment-based settings (mostly declarative) |
| `database.py` | DatabaseManager singleton, connection pooling |
| `main.py` | App startup and route registration |
| `tutor/api/sessions.py` | REST endpoint handlers |
| `tutor/api/curriculum.py` | Curriculum endpoint handlers |
| `book_ingestion/api/routes.py` | Book API endpoints |
| `evaluation/*` | Evaluation pipeline (has its own QA cycle) |

---

## TESTING CONVENTIONS

Follow these patterns from the existing test suite:

### Unit Test Pattern
```python
"""Unit tests for <module_name>."""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

class TestClassName:
    """Tests for ClassName."""

    def test_method_does_expected_thing(self):
        """Test that method does X when given Y."""
        # Arrange
        ...
        # Act
        result = function_under_test(input)
        # Assert
        assert result == expected

    def test_method_handles_edge_case(self):
        """Test that method handles edge case gracefully."""
        ...
```

### Key Mocking Strategies
- **LLM calls**: Always mock `LLMService.call_gpt_5_2()`, `call_anthropic()`, etc. Never make real API calls.
- **Database**: Use the `db_session` fixture (in-memory SQLite) from `tests/conftest.py`.
- **S3**: Mock boto3 clients or use `unittest.mock.patch`.
- **External services**: Mock at the service boundary, not deep inside.
- **Async methods**: Use `AsyncMock` for async functions.

### File Naming Convention
- Test files: `tests/unit/test_<module_name>.py`
- Test classes: `Test<ClassName>` or `Test<FunctionName>`
- Test methods: `test_<method>_<scenario>_<expected_outcome>`

### What NOT to Test
- Pure Pydantic model declarations (field definitions without custom validators)
- `__init__.py` files that only re-export
- Prompt text content (test the prompt *construction* logic, not the prose)
- Config.py environment variable declarations (tested by Pydantic itself)
- Import-only modules

---

## Step 0: Create progress log

Create a JSON log file at `$ARGUMENTS.log` in the root folder. Keep updating status/progress to this file. Anyone looking at this file should understand what is done, what's going on currently, and what's planned next.

---

## Step 0.5: Create a new branch from latest main

```bash
git checkout main && git pull origin main
git checkout -b code-coverage/$(date +%Y%m%d-%H%M%S)
```

All changes in this run will be committed to this branch.

---

## Step 1: Measure BASELINE coverage

Run the existing unit tests with coverage reporting:

```bash
cd llm-backend && source venv/bin/activate
python -m pytest tests/unit/ -v --cov=. --cov-report=term-missing --cov-report=json:coverage-baseline.json --no-header -q 2>&1
```

Parse the JSON coverage report to build a per-file coverage map:
- Which files have 0% coverage (never tested)
- Which files have partial coverage (and which lines are missing)
- What is the overall line coverage percentage

Log the baseline numbers to the progress file.

---

## Step 2: Build the coverage gap analysis

Using the baseline coverage data AND the priority map above, create a prioritized work queue:

1. **Read every uncovered file** to understand what functions/classes need tests.
2. **Sort by priority**: P0 files first, then P1, P2, P3.
3. **Within each priority**, sort by impact: files with more uncovered logic first.
4. **Skip files** that fall into "What NOT to Test" (pure declarations, `__init__.py`, etc.).
5. **Estimate** how many test functions each file needs.

Log the full work queue to the progress file.

---

## Step 3: Generate unit tests — iterate through the work queue

For each file in the work queue:

1. **Read the source file** thoroughly. Understand every function, class, and method.
2. **Identify testable behaviors**:
   - Happy path for each public method
   - Edge cases (empty inputs, None values, boundary conditions)
   - Error handling paths (exceptions raised, invalid input)
   - State transitions (for stateful classes like SessionState)
3. **Write the test file** at `tests/unit/test_<module_name>.py`.
4. **Mock external dependencies** (LLM, DB, S3, network) — unit tests must be fast and deterministic.
5. **Run the new test file** immediately to verify it passes:
   ```bash
   cd llm-backend && source venv/bin/activate
   python -m pytest tests/unit/test_<module_name>.py -v --no-header -q 2>&1
   ```
6. **If tests fail**: Debug and fix. Common issues:
   - Import errors → check module paths
   - Mock not applied correctly → verify patch target
   - Async issues → use `pytest.mark.asyncio` and `AsyncMock`
7. **Once passing**, move to the next file.

**Important guidelines while writing tests:**
- **Don't over-mock**: If a helper function is pure (no side effects), call it directly.
- **Test behavior, not implementation**: Assert on outputs and side effects, not internal method calls.
- **One concern per test**: Each test should verify one specific behavior.
- **Descriptive names**: `test_process_turn_returns_safety_response_when_content_unsafe` > `test_process_turn_2`
- **Use fixtures**: Leverage existing fixtures from `conftest.py` and add new ones when a pattern repeats 3+ times.
- **Group related tests**: Use `TestClassName` classes to organize tests for the same unit.

---

## Step 4: Run full test suite and measure POST coverage

After all test files are written:

```bash
cd llm-backend && source venv/bin/activate
python -m pytest tests/unit/ -v --cov=. --cov-report=term-missing --cov-report=json:coverage-final.json --cov-report=html:htmlcov --no-header 2>&1
```

Parse the final JSON coverage report and compare with baseline.

---

## Step 5: Gap check — iterate if below 80%

If overall coverage is still below 80%:

1. Identify the files dragging coverage down.
2. Go back to Step 3 for those specific files.
3. Write additional tests targeting the uncovered lines (the `--cov-report=term-missing` output shows exact line numbers).
4. Re-run coverage.
5. Repeat until 80% overall is reached or all reasonable code paths are tested.

---

## Step 6: Final validation

1. Run the complete test suite (unit + integration) to make sure nothing is broken:
   ```bash
   cd llm-backend && source venv/bin/activate
   python -m pytest tests/ -x -q --no-header 2>&1
   ```
   (Integration tests may be skipped if they require external services. That's OK — focus on unit tests passing.)

2. Verify no test relies on external services (no real LLM calls, no real DB, no real S3).

3. Commit all new test files:
   ```bash
   git add tests/unit/test_*.py
   git commit -m "Add unit tests to achieve 80%+ code coverage"
   ```

---

## Step 7: Generate the coverage comparison report

Produce a detailed comparison report:

```
## Code Coverage Report

### Summary
| Metric | Baseline | Final | Delta |
|--------|----------|-------|-------|
| Overall Line Coverage | X% | Y% | +Z% |
| Files with 0% coverage | N | M | -K |
| Total test files | A | B | +C |
| Total test functions | D | E | +F |

### Coverage by Priority Tier
| Tier | Target | Achieved | Status |
|------|--------|----------|--------|
| P0 — Critical Runtime | 90% | X% | ✅/❌ |
| P1 — Business Logic | 80% | X% | ✅/❌ |
| P2 — Offline Pipeline | 70% | X% | ✅/❌ |
| P3 — Infrastructure | 60% | X% | ✅/❌ |

### Per-File Coverage Details
| File | Before | After | Lines Missing |
|------|--------|-------|---------------|
| tutor/orchestration/orchestrator.py | 0% | X% | ... |
| ... | ... | ... | ... |

### New Test Files Created
(list each new test file and what it covers)

### Known Gaps
(list any files that couldn't be fully tested and why — e.g., requires integration test, too tightly coupled)

### Recommendations
(list any refactoring suggestions that would improve testability)
```

---

## Step 8: Email the final report

1. Save the comparison report from Step 7 as a nicely formatted HTML file:
   ```bash
   REPORT_FILE="$(pwd)/$ARGUMENTS-report.html"
   ```
   Write the full coverage report as a well-structured HTML document to this file (use proper `<html>`, `<head>`, `<body>` tags, and CSS for readability — use a clean table style with alternating row colors).

2. Send the email using the Python email helper:
   ```bash
   cd llm-backend && source venv/bin/activate
   BRANCH=$(git branch --show-current)
   LOGFILE="$(pwd)/$ARGUMENTS.log"
   REPORT_FILE="$(pwd)/$ARGUMENTS-report.html"

   python scripts/send_coverage_report.py \
       --to "manishjain.py@gmail.com" \
       --subject "Code Coverage Report — $BRANCH — $(date +%Y-%m-%d)" \
       --report "$REPORT_FILE" \
       --log "$LOGFILE"
   ```

   If the Python email script fails (e.g., SMTP not configured), fall back to macOS Mail.app:
   ```bash
   osascript -e '
   tell application "Mail"
       set newMessage to make new outgoing message with properties {subject:"Code Coverage Report — '"$BRANCH"'", content:"See attached HTML report and log file.", visible:false}
       tell newMessage
           make new to recipient at end of to recipients with properties {address:"manishjain.py@gmail.com"}
           make new attachment with properties {file name:POSIX file "'"$REPORT_FILE"'"} at after the last paragraph
           make new attachment with properties {file name:POSIX file "'"$LOGFILE"'"} at after the last paragraph
       end tell
       send newMessage
   end tell'
   ```

   If both fail, log the error and note that the report is saved locally at `$REPORT_FILE`.
