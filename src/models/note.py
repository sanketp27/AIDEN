"""
Note data models for AIDEN v2.0
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
import uuid


class Note(BaseModel):
    """Note model with full fields"""
    note_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    project: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_schema_extra = {
            "example": {
                "note_id": "660e8400-e29b-41d4-a716-446655440000",
                "user_id": "user123",
                "title": "AIDEN Implementation Notes",
                "content": "Key points from the architecture review...",
                "tags": ["technical", "architecture"],
                "project": "AIDEN_v2"
            }
        }


class NoteCreate(BaseModel):
    """Model for creating a new note"""
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    project: Optional[str] = None


class NoteUpdate(BaseModel):
    """Model for updating a note"""
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    project: Optional[str] = None


class NoteFilter(BaseModel):
    """Model for filtering notes"""
    tags: Optional[list[str]] = None
    project: Optional[str] = None
    search_query: Optional[str] = None  # For semantic search
    limit: int = 50
    offset: int = 0


class NoteSearchResult(BaseModel):
    """Result from semantic search"""
    note: Note
    similarity_score: float
    rank: int
