"""Exposure controller (UC006).

Filters a ContextSnapshot according to an ExposurePolicy,
ensuring only permitted context reaches the model context window.
"""

from __future__ import annotations

from context_agent.models.context import ContextItem, ContextSnapshot, ContextView
from context_agent.models.policy import ExposurePolicy
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class ExposureController:
    """Applies ExposurePolicy to a ContextSnapshot and returns a ContextView."""

    async def apply(
        self,
        snapshot: ContextSnapshot,
        policy: ExposurePolicy,
    ) -> ContextView:
        """Filter snapshot items based on policy rules.

        Filtered-out items are counted but not returned.
        """
        visible: list[ContextItem] = []
        hidden_count = 0

        for item in snapshot.items:
            if not self._is_allowed(item, policy):
                hidden_count += 1
                continue
            visible.append(item)

        logger.debug(
            "exposure control applied",
            scope_id=snapshot.scope_id,
            total=len(snapshot.items),
            visible=len(visible),
            hidden=hidden_count,
            policy_id=policy.policy_id,
        )

        return ContextView(
            snapshot_id=snapshot.snapshot_id,
            scope_id=snapshot.scope_id,
            visible_items=visible,
            hidden_item_count=hidden_count,
            applied_policy_id=policy.policy_id,
        )

    def _is_allowed(self, item: ContextItem, policy: ExposurePolicy) -> bool:
        # Check source type gate
        if not policy.allows_source_type(item.source_type):
            return False

        # Check memory type gate
        if item.memory_type is not None and not policy.allows_memory_type(item.memory_type):
            return False

        # Check state-only fields (tool results from state-only source types)
        if item.source_type in policy.state_only_fields:
            return False

        # Check scratchpad field gates
        if item.source_type == "scratchpad":
            field_name = item.metadata.get("field_name", "")
            if policy.allowed_scratchpad_fields and field_name not in policy.allowed_scratchpad_fields:
                return False

        # Check tool gates
        if item.source_type == "tool_result":
            tool_id = item.metadata.get("tool_id", "")
            if not policy.allows_tool(tool_id):
                return False

        return True

    async def get_default_policy(self, scope_id: str) -> ExposurePolicy:
        """Return a permissive default policy for a scope (allow everything)."""
        return ExposurePolicy(scope_id=scope_id)
