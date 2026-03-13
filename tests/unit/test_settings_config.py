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
llm:
  api_key: secret-key
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
    assert settings.llm_api_key == "secret-key"
    assert settings.api_keys == ["key-1"]
    assert settings.openjiuwen_config_path == str((config_dir / "openjiuwen.yaml").resolve())


def test_settings_load_compression_and_retrieval_sections(monkeypatch, tmp_path):
    config_path = tmp_path / "context_agent.yaml"
    config_path.write_text(
        """
compression:
  llm:
    base_url: https://compression.example.com/v1
    model: minimax-text
    api_key: compression-key
    timeout_s: 12.5
    max_retries: 4
  compaction_trigger_ratio: 0.9
memory:
  hot_tier_ttl_s: 120
  max_notes_per_session: 25
retrieval:
  default_top_k: 7
  timeout_ms: 480
  rerank_top_k: 3
  hybrid:
    vector_weight: 0.75
    sparse_weight: 0.25
    rrf_k: 45
  jit_cache:
    ttl_s: 90
    local_max_entries: 321
  hotness:
    alpha: 0.35
    half_life_days: 21
  tool_selection:
    rag_threshold: 15
    top_k: 6
context_health:
  thresholds:
    poisoning: 0.8
    distraction: 0.6
    confusion: 0.45
    clash: 0.7
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("CA_CONTEXT_AGENT_CONFIG_PATH", str(config_path))

    settings = Settings()

    assert settings.llm_base_url == "https://compression.example.com/v1"
    assert settings.llm_model == "minimax-text"
    assert settings.llm_api_key == "compression-key"
    assert settings.llm_timeout_s == 12.5
    assert settings.llm_max_retries == 4
    assert settings.compaction_trigger_ratio == 0.9
    assert settings.hot_tier_ttl_s == 120
    assert settings.max_notes_per_session == 25
    assert settings.retrieval_default_top_k == 7
    assert settings.retrieval_timeout_ms == 480
    assert settings.retrieval_rerank_top_k == 3
    assert settings.retrieval_vector_weight == 0.75
    assert settings.retrieval_sparse_weight == 0.25
    assert settings.retrieval_rrf_k == 45
    assert settings.jit_cache_ttl_s == 90
    assert settings.jit_cache_local_max_entries == 321
    assert settings.retrieval_hotness_alpha == 0.35
    assert settings.retrieval_hotness_half_life_days == 21
    assert settings.tool_rag_threshold == 15
    assert settings.tool_top_k == 6
    assert settings.context_health_poisoning_threshold == 0.8
    assert settings.context_health_distraction_threshold == 0.6
    assert settings.context_health_confusion_threshold == 0.45
    assert settings.context_health_clash_threshold == 0.7


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

    assert settings.openjiuwen_config_path == str(
        (tmp_path / "shared" / "openjiuwen.yaml").resolve()
    )


def test_resolve_context_agent_config_path_prefers_runtime_default(monkeypatch, tmp_path):
    runtime_config = tmp_path / ".local" / "config" / "context_agent.yaml"
    runtime_config.parent.mkdir(parents=True)
    runtime_config.write_text("http:\n  port: 8080\n", encoding="utf-8")
    repo_template = tmp_path / "config" / "context_agent.yaml"
    repo_template.parent.mkdir()
    repo_template.write_text("http:\n  port: 9000\n", encoding="utf-8")

    monkeypatch.delenv("CA_CONTEXT_AGENT_CONFIG_PATH", raising=False)
    monkeypatch.delenv("CA_SETTINGS_PATH", raising=False)
    monkeypatch.setattr(
        "context_agent.config.settings.DEFAULT_CONTEXT_AGENT_CONFIG_PATH",
        runtime_config,
    )
    monkeypatch.setattr(
        "context_agent.config.settings.REPOSITORY_CONTEXT_AGENT_TEMPLATE_PATH",
        repo_template,
    )

    assert resolve_context_agent_config_path() == runtime_config.resolve()


def test_resolve_context_agent_config_path_falls_back_to_repo_template(monkeypatch, tmp_path):
    runtime_config = tmp_path / ".local" / "config" / "context_agent.yaml"
    repo_template = tmp_path / "config" / "context_agent.yaml"
    repo_template.parent.mkdir()
    repo_template.write_text("http:\n  port: 9000\n", encoding="utf-8")

    monkeypatch.delenv("CA_CONTEXT_AGENT_CONFIG_PATH", raising=False)
    monkeypatch.delenv("CA_SETTINGS_PATH", raising=False)
    monkeypatch.setattr(
        "context_agent.config.settings.DEFAULT_CONTEXT_AGENT_CONFIG_PATH",
        runtime_config,
    )
    monkeypatch.setattr(
        "context_agent.config.settings.REPOSITORY_CONTEXT_AGENT_TEMPLATE_PATH",
        repo_template,
    )

    assert resolve_context_agent_config_path() == repo_template.resolve()
