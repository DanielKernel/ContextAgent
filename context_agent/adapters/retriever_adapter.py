"""Retriever adapter.

Wraps openJiuwen HybridRetriever, AgenticRetriever, and GraphRetriever
behind a single RetrieverPort ABC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from context_agent.models.context import ContextItem
from context_agent.utils.errors import AdapterError, ErrorCode
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)


class RetrieverPort(ABC):
    """Abstract interface for all retrieval strategies."""

    @abstractmethod
    async def hybrid_search(
        self,
        scope_id: str,
        query: str,
        top_k: int = 10,
        vector_weight: float = 0.6,
        sparse_weight: float = 0.4,
        filters: dict[str, Any] | None = None,
    ) -> list[ContextItem]:
        """Vector + sparse hybrid retrieval with RRF fusion."""

    @abstractmethod
    async def agentic_search(
        self,
        scope_id: str,
        query: str,
        locator: str,
        top_k: int = 5,
    ) -> list[ContextItem]:
        """Agentic (JIT) retrieval for vector and graph references."""

    @abstractmethod
    async def graph_search(
        self,
        scope_id: str,
        query: str,
        depth: int = 2,
    ) -> list[ContextItem]:
        """Graph relation retrieval."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        items: list[ContextItem],
        top_k: int = 5,
    ) -> list[ContextItem]:
        """Re-rank a list of candidate items."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if retrieval backend is reachable."""


class OpenJiuwenRetrieverAdapter(RetrieverPort):
    """openJiuwen retriever stack implementation of RetrieverPort.

    Module paths used:
      openjiuwen.core.retrieval.retriever.hybrid_retriever.HybridRetriever
      openjiuwen.core.retrieval.retriever.agentic_retriever.AgenticRetriever
      openjiuwen.core.retrieval.retriever.graph_retriever.GraphRetriever
      openjiuwen.core.retrieval.reranker.StandardReranker
    """

    def __init__(
        self,
        hybrid_retriever: Any,
        agentic_retriever: Any,
        graph_retriever: Any | None = None,
        reranker: Any | None = None,
    ) -> None:
        self._hybrid = hybrid_retriever
        self._agentic = agentic_retriever
        self._graph = graph_retriever
        self._reranker = reranker

    def _to_context_items(self, results: Any, tier: str = "warm") -> list[ContextItem]:
        """Convert openJiuwen retrieval results to ContextItem list."""
        items = []
        for r in results or []:
            content = getattr(r, "content", getattr(r, "text", str(r)))
            score = getattr(r, "score", getattr(r, "relevance_score", 1.0))
            items.append(
                ContextItem(
                    source_type="retrieval",
                    tier=tier,
                    score=float(score),
                    content=str(content),
                    metadata={
                        "doc_id": getattr(r, "id", ""),
                        "source": getattr(r, "source", ""),
                    },
                )
            )
        return items

    async def hybrid_search(
        self,
        scope_id: str,
        query: str,
        top_k: int = 10,
        vector_weight: float = 0.6,
        sparse_weight: float = 0.4,
        filters: dict[str, Any] | None = None,
    ) -> list[ContextItem]:
        try:
            results = await self._hybrid.retrieve(
                query=query,
                user_id=scope_id,
                top_k=top_k,
                vector_weight=vector_weight,
                sparse_weight=sparse_weight,
                filters=filters or {},
            )
            return self._to_context_items(results, tier="warm")
        except Exception as exc:
            logger.warning("hybrid_search failed", scope_id=scope_id, error=str(exc))
            raise AdapterError("HybridRetriever", str(exc), code=ErrorCode.RETRIEVAL_FAILED) from exc

    async def agentic_search(
        self,
        scope_id: str,
        query: str,
        locator: str,
        top_k: int = 5,
    ) -> list[ContextItem]:
        try:
            results = await self._agentic.retrieve(
                query=query,
                user_id=scope_id,
                locator=locator,
                top_k=top_k,
            )
            return self._to_context_items(results, tier="cold")
        except Exception as exc:
            raise AdapterError("AgenticRetriever", str(exc), code=ErrorCode.RETRIEVAL_FAILED) from exc

    async def graph_search(
        self,
        scope_id: str,
        query: str,
        depth: int = 2,
    ) -> list[ContextItem]:
        if self._graph is None:
            return []
        try:
            results = await self._graph.retrieve(
                query=query,
                user_id=scope_id,
                depth=depth,
            )
            return self._to_context_items(results, tier="cold")
        except Exception as exc:
            raise AdapterError("GraphRetriever", str(exc), code=ErrorCode.GRAPH_DB_UNAVAILABLE) from exc

    async def rerank(
        self,
        query: str,
        items: list[ContextItem],
        top_k: int = 5,
    ) -> list[ContextItem]:
        if self._reranker is None or not items:
            return items[:top_k]
        try:
            docs = [{"content": it.content, "id": it.item_id} for it in items]
            reranked = await self._reranker.rerank(query=query, documents=docs, top_k=top_k)
            id_to_item = {it.item_id: it for it in items}
            result = []
            for r in reranked:
                item_id = r.get("id", "")
                if item_id in id_to_item:
                    item = id_to_item[item_id].model_copy()
                    item.score = float(r.get("score", item.score))
                    result.append(item)
            return result
        except Exception as exc:
            logger.warning("rerank failed, returning original order", error=str(exc))
            return items[:top_k]

    async def health_check(self) -> bool:
        try:
            await self._hybrid.retrieve(query="health", user_id="__health__", top_k=1)
            return True
        except Exception:
            return False
