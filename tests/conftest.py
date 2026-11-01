import socket
from pathlib import Path
from typing import Any, NoReturn

import pytest

from etf_analyst import paths


class NetworkBlockedError(RuntimeError):
    """A test tried to use the network. Mock the call instead (e.g. ``yahoo.get_json``)."""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that opens a network connection or does a DNS lookup.

    Tests must be fast, deterministic and offline, so every external call is mocked. This
    guard makes a forgotten mock fail loudly instead of quietly calling Yahoo Finance.
    """

    def blocked(*args: Any, **kwargs: Any) -> NoReturn:
        raise NetworkBlockedError(
            "tests must not use the network; monkeypatch yahoo.get_json (or the caller) instead"
        )

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def tmp_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the package's reports/ and reports/data/ at a temporary directory."""
    reports = tmp_path / "reports"
    (reports / "data").mkdir(parents=True)
    monkeypatch.setattr(paths, "REPORTS_DIR", reports)
    monkeypatch.setattr(paths, "DATA_DIR", reports / "data")
    return reports
