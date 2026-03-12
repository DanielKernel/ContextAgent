"""Tests for logging configuration helpers."""

from __future__ import annotations

from context_agent.utils.logging import _should_use_colors


class _Stream:
    def __init__(self, is_tty: bool):
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def test_should_use_colors_for_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert _should_use_colors(_Stream(True)) is True


def test_should_not_use_colors_for_non_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert _should_use_colors(_Stream(False)) is False


def test_no_color_overrides_tty(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert _should_use_colors(_Stream(True)) is False


def test_force_color_overrides_no_tty(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert _should_use_colors(_Stream(False)) is True
