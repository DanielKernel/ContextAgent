"""Compatibility bridge for openJiuwen pgvector retrieval store."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from openjiuwen.core.foundation.store.base_vector_store import (
    BaseVectorStore,
    CollectionSchema,
    FieldSchema,
    VectorDataType,
    VectorSearchResult,
)
from openjiuwen.core.foundation.store.vector_fields.pg_fields import PGVectorField
from openjiuwen.core.memory.migration.operation.operations import (
    AddScalarFieldOperation,
    RenameScalarFieldOperation,
    UpdateEmbeddingDimensionOperation,
    UpdateScalarFieldTypeOperation,
)
from openjiuwen.core.retrieval.common.config import StoreType, VectorStoreConfig
from openjiuwen.core.retrieval.vector_store.pg_store import PGVectorStore
from sqlalchemy import delete, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class OpenJiuwenPGVectorStoreBridge(BaseVectorStore):
    """Adapt retrieval PGVectorStore to the BaseVectorStore contract used by LongTermMemory."""

    _METADATA_TABLE = "_contextagent_vector_collection_metadata"

    def __init__(self, vector_store_config: dict[str, Any]) -> None:
        dsn = vector_store_config.get("dsn")
        if not dsn:
            raise ValueError("vector_store.dsn is required for pgvector bridge")

        self._dsn = dsn
        self._distance_metric = vector_store_config.get("distance", "cosine")
        self._index_type = vector_store_config.get("index_type", "hnsw")
        self._lists = vector_store_config.get("lists", 100)
        self._schema_name = vector_store_config.get("schema", "public")
        self._embedding_dimension = vector_store_config.get("embedding_dimension")
        parsed_dsn = urlparse(dsn)
        self._database_name = parsed_dsn.path.lstrip("/") or "postgres"
        self._engine: AsyncEngine = create_async_engine(dsn, pool_pre_ping=True, echo=False)
        self._stores: dict[str, PGVectorStore] = {}

    def _build_store(self, collection_name: str) -> PGVectorStore:
        config = VectorStoreConfig(
            store_provider=StoreType.PGVector,
            database_name=self._database_name,
            collection_name=collection_name,
            distance_metric=self._distance_metric,
        )
        vector_field = PGVectorField(
            vector_field="embedding",
            index_type=self._index_type,
            lists=self._lists,
        )
        return PGVectorStore(
            config=config,
            pg_uri=self._dsn,
            vector_field=vector_field,
        )

    def _get_store(self, collection_name: str) -> PGVectorStore:
        store = self._stores.get(collection_name)
        if store is None:
            store = self._build_store(collection_name)
            self._stores[collection_name] = store
        return store

    async def _ensure_metadata_table(self) -> None:
        async with self._engine.begin() as conn:
            if self._schema_name and self._schema_name != "public":
                await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self._schema_name}"))
            await conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._schema_name}.{self._METADATA_TABLE} (
                        collection_name TEXT PRIMARY KEY,
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                    )
                    """
                )
            )

    async def create_collection(
        self,
        collection_name: str,
        schema: CollectionSchema | dict[str, Any],
        **kwargs: object,
    ) -> None:
        store = self._get_store(collection_name)
        if isinstance(schema, dict):
            schema = CollectionSchema.from_dict(schema)
        dim = self._embedding_dimension
        if dim is None:
            vector_fields = schema.get_vector_fields()
            if vector_fields:
                dim = vector_fields[0].dim
        if dim is None:
            raise ValueError("vector collection schema is missing embedding dimension")
        await store._get_or_create_table(dim)
        await self._ensure_metadata_table()

    async def delete_collection(
        self,
        collection_name: str,
        **kwargs: object,
    ) -> None:
        store = self._get_store(collection_name)
        await store.delete_table(collection_name)
        await self._ensure_metadata_table()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM "
                    f"{self._schema_name}.{self._METADATA_TABLE} "
                    "WHERE collection_name = :collection_name"
                ),
                {"collection_name": collection_name},
            )

    async def collection_exists(
        self,
        collection_name: str,
        **kwargs: object,
    ) -> bool:
        store = self._get_store(collection_name)
        return await store.table_exists(collection_name)

    async def get_schema(
        self,
        collection_name: str,
        **kwargs: object,
    ) -> CollectionSchema:
        store = self._get_store(collection_name)
        table = await store._get_or_create_table(self._embedding_dimension or 0)
        if table is None:
            raise ValueError(f"collection does not exist: {collection_name}")

        fields: list[FieldSchema] = []
        for column in table.columns:
            if column.name == "id":
                fields.append(
                    FieldSchema(
                        name="id",
                        dtype=VectorDataType.VARCHAR,
                        is_primary=True,
                    )
                )
            elif column.name == "embedding":
                dim = getattr(column.type, "dim", None) or self._embedding_dimension
                fields.append(
                    FieldSchema(
                        name="embedding",
                        dtype=VectorDataType.FLOAT_VECTOR,
                        dim=dim,
                    )
                )
            elif isinstance(column.type, JSONB):
                fields.append(FieldSchema(name=column.name, dtype=VectorDataType.JSON))
            else:
                fields.append(FieldSchema(name=column.name, dtype=VectorDataType.VARCHAR))

        return CollectionSchema.from_fields(fields)

    async def add_docs(
        self,
        collection_name: str,
        docs: list[dict[str, Any]],
        **kwargs: object,
    ) -> None:
        store = self._get_store(collection_name)
        payload: list[dict[str, Any]] = []
        for doc in docs:
            metadata = dict(doc.get("metadata") or {})
            extra_fields = {
                key: value
                for key, value in doc.items()
                if key not in {"id", "pk", "embedding", "metadata", "text", "content"}
            }
            metadata.update(extra_fields)
            payload.append(
                {
                    "id": str(doc.get("id") or doc.get("pk")),
                    "embedding": doc.get("embedding"),
                    "content": doc.get("text", doc.get("content", "")),
                    "metadata": metadata,
                }
            )
        await store.add(payload, batch_size=kwargs.get("batch_size"))

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        vector_field: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
        **kwargs: object,
    ) -> list[VectorSearchResult]:
        store = self._get_store(collection_name)
        results = await store.search(query_vector=query_vector, top_k=top_k, filters=filters)
        return [
            VectorSearchResult(
                score=result.score,
                fields={
                    "id": result.id,
                    "text": result.text,
                    "metadata": result.metadata,
                },
            )
            for result in results
        ]

    async def delete_docs_by_ids(
        self,
        collection_name: str,
        ids: list[str],
        **kwargs: object,
    ) -> None:
        store = self._get_store(collection_name)
        await store.delete(ids=ids)

    async def delete_docs_by_filters(
        self,
        collection_name: str,
        filters: dict[str, Any],
        **kwargs: object,
    ) -> None:
        store = self._get_store(collection_name)
        table = await store._get_or_create_table(self._embedding_dimension or 0)
        if table is None:
            return
        conds = store.build_filters(table, filters)
        async with store._async_session() as session, session.begin():
            stmt = delete(table)
            if conds:
                stmt = stmt.where(*conds)
            await session.execute(stmt)

    async def list_collection_names(self) -> list[str]:
        async with self._engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names(
                    schema=self._schema_name
                )
            )
        return [name for name in table_names if name != self._METADATA_TABLE]

    async def update_schema(self, collection_name: str, operations: list[Any]) -> None:
        if not operations:
            return
        type_mapping = {
            "string": "TEXT",
            "str": "TEXT",
            "int": "BIGINT",
            "integer": "BIGINT",
            "float": "DOUBLE PRECISION",
            "double": "DOUBLE PRECISION",
            "bool": "BOOLEAN",
            "boolean": "BOOLEAN",
            "json": "JSONB",
        }
        async with self._engine.begin() as conn:
            for operation in operations:
                if isinstance(operation, AddScalarFieldOperation):
                    column_type = type_mapping.get(operation.field_type.lower(), "TEXT")
                    await conn.execute(
                        text(
                            f"ALTER TABLE {self._schema_name}.{collection_name} "
                            f"ADD COLUMN IF NOT EXISTS {operation.field_name} {column_type}"
                        )
                    )
                elif isinstance(operation, RenameScalarFieldOperation):
                    await conn.execute(
                        text(
                            f"ALTER TABLE {self._schema_name}.{collection_name} "
                            "RENAME COLUMN "
                            f"{operation.old_field_name} TO {operation.new_field_name}"
                        )
                    )
                elif isinstance(operation, UpdateScalarFieldTypeOperation):
                    column_type = type_mapping.get(operation.new_field_type.lower(), "TEXT")
                    await conn.execute(
                        text(
                            f"ALTER TABLE {self._schema_name}.{collection_name} "
                            f"ALTER COLUMN {operation.field_name} TYPE {column_type}"
                        )
                    )
                elif isinstance(operation, UpdateEmbeddingDimensionOperation):
                    raise NotImplementedError(
                        "PGVector embedding dimension migration is not supported by the bridge"
                    )

    async def update_collection_metadata(
        self, collection_name: str, metadata: dict[str, Any]
    ) -> None:
        await self._ensure_metadata_table()
        existing = await self.get_collection_metadata(collection_name)
        existing.update(metadata)
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    f"""
                    INSERT INTO {self._schema_name}.{self._METADATA_TABLE}
                    (collection_name, metadata)
                    VALUES (:collection_name, CAST(:metadata AS JSONB))
                    ON CONFLICT (collection_name)
                    DO UPDATE SET metadata = EXCLUDED.metadata
                    """
                ),
                {"collection_name": collection_name, "metadata": json.dumps(existing)},
            )

    async def get_collection_metadata(self, collection_name: str) -> dict[str, Any]:
        await self._ensure_metadata_table()
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"SELECT metadata FROM {self._schema_name}.{self._METADATA_TABLE} "
                    f"WHERE collection_name = :collection_name"
                ),
                {"collection_name": collection_name},
            )
            row = result.first()
        if row is None or row[0] is None:
            return {}
        return dict(row[0])
