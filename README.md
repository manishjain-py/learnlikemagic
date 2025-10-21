# Learn Like Magic 🪄

An AI-powered adaptive tutoring system that personalizes learning experiences for students using structured teaching guidelines and real-time assessment.

## Overview

Learn Like Magic is an intelligent tutoring platform that:
- **Adapts to Each Student**: Dynamically adjusts difficulty and teaching approach based on performance
- **Follows Pedagogical Guidelines**: Uses expert-authored teaching guidelines for consistent, high-quality instruction
- **Provides Real-time Feedback**: Grades responses instantly and identifies misconceptions
- **Tracks Mastery Progress**: Measures understanding over time using exponential moving averages
- **Supports Multiple Curricula**: Organized by country, board, grade, subject, topic, and subtopic

## Architecture

```
learnlikemagic/
├── llm-backend/          # FastAPI + LangGraph agent
├── llm-frontend/         # React + TypeScript UI
└── docker-compose.yml    # Multi-container setup
```

### Technology Stack

**Backend:**
- FastAPI (REST API)
- LangGraph (Agent orchestration)
- OpenAI GPT-4o-mini (LLM)
- SQLite + FTS5 (Database + Full-text search)
- SQLAlchemy (ORM)

**Frontend:**
- React 18
- TypeScript
- Vite (Build tool)

## Quick Start

### Prerequisites
- Python 3.9+
- Node.js 18+
- OpenAI API key

### Option 1: Manual Setup

#### Backend
```bash
cd llm-backend

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# Initialize database
python db.py --migrate
python db.py --seed-guidelines data/seed_guidelines.json

# Start server
uvicorn main:app --reload
```

Backend runs at http://localhost:8000
API docs at http://localhost:8000/docs

#### Frontend
```bash
cd llm-frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

Frontend runs at http://localhost:3000

### Option 2: Docker Compose

```bash
# From project root
docker-compose up --build
```

- Backend: http://localhost:8000
- Frontend: http://localhost:3000

## How It Works

### 1. Curriculum Selection
Students browse and select learning content:
- **Country**: India, USA, etc.
- **Board**: CBSE, ICSE, State boards
- **Grade**: 1-12
- **Subject**: Mathematics, English, etc.
- **Topic**: Fractions, Grammar, etc.
- **Subtopic**: Specific learning unit

### 2. Adaptive Learning Session
Once a subtopic is selected:
1. System fetches the teaching guideline
2. LLM generates personalized teaching content following the guideline
3. Student answers questions
4. System grades responses and identifies misconceptions
5. **If correct (score ≥ 0.8)**: Advance to next step
6. **If struggling (score < 0.8)**: Provide remediation with scaffolding
7. Mastery score updates continuously
8. Session ends after 10 steps or 85% mastery

### 3. Teaching Guidelines
Each subtopic has a structured guideline containing:
- **Teaching Approach**: Concrete → Conceptual → Abstract
- **Depth Level**: Basic, Intermediate, or Advanced
- **Common Misconceptions**: What to watch for
- **Scaffolding Strategies**: How to help struggling students
- **Assessment Criteria**: Mastery rubric

### 4. LangGraph Agent Flow
```
Start → Present → Check → (Advance | Remediate) → Diagnose → Present → ...
```

- **Present**: Generate teaching turn using guideline
- **Check**: Grade student response
- **Advance**: Move to next step (if correct)
- **Remediate**: Provide scaffolding (if struggling)
- **Diagnose**: Update mastery score

## Current Curriculum

**Grade 3, CBSE, India** (4 subtopics):

**Mathematics**
- Fractions → Comparing Like Denominators
- Fractions → Adding Like Denominators
- Multiplication → Times Tables 2-5

**English**
- Grammar → Nouns and Pronouns

## API Endpoints

### Curriculum Discovery
```http
GET /curriculum?country=India&board=CBSE&grade=3
→ Returns subjects

GET /curriculum?country=India&board=CBSE&grade=3&subject=Mathematics
→ Returns topics

GET /curriculum?...&subject=Mathematics&topic=Fractions
→ Returns subtopics with guideline IDs
```

### Learning Sessions
```http
POST /sessions
→ Create new session with guideline_id

POST /sessions/{id}/step
→ Submit student answer, get next turn

GET /sessions/{id}/summary
→ Get session completion summary
```

## Project Structure

```
learnlikemagic/
├── llm-backend/
│   ├── graph/                    # LangGraph agent nodes
│   ├── data/                     # Seed data (guidelines)
│   ├── main.py                   # FastAPI app
│   ├── models.py                 # Data models
│   ├── db.py                     # Database utilities
│   ├── guideline_repository.py   # Guideline data access
│   ├── llm.py                    # OpenAI integration
│   ├── requirements.txt
│   └── README.md
├── llm-frontend/
│   ├── src/
│   │   ├── App.tsx              # Main component
│   │   ├── api.ts               # API client
│   │   └── App.css              # Styles
│   ├── package.json
│   └── README.md
├── .claude/                      # Claude Code configuration
├── docker-compose.yml
└── README.md (this file)
```

## Adding New Content

To add a new subtopic:

1. **Create teaching guideline** in `llm-backend/data/seed_guidelines.json`:
```json
{
  "id": "g5",
  "country": "India",
  "board": "CBSE",
  "grade": 3,
  "subject": "Mathematics",
  "topic": "Addition",
  "subtopic": "3-digit Addition",
  "guideline": "Detailed teaching instructions...",
  "metadata": { ... }
}
```

2. **Seed the database**:
```bash
cd llm-backend
python db.py --seed-guidelines data/seed_guidelines.json
```

3. **Restart the backend** - new subtopic appears automatically!

## Development

### Backend Development
```bash
cd llm-backend
source .venv/bin/activate

# Run with auto-reload
uvicorn main:app --reload

# View logs
tail -f logs/app.log  # If logging configured

# Run migrations
python db.py --migrate

# Seed data
python db.py --seed-guidelines data/seed_guidelines.json
```

### Frontend Development
```bash
cd llm-frontend

# Run dev server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## Configuration

### Backend (.env)
```bash
# Required
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini

# Optional
DATABASE_URL=sqlite:///./tutor.db
API_HOST=0.0.0.0
API_PORT=8000
```

### Frontend
```bash
# Optional
VITE_API_URL=http://localhost:8000
```

## Features

✅ Multi-curriculum support (country/board/grade structure)
✅ Structured teaching guidelines
✅ Dynamic content generation by AI
✅ Real-time assessment and grading
✅ Adaptive difficulty adjustment
✅ Misconception identification
✅ Personalized remediation
✅ Mastery tracking (EMA-based)
✅ Session state persistence
✅ Curriculum discovery API
✅ Interactive chat-based UI
✅ Progress visualization

## Future Enhancements

- Expand curriculum to 50+ subtopics
- Multi-grade support (1-12)
- Voice interface for younger learners
- Gamification (badges, streaks)
- Parent/teacher dashboard
- Analytics and reporting
- Spaced repetition
- Mobile apps

## Contributing

This is currently a proof-of-concept. For contributions:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues or questions:
- Check the README in llm-backend/ and llm-frontend/
- Review API docs at http://localhost:8000/docs
- Open an issue on GitHub

---

**Learn Like Magic** - Personalized AI Tutoring for Every Student 🎓✨
