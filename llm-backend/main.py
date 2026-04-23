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
from shared.api import health
from shared.api import llm_config_routes
from shared.api import feature_flag_routes
from shared.api import issue_routes
from tutor.api import curriculum, practice, sessions, transcription, tts
from autoresearch.tutor_teaching_quality.evaluation.api import router as evaluation_router
from auth.api.auth_routes import router as auth_router
from auth.api.profile_routes import router as profile_router
from auth.api.enrichment_routes import router as enrichment_router
from api.docs import router as docs_router
from api.test_scenarios import router as test_scenarios_router
from api.pixi_poc import router as pixi_poc_router
from book_ingestion_v2.api import book_routes as v2_book_routes
from book_ingestion_v2.api import toc_routes as v2_toc_routes
from book_ingestion_v2.api import page_routes as v2_page_routes
from book_ingestion_v2.api import processing_routes as v2_processing_routes
from book_ingestion_v2.api import sync_routes as v2_sync_routes
from book_ingestion_v2.api import visual_preview_routes as v2_visual_preview_routes

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
app.include_router(practice.router)         # Practice v2: /practice/*
app.include_router(transcription.router)  # Audio-to-text via Whisper
app.include_router(tts.router)              # Text-to-speech via Google Cloud TTS
app.include_router(evaluation_router)  # Evaluation pipeline endpoints
app.include_router(auth_router)              # Auth: POST /auth/sync
app.include_router(profile_router)           # Profile: GET/PUT /profile
app.include_router(enrichment_router)       # Enrichment: GET/PUT /profile/enrichment, /profile/personality
app.include_router(docs_router)              # Docs: GET /api/docs
app.include_router(llm_config_routes.router) # LLM config: GET/PUT /api/admin/llm-config
app.include_router(feature_flag_routes.router)  # Feature flags: GET/PUT /api/admin/feature-flags
app.include_router(test_scenarios_router)    # Test scenarios: GET /api/test-scenarios
app.include_router(v2_book_routes.router)   # Book Ingestion V2: /admin/v2/books
app.include_router(v2_toc_routes.router)    # Book Ingestion V2: /admin/v2/books/{id}/toc
app.include_router(v2_page_routes.router)   # Book Ingestion V2: /admin/v2/books/{id}/chapters/{id}/pages
app.include_router(v2_processing_routes.router)  # Book Ingestion V2: processing, topics, jobs
app.include_router(v2_sync_routes.router)        # Book Ingestion V2: sync + results
app.include_router(v2_visual_preview_routes.router)  # Book Ingestion V2: visual preview store
app.include_router(pixi_poc_router)              # Pixi.js PoC: code generation
app.include_router(issue_routes.router)          # Issue reporting: /issues/*


@app.on_event("startup")
async def startup_event():
    """Validate database connection on startup."""
    logger = logging.getLogger(__name__)
    logger.info("Starting LearnLikeMagic LLM Backend")

    db_manager = get_db_manager()
    is_healthy = db_manager.health_check()

    if not is_healthy:
        logger.warning("Database health check failed on startup")
    else:
        logger.info("Database connection healthy")

    logger.info("Application started successfully")


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True
    )
