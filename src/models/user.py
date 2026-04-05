"""
User and authentication models for AIDEN v2.0
"""
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid


class UserRole(str, Enum):
    """User roles with different access levels"""
    EXECUTIVE = "executive"  # C-suite, senior managers
    USER = "user"           # Standard knowledge workers
    DEVELOPER = "developer"  # API/webhook access
    GUEST = "guest"         # Read-only evaluator / demo access


class UserClaims(BaseModel):
    """JWT token payload"""
    user_id: str
    role: UserRole
    email: Optional[EmailStr] = None
    name: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user123",
                "role": "user",
                "email": "john@example.com",
                "name": "John Doe"
            }
        }


class User(BaseModel):
    """Full user record"""
    user_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: EmailStr
    name: str
    hashed_password: str
    role: UserRole = UserRole.USER
    api_keys: list[str] = Field(default_factory=list)
    webhook_url: Optional[str] = None
    briefing_time: str = "08:00"  # Morning briefing time (HH:MM)
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user123",
                "email": "john@example.com",
                "name": "John Doe",
                "role": "user",
                "briefing_time": "08:00",
                "is_active": True
            }
        }


class UserCreate(BaseModel):
    """Model for creating a new user"""
    email: EmailStr
    name: str
    password: str
    role: UserRole = UserRole.USER


class UserLogin(BaseModel):
    """Model for user login"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    role: str


class APIKeyCreate(BaseModel):
    """Model for creating API key"""
    description: Optional[str] = None


class APIKeyResponse(BaseModel):
    """API key creation response"""
    key: str
    description: Optional[str] = None
    created_at: str