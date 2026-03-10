"""Core context data models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class MemoryType(str, Enum):
    """Semantic classification of memory content."""

    PROCEDURAL = "procedural"  # rules, instructions, preferences
    EPISODIC = "episodic"      # historical cases, few-shot examples
    SEMANTIC = "semantic"      # facts, entities, domain knowledge
    VARIABLE = "variable"      # current session state, task variables


class OutputType(str, Enum):
    """Requested output format from ContextAPIRouter."""

    SNAPSHOT = "snapshot"                    # full aggregated context snapshot
    SUMMARY = "summary"                      # compressed background summary
    SEARCH = "search"                        # tiered memory search results
    COMPRESSED_BACKGROUND = "compressed_background"  # task-oriented compressed context
    COMPRESSED = "compressed"               # generic compressed output
    RAW = "raw"                             # uncompressed concatenation
    STRUCTURED = "structured"               # structured JSON output (compaction)


class ContextItem(BaseModel):
    """A single context unit from any source."""

    item_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    snapshot_id: str = ""
    source_type: str  # memory_type / tool_result / external / working_note
    tier: str = "warm"  # hot / warm / cold
    modality: str = "text"  # text / image / audio
    language: str = "zh"  # ISO 639-1
    memory_type: MemoryType | None = None
    score: float = 1.0  # relevance score [0, 1]
    content: str = ""
    raw_content_ref: str | None = None  # S3 path for large content
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("score")
    @classmethod
    def clamp_score(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class ContextSnapshot(BaseModel):
    """Aggregated context assembled for a single inference call."""

    snapshot_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scope_id: str
    user_id: str = ""
    session_id: str = ""
    query: str = ""
    items: list[ContextItem] = Field(default_factory=list)
    total_tokens: int = 0
    token_budget: int = 4096
    degraded_sources: list[str] = Field(default_factory=list)  # sources that fell back
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def is_over_budget(self) -> bool:
        return self.total_tokens > self.token_budget

    def add_item(self, item: ContextItem) -> None:
        item.snapshot_id = self.snapshot_id
        self.items.append(item)


class ContextView(BaseModel):
    """A filtered projection of a ContextSnapshot after exposure control."""

    snapshot_id: str
    scope_id: str
    visible_items: list[ContextItem] = Field(default_factory=list)
    hidden_item_count: int = 0
    applied_policy_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContextOutput(BaseModel):
    """Unified output returned by ContextAPIRouter."""

    output_type: OutputType
    scope_id: str
    session_id: str = ""
    user_id: str = ""
    # Generic content field (compressed text, version_id, etc.)
    content: str = ""
    token_count: int = 0
    snapshot: ContextSnapshot | None = None   # for SNAPSHOT
    compressed_text: str | None = None        # for SUMMARY / COMPRESSED_BACKGROUND (legacy)
    search_items: list[ContextItem] | None = None  # for SEARCH
    latency_ms: float = 0.0
    degraded: bool = False
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
