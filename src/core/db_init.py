"""
AIDEN v2.0 — Database Initialization
Defines all MongoDB collections with their schemas and indexes.
Called once at application startup via the lifespan hook.
"""
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, TEXT
from src.core.config import settings
import structlog

log = structlog.get_logger()


COLL_SESSIONS      = "adk_sessions"
COLL_USERS         = "users"
COLL_RECURRING     = "recurring_tasks"          # recurring task templates
COLL_GMAIL_PROC    = "gmail_processed"            # idempotency log for Gmail pipeline
COLL_JWT_TOKENS    = "jwt_tokens"                 # active JWT tokens with TTL
# Per-user task/note collections follow: {user_id}__tasks, {user_id}__notes


TASK_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["task_id", "user_id", "title", "status", "priority"],
        "properties": {
            "task_id":          {"bsonType": "string"},
            "user_id":          {"bsonType": "string"},
            "title":            {"bsonType": "string", "minLength": 1},
            "description":      {"bsonType": ["string", "null"]},
            "priority":         {"bsonType": "string", "enum": ["P0","P1","P2","P3"]},
            "status":           {"bsonType": "string", "enum": ["todo","in_progress","completed","cancelled"]},
            "due_date":         {"bsonType": ["date", "null"]},
            "tags":             {"bsonType": "array",  "items": {"bsonType": "string"}},
            "linked_event_id":  {"bsonType": ["string", "null"]},
            "recurring_id":     {"bsonType": ["string", "null"]},   # links to recurring_tasks
            "created_at":       {"bsonType": "date"},
            "updated_at":       {"bsonType": "date"},
        }
    }
}

NOTE_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["note_id", "user_id", "title", "content"],
        "properties": {
            "note_id":    {"bsonType": "string"},
            "user_id":    {"bsonType": "string"},
            "title":      {"bsonType": "string", "minLength": 1},
            "content":    {"bsonType": "string"},
            "tags":       {"bsonType": "array",  "items": {"bsonType": "string"}},
            "project":    {"bsonType": ["string", "null"]},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        }
    }
}

RECURRING_TASK_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["recurring_id", "user_id", "title", "frequency"],
        "properties": {
            "recurring_id":  {"bsonType": "string"},
            "user_id":       {"bsonType": "string"},
            "title":         {"bsonType": "string"},
            "description":   {"bsonType": ["string", "null"]},
            "priority":      {"bsonType": "string", "enum": ["P0","P1","P2","P3"]},
            "tags":          {"bsonType": "array", "items": {"bsonType": "string"}},
            "frequency":     {"bsonType": "string",
                              "enum": ["daily","weekly","monthly","weekdays","weekends"]},
            "interval":      {"bsonType": "int"},          # every N days/weeks/months
            "days_of_week":  {"bsonType": ["array", "null"]},  # [0=Mon..6=Sun]
            "time_of_day":   {"bsonType": ["string", "null"]}, # "HH:MM"
            "start_date":    {"bsonType": "date"},
            "end_date":      {"bsonType": ["date", "null"]},
            "is_active":     {"bsonType": "bool"},
            "last_created":       {"bsonType": ["date", "null"]},
            "created_at":         {"bsonType": "date"},
            # Streak / habit tracking
            "current_streak":     {"bsonType": "int"},
            "longest_streak":     {"bsonType": "int"},
            "total_completions":  {"bsonType": "int"},
            "last_completed_date": {"bsonType": ["string", "null"]},
            "completion_history": {"bsonType": "array",
                                   "items": {"bsonType": "string"}},
        }
    }
}

USER_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        # email and hashed_password are always required (mandatory registration)
        "required": ["user_id", "name", "email", "hashed_password"],
        "properties": {
            "user_id":           {"bsonType": "string"},
            "name":              {"bsonType": "string"},
            "email":             {"bsonType": "string"},
            "hashed_password":   {"bsonType": "string"},
            # Telegram identity — None until user registers via bot
            "telegram_chat_id":  {"bsonType": ["long", "int", "null"]},
            "telegram_username": {"bsonType": ["string", "null"]},
            "role":              {"bsonType": "string",
                                  "enum": ["executive","user","developer","guest"]},
            "api_keys":          {"bsonType": "array"},
            "webhook_url":       {"bsonType": ["string", "null"]},
            "briefing_time":     {"bsonType": "string"},
            "is_active":         {"bsonType": "bool"},
            "created_at":        {"bsonType": "date"},
            "updated_at":        {"bsonType": "date"},
        }
    }
}

JWT_TOKEN_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["user_id", "token", "expires_at", "created_at"],
        "properties": {
            "user_id":    {"bsonType": "string"},
            "token":      {"bsonType": "string"},
            "expires_at": {"bsonType": "date"},
            "created_at": {"bsonType": "date"},
            "revoked":    {"bsonType": "bool"},
        }
    }
}

SESSION_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["session_id", "app_name", "user_id"],
        "properties": {
            "session_id":       {"bsonType": "string"},
            "app_name":         {"bsonType": "string"},
            "user_id":          {"bsonType": "string"},
            "state":            {"bsonType": "object"},
            "events":           {"bsonType": "array"},
            "last_update_time": {"bsonType": "double"},
        }
    }
}



GMAIL_PROCESSED_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["user_id", "email_id"],
        "properties": {
            "user_id":      {"bsonType": "string"},
            "email_id":     {"bsonType": "string"},
            "subject":      {"bsonType": ["string", "null"]},
            "processed_at": {"bsonType": "date"},
        }
    }
}

async def _ensure_collection(db, name: str, schema: dict | None = None):
    """Create collection if it doesn't exist, applying schema validator."""
    existing = await db.list_collection_names()
    if name not in existing:
        kwargs = {}
        if schema:
            kwargs["validator"] = schema
            kwargs["validationAction"] = "warn"   # warn (not error) so we don't break on partial docs
        await db.create_collection(name, **kwargs)
        log.info("collection_created", collection=name)
    else:
        # Update validator on existing collection (no-op if unchanged)
        if schema:
            try:
                await db.command("collMod", name, validator=schema, validationAction="warn")
            except Exception as e:
                log.warning("validator_update_failed", collection=name, error=str(e))


async def _safe_create_index(collection, keys: list, **kwargs):
    """
    create_index wrapper that survives index-migration conflicts:
      85 IndexOptionsConflict  — same key exists under a different name → drop & recreate
      86 IndexKeySpecsConflict — same name exists with different options → drop & recreate
    Any other error is re-raised immediately.
    """
    try:
        await collection.create_index(keys, **kwargs)
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code not in (85, 86):
            raise
        target_name = kwargs.get("name")
        key_set = {k for k, _ in keys}
        log.warning(
            "index_conflict_auto_fix",
            collection=collection.name,
            code=code,
            target=target_name,
            reason=str(exc),
        )
        info = await collection.index_information()
        for idx_name, idx_info in info.items():
            if idx_name == "_id_":
                continue
            idx_keys = {k for k, _ in idx_info.get("key", [])}
            if idx_keys == key_set or idx_name == target_name:
                try:
                    await collection.drop_index(idx_name)
                    log.info("stale_index_dropped", collection=collection.name, index=idx_name)
                except Exception:
                    pass
        await collection.create_index(keys, **kwargs)
        log.info("index_created_after_fix", collection=collection.name, name=target_name)


async def _ensure_global_indexes(db):
    """Create indexes on global (non-per-user) collections."""

    sessions = db[COLL_SESSIONS]
    await _safe_create_index(
        sessions,
        [("session_id", ASCENDING), ("app_name", ASCENDING), ("user_id", ASCENDING)],
        unique=True, background=True, name="idx_session_lookup",
    )
    await _safe_create_index(
        sessions,
        [("user_id", ASCENDING), ("last_update_time", DESCENDING)],
        background=True, name="idx_session_user_time",
    )

    users = db[COLL_USERS]
    await _safe_create_index(
        users,
        [("user_id", ASCENDING)],
        unique=True, background=True, name="idx_users_user_id",
    )
    # email is required for all users — non-sparse unique index is correct here
    await _safe_create_index(
        users,
        [("email", ASCENDING)],
        unique=True, background=True, name="idx_users_email",
    )
    # telegram_chat_id — sparse so non-Telegram users (null) don't conflict
    await _safe_create_index(
        users,
        [("telegram_chat_id", ASCENDING)],
        unique=True, sparse=True, background=True, name="idx_users_telegram_chat_id",
    )


    recurring = db[COLL_RECURRING]
    await _safe_create_index(
        recurring,
        [("recurring_id", ASCENDING)],
        unique=True, background=True, name="idx_recurring_id",
    )
    await _safe_create_index(
        recurring,
        [("user_id", ASCENDING), ("is_active", ASCENDING)],
        background=True, name="idx_recurring_user_active",
    )
    await _safe_create_index(
        recurring,
        [("last_created", ASCENDING)],
        background=True, name="idx_recurring_last_created",
    )

    gmail_proc = db[COLL_GMAIL_PROC]
    await _safe_create_index(
        gmail_proc,
        [("user_id", ASCENDING), ("email_id", ASCENDING)],
        unique=True, background=True, name="idx_gmail_processed",
    )
    await _safe_create_index(
        gmail_proc,
        [("processed_at", DESCENDING)],
        background=True, name="idx_gmail_processed_at",
    )

    jwt_tokens = db[COLL_JWT_TOKENS]
    await _safe_create_index(
        jwt_tokens,
        [("user_id", ASCENDING)],
        background=True, name="idx_jwt_user_id",
    )
    await _safe_create_index(
        jwt_tokens,
        [("token", ASCENDING)],
        unique=True, background=True, name="idx_jwt_token",
    )
    # TTL index: MongoDB auto-removes documents after expires_at
    await _safe_create_index(
        jwt_tokens,
        [("expires_at", ASCENDING)],
        expireAfterSeconds=0, background=True, name="idx_jwt_ttl",
    )

    log.info("global_indexes_ensured")

async def initialize_database():
    """
    Entry point called from lifespan.
    Creates global collections + indexes.
    Per-user collections are created lazily on first write (see task_repo / notes_repo).
    """
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB]

    log.info("db_initialization_start", db=settings.MONGO_DB)

    await _ensure_collection(db, COLL_SESSIONS, SESSION_SCHEMA)
    await _ensure_collection(db, COLL_USERS,    USER_SCHEMA)
    await _ensure_collection(db, COLL_RECURRING, RECURRING_TASK_SCHEMA)
    await _ensure_collection(db, COLL_GMAIL_PROC, GMAIL_PROCESSED_SCHEMA)
    await _ensure_collection(db, COLL_JWT_TOKENS, JWT_TOKEN_SCHEMA)

    await _ensure_global_indexes(db)

    client.close()
    log.info("db_initialization_complete")