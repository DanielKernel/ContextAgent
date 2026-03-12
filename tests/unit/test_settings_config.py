"""Tests for ContextAgent YAML-backed settings loading."""

from __future__ import annotations

from pathlib import Path

from context_agent.config.settings import Settings, resolve_context_agent_config_path


def test_settings_load_from_context_agent_yaml(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "context_agent.yaml"
    config_path.write_text(
        """
service:
  log_level: DEBUG
http:
  port: 9010
integrations:
  openjiuwen:
    config_path: openjiuwen.yaml
auth:
  api_keys:
    - key-1
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("CA_CONTEXT_AGENT_CONFIG_PATH", str(config_path))

    settings = Settings()

    assert settings.http_port == 9010
    assert settings.log_level == "DEBUG"
    assert settings.api_keys == ["key-1"]
    assert settings.openjiuwen_config_path == str((config_dir / "openjiuwen.yaml").resolve())


def test_env_values_override_context_agent_yaml(monkeypatch, tmp_path):
    config_path = tmp_path / "context_agent.yaml"
    config_path.write_text("http:\n  port: 9010\n", encoding="utf-8")

    monkeypatch.setenv("CA_CONTEXT_AGENT_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("CA_HTTP_PORT", "8123")

    settings = Settings()

    assert settings.http_port == 8123


def test_resolve_context_agent_config_path_uses_compat_alias(monkeypatch, tmp_path):
    config_path = tmp_path / "context_agent.yaml"
    config_path.write_text("http:\n  port: 8080\n", encoding="utf-8")
    monkeypatch.delenv("CA_CONTEXT_AGENT_CONFIG_PATH", raising=False)
    monkeypatch.setenv("CA_SETTINGS_PATH", str(config_path))

    resolved = resolve_context_agent_config_path()

    assert resolved == Path(config_path).resolve()


def test_settings_resolve_nested_openjiuwen_path_relative_to_config(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "context_agent.yaml"
    config_path.write_text(
        """
integrations:
  openjiuwen:
    config_path: ../shared/openjiuwen.yaml
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("CA_CONTEXT_AGENT_CONFIG_PATH", str(config_path))

    settings = Settings()

    assert settings.openjiuwen_config_path == str((tmp_path / "shared" / "openjiuwen.yaml").resolve())
