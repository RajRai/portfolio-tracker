import json

import pandas as pd
import pytest

from src.reports import model_portfolio
from src.tools import ToolDataError


def _fake_report_writer(*args, output, **kwargs):
    output.write_text(
        """
<!doctype html>
<html>
<head><title>Report</title></head>
<body><div class="container">stub</div></body>
</html>
""".strip(),
        encoding="utf-8",
    )


def test_create_model_portfolio_report_writes_tool_only_artifacts(monkeypatch, tmp_path):
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 11.0, 12.0],
            "BBB": [20.0, 18.0, 18.0],
            "VT": [100.0, 101.0, 102.0],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04"]),
    )

    monkeypatch.setattr(model_portfolio, "get_polygon_prices", lambda symbols, start, end: prices[symbols].copy())
    monkeypatch.setattr(model_portfolio, "get_polygon_dividends", lambda symbols, start, end: pd.DataFrame(columns=symbols))
    monkeypatch.setattr(model_portfolio.qs.reports, "html", _fake_report_writer)

    payload = model_portfolio.create_model_portfolio_report(
        {
            "reportName": "Public Model",
            "startDate": "2026-01-01",
            "holdings": [
                {"ticker": "AAA", "weight": 60},
                {"ticker": "BBB", "weight": 40},
            ],
            "benchmark": {
                "mode": "ticker",
                "ticker": "VT",
            },
        },
        out_dir=tmp_path,
    )

    assert payload["account"]["disable_live"] is True
    assert payload["account"]["report"].startswith("/reports/tool-model-portfolios/")
    assert payload["effectiveStartDate"] == "2026-01-02"
    assert payload["warnings"] == [
        "The selected start date, 2026-01-01, was not a market trading day, so the report starts on 2026-01-02."
    ]

    tool_dir = tmp_path / "tool-model-portfolios"
    assert tool_dir.exists()
    assert list(tool_dir.glob("report_*.html"))
    assert list(tool_dir.glob("report_*_interactive.json"))
    assert list(tool_dir.glob("weights_*.csv"))
    assert list(tool_dir.glob("trades_*.csv"))
    assert not (tmp_path / "accounts.json").exists()


def test_create_model_portfolio_report_supports_portfolio_benchmark(monkeypatch, tmp_path):
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 11.0, 12.0],
            "BBB": [20.0, 21.0, 22.0],
            "CCC": [30.0, 28.0, 29.0],
        },
        index=pd.to_datetime(["2026-02-03", "2026-02-04", "2026-02-05"]),
    )

    monkeypatch.setattr(model_portfolio, "get_polygon_prices", lambda symbols, start, end: prices[symbols].copy())
    monkeypatch.setattr(model_portfolio, "get_polygon_dividends", lambda symbols, start, end: pd.DataFrame(columns=symbols))
    monkeypatch.setattr(model_portfolio.qs.reports, "html", _fake_report_writer)

    payload = model_portfolio.create_model_portfolio_report(
        {
            "reportName": "Custom Benchmark",
            "startDate": "2026-02-03",
            "holdings": [
                {"ticker": "AAA", "weight": 50},
                {"ticker": "BBB", "weight": 50},
            ],
            "benchmark": {
                "mode": "portfolio",
                "label": "Equal Weight Benchmark",
                "holdings": [
                    {"ticker": "BBB", "weight": 70},
                    {"ticker": "CCC", "weight": 30},
                ],
            },
        },
        out_dir=tmp_path,
    )

    interactive_path = next((tmp_path / "tool-model-portfolios").glob("report_*_interactive.json"))
    interactive_payload = json.loads(interactive_path.read_text(encoding="utf-8"))

    assert payload["warnings"] == []
    assert interactive_payload["benchmark"]["type"] == "portfolio"
    assert interactive_payload["benchmark"]["label"] == "Equal Weight Benchmark"
    assert "ticker" not in interactive_payload["benchmark"]


def test_create_model_portfolio_report_explains_when_start_date_is_after_latest_market_date(monkeypatch, tmp_path):
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 11.0],
            "VT": [100.0, 101.0],
        },
        index=pd.to_datetime(["2026-05-15", "2026-05-16"]),
    )

    monkeypatch.setattr(model_portfolio, "get_polygon_prices", lambda symbols, start, end: prices[symbols].copy())
    monkeypatch.setattr(model_portfolio, "get_polygon_dividends", lambda symbols, start, end: pd.DataFrame(columns=symbols))
    monkeypatch.setattr(model_portfolio.qs.reports, "html", _fake_report_writer)

    with pytest.raises(ToolDataError, match=r"Try an earlier trading day\. Latest available market date was 2026-05-16\."):
        model_portfolio.create_model_portfolio_report(
            {
                "reportName": "Too Recent",
                "startDate": "2026-05-18",
                "holdings": [
                    {"ticker": "AAA", "weight": 100},
                ],
                "benchmark": {
                    "mode": "ticker",
                    "ticker": "VT",
                },
            },
            out_dir=tmp_path,
        )
