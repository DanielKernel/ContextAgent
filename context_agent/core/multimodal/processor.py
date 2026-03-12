"""Multimodal context processor (UC015).

Handles text, image, and audio inputs. Text is passed through directly;
image and audio have stub implementations with placeholder extraction.
Language detection via langdetect.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
from typing import Any

from context_agent.models.context import ContextItem
from context_agent.utils.logging import get_logger

logger = get_logger(__name__)

try:
    from langdetect import detect as _langdetect_detect  # type: ignore

    def _detect_language(text: str) -> str:
        try:
            return _langdetect_detect(text)
        except Exception as exc:
            logger.debug("language detection failed", error=str(exc))
            return "unknown"

except ImportError:
    def _detect_language(text: str) -> str:  # type: ignore
        return "unknown"


class ModalityType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"


@dataclass
class MultimodalInput:
    modality: ModalityType
    content: Any  # str for text; bytes or base64 str for image/audio
    source_id: str = ""
    metadata: dict[str, Any] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


class MultimodalProcessor:
    """Normalises multimodal inputs to ContextItems."""

    async def process(self, inp: MultimodalInput) -> ContextItem:
        """Convert a multimodal input to a ContextItem."""
        if inp.modality == ModalityType.TEXT:
            return await self._process_text(inp)
        elif inp.modality == ModalityType.IMAGE:
            return await self._process_image(inp)
        elif inp.modality == ModalityType.AUDIO:
            return await self._process_audio(inp)
        else:
            raise ValueError(f"Unsupported modality: {inp.modality}")

    async def process_batch(self, inputs: list[MultimodalInput]) -> list[ContextItem]:
        """Process multiple inputs in sequence."""
        items = []
        for inp in inputs:
            try:
                item = await self.process(inp)
                items.append(item)
            except Exception as exc:
                logger.warning(
                    "multimodal processing failed",
                    modality=inp.modality,
                    error=str(exc),
                )
        return items

    # ── Modality handlers ─────────────────────────────────────────────────────

    async def _process_text(self, inp: MultimodalInput) -> ContextItem:
        text = str(inp.content)
        language = _detect_language(text)
        return ContextItem(
            source_type="text",
            tier="hot",
            score=1.0,
            content=text,
            metadata={
                **inp.metadata,
                "source_id": inp.source_id,
                "language": language,
                "modality": ModalityType.TEXT,
            },
        )

    async def _process_image(self, inp: MultimodalInput) -> ContextItem:
        # Stub: real implementation would call a vision API or extract embeddings
        content = inp.content
        if isinstance(content, bytes):
            size_kb = len(content) // 1024
            placeholder = f"[IMAGE: {size_kb}KB binary data]"
        elif isinstance(content, str) and content.startswith("data:image"):
            placeholder = "[IMAGE: base64-encoded inline image]"
        else:
            placeholder = f"[IMAGE: {str(content)[:64]}]"

        logger.debug("image processed (stub)", source_id=inp.source_id)
        return ContextItem(
            source_type="image",
            tier="hot",
            score=1.0,
            content=placeholder,
            metadata={
                **inp.metadata,
                "source_id": inp.source_id,
                "modality": ModalityType.IMAGE,
                "stub": True,
            },
        )

    async def _process_audio(self, inp: MultimodalInput) -> ContextItem:
        # Stub: real implementation would transcribe via Whisper / ASR
        content = inp.content
        if isinstance(content, bytes):
            duration_hint = f"~{len(content) // 16000}s"
        else:
            duration_hint = "unknown duration"

        placeholder = f"[AUDIO: {duration_hint}, transcription pending]"
        logger.debug("audio processed (stub)", source_id=inp.source_id)
        return ContextItem(
            source_type="audio",
            tier="hot",
            score=1.0,
            content=placeholder,
            metadata={
                **inp.metadata,
                "source_id": inp.source_id,
                "modality": ModalityType.AUDIO,
                "stub": True,
            },
        )
