"""Context exposure policy models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from context_agent.models.context import MemoryType


class ExposurePolicy(BaseModel):
    """Defines what context is visible for a given scope/session."""

    policy_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scope_id: str
    session_id: str | None = None  # None means scope-wide default

    # Memory type gates
    allowed_memory_types: list[MemoryType] = Field(
        default_factory=lambda: list(MemoryType)
    )

    # Scratchpad field gates
    allowed_scratchpad_fields: list[str] = Field(default_factory=list)  # empty = all

    # Tool gates
    allowed_tool_ids: list[str] = Field(default_factory=list)  # empty = all

    # Fields kept in state layer but NOT injected into model context
    state_only_fields: list[str] = Field(default_factory=list)

    # Source type gates: e.g. ["tool_result", "external"] to restrict
    allowed_source_types: list[str] = Field(default_factory=list)  # empty = all

    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def allows_memory_type(self, memory_type: MemoryType) -> bool:
        return not self.allowed_memory_types or memory_type in self.allowed_memory_types

    def allows_source_type(self, source_type: str) -> bool:
        return not self.allowed_source_types or source_type in self.allowed_source_types

    def allows_tool(self, tool_id: str) -> bool:
        return not self.allowed_tool_ids or tool_id in self.allowed_tool_ids
