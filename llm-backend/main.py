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
from api.routes import health, curriculum, sessions

# Validate configuration on startup
validate_required_settings()

# Initialize FastAPI app
app = FastAPI(
    title="LearnLikeMagic LLM Backend",
    description="AI-powered adaptive tutoring API with LangGraph orchestration",
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
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True
    )
