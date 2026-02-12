"""
Configuration management for Learn Like Magic backend.

Centralizes all configuration using Pydantic settings with environment variable support.
"""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, PostgresDsn


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database Configuration
    database_url: PostgresDsn = Field(
        default="postgresql://llmuser:dev_password@localhost:5432/tutor",
        description="PostgreSQL connection URL"
    )
    db_pool_size: int = Field(
        default=5,
        description="Database connection pool size"
    )
    db_max_overflow: int = Field(
        default=10,
        description="Maximum overflow connections"
    )
    db_pool_timeout: int = Field(
        default=30,
        description="Connection pool timeout in seconds"
    )

    # API Configuration
    api_host: str = Field(
        default="0.0.0.0",
        description="API server host"
    )
    api_port: int = Field(
        default=8000,
        description="API server port"
    )

    # LLM Configuration
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key (required at runtime)"
    )
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API key (optional)"
    )
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key (optional, for Claude models)"
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model to use"
    )
    app_llm_provider: str = Field(
        default="openai",
        description="[DEPRECATED] Use tutor_llm_provider instead. Kept for backward compatibility."
    )
    tutor_llm_provider: str = Field(
        default="",
        description="LLM provider for tutor workflow: openai (gpt-5.2), anthropic (opus-4.6), or anthropic-haiku (haiku-4.5). Falls back to app_llm_provider if empty."
    )
    ingestion_llm_provider: str = Field(
        default="openai",
        description="LLM provider for book ingestion workflow: openai (gpt-4o-mini). Anthropic support coming soon."
    )

    # Application Settings
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )
    log_format: str = Field(
        default="json",
        description="Logging format: 'json' for structured, 'text' for human-readable"
    )
    environment: str = Field(
        default="development",
        description="Environment: development, staging, production"
    )

    # AWS Configuration (for book ingestion feature)
    aws_region: str = Field(
        default="us-east-1",
        description="AWS region for S3 bucket"
    )
    aws_s3_bucket: str = Field(
        default="learnlikemagic-books",
        description="S3 bucket name for book storage"
    )
    # AWS credentials are auto-detected from ~/.aws/credentials or environment

    @property
    def resolved_tutor_provider(self) -> str:
        """Resolve tutor provider: tutor_llm_provider takes precedence, falls back to app_llm_provider."""
        return self.tutor_llm_provider if self.tutor_llm_provider else self.app_llm_provider

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Get or create the global settings instance.

    Returns:
        Settings: Application settings
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings():
    """Reset the global settings instance (useful for testing)."""
    global _settings
    _settings = None


def validate_required_settings():
    """
    Validate that all required settings are present at runtime.

    Should be called after settings are loaded but before application starts.
    Raises ValueError if required settings are missing.
    """
    settings = get_settings()

    if not settings.openai_api_key or settings.openai_api_key == "":
        raise ValueError(
            "OPENAI_API_KEY environment variable is required but not set. "
            "Please ensure the secret is properly configured in App Runner or your environment."
        )

    if not settings.database_url:
        raise ValueError("DATABASE_URL is required but not set")

    return True
