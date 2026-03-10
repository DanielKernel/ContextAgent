"""Working memory note models (structured scratchpad)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NoteType(str, Enum):
    """Semantic type of a working memory note."""

    TASK_PLAN = "task_plan"          # structured task plan with steps
    KEY_DECISION = "key_decision"    # architectural or business decisions made
    OPEN_QUESTION = "open_question"  # unresolved questions to track
    RISK_ITEM = "risk_item"          # identified risks
    CURRENT_STATUS = "current_status"  # current progress / execution state
    KEY_CONSTRAINT = "key_constraint"  # non-negotiable constraints
    HANDOFF_SUMMARY = "handoff_summary"  # sub-agent handoff summary


# JSON-Schema-like content templates per NoteType
NOTE_CONTENT_SCHEMAS: dict[NoteType, dict[str, Any]] = {
    NoteType.TASK_PLAN: {
        "goal": str,
        "steps": list,
        "current_step_index": int,
        "completed_steps": list,
    },
    NoteType.KEY_DECISION: {
        "decision": str,
        "rationale": str,
        "alternatives_rejected": list,
    },
    NoteType.OPEN_QUESTION: {
        "question": str,
        "context": str,
        "priority": str,  # high / medium / low
    },
    NoteType.RISK_ITEM: {
        "risk": str,
        "impact": str,
        "mitigation": str,
    },
    NoteType.CURRENT_STATUS: {
        "phase": str,
        "progress_summary": str,
        "pending_actions": list,
    },
    NoteType.KEY_CONSTRAINT: {
        "constraint": str,
        "source": str,
    },
    NoteType.HANDOFF_SUMMARY: {
        "sub_agent_id": str,
        "task_summary": str,
        "result_summary": str,
        "artifacts": list,
    },
}


class WorkingNote(BaseModel):
    """A structured working memory note persisted outside the context window."""

    note_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scope_id: str
    session_id: str
    note_type: NoteType
    content: dict[str, Any]  # validated against NOTE_CONTENT_SCHEMAS[note_type]
    schema_version: int = 1
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None  # None = lives until session ends


class NoteRef(BaseModel):
    """Lightweight reference to a WorkingNote (used as ContextRef.locator)."""

    note_id: str
    note_type: NoteType
    scope_id: str
    session_id: str
    summary: str = ""
