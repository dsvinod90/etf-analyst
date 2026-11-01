import json
from pathlib import Path

import pytest

import verify_tables as vt

ETFS: dict[str, vt.ETF] = {
    "VOO": {
        "ticker": "VOO",
        "price": 694.81,
        "cagr_pct": {"5y": 12.01, "10y": 15.42},
        "volatility_1y_pct": 12.76,
        "volatility_5y_pct": 16.89,
        "max_drawdown_5y_pct": -24.52,
        "expense_ratio_pct": 0.03,
        "ttm_dividend_yield_pct": 1.07,
        "total_return_pct": {"1m": -1.07, "3m": 0.03},
        "price_vs_sma200_pct": 3.67,
        "rsi_14": 40.3,
    },
}

REPORT = """# Report

| Tier | Ticker | Price | 10y CAGR | Volatility (1y / 5y) | Max DD | Expense |
|---|---|---|---|---|---|---|
| Core | **VOO** | $694.81 | 15.4% | 12.8% / 16.9% | −24.5% | 0.03% |
"""


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("10y CAGR", 15.42),
        ("3m", 0.03),
        ("Max DD (5y)", -24.52),
        ("Expense ratio", 0.03),
        ("RSI (14)", 40.3),
        ("vs 200-day avg", 3.67),
        ("**Price**", 694.81),
    ],
)
def test_column_for_maps_headers_to_fields(header: str, expected: float) -> None:
    column = vt.column_for(header)
    assert column is not None
    assert column.getters[0](ETFS["VOO"]) == expected


def test_descriptive_columns_are_not_checked() -> None:
    assert vt.column_for("Name") is None
    assert vt.column_for("Theme") is None


def test_volatility_without_window_matches_either() -> None:
    column = vt.column_for("Volatility")
    assert column is not None
    assert column.any_of


def test_number_texts_normalizes_signs_and_symbols() -> None:
    assert vt.number_texts("−24.52%") == ["-24.52"]
    assert vt.number_texts("**$1,729.30**") == ["1729.30"]
    assert vt.number_texts("12.8% / 16.9%") == ["12.8", "16.9"]


@pytest.mark.parametrize(
    ("reported", "actual", "text", "ok"),
    [
        (15.4, 15.42, "15.4", True),  # rounded to 1 decimal
        (15.4, 15.46, "15.4", False),
        (694.81, 694.81, "694.81", True),
        (0.03, 0.04, "0.03", True),  # always allow about a cent
        (0.03, 0.05, "0.03", False),
    ],
)
def test_close_enough_allows_rounding_only(
    reported: float, actual: float, text: str, ok: bool
) -> None:
    assert vt.close_enough(reported, actual, text) is ok


def test_tables_parses_headers_and_rows() -> None:
    [(headers, rows)] = list(vt.tables(REPORT))
    assert headers[1] == "Ticker"
    assert rows[0][1] == "**VOO**"


def test_check_report_matches_a_correct_report() -> None:
    result = vt.check_report(REPORT, ETFS)
    assert result.checked == 6  # price, CAGR, 2 x volatility, drawdown, expense
    assert result.accuracy_pct == 100.0
    assert not result.mismatches


def test_check_report_catches_a_wrong_number() -> None:
    result = vt.check_report(REPORT.replace("15.4%", "16.4%"), ETFS)
    assert result.matched == 5
    assert result.mismatches == [
        {"ticker": "VOO", "column": "10y CAGR", "reported": "16.4", "actual": [15.42]}
    ]


def test_unknown_tickers_are_unverifiable() -> None:
    result = vt.check_report(REPORT.replace("VOO", "ABCD"), ETFS)
    assert result.checked == 0
    assert result.accuracy_pct is None
    assert {u["reason"] for u in result.unverifiable} == {"ticker not in data file"}


# --- path confinement --------------------------------------------------------------------


def test_in_dir_accepts_files_inside_base(tmp_path: Path) -> None:
    (tmp_path / "r.md").write_text("x")
    assert vt.in_dir(tmp_path / "r.md", tmp_path, ".md", "report") == (tmp_path / "r.md").resolve()


@pytest.mark.parametrize("path", ["/etc/passwd", "../outside.md", "inside.txt"])
def test_in_dir_refuses_other_paths(path: str, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        vt.in_dir(tmp_path / path if not path.startswith("/") else path, tmp_path, ".md", "report")


def test_find_data_file_ignores_paths_outside_the_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    real = data_dir / "etf-data-1.json"
    real.write_text(json.dumps({"all_etfs": []}))
    secret = tmp_path / "secret.json"
    secret.write_text("{}")
    report = tmp_path / "report.md"
    report.write_text(f"**Data file:** `{secret}`")
    monkeypatch.setattr(vt, "DATA_DIR", data_dir)

    assert vt.find_data_file(report, report.read_text()) == real


def test_main_checks_a_report_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data = data_dir / "etf-data-1.json"
    data.write_text(json.dumps({"generated_at": "now", "all_etfs": list(ETFS.values())}))
    report = tmp_path / "etf-report.md"
    report.write_text(f"**Data file:** `{data}`\n\n{REPORT}")
    monkeypatch.setattr(vt, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(vt, "DATA_DIR", data_dir)

    vt.main([str(report)])
    out = json.loads(capsys.readouterr().out)
    assert out["data_file"] == str(data.resolve())
    assert out["numeric_accuracy_pct"] == 100.0
    assert out["note"] is None


def test_main_refuses_a_data_file_outside_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "r.md"
    report.write_text(REPORT)
    monkeypatch.setattr(vt, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(vt, "DATA_DIR", tmp_path / "data")
    with pytest.raises(SystemExit):
        vt.main([str(report), "--data", "/etc/hosts.json"])
