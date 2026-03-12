"""Context version manager (UC013).

Creates immutable snapshots of context state, stored in object storage (S3).
Supports listing, restoring, and diffing versions.
"""

from __future__ import annotations

import json
from typing import Any

from context_agent.adapters.context_engine_adapter import ContextEnginePort
from context_agent.models.context import ContextSnapshot
from context_agent.models.version import ContextVersionRecord
from context_agent.utils.errors import ContextAgentError, ErrorCode
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class ContextVersionManager:
    """Manages versioned snapshots of context state.

    Storage backend: S3-compatible object store.
    Falls back to in-memory dict when S3 is not configured.
    """

    def __init__(
        self,
        context_engine: ContextEnginePort | None = None,
        s3_client: Any | None = None,  # aioboto3 S3 client
        bucket: str = "context-agent-versions",
    ) -> None:
        self._ce = context_engine
        self._s3 = s3_client
        self._bucket = bucket
        # In-memory fallback: {context_id: [ContextVersionRecord]}
        self._local: dict[str, list[ContextVersionRecord]] = {}
        self._local_data: dict[str, str] = {}  # version_id → serialized state

    async def create_snapshot(
        self,
        snapshot: ContextSnapshot,
        label: str = "",
        created_by: str = "system",
    ) -> ContextVersionRecord:
        """Serialize and persist a context snapshot, returning the version record."""
        state_json = snapshot.model_dump_json()
        context_id = f"{snapshot.scope_id}:{snapshot.session_id}"

        record = ContextVersionRecord(
            context_id=context_id,
            scope_id=snapshot.scope_id,
            label=label,
            token_count=snapshot.total_tokens,
            item_count=len(snapshot.items),
            is_compressed=False,
            created_by=created_by,
        )
        record.state_ref = f"{self._bucket}/{record.version_id}.json"

        await self._store(record.version_id, state_json)

        # Register in local index
        self._local.setdefault(context_id, []).append(record)

        logger.info(
            "context snapshot created",
            version_id=record.version_id,
            scope_id=snapshot.scope_id,
            label=label,
        )
        return record

    async def restore(
        self,
        scope_id: str,
        session_id: str,
        version_id: str,
    ) -> ContextSnapshot:
        """Load and return a previously saved context snapshot."""
        raw = await self._load(version_id)
        if raw is None:
            raise ContextAgentError(
                f"Version '{version_id}' not found",
                code=ErrorCode.VERSION_NOT_FOUND,
            )
        snapshot = ContextSnapshot.model_validate_json(raw)
        logger.info("context restored", version_id=version_id, scope_id=scope_id)
        return snapshot

    async def list_versions(
        self,
        scope_id: str,
        session_id: str,
        limit: int = 20,
    ) -> list[ContextVersionRecord]:
        """List available versions for a context, newest first."""
        context_id = f"{scope_id}:{session_id}"
        records = self._local.get(context_id, [])
        return sorted(records, key=lambda r: r.created_at, reverse=True)[:limit]

    async def delete_version(self, version_id: str) -> None:
        """Delete a specific version from storage."""
        try:
            if self._s3 is not None:
                await self._s3.delete_object(
                    Bucket=self._bucket, Key=f"{version_id}.json"
                )
            self._local_data.pop(version_id, None)
        except Exception as exc:
            logger.warning("version delete failed", version_id=version_id, error=str(exc))
            raise ContextAgentError(
                f"Failed to delete version '{version_id}'",
                code=ErrorCode.OBJECT_STORE_UNAVAILABLE,
                details={"version_id": version_id, "cause": str(exc)},
            ) from exc
        for records in self._local.values():
            records[:] = [record for record in records if record.version_id != version_id]

    # ── Storage helpers ───────────────────────────────────────────────────────

    async def _store(self, version_id: str, data: str) -> None:
        if self._s3 is not None:
            try:
                await self._s3.put_object(
                    Bucket=self._bucket,
                    Key=f"{version_id}.json",
                    Body=data.encode(),
                    ContentType="application/json",
                )
                return
            except Exception as exc:
                logger.warning("S3 store failed, using local fallback", error=str(exc))
        self._local_data[version_id] = data

    async def _load(self, version_id: str) -> str | None:
        if self._s3 is not None:
            try:
                resp = await self._s3.get_object(
                    Bucket=self._bucket, Key=f"{version_id}.json"
                )
                body = await resp["Body"].read()
                return body.decode()
            except Exception as exc:
                if version_id in self._local_data:
                    logger.warning(
                        "S3 load failed, using local fallback",
                        version_id=version_id,
                        error=str(exc),
                    )
                else:
                    raise ContextAgentError(
                        f"Failed to load version '{version_id}' from object storage",
                        code=ErrorCode.OBJECT_STORE_UNAVAILABLE,
                        details={"version_id": version_id, "cause": str(exc)},
                    ) from exc
        return self._local_data.get(version_id)
