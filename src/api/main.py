"""
AIDEN v2.0 FastAPI Application
Main API server with all routers and middleware
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.api.routers import chat, tasks, notes, voice, vision, voice_ws
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
    log.info("aiden_api_starting", version="2.0.0", env=settings.ENV)
    yield
    log.info("aiden_api_shutting_down")


# Create FastAPI app
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
    ["http://localhost:8501", "http://127.0.0.1:8501"]
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


# Request logging middleware
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
app.include_router(voice_ws.router)  # WebSocket for real-time voice


# Health check endpoint
@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint for Docker and monitoring"""
    return {
        "status": "ok",
        "version": "2.0.0",
        "environment": settings.ENV,
        "services": {
            # Fix Bug #9: Never expose raw connection URIs – they may contain credentials.
            "mongodb": "configured" if settings.MONGO_URI else "missing",
            "chromadb": settings.chroma_url,
            "mcp_calendar": settings.CALENDAR_MCP_URL
        }
    }


# Root endpoint
@app.get("/", tags=["System"])
async def root():
    """API root endpoint"""
    return {
        "name": "AIDEN v2.0 API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# Run with uvicorn
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.is_development,
        workers=settings.API_WORKERS
    )
