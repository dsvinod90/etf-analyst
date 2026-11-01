import json
from pathlib import Path

import pytest

from etf_analyst import screen, yahoo
from tests.helpers import chart_response


@pytest.fixture
def fake_yahoo(monkeypatch: pytest.MonkeyPatch) -> None:
    prices = [100.0 + i for i in range(300)]
    monkeypatch.setattr(yahoo, "get_json", lambda url: chart_response(prices))


@pytest.mark.usefixtures("fake_yahoo")
def test_run_screen_scores_requested_tickers_and_records_errors(tmp_reports: Path) -> None:
    out = screen.run_screen(["VOO", "SPY", "../BAD"], top=1)
    assert out["mode"] == "tickers"
    assert out["candidates_analyzed"] == 2
    assert len(out["long_term_picks"]) == 1
    assert out["errors"] == {"../BAD": "invalid ticker symbol"}
    assert "saved_to" not in out


@pytest.mark.usefixtures("fake_yahoo")
def test_run_screen_saves_every_fund_when_asked(tmp_reports: Path) -> None:
    out = screen.run_screen(["VOO", "SPY"], top=1, save=True)
    saved_path = Path(out["saved_to"])
    assert saved_path.parent == tmp_reports / "data"
    saved = json.loads(saved_path.read_text())
    assert {e["ticker"] for e in saved["all_etfs"]} == {"VOO", "SPY"}
    assert saved["saved_to"] == out["saved_to"]


@pytest.mark.usefixtures("fake_yahoo", "tmp_reports")
def test_main_splits_ticker_lists_and_prints_json(capsys: pytest.CaptureFixture[str]) -> None:
    screen.main(["voo,spy", "--top", "5"])
    out = json.loads(capsys.readouterr().out)
    assert {e["ticker"] for e in out["long_term_picks"]} == {"VOO", "SPY"}
