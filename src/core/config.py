"""
AIDEN v2.0 Configuration
Environment-based settings using Pydantic Settings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal, Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False
    )

    # === Gemini API ===
    GEMINI_API_KEY: str

    # === MongoDB ===
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "aiden"

    # === ChromaDB ===
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8001

    # === JWT Authentication ===
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 hours

    # === MCP Servers ===
    CALENDAR_MCP_URL: str = "http://localhost:3000/sse"
    GMAIL_MCP_URL: str = "https://gmail.mcp.claude.com/mcp"

    # === Google Cloud (placeholder for P3+) ===
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    GCP_PROJECT_ID: Optional[str] = None

    # === Environment ===
    ENV: Literal["development", "production", "test"] = "development"
    DEBUG: bool = True

    # === API Server ===
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_WORKERS: int = 1

    # === Streamlit UI ===
    UI_PORT: int = 8501

    # === Model Configuration ===
    DEFAULT_MODEL: str = "gemini-2.0-flash"
    ORCHESTRATOR_MODEL: str = "gemini-2.0-pro"
    VISION_MODEL: str = "gemini-2.0-flash"

    # === Performance ===
    SESSION_CACHE_TTL: int = 60  # seconds
    QUERY_CACHE_TTL: int = 30    # seconds
    MAX_CONCURRENT_AGENTS: int = 5

    # === Limits ===
    MAX_IMAGE_SIZE_MB: int = 20
    MAX_IMAGES_PER_REQUEST: int = 5
    MAX_MESSAGE_LENGTH: int = 10000
    MAX_TASKS_PER_USER: int = 1000
    MAX_NOTES_PER_USER: int = 5000

    @property
    def mongodb_url(self) -> str:
        """Full MongoDB connection URL"""
        return f"{self.MONGO_URI}/{self.MONGO_DB}"

    @property
    def chroma_url(self) -> str:
        """ChromaDB HTTP URL"""
        return f"http://{self.CHROMA_HOST}:{self.CHROMA_PORT}"

    @property
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.ENV == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development"""
        return self.ENV == "development"


# Singleton settings instance
settings = Settings()
