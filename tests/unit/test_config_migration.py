"""Tests for upgrade-time config migration helpers."""

from __future__ import annotations

from context_agent.config.migration import (
    merge_missing_values,
    merge_preserving_existing,
    migrate_config_file,
)


def test_merge_missing_values_only_inserts_absent_keys():
    existing = {
        "http_port": 9000,
        "auth_enabled": False,
        "nested": {
            "present": "keep-me",
        },
    }
    defaults = {
        "http_port": 8080,
        "log_level": "INFO",
        "nested": {
            "present": "default",
            "missing": "add-me",
        },
    }

    merged, inserted = merge_missing_values(existing, defaults)

    assert merged["http_port"] == 9000
    assert merged["log_level"] == "INFO"
    assert merged["nested"]["present"] == "keep-me"
    assert merged["nested"]["missing"] == "add-me"
    assert inserted == ["log_level", "nested.missing"]


def test_migrate_config_file_preserves_existing_values(tmp_path):
    target = tmp_path / "context_agent.yaml"
    template = tmp_path / "template.yaml"
    target.write_text("http:\n  port: 9000\n", encoding="utf-8")
    template.write_text("http:\n  port: 8080\nservice:\n  log_level: INFO\n", encoding="utf-8")

    result = migrate_config_file(target, template)

    assert result["mode"] == "merged"
    assert result["inserted_paths"] == ["service"]
    target_text = target.read_text(encoding="utf-8")
    assert "port: 9000" in target_text
    assert "log_level: INFO" in target_text


def test_migrate_config_file_creates_target_from_template(tmp_path):
    target = tmp_path / "openjiuwen.yaml"
    template = tmp_path / "template.yaml"
    template.write_text("user_id: context-agent\n", encoding="utf-8")

    result = migrate_config_file(target, template)

    assert result["mode"] == "created"
    assert target.read_text(encoding="utf-8").strip() == "user_id: context-agent"


def test_merge_preserving_existing_can_replace_vector_store_only():
    existing = {
        "user_id": "custom-user",
        "llm_config": {
            "model": "custom-model",
            "api_key": "${CUSTOM_KEY}",
        },
        "embedding_config": {
            "model": "custom-embedding",
        },
        "vector_store": {
            "backend": "qdrant",
            "host": "10.0.0.8",
        },
    }
    defaults = {
        "user_id": "context-agent",
        "llm_config": {
            "model": "${CTXLLM_MODEL}",
            "timeout": 30,
        },
        "embedding_config": {
            "model": "${EMBED_MODEL}",
            "dimension": 1024,
        },
        "vector_store": {
            "backend": "pgvector",
            "dsn": "postgresql://postgres@127.0.0.1:55432/context_agent",
        },
        "memory_config": {
            "top_k": 10,
        },
    }

    merged, inserted = merge_preserving_existing(
        existing,
        defaults,
        replace_top_level_keys={"vector_store"},
    )

    assert merged["user_id"] == "custom-user"
    assert merged["llm_config"]["model"] == "custom-model"
    assert merged["llm_config"]["api_key"] == "${CUSTOM_KEY}"
    assert merged["llm_config"]["timeout"] == 30
    assert merged["embedding_config"]["model"] == "custom-embedding"
    assert merged["embedding_config"]["dimension"] == 1024
    assert merged["vector_store"] == defaults["vector_store"]
    assert merged["memory_config"] == {"top_k": 10}
    assert "memory_config" in inserted


def test_migrate_config_file_can_replace_top_level_keys(tmp_path):
    target = tmp_path / "openjiuwen.yaml"
    template = tmp_path / "template.yaml"
    target.write_text(
        "\n".join(
            [
                "llm_config:",
                "  model: custom-model",
                "vector_store:",
                "  backend: qdrant",
                "  host: 10.0.0.8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    template.write_text(
        "\n".join(
            [
                "llm_config:",
                "  model: ${CTXLLM_MODEL}",
                "  timeout: 30",
                "vector_store:",
                "  backend: pgvector",
                "  dsn: postgresql://postgres@127.0.0.1:55432/context_agent",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = migrate_config_file(
        target,
        template,
        replace_top_level_keys={"vector_store"},
    )

    assert result["mode"] == "merged"
    text = target.read_text(encoding="utf-8")
    assert "model: custom-model" in text
    assert "timeout: 30" in text
    assert "backend: pgvector" in text
    assert "dsn: postgresql://postgres@127.0.0.1:55432/context_agent" in text
    assert "host: 10.0.0.8" not in text
