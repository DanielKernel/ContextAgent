"""Tests for upgrade-time config migration helpers."""

from __future__ import annotations

from context_agent.config.migration import merge_missing_values, migrate_config_file


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
