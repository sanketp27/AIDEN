"""
AIDEN v3.0 — Settings
Merged from final project + MCP integration layer.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal, Optional


class Settings(BaseSettings):

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
    CHROMA_PATH: str = "./data/chroma"

    # === JWT Authentication ===
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # === Google Cloud / Vertex AI ===
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None
    GCP_PROJECT_ID:        Optional[str] = None
    GOOGLE_CLOUD_PROJECT:  Optional[str] = None
    GOOGLE_CLOUD_LOCATION: str           = "us-central1"

    # === Gmail OAuth ===
    GMAIL_CLIENT_ID:     str = ""
    GMAIL_CLIENT_SECRET: str = ""
    GMAIL_POLL_INTERVAL_MINUTES: int = 15
    GMAIL_MAX_EMAILS_PER_RUN:    int = 30
    GMAIL_MARK_READ_AFTER_TASK:  bool = True

    # === Telegram Bot ===
    TELEGRAM_BOT_TOKEN:    str = ""
    TELEGRAM_BOT_USERNAME: str = ""
    BOT_SERVICE_SECRET:    str = ""
    AIDEN_API_URL:         str = "http://localhost:8000"
    AIDEN_UI_URL:          str = "http://localhost:3000"

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
    ORCHESTRATOR_MODEL:   str = "gemini-2.5-pro"
    TASK_AGENT_MODEL:     str = "gemini-2.5-flash"
    CALENDAR_AGENT_MODEL: str = "gemini-2.5-flash"
    NOTES_AGENT_MODEL:    str = "gemini-2.5-flash"
    VOICE_AGENT_MODEL:    str = "gemini-2.5-flash"           # STT — audio understanding
    VOICE_TTS_MODEL:      str = "gemini-2.5-flash-preview-tts"  # TTS — audio generation
    VOICE_LIVE_MODEL:     str = "gemini-3.1-flash-live-preview"  # WebSocket real-time
    VISION_MODEL:         str = "gemini-2.5-flash"
    DEFAULT_MODEL:        str = "gemini-2.5-flash"

    # === Limits ===
    MAX_IMAGE_SIZE_MB:       int = 20
    MAX_IMAGES_PER_REQUEST:  int = 5
    MAX_MESSAGE_LENGTH:      int = 10000
    MAX_TASKS_PER_USER:      int = 1000
    MAX_NOTES_PER_USER:      int = 5000
    SESSION_CACHE_TTL:       int = 60
    QUERY_CACHE_TTL:         int = 30
    MAX_CONCURRENT_AGENTS:   int = 5

    WORKSPACE_MCP_PORT: int = 8001
    MONGO_MCP_PORT:     int = 8002
    NOTION_MCP_PORT:    int = 8003
    GITHUB_MCP_PORT:    int = 8004

    WORKSPACE_MCP_ENABLED: bool = True
    MONGO_MCP_ENABLED:     bool = True
    NOTION_MCP_ENABLED:    bool = True
    GITHUB_MCP_ENABLED:    bool = True

    # ── External service tokens (v3.0) ─────────────────────────────────────
    NOTION_TOKEN: Optional[str] = None   # Notion Integration Token
    GITHUB_TOKEN: Optional[str] = None   # GitHub PAT (dev users fallback)

    # ── Legacy MCP URLs (kept for backward compat) ────────────────────────
    CALENDAR_MCP_URL: str = "http://localhost:8001/mcp"   # now workspace-mcp
    GMAIL_MCP_URL:    str = "http://localhost:8001/mcp"   # now workspace-mcp

    @property
    def mongodb_url(self) -> str:
        return f"{self.MONGO_URI}/{self.MONGO_DB}"

    @property
    def chroma_path_str(self) -> str:
        return self.CHROMA_PATH

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.ENV == "development"


settings = Settings()
