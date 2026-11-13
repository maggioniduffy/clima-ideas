"""Shared pytest fixtures."""

import pytest

_DROP = (
    "GITHUB_ACTIONS",
    "FORCE_COLOR",
    "PY_COLORS",
    "TTY_COMPATIBLE",
    "TTY_INTERACTIVE",
)


@pytest.fixture(autouse=True)
def plain_terminal(monkeypatch):
    """Force plain, unwrapped CLI output.

    GitHub Actions makes rich/typer emit ANSI colour (it detects
    ``GITHUB_ACTIONS``), which splits option names like ``--mode`` in
    ``--help`` output and breaks substring assertions.
    """
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", "200")
    for name in _DROP:
        monkeypatch.delenv(name, raising=False)
