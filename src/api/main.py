from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.api.routers import chat, tasks, notes, voice, vision, voice_ws, habits, forecast, briefing, gmail, auth, preferences, sessions, demo
from src.core.config import settings
import structlog
import time

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()


# Fix Bug #6: Use lifespan context manager instead of deprecated @app.on_event
@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    os.environ.setdefault("GOOGLE_API_KEY", settings.GEMINI_API_KEY)
    os.environ.setdefault("GEMINI_API_KEY", settings.GEMINI_API_KEY)

    _gcp_project = settings.GOOGLE_CLOUD_PROJECT or settings.GCP_PROJECT_ID
    if _gcp_project:
        from src.core.vertex_init import init_vertex
        init_vertex(project_id=_gcp_project, location=settings.GOOGLE_CLOUD_LOCATION)
        log.info("vertex_ai_enabled", project=_gcp_project)
    else:
        log.info("vertex_ai_skipped", reason="GOOGLE_CLOUD_PROJECT not set — using direct Gemini API")

    # Initialize database collections + indexes
    from src.core.db_init import initialize_database
    await initialize_database()

    # Start APScheduler (recurring tasks + briefings + Gmail pipeline)
    from src.core.scheduler import start_scheduler
    start_scheduler()

    # Start Telegram bot as background asyncio task (non-blocking)
    telegram_task = None
    try:
        from src.integrations.telegram_bot import bot_settings, run_bot
        if bot_settings.TELEGRAM_BOT_TOKEN:
            import asyncio
            telegram_task = asyncio.create_task(run_bot())
            log.info("telegram_bot_task_started")
        else:
            log.info("telegram_bot_skipped", reason="TELEGRAM_BOT_TOKEN not set")
    except Exception as exc:
        log.warning("telegram_bot_start_failed", error=str(exc))
    log.info("aiden_api_starting", version="2.0.0", env=settings.ENV)
    yield

    # Graceful shutdown
    from src.core.scheduler import stop_scheduler
    stop_scheduler()

    if telegram_task and not telegram_task.done():
        telegram_task.cancel()
        try:
            import asyncio
            await asyncio.wait_for(telegram_task, timeout=5)
        except Exception:
            pass
    log.info("aiden_api_shutting_down")


app = FastAPI(
    title="AIDEN v2.0 API",
    description="AI Intelligent Daily Executive Navigator - Multi-agent productivity system",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

# Fix Bug #2: allow_origins=["*"] with allow_credentials=True is rejected by browsers.
# Use explicit origins in production; fall back to localhost for development.
ALLOWED_ORIGINS = (
    [
        "http://localhost:8501", "http://127.0.0.1:8501",  # Streamlit UI
        "http://localhost:3000", "http://127.0.0.1:3000",  # HTML UI (python -m http.server)
        "http://localhost:5173", "http://127.0.0.1:5173",  # Vite dev server
        "http://0.0.0.0:3000",  "http://0.0.0.0:8501",    # 0.0.0.0 variants
        "null",                                               # file:// opened directly
    ]
    if settings.is_development
    else [o.strip() for o in getattr(settings, "ALLOWED_ORIGINS", "").split(",") if o.strip()]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests with timing"""
    start_time = time.time()

    response = await call_next(request)

    duration = time.time() - start_time

    log.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration * 1000, 2)
    )

    return response


# Exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    log.error("unhandled_exception", error=str(exc), path=request.url.path)

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "error": str(exc) if settings.DEBUG else "An error occurred"
        }
    )


# Include routers
app.include_router(chat.router)
app.include_router(tasks.router)
app.include_router(notes.router)
app.include_router(voice.router)
app.include_router(vision.router)
app.include_router(voice_ws.router)
app.include_router(habits.router)
app.include_router(forecast.router)
app.include_router(briefing.router)
app.include_router(gmail.router)
app.include_router(auth.router)
app.include_router(preferences.router)
app.include_router(sessions.router)
app.include_router(demo.router)


@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint for Docker and monitoring"""
    try:
        from src.integrations.telegram_bot import bot_settings as tg_settings
        tg_status = "enabled" if tg_settings.TELEGRAM_BOT_TOKEN else "disabled"
    except Exception:
        tg_status = "unavailable"

    from src.services.gmail_pipeline import _pipeline_registry
    return {
        "status": "ok",
        "version": "2.0.0",
        "environment": settings.ENV,
        "services": {
            "mongodb":       "configured" if settings.MONGO_URI else "missing",
            "chromadb":      f"persistent:{settings.CHROMA_PATH}",
            "mcp_calendar":  settings.CALENDAR_MCP_URL,
            "mcp_gmail":     settings.GMAIL_MCP_URL,
            "telegram_bot":  tg_status,
            "gmail_pipeline": f"{len(_pipeline_registry)} user(s) connected",
        },
    }


@app.get("/", tags=["System"])
async def root():
    """API root endpoint"""
    return {
        "name": "AIDEN v2.0 API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.is_development,
        workers=settings.API_WORKERS
    )
