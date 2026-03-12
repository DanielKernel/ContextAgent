"""JIT context reference models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class RefType(str, Enum):
    """Type of just-in-time context reference."""

    VECTOR = "vector"             # semantic vector search
    GRAPH = "graph"               # graph relation query
    MEMORY = "memory"             # openJiuwen LongTermMemory entry
    SCRATCHPAD = "scratchpad"     # working memory note
    TOOL_RESULT = "tool_result"   # cached tool call output
    FILE = "file"                 # file path reference
    OBJECT = "object"             # object store ID


class ContextRef(BaseModel):
    """A lightweight reference to context that can be resolved on demand."""

    ref_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ref_type: RefType
    scope_id: str
    locator: str  # path / ID / query template / object key depending on ref_type
    description: str = ""  # human-readable hint for what this ref points to
    resolved: bool = False
    expires_at: datetime | None = None  # TTL; None = no expiry
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        expires_at = self.expires_at
        now = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return now > expires_at
