"""
FastAPI middleware for JWT authentication and authorization
Per-user data isolation helpers
"""
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from src.core.config import settings
from src.models.user import UserClaims, UserRole
from typing import Optional
import structlog

log = structlog.get_logger()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token security
security = HTTPBearer()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str, role: UserRole, email: Optional[str] = None) -> tuple[str, int]:
    """Create JWT access token"""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)

    payload = {
        "sub": user_id,
        "role": role.value,
        "email": email,
        "exp": expire,
        "iat": now
    }

    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    log.info("token_created", user_id=user_id, expires_in=settings.JWT_EXPIRE_MINUTES)

    return token, settings.JWT_EXPIRE_MINUTES * 60  # Return token and seconds until expiry


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> UserClaims:
    """Dependency to extract and validate JWT token"""
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )

        user_id = payload.get("sub")
        role = payload.get("role", "user")
        email = payload.get("email")

        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token: missing user_id")

        return UserClaims(
            user_id=user_id,
            role=UserRole(role),
            email=email
        )

    except JWTError as e:
        log.warning("jwt_validation_failed", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_active_user(current_user: UserClaims = Depends(get_current_user)) -> UserClaims:
    """Dependency to get current active user (can add additional checks here)"""
    return current_user


def require_role(*allowed_roles: UserRole):
    """Decorator factory for role-based access control"""
    async def role_checker(current_user: UserClaims = Depends(get_current_user)) -> UserClaims:
        if current_user.role not in allowed_roles:
            log.warning("access_denied", user_id=current_user.user_id, role=current_user.role, required=allowed_roles)
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required roles: {[r.value for r in allowed_roles]}"
            )
        return current_user
    return role_checker


# === Per-User Data Isolation Helpers ===

def get_user_collection(user_id: str, collection: str) -> str:
    """Get namespaced collection name for user"""
    return f"{user_id}__{collection}"


def get_user_chroma_collection(user_id: str) -> str:
    """Get namespaced ChromaDB collection for user"""
    return f"notes_{user_id}"


# === Optional: API Key Authentication (for developers) ===

async def get_user_from_api_key(api_key: str) -> Optional[UserClaims]:
    """Validate API key and return user claims (implement in P3+)"""
    # TODO: Implement API key validation against database
    # For now, this is a placeholder
    return None
