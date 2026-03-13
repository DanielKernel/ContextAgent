"""Helpers for non-destructive config migration during upgrades."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


def load_config_mapping(path: str | Path) -> dict[str, Any]:
    """Load a YAML or JSON config file that must contain a mapping."""
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    suffix = config_path.suffix.lower()
    raw_text = config_path.read_text(encoding="utf-8")
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(raw_text) or {}
    elif suffix == ".json":
        data = json.loads(raw_text)
    else:
        raise ValueError(f"Unsupported config format: {config_path.name}")

    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping: {config_path}")
    return data


def merge_missing_values(
    existing: dict[str, Any],
    defaults: dict[str, Any],
    *,
    path_prefix: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Fill only missing keys from defaults, preserving existing user values."""
    merged = dict(existing)
    inserted_paths: list[str] = []

    for key, default_value in defaults.items():
        dotted_path = f"{path_prefix}.{key}" if path_prefix else key
        if key not in merged:
            merged[key] = default_value
            inserted_paths.append(dotted_path)
            continue

        existing_value = merged[key]
        if isinstance(existing_value, dict) and isinstance(default_value, dict):
            nested_merged, nested_paths = merge_missing_values(
                existing_value,
                default_value,
                path_prefix=dotted_path,
            )
            merged[key] = nested_merged
            inserted_paths.extend(nested_paths)

    return merged, inserted_paths


def merge_preserving_existing(
    existing: dict[str, Any],
    defaults: dict[str, Any],
    *,
    replace_top_level_keys: set[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Merge configs while preserving existing values except selected top-level keys.

    This is used when reinstall/bootstrap should keep user-tuned sections like
    ``llm_config`` and ``embedding_config`` while regenerating a backend-specific
    section such as ``vector_store``.
    """
    replaced = replace_top_level_keys or set()
    merged = dict(defaults)
    inserted_paths: list[str] = []

    for key, default_value in defaults.items():
        if key in replaced:
            if key not in existing:
                inserted_paths.append(key)
            continue

        if key not in existing:
            inserted_paths.append(key)
            continue

        existing_value = existing[key]
        if isinstance(existing_value, dict) and isinstance(default_value, dict):
            nested_merged, nested_paths = merge_missing_values(
                existing_value,
                default_value,
                path_prefix=key,
            )
            merged[key] = nested_merged
            inserted_paths.extend(nested_paths)
        else:
            merged[key] = existing_value

    for key, existing_value in existing.items():
        if key in replaced or key in merged:
            continue
        merged[key] = existing_value

    return merged, inserted_paths


def migrate_config_file(
    target_path: str | Path,
    template_path: str | Path,
    *,
    replace_top_level_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Merge missing values from a template config into a target config file."""
    target = Path(target_path).expanduser().resolve()
    template = Path(template_path).expanduser().resolve()

    defaults = load_config_mapping(template)
    if target.exists():
        existing = load_config_mapping(target)
        merged, inserted_paths = merge_preserving_existing(
            existing,
            defaults,
            replace_top_level_keys=replace_top_level_keys,
        )
        target.write_text(
            yaml.safe_dump(merged, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        return {"mode": "merged", "inserted_paths": inserted_paths, "path": str(target)}

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(defaults, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    return {"mode": "created", "inserted_paths": list(defaults.keys()), "path": str(target)}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Non-destructively migrate config files.")
    parser.add_argument("--target", required=True, help="Config file to migrate")
    parser.add_argument("--template", required=True, help="Template/default config file")
    parser.add_argument(
        "--replace-top-level-key",
        action="append",
        dest="replace_top_level_keys",
        default=[],
        help="Top-level key to regenerate from the template instead of preserving the existing value",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    result = migrate_config_file(
        args.target,
        args.template,
        replace_top_level_keys=set(args.replace_top_level_keys),
    )
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
