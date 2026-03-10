"""Context version management models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ContextVersionRecord(BaseModel):
    """Immutable snapshot of a context state at a point in time."""

    version_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    context_id: str  # logical context identifier (scope_id + session_id)
    scope_id: str
    label: str = ""  # human-readable description, e.g. "before_compaction"
    state_ref: str = ""  # S3/object store path to serialized state
    token_count: int = 0
    item_count: int = 0
    is_compressed: bool = False
    created_by: str = "system"  # system / user / agent
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)
