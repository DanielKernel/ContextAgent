"""Sub-agent context manager (UC014).

Handles context scoping for multi-agent delegation:
  - Create child scopes from parent scope
  - Inject delegated context based on ExposurePolicy
  - Receive result context from child agents and merge back
  - Propagate version records across scope boundaries
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from context_agent.core.context.exposure_controller import ExposureController
from context_agent.core.context.version_manager import ContextVersionManager
from context_agent.models.context import ContextItem, ContextSnapshot, ContextView
from context_agent.models.policy import ExposurePolicy
from context_agent.utils.logging import get_logger
from context_agent.utils.tracing import traced_span

logger = get_logger(__name__)


@dataclass
class DelegationTicket:
    """Lightweight token representing a sub-agent delegation."""

    ticket_id: str
    parent_scope_id: str
    child_scope_id: str
    parent_version_id: str
    task_description: str
    created_at: float
    ttl_s: float = 300.0

    @property
    def is_expired(self) -> bool:
        return time.monotonic() - self.created_at > self.ttl_s

    @staticmethod
    def create(
        parent_scope_id: str, child_scope_id: str, parent_version_id: str, task: str
    ) -> "DelegationTicket":
        return DelegationTicket(
            ticket_id=str(uuid.uuid4()),
            parent_scope_id=parent_scope_id,
            child_scope_id=child_scope_id,
            parent_version_id=parent_version_id,
            task_description=task,
            created_at=time.monotonic(),
        )


class SubAgentContextManager:
    """Manages context lifecycle for sub-agent delegation."""

    def __init__(
        self,
        exposure_controller: ExposureController | None = None,
        version_manager: ContextVersionManager | None = None,
    ) -> None:
        self._ec = exposure_controller or ExposureController()
        self._vm = version_manager or ContextVersionManager()
        # Track active delegations
        self._tickets: dict[str, DelegationTicket] = {}

    async def delegate(
        self,
        parent_snapshot: ContextSnapshot,
        task_description: str,
        policy: ExposurePolicy | None = None,
        ttl_s: float = 300.0,
    ) -> tuple[ContextView, DelegationTicket]:
        """Create a child scope with filtered context for a sub-agent.

        Returns:
            (ContextView, DelegationTicket) — view for the child agent,
            ticket for result merging.
        """
        async with traced_span(
            "sub_agent_manager.delegate",
            {"parent_scope_id": parent_snapshot.scope_id},
        ):
            # Save parent snapshot version
            version = await self._vm.create_snapshot(
                parent_snapshot,
                label=f"pre-delegation:{task_description[:32]}",
                created_by="sub_agent_manager",
            )

            child_scope_id = f"{parent_snapshot.scope_id}:child:{uuid.uuid4().hex[:8]}"
            ticket = DelegationTicket.create(
                parent_snapshot.scope_id, child_scope_id, version.version_id, task_description
            )
            ticket.ttl_s = ttl_s
            self._tickets[ticket.ticket_id] = ticket

            # Apply exposure policy to create child context view
            if policy is None:
                policy = await self._ec.get_default_policy(parent_snapshot.scope_id)
            child_view = await self._ec.apply(parent_snapshot, policy)
            child_view.scope_id = child_scope_id

            logger.info(
                "delegation created",
                ticket_id=ticket.ticket_id,
                parent_scope=parent_snapshot.scope_id,
                child_scope=child_scope_id,
                visible_items=len(child_view.visible_items),
            )
            return child_view, ticket

    async def receive_result(
        self,
        ticket: DelegationTicket,
        result_items: list[ContextItem],
    ) -> list[ContextItem]:
        """Merge sub-agent result items back to the parent scope.

        Validates the ticket is still valid and tags items with parent scope.
        """
        if ticket.is_expired:
            logger.warning("delegation ticket expired", ticket_id=ticket.ticket_id)
            return []

        merged: list[ContextItem] = []
        for item in result_items:
            updated = item.model_copy(
                update={
                    "metadata": {
                        **item.metadata,
                        "delegated_from": ticket.child_scope_id,
                        "ticket_id": ticket.ticket_id,
                    }
                }
            )
            merged.append(updated)

        self._tickets.pop(ticket.ticket_id, None)
        logger.info(
            "delegation result received",
            ticket_id=ticket.ticket_id,
            items_merged=len(merged),
        )
        return merged

    def get_active_tickets(self, parent_scope_id: str) -> list[DelegationTicket]:
        """Return all non-expired delegation tickets for a parent scope."""
        return [
            t
            for t in self._tickets.values()
            if t.parent_scope_id == parent_scope_id and not t.is_expired
        ]
