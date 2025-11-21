# Learn Like Magic - Backend

FastAPI backend with LangGraph agent for adaptive tutoring.

## Architecture

```
llm-backend/
├── api/                           # API layer
│   └── routes/                   # FastAPI route handlers
│       ├── health.py             # Health check endpoints
│       ├── curriculum.py         # Curriculum discovery
│       └── sessions.py           # Session management
├── services/                      # Business logic layer
│   ├── session_service.py        # Session orchestration
│   ├── llm_service.py            # OpenAI API wrapper (GPT-4o, GPT-5.1)
│   └── agent_logging_service.py  # Dual-format logging (JSONL + TXT)
├── repositories/                  # Data access layer
│   ├── session_repository.py     # Session CRUD
│   ├── event_repository.py       # Event logging
│   └── guideline_repository.py   # Guideline queries
├── workflows/                     # LangGraph workflow (3-agent system)
│   ├── tutor_workflow.py         # Main workflow orchestration
│   ├── state.py                  # SimplifiedState TypedDict
│   ├── schemas.py                # Pydantic validation models
│   └── helpers.py                # Utility functions
├── agents/                        # Agent implementations
│   ├── planner_agent.py          # PLANNER (GPT-5.1 deep reasoning)
│   ├── executor_agent.py         # EXECUTOR (GPT-4o question generation)
│   ├── evaluator_agent.py        # EVALUATOR (GPT-4o grading & routing)
│   ├── base.py                   # Base agent class
│   └── prompts/                  # External prompt templates
│       ├── planner_initial.txt   # Initial planning prompt
│       ├── planner_replan.txt    # Adaptive replanning prompt
│       ├── executor.txt          # Message generation prompt
│       └── evaluator.txt         # Evaluation prompt
├── adapters/                      # Integration adapters
│   ├── workflow_adapter.py       # SessionService ↔ TutorWorkflow bridge
│   └── state_adapter.py          # TutorState ↔ SimplifiedState converter
├── prompts/                       # LLM prompt templates
│   ├── templates/                # Template files
│   │   ├── teaching_prompt.txt   # Teaching/present node
│   │   ├── grading_prompt.txt    # Grading/check node
│   │   └── remediation_prompt.txt # Remediation helper
│   └── loader.py                 # PromptLoader class
├── models/                        # Data models (separated by concern)
│   ├── database.py               # SQLAlchemy ORM models
│   ├── domain.py                 # Business logic models (Pydantic)
│   └── schemas.py                # API request/response schemas
├── utils/                         # Shared utilities
│   ├── formatting.py             # History & response formatting
│   ├── constants.py              # Centralized constants
│   └── exceptions.py             # Custom exceptions
├── tests/                         # Test suite
│   ├── conftest.py               # Pytest fixtures
│   ├── unit/                     # Unit tests
│   └── integration/              # Integration tests
├── data/
│   └── seed_guidelines.json      # Teaching guidelines
├── main.py                        # FastAPI app (66 lines, clean!)
├── database.py                    # Database manager
├── config.py                      # Configuration management
├── llm.py                         # OpenAI LLM abstraction
├── requirements.txt               # Production dependencies
├── requirements-dev.txt           # Development dependencies
├── pytest.ini                     # Pytest configuration
├── Dockerfile                     # Container image (Python 3.11)
├── .env                          # Environment configuration
└── .env.example                  # Example configuration
```

### Design Principles

- **Single Responsibility Principle (SRP)**: Each module/function has one clear purpose
- **Separation of Concerns**: API → Services → Repositories → Database
- **Dependency Injection**: Pass dependencies as parameters for testability
- **DRY**: No code duplication, shared utilities for common operations
- **Pure Functions**: Graph nodes as state transformations without side effects
- **External Templates**: Prompts stored as separate files for easy versioning

## Setup

### Requirements

- **Python 3.10+** (Production uses 3.11, local development supports 3.10-3.13)
- **PostgreSQL** (Production) or **SQLite** (Development)
- **OpenAI API Key**
- **AWS CLI** (for S3 operations - installed at `/opt/homebrew/bin/aws` on macOS with Homebrew)

### 1. Create Virtual Environment

```bash
# Use Python 3.11+ to match production (Docker uses 3.11)
# Check your Python version first
python3 --version

# Create venv (use python3.11 or python3.13 if available)
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Verify Python version in venv
python --version
```

### 2. Install Dependencies

```bash
# Production dependencies
pip install -r requirements.txt

# Development dependencies (includes testing tools)
pip install -r requirements-dev.txt
```

### 3. Configure Environment

**Option A: Automated Setup (Recommended for team members)**

If you have access to `infra/terraform/terraform.tfvars`:
```bash
# Run setup script to auto-generate .env from terraform config
./scripts/setup-env.sh
```

This will automatically populate `.env` with production database credentials and API keys.

**Option B: Manual Setup**

```bash
# Copy the example file
cp .env.example .env

# Edit with your values
nano .env
```

Required environment variables:
```bash
# LLM Configuration
OPENAI_API_KEY=sk-your-key-here
LLM_MODEL=gpt-4o-mini

# Database
DATABASE_URL=postgresql://user:password@host:5432/database
# Or for local SQLite: sqlite:///./tutor.db

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
```

⚠️ **Security Note**: The `.env` file is gitignored and will never be committed. Each developer must set it up locally.

### 4. Initialize Database

```bash
# Create tables
python db.py --migrate

# Seed teaching guidelines
python db.py --seed-guidelines data/seed_guidelines.json
```

### 5. Start Server

```bash
uvicorn main:app --reload
```

API available at: http://localhost:8000
Interactive docs at: http://localhost:8000/docs

## API Endpoints

### Health Check
```http
GET /
→ {"status": "ok", "service": "Adaptive Tutor API", "version": "0.1.0"}
```

### Curriculum Discovery
```http
GET /curriculum?country=India&board=CBSE&grade=3
→ Returns: {"subjects": ["Mathematics", "English"]}

GET /curriculum?country=India&board=CBSE&grade=3&subject=Mathematics
→ Returns: {"topics": ["Fractions", "Multiplication"]}

GET /curriculum?...&subject=Mathematics&topic=Fractions
→ Returns: {"subtopics": [{"subtopic": "...", "guideline_id": "g1"}, ...]}
```

### Learning Sessions
```http
POST /sessions
Content-Type: application/json

{
  "student": {
    "id": "s1",
    "grade": 3,
    "prefs": {"style": "standard", "lang": "en"}
  },
  "goal": {
    "topic": "Fractions",
    "syllabus": "CBSE-G3",
    "learning_objectives": ["Compare fractions"],
    "guideline_id": "g1"
  }
}

→ Returns: {
  "session_id": "uuid",
  "first_turn": {
    "message": "...",
    "hints": ["..."],
    "step_idx": 0,
    "mastery_score": 0.0
  }
}
```

```http
POST /sessions/{session_id}/step
Content-Type: application/json

{
  "student_reply": "5/8 is bigger"
}

→ Returns: {
  "next_turn": {...},
  "routing": "Advance",
  "last_grading": {...}
}
```

```http
GET /sessions/{session_id}/summary
→ Returns: {
  "steps_completed": 7,
  "mastery_score": 0.82,
  "misconceptions_seen": [...],
  "suggestions": [...]
}
```

## Database Schema

### Tables

#### teaching_guidelines
```sql
id TEXT PRIMARY KEY
country TEXT
board TEXT
grade INTEGER
subject TEXT
topic TEXT
subtopic TEXT
guideline TEXT
metadata_json TEXT
created_at DATETIME
INDEX idx_curriculum (country, board, grade, subject, topic)
```

#### sessions
```sql
id TEXT PRIMARY KEY
student_json TEXT
goal_json TEXT
state_json TEXT
mastery REAL
step_idx INTEGER
created_at DATETIME
updated_at DATETIME
```

#### events
```sql
id TEXT PRIMARY KEY
session_id TEXT FOREIGN KEY
node TEXT
step_idx INTEGER
payload_json TEXT
created_at DATETIME
INDEX idx_session_step (session_id, step_idx)
```

## LangGraph Workflow (3-Agent System)

### Architecture

The tutoring system uses a **3-agent adaptive architecture** with LangGraph orchestration:

1. **PLANNER** (GPT-5.1 with deep reasoning)
   - Strategic planning and replanning
   - Creates study plans with 3-5 steps
   - Adapts when students struggle

2. **EXECUTOR** (GPT-4o)
   - Fast question generation
   - Context-aware teaching messages
   - Follows plan's teaching approach

3. **EVALUATOR** (GPT-4o)
   - Evaluates student responses (0.0-1.0 score)
   - Provides constructive feedback
   - Routes workflow (continue/replan/end)
   - Off-topic detection & redirection

### Workflow Flow

```
START → ROUTER (smart entry point)
          ↓
          ├─→ PLANNER (new session) → EXECUTOR → END
          │                              ↓
          ├─→ EVALUATOR (student response) → (routing decision)
          │                                      ↓
          │                                      ├─→ replan → PLANNER
          │                                      ├─→ continue → EXECUTOR → END
          │                                      └─→ end → END
          │
          └─→ EXECUTOR (edge case)
```

### Key Features

- **Session Persistence**: SQLite checkpointing with LangGraph
- **Adaptive Teaching**: Dynamic replanning when students struggle
- **Comprehensive Logging**: Dual-format (JSONL + TXT) agent execution logs
- **Smart Routing**: Context-aware entry point prevents infinite loops
- **Cost Optimization**: GPT-5.1 for planning only, GPT-4o for execution

## Teaching Guidelines

Guidelines are structured JSON documents in `data/seed_guidelines.json`:

```json
{
  "id": "g1",
  "country": "India",
  "board": "CBSE",
  "grade": 3,
  "subject": "Mathematics",
  "topic": "Fractions",
  "subtopic": "Comparing Like Denominators",
  "guideline": "Detailed teaching instructions...",
  "metadata": {
    "learning_objectives": ["..."],
    "depth_level": "basic",
    "common_misconceptions": ["..."],
    "scaffolding_strategies": ["..."],
    "assessment_criteria": {...}
  }
}
```

### Adding New Guidelines

1. Edit `data/seed_guidelines.json`
2. Run: `python db.py --seed-guidelines data/seed_guidelines.json`
3. Restart server

## Repository Pattern

The `guideline_repository.py` provides abstraction over database access:

```python
from guideline_repository import TeachingGuidelineRepository

repo = TeachingGuidelineRepository(db)

# Get subjects for a curriculum
subjects = repo.get_subjects("India", "CBSE", 3)

# Get topics for a subject
topics = repo.get_topics("India", "CBSE", 3, "Mathematics")

# Get subtopics with guideline IDs
subtopics = repo.get_subtopics("India", "CBSE", 3, "Mathematics", "Fractions")

# Get specific guideline
guideline = repo.get_guideline_by_id("g1")
```

This pattern isolates the rest of the codebase from database schema changes.

## CLI Commands

### Database Management

```bash
# Create database tables
python db.py --migrate

# Seed teaching guidelines
python db.py --seed-guidelines data/seed_guidelines.json

# Both show usage if run without args
python db.py
```

## Development

### Run with Auto-Reload

```bash
uvicorn main:app --reload --log-level debug
```

### Environment Variables

```bash
OPENAI_API_KEY=sk-...          # Required
LLM_MODEL=gpt-4o-mini          # Optional, default: gpt-4o-mini
DATABASE_URL=sqlite:///./tutor.db  # Optional
API_HOST=0.0.0.0               # Optional
API_PORT=8000                  # Optional
```

### Manual API Testing

```bash
# Check API health
curl http://localhost:8000

# Get curriculum
curl "http://localhost:8000/curriculum?country=India&board=CBSE&grade=3"

# Create session (replace guideline_id with actual ID)
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "student": {"id": "s1", "grade": 3},
    "goal": {
      "topic": "Fractions",
      "syllabus": "CBSE-G3",
      "learning_objectives": ["Compare fractions"],
      "guideline_id": "g1"
    }
  }'
```

### Debugging & Logs

#### Streaming Session Logs (Live)

To monitor agent execution in real-time during a tutoring session:

```bash
# Stream logs for a specific session (follows new log entries)
curl -N "http://localhost:8000/sessions/{session_id}/logs/stream?follow=true"

# Example:
curl -N "http://localhost:8000/sessions/2469eccd-8ad4-485b-a33b-272657c67f7b/logs/stream?follow=true"
```

The `-N` flag disables buffering for real-time streaming. You'll see:
- Agent executions (PLANNER, EXECUTOR, EVALUATOR)
- Reasoning traces
- State transitions
- Performance metrics

#### Agent Log Files

Agent execution logs are stored in two formats:

```bash
# Machine-readable JSON logs
logs/sessions/{session_id}/agent_steps.jsonl

# Human-readable text logs
logs/sessions/{session_id}/agent_steps.txt
```

#### Checkpoint Database

LangGraph checkpoints are stored in:
```bash
checkpoints/tutor_sessions.db
```

Query session state:
```bash
sqlite3 checkpoints/tutor_sessions.db "SELECT thread_id, checkpoint_ns FROM checkpoints;"
```

## Testing

The project uses **pytest** for automated testing with coverage reporting.

### Test Structure

```
tests/
├── conftest.py          # Shared fixtures (db_session, sample data, mocks)
├── unit/                # Fast, isolated tests (no external dependencies)
│   └── test_formatting.py
└── integration/         # Tests with database, external services
```

### Running Tests

```bash
# Activate virtual environment first
source venv/bin/activate

# Set dummy API key for tests (required for module imports)
export OPENAI_API_KEY=sk-test-dummy-key

# Run all tests with coverage
pytest

# Run specific test file
pytest tests/unit/test_formatting.py

# Run with verbose output
pytest -v

# Run only unit tests (fast)
pytest -m unit

# Run only integration tests
pytest -m integration

# Run tests matching a pattern
pytest -k "test_format"

# Show test coverage report
pytest --cov=. --cov-report=term-missing

# Generate HTML coverage report
pytest --cov=. --cov-report=html
# Open htmlcov/index.html in browser
```

### Test Markers

Tests are organized with markers (defined in `pytest.ini`):

- `@pytest.mark.unit` - Fast tests with no external dependencies
- `@pytest.mark.integration` - Tests requiring database or external services
- `@pytest.mark.slow` - Tests taking >1 second
- `@pytest.mark.smoke` - Quick smoke tests for deployment verification

### Writing Tests

```python
# tests/unit/test_example.py
import pytest
from utils.formatting import format_conversation_history

class TestFormatting:
    """Tests for conversation formatting."""

    def test_format_empty_history(self):
        """Test formatting empty history returns placeholder."""
        result = format_conversation_history([])
        assert result == "(First turn - no history yet)"

    def test_format_multiple_entries(self, sample_tutor_state):
        """Test formatting history with multiple entries."""
        # Use fixtures from conftest.py
        history = sample_tutor_state.history
        result = format_conversation_history(history)
        assert "Teacher:" in result
        assert "Student:" in result
```

### Available Fixtures

Defined in `tests/conftest.py`:

- `db_session` - In-memory SQLite database session
- `client` - FastAPI TestClient
- `sample_student` - Student data model
- `sample_goal` - Learning goal data
- `sample_tutor_state` - Complete tutor state
- `sample_grading_result` - Grading result data
- `mock_llm_provider` - Mocked LLM for testing without API calls

### Coverage Configuration

Configured in `pytest.ini`:

- **Target**: All modules except tests, migrations, old files
- **Reports**: Terminal (missing lines) + HTML
- **Threshold**: Aim for >80% coverage on new code

### Test Best Practices

1. **Arrange-Act-Assert**: Structure tests clearly
2. **One assertion per test**: Keep tests focused
3. **Use fixtures**: Leverage shared test data
4. **Mock external services**: Use `mock_llm_provider` for LLM calls
5. **Test edge cases**: Empty inputs, None values, errors
6. **Descriptive names**: `test_format_empty_history` not `test1`
7. **Docstrings**: Explain what the test verifies

## Deployment

### Docker

```bash
docker build -t llm-backend .
docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... llm-backend
```

### Production Considerations

- Use PostgreSQL instead of SQLite for production
- Enable HTTPS with proper certificates
- Add authentication and authorization
- Implement rate limiting
- Set up monitoring and logging
- Use environment secrets management
- Enable CORS only for trusted origins

## Dependencies

### Production (`requirements.txt`)

- **fastapi**: Web framework
- **uvicorn[standard]**: ASGI server with performance optimizations
- **langgraph**: Agent orchestration framework
- **langchain-core**: LangChain utilities
- **openai**: OpenAI API client
- **sqlalchemy**: ORM for database operations
- **psycopg2-binary**: PostgreSQL adapter
- **pydantic**: Data validation and settings
- **pydantic-settings**: Environment configuration
- **python-dotenv**: .env file support

### Development (`requirements-dev.txt`)

- **pytest**: Testing framework
- **pytest-asyncio**: Async test support
- **pytest-cov**: Coverage reporting
- **pytest-mock**: Mocking utilities
- **httpx**: TestClient for FastAPI
- **requests-mock**: Mock HTTP requests
- **faker**: Generate test data
- **black**: Code formatter
- **flake8**: Linter
- **mypy**: Type checker
- **isort**: Import sorter
- **ipython**: Enhanced Python REPL

## Troubleshooting

### Port already in use
```bash
lsof -ti:8000 | xargs kill -9
```

### Database locked
```bash
rm tutor.db
python db.py --migrate
python db.py --seed-guidelines data/seed_guidelines.json
```

### OpenAI API errors
- Check API key is valid
- Verify you have credits
- Check rate limits

### Import errors
```bash
# Ensure virtual environment is activated
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Test failures due to missing OPENAI_API_KEY
```bash
# Tests require the API key environment variable (even with a dummy value)
export OPENAI_API_KEY=sk-test-dummy-key
pytest
```

### Python version issues
```bash
# Check Python version (must be 3.10+)
python --version

# If using older Python, install 3.11+ and recreate venv
# On macOS with Homebrew:
brew install python@3.11
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt requirements-dev.txt
```

### Coverage reports not generating
```bash
# Ensure pytest-cov is installed
pip install pytest-cov

# Run with explicit coverage options
pytest --cov=. --cov-report=html --cov-report=term-missing
```

## Support

For issues specific to the backend:
- Check logs in terminal
- Review API docs at http://localhost:8000/docs
- Verify database has been migrated and seeded
- Ensure OpenAI API key is configured

---

**Backend Version**: 3.0 (3-Agent LangGraph System)
**Last Updated**: 2025-11-21
