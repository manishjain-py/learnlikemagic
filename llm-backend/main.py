"""
LearnLikeMagic LLM Backend - FastAPI Application

This is the main entry point for the adaptive tutoring API.
All business logic has been extracted to services, repositories, and utilities
for better modularity and testability.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings, validate_required_settings
from database import get_db_manager
from book_ingestion.api import routes as admin_routes
from study_plans.api import admin as admin_guidelines
from shared.api import health
from shared.api import llm_config_routes
from tutor.api import curriculum, sessions, transcription, tts
from evaluation.api import router as evaluation_router
from auth.api.auth_routes import router as auth_router
from auth.api.profile_routes import router as profile_router
from api.docs import router as docs_router
from api.test_scenarios import router as test_scenarios_router

# Validate configuration on startup
validate_required_settings()

# Configure logging
import logging
import sys
import json
from datetime import datetime

settings = get_settings()

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
            if isinstance(msg_data, dict):
                log_entry.update(msg_data)
            else:
                log_entry["message"] = msg
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
        handlers=[handler],
        force=True  # Ensure we override any existing config
    )
else:
    # Keep existing text format for development
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True
    )

# Initialize FastAPI app
app = FastAPI(
    title="LearnLikeMagic LLM Backend",
    description="AI-powered adaptive tutoring API with single master tutor architecture",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(curriculum.router)
app.include_router(sessions.router)
app.include_router(transcription.router)  # Audio-to-text via Whisper
app.include_router(tts.router)              # Text-to-speech via OpenAI TTS
app.include_router(evaluation_router)  # Evaluation pipeline endpoints
app.include_router(admin_routes.router)  # Book ingestion admin routes
app.include_router(admin_guidelines.router)  # Phase 6 guidelines admin UI
app.include_router(auth_router)              # Auth: POST /auth/sync
app.include_router(profile_router)           # Profile: GET/PUT /profile
app.include_router(docs_router)              # Docs: GET /api/docs
app.include_router(llm_config_routes.router) # LLM config: GET/PUT /api/admin/llm-config
app.include_router(test_scenarios_router)    # Test scenarios: GET /api/test-scenarios


@app.on_event("startup")
async def startup_event():
    """Validate database connection on startup."""
    print("🚀 Starting LearnLikeMagic LLM Backend...")

    db_manager = get_db_manager()
    is_healthy = db_manager.health_check()

    if not is_healthy:
        print("⚠️  WARNING: Database health check failed on startup")
    else:
        print("✅ Database connection healthy")

    print("✅ Application started successfully")


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True
    )
