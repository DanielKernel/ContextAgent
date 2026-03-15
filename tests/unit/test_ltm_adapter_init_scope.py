import pytest
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace

from context_agent.adapters.ltm_adapter import OpenJiuwenLTMAdapter

@pytest.mark.asyncio
async def test_ensure_scope_config_initializes_missing_scope() -> None:
    # Setup
    ltm = Mock()
    ltm.get_scope_config = AsyncMock(return_value=None)
    ltm.set_scope_config = AsyncMock()
    ltm.search_user_mem = AsyncMock(return_value=[])
    # Mock internal cache to simulate "not in cache"
    ltm._scope_config = {}

    default_scope_config = SimpleNamespace(some_config="value")

    adapter = OpenJiuwenLTMAdapter(
        ltm=ltm,
        default_scope_config=default_scope_config,
    )

    # Act
    await adapter.search("new-scope", "query")

    # Assert
    ltm.get_scope_config.assert_called_once_with("new-scope")
    ltm.set_scope_config.assert_called_once_with("new-scope", default_scope_config)
    assert "new-scope" in adapter._initialized_scopes

@pytest.mark.asyncio
async def test_ensure_scope_config_skips_existing_scope_in_kv() -> None:
    # Setup
    ltm = Mock()
    existing_config = SimpleNamespace(some_config="existing")
    ltm.get_scope_config = AsyncMock(return_value=existing_config)
    ltm.set_scope_config = AsyncMock()
    ltm.search_user_mem = AsyncMock(return_value=[])
    ltm._scope_config = {}

    default_scope_config = SimpleNamespace(some_config="default")

    adapter = OpenJiuwenLTMAdapter(
        ltm=ltm,
        default_scope_config=default_scope_config,
    )

    # Act
    await adapter.search("existing-scope", "query")

    # Assert
    ltm.get_scope_config.assert_called_once_with("existing-scope")
    ltm.set_scope_config.assert_not_called()
    assert "existing-scope" in adapter._initialized_scopes

@pytest.mark.asyncio
async def test_ensure_scope_config_skips_if_in_internal_cache() -> None:
    # Setup
    ltm = Mock()
    ltm.get_scope_config = AsyncMock()
    ltm.set_scope_config = AsyncMock()
    ltm.search_user_mem = AsyncMock(return_value=[])
    # Simulate internal cache hit
    ltm._scope_config = {"cached-scope": "config"}

    default_scope_config = SimpleNamespace(some_config="default")

    adapter = OpenJiuwenLTMAdapter(
        ltm=ltm,
        default_scope_config=default_scope_config,
    )

    # Act
    await adapter.search("cached-scope", "query")

    # Assert
    ltm.get_scope_config.assert_not_called()
    ltm.set_scope_config.assert_not_called()
    assert "cached-scope" in adapter._initialized_scopes

@pytest.mark.asyncio
async def test_ensure_scope_config_skips_if_already_initialized_locally() -> None:
    # Setup
    ltm = Mock()
    ltm.get_scope_config = AsyncMock()
    ltm.set_scope_config = AsyncMock()
    ltm.search_user_mem = AsyncMock(return_value=[])
    ltm._scope_config = {}

    default_scope_config = SimpleNamespace(some_config="default")

    adapter = OpenJiuwenLTMAdapter(
        ltm=ltm,
        default_scope_config=default_scope_config,
    )
    # Manually mark initialized
    adapter._initialized_scopes.add("known-scope")

    # Act
    await adapter.search("known-scope", "query")

    # Assert
    ltm.get_scope_config.assert_not_called()
    ltm.set_scope_config.assert_not_called()
