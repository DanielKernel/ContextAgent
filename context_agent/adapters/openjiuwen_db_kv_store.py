"""ContextAgent-owned compatibility wrapper for openJiuwen DbBasedKVStore."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from openjiuwen.core.foundation.store.base_kv_store import BasedKVStorePipeline
from openjiuwen.core.foundation.store.kv.db_based_kv_store import (
    DbBasedKVStore,
    KVStoreTable,
)


class OpenJiuwenDbBasedKVStoreCompat(DbBasedKVStore):
    """Use dialect-correct UPSERT statements without mutating openJiuwen modules."""

    def _get_upsert_stmt(self, key: str, value: str):
        dialect_name = self.engine.dialect.name
        if dialect_name == "mysql":
            return (
                mysql_insert(KVStoreTable)
                .values(key=key, value=value)
                .on_duplicate_key_update(value=value)
            )
        if dialect_name == "postgresql":
            return (
                postgres_insert(KVStoreTable)
                .values(key=key, value=value)
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_={"value": value},
                )
            )
        return (
            sqlite_insert(KVStoreTable)
            .values(key=key, value=value)
            .on_conflict_do_update(
                index_elements=["key"],
                set_={"value": value},
            )
        )

    def pipeline(self):
        async def execute(operations):
            await self._create_table_if_not_exist()
            results = []
            async with self.async_session() as session:
                async with session.begin():
                    set_ops = []
                    get_keys = []
                    exists_keys = []
                    for op in operations:
                        op_type = op[0]
                        if op_type == "set":
                            set_ops.append((op[1], op[2]))
                        elif op_type == "get":
                            get_keys.append(op[1])
                        elif op_type == "exists":
                            exists_keys.append(op[1])

                    for key, value in set_ops:
                        encoded_value = self._encode_value(value)
                        await session.execute(self._get_upsert_stmt(key, encoded_value))

                    get_results = {}
                    if get_keys:
                        stmt = select(KVStoreTable).where(KVStoreTable.key.in_(get_keys))
                        rows = (await session.execute(stmt)).scalars().all()
                        for rec in rows:
                            get_results[rec.key] = self._decode_value(rec.value)

                    exists_results = {}
                    if exists_keys:
                        stmt = select(KVStoreTable).where(KVStoreTable.key.in_(exists_keys))
                        rows = (await session.execute(stmt)).scalars().all()
                        for rec in rows:
                            exists_results[rec.key] = True
                        for key in exists_keys:
                            exists_results.setdefault(key, False)

                    for op in operations:
                        op_type = op[0]
                        key = op[1]
                        if op_type == "set":
                            results.append(None)
                        elif op_type == "get":
                            results.append(get_results.get(key))
                        elif op_type == "exists":
                            results.append(exists_results.get(key, False))

            return results

        return BasedKVStorePipeline(execute)
