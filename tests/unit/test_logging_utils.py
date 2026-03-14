"""Tests for logging configuration helpers."""

from __future__ import annotations

import logging

import pytest

from context_agent.utils.logging import _should_use_colors, configure_logging


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


def test_configure_logging_quiets_http_clients():
    configure_logging("INFO")

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_configure_logging_renders_plain_exceptions_without_ansi(capsys: pytest.CaptureFixture[str]):
    configure_logging("INFO")

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logging.getLogger("context-agent-test").exception("failure")

    output = capsys.readouterr().out

    assert "\x1b[" not in output
    assert "RuntimeError: boom" in output
    assert "locals" not in output
