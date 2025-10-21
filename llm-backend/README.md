# Learn Like Magic - Backend

FastAPI backend with LangGraph agent for adaptive tutoring.

## Architecture

```
llm-backend/
├── graph/                         # LangGraph agent
│   ├── state.py                  # State definitions & prompts
│   ├── nodes.py                  # Node implementations
│   └── build_graph.py            # Graph compilation
├── data/
│   └── seed_guidelines.json      # Teaching guidelines
├── main.py                        # FastAPI application
├── models.py                      # Pydantic & SQLAlchemy models
├── db.py                          # Database utilities & CLI
├── guideline_repository.py        # Repository pattern for guidelines
├── llm.py                         # OpenAI LLM abstraction
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Container image
├── .env                          # Environment configuration
└── .env.example                  # Example configuration
```

## Setup

### 1. Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your OpenAI API key:
```bash
OPENAI_API_KEY=sk-your-key-here
LLM_MODEL=gpt-4o-mini
DATABASE_URL=sqlite:///./tutor.db
```

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

## LangGraph Agent

### Nodes

1. **Present**: Generate teaching turn based on guideline
2. **Check**: Grade student response
3. **Diagnose**: Update evidence and mastery score
4. **Remediate**: Provide scaffolding for struggling students
5. **Advance**: Move to next step

### Flow

```
Start → Present → Check
                    ├─> Advance → Present (if score ≥ 0.8)
                    └─> Remediate → Diagnose → Present (if score < 0.8)
```

### Routing Logic

- **After Check**:
  - If score ≥ 0.8 AND confidence ≥ 0.6 → Advance
  - Otherwise → Remediate

- **After Advance**:
  - If step_idx ≥ 10 OR mastery ≥ 0.85 → End
  - Otherwise → Present

- **After Remediate**:
  - Always → Diagnose → Present

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

### Testing

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

- **fastapi**: Web framework
- **uvicorn**: ASGI server
- **langgraph**: Agent orchestration
- **langchain-core**: LangChain utilities
- **openai**: OpenAI API client
- **sqlalchemy**: ORM
- **aiosqlite**: Async SQLite
- **pydantic**: Data validation
- **python-dotenv**: Environment configuration

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
source .venv/bin/activate
pip install -r requirements.txt
```

## Support

For issues specific to the backend:
- Check logs in terminal
- Review API docs at http://localhost:8000/docs
- Verify database has been migrated and seeded
- Ensure OpenAI API key is configured

---

**Backend Version**: 2.0
**Last Updated**: 2025-10-21
