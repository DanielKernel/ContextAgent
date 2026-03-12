"""Functional tests for MultimodalProcessor."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import context_agent.core.multimodal.processor as multimodal_module
from context_agent.core.multimodal.processor import (
    ModalityType,
    MultimodalInput,
    MultimodalProcessor,
)


@pytest.mark.asyncio
class TestMultimodalProcessor:
    async def test_text_processing(self):
        processor = MultimodalProcessor()
        inp = MultimodalInput(
            modality=ModalityType.TEXT,
            content="Please summarise the Q3 financial results.",
            source_id="user-msg-001",
        )
        item = await processor.process(inp)
        assert item.source_type == "text"
        assert "Q3" in item.content
        assert item.metadata["source_id"] == "user-msg-001"
        assert "language" in item.metadata

    async def test_image_processing_bytes(self):
        processor = MultimodalProcessor()
        fake_bytes = b"\x00" * 5120  # 5 KB
        inp = MultimodalInput(
            modality=ModalityType.IMAGE,
            content=fake_bytes,
            source_id="screenshot-001",
        )
        item = await processor.process(inp)
        assert item.source_type == "image"
        assert "IMAGE" in item.content
        assert item.metadata.get("stub") is True

    async def test_image_processing_base64(self):
        processor = MultimodalProcessor()
        inp = MultimodalInput(
            modality=ModalityType.IMAGE,
            content="data:image/png;base64,iVBORw0KGgo=",
            source_id="img-b64",
        )
        item = await processor.process(inp)
        assert "base64" in item.content.lower()

    async def test_audio_processing(self):
        processor = MultimodalProcessor()
        fake_audio = b"\x00" * (16000 * 5)  # 5 seconds @ 16kHz
        inp = MultimodalInput(
            modality=ModalityType.AUDIO,
            content=fake_audio,
            source_id="audio-001",
        )
        item = await processor.process(inp)
        assert item.source_type == "audio"
        assert "AUDIO" in item.content
        assert item.metadata.get("stub") is True

    async def test_batch_processing(self):
        processor = MultimodalProcessor()
        inputs = [
            MultimodalInput(modality=ModalityType.TEXT, content="text message"),
            MultimodalInput(modality=ModalityType.IMAGE, content=b"\xff" * 1024),
            MultimodalInput(modality=ModalityType.AUDIO, content=b"\x00" * 8000),
        ]
        items = await processor.process_batch(inputs)
        assert len(items) == 3
        types = {i.source_type for i in items}
        assert types == {"text", "image", "audio"}

    async def test_invalid_modality_raises(self):
        processor = MultimodalProcessor()
        inp = MultimodalInput(modality="video", content="bytes")  # type: ignore
        with pytest.raises(ValueError, match="Unsupported modality"):
            await processor.process(inp)

    async def test_batch_error_tolerance(self):
        """Batch processing should skip failing items, not raise."""
        processor = MultimodalProcessor()
        inputs = [
            MultimodalInput(modality=ModalityType.TEXT, content="good"),
            MultimodalInput(modality="video", content="bad"),  # type: ignore
        ]
        items = await processor.process_batch(inputs)
        # Only the good item should survive
        assert len(items) == 1
        assert items[0].content == "good"

    async def test_text_preserves_metadata(self):
        processor = MultimodalProcessor()
        inp = MultimodalInput(
            modality=ModalityType.TEXT,
            content="test",
            metadata={"priority": "high", "turn": 3},
        )
        item = await processor.process(inp)
        assert item.metadata["priority"] == "high"
        assert item.metadata["turn"] == 3

    async def test_process_batch_logs_warning_when_text_processing_fails(self):
        processor = MultimodalProcessor()
        inp = MultimodalInput(modality=ModalityType.TEXT, content="test")

        with patch.object(multimodal_module, "_detect_language", side_effect=RuntimeError("lang boom")):
            with patch.object(multimodal_module.logger, "warning") as warning:
                items = await processor.process_batch([inp])

        assert items == []
        warning.assert_called_once()
