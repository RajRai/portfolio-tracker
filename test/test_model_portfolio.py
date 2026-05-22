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


def _capturing_report_writer(captured):
    def writer(*args, output, **kwargs):
        captured["portfolio_name"] = getattr(args[0], "name", None) if args else None
        benchmark = kwargs.get("benchmark")
        captured["benchmark_name"] = getattr(benchmark, "name", None)
        captured["benchmark_index_name"] = getattr(getattr(benchmark, "index", None), "name", None)
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

    return writer


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
            "endDate": "2026-01-04",
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
    assert payload["effectiveEndDate"] == "2026-01-04"
    assert payload["warnings"] == [
        "The selected start date, 2026-01-01, was not a market trading day, so the report starts on 2026-01-02."
    ]
    assert payload["rangeInfo"]["symbolRanges"] == [
        {
            "ticker": "AAA",
            "scope": "portfolio",
            "firstDate": "2026-01-02",
            "lastDate": "2026-01-04",
            "limitsStart": False,
            "limitsEnd": False,
        },
        {
            "ticker": "BBB",
            "scope": "portfolio",
            "firstDate": "2026-01-02",
            "lastDate": "2026-01-04",
            "limitsStart": False,
            "limitsEnd": False,
        },
        {
            "ticker": "VT",
            "scope": "benchmark",
            "firstDate": "2026-01-02",
            "lastDate": "2026-01-04",
            "limitsStart": False,
            "limitsEnd": False,
        },
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
            "endDate": "2026-02-05",
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


def test_normalize_weighted_holdings_defaults_missing_weight_to_one():
    holdings = model_portfolio._normalize_weighted_holdings(
        [
            {"ticker": "AAA"},
            {"ticker": "BBB", "weight": 2},
            {"ticker": "AAA"},
        ],
        "portfolio",
    )

    assert holdings == [
        {"ticker": "AAA", "weight": pytest.approx(0.5)},
        {"ticker": "BBB", "weight": pytest.approx(0.5)},
    ]


def test_build_buy_and_hold_basket_supports_daily_rebalancing():
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 20.0, 20.0],
            "BBB": [10.0, 10.0, 20.0],
        },
        index=pd.to_datetime(["2026-03-03", "2026-03-04", "2026-03-05"]),
    )
    asset_returns = pd.DataFrame(
        {
            "AAA": [0.0, 1.0, 0.0],
            "BBB": [0.0, 0.0, 1.0],
        },
        index=prices.index,
    )
    holdings = [
        {"ticker": "AAA", "weight": 0.5},
        {"ticker": "BBB", "weight": 0.5},
    ]

    drifting = model_portfolio._build_buy_and_hold_basket(
        prices,
        holdings,
        asset_returns,
        pd.Timestamp("2026-03-03"),
        rebalance_period="none",
    )
    rebalanced = model_portfolio._build_buy_and_hold_basket(
        prices,
        holdings,
        asset_returns,
        pd.Timestamp("2026-03-03"),
        rebalance_period="daily",
    )

    assert drifting["returns"].loc[pd.Timestamp("2026-03-05")] == pytest.approx(1 / 3)
    assert rebalanced["returns"].loc[pd.Timestamp("2026-03-05")] == pytest.approx(0.5)
    assert rebalanced["weights_df"].loc[pd.Timestamp("2026-03-05"), "AAA"] == pytest.approx(0.5)
    assert rebalanced["weights_df"].loc[pd.Timestamp("2026-03-05"), "BBB"] == pytest.approx(0.5)


def test_build_buy_and_hold_basket_supports_weekly_rebalancing():
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 20.0, 20.0],
            "BBB": [10.0, 10.0, 20.0],
        },
        index=pd.to_datetime(["2026-03-05", "2026-03-06", "2026-03-09"]),
    )
    asset_returns = pd.DataFrame(
        {
            "AAA": [0.0, 1.0, 0.0],
            "BBB": [0.0, 0.0, 1.0],
        },
        index=prices.index,
    )
    holdings = [
        {"ticker": "AAA", "weight": 0.5},
        {"ticker": "BBB", "weight": 0.5},
    ]

    weekly = model_portfolio._build_buy_and_hold_basket(
        prices,
        holdings,
        asset_returns,
        pd.Timestamp("2026-03-05"),
        rebalance_period="weekly",
    )

    assert weekly["weights_df"].loc[pd.Timestamp("2026-03-06"), "AAA"] == pytest.approx(0.5)
    assert weekly["weights_df"].loc[pd.Timestamp("2026-03-06"), "BBB"] == pytest.approx(0.5)
    assert weekly["returns"].loc[pd.Timestamp("2026-03-09")] == pytest.approx(0.5)


def test_create_model_portfolio_report_rebalances_strategy_and_benchmark_independently(monkeypatch, tmp_path):
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 20.0, 20.0],
            "BBB": [10.0, 10.0, 20.0],
        },
        index=pd.to_datetime(["2026-03-03", "2026-03-04", "2026-03-05"]),
    )

    monkeypatch.setattr(model_portfolio, "get_polygon_prices", lambda symbols, start, end: prices[symbols].copy())
    monkeypatch.setattr(model_portfolio, "get_polygon_dividends", lambda symbols, start, end: pd.DataFrame(columns=symbols))
    monkeypatch.setattr(model_portfolio.qs.reports, "html", _fake_report_writer)

    payload = model_portfolio.create_model_portfolio_report(
        {
            "reportName": "Independent Rebalance",
            "startDate": "2026-03-03",
            "endDate": "2026-03-05",
            "portfolioRebalancePeriod": "none",
            "benchmarkRebalancePeriod": "daily",
            "holdings": [
                {"ticker": "AAA", "weight": 50},
                {"ticker": "BBB", "weight": 50},
            ],
            "benchmark": {
                "mode": "portfolio",
                "label": "Equal Weight Benchmark",
                "holdings": [
                    {"ticker": "AAA", "weight": 50},
                    {"ticker": "BBB", "weight": 50},
                ],
            },
        },
        out_dir=tmp_path,
    )

    interactive_path = next((tmp_path / "tool-model-portfolios").glob("report_*_interactive.json"))
    interactive_payload = json.loads(interactive_path.read_text(encoding="utf-8"))

    assert payload["portfolioRebalancePeriod"] == "none"
    assert payload["benchmarkRebalancePeriod"] == "daily"
    assert interactive_payload["meta"]["portfolio_rebalance_period"] == "none"
    assert interactive_payload["meta"]["benchmark_rebalance_period"] == "daily"
    assert interactive_payload["portfolio"]["daily"][-1]["v"] == pytest.approx(1 / 3)
    assert interactive_payload["benchmark"]["daily"][-1]["v"] == pytest.approx(0.5)


def test_create_model_portfolio_report_applies_start_date_market_cap_weighting_to_portfolio_and_benchmark(monkeypatch, tmp_path):
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 11.0, 12.0],
            "BBB": [20.0, 21.0, 22.0],
            "CCC": [30.0, 31.0, 32.0],
        },
        index=pd.to_datetime(["2026-03-03", "2026-03-04", "2026-03-05"]),
    )
    estimate_calls = []

    monkeypatch.setattr(model_portfolio, "get_polygon_prices", lambda symbols, start, end: prices[symbols].copy())
    monkeypatch.setattr(model_portfolio, "get_polygon_dividends", lambda symbols, start, end: pd.DataFrame(columns=symbols))
    monkeypatch.setattr(model_portfolio.qs.reports, "html", _fake_report_writer)

    def fake_estimate_market_cap_weights(tickers, latest_prices, as_of_prices, api_key=None):
        estimate_calls.append((tuple(tickers), dict(latest_prices), dict(as_of_prices)))
        if tuple(tickers) == ("AAA", "BBB"):
            return {
                "rows": [
                    {"ticker": "AAA", "weight": 0.8},
                    {"ticker": "BBB", "weight": 0.2},
                ],
                "missing": [],
            }
        return {
            "rows": [
                {"ticker": "BBB", "weight": 0.25},
                {"ticker": "CCC", "weight": 0.75},
            ],
            "missing": [],
        }

    monkeypatch.setattr(model_portfolio, "estimate_market_cap_weights", fake_estimate_market_cap_weights)

    payload = model_portfolio.create_model_portfolio_report(
        {
            "reportName": "Market Cap Model",
            "startDate": "2026-03-03",
            "endDate": "2026-03-05",
            "weightingMode": "market_cap_start",
            "holdings": [
                {"ticker": "AAA", "weight": 60},
                {"ticker": "BBB", "weight": 40},
            ],
            "benchmark": {
                "mode": "portfolio",
                "label": "Benchmark Cap Weight",
                "weightingMode": "market_cap_start",
                "holdings": [
                    {"ticker": "BBB", "weight": 70},
                    {"ticker": "CCC", "weight": 30},
                ],
            },
        },
        out_dir=tmp_path,
    )

    assert [call[0] for call in estimate_calls] == [("AAA", "BBB"), ("BBB", "CCC")]
    assert payload["warnings"] == [
        "Portfolio weights were estimated from current market caps scaled to 2026-03-03 using the historical/current price ratio.",
        "Benchmark weights were estimated from current market caps scaled to 2026-03-03 using the historical/current price ratio.",
    ]

    trades_path = next((tmp_path / "tool-model-portfolios").glob("trades_*.csv"))
    trades = pd.read_csv(trades_path)
    assert trades["Trade Size (% of Account)"].tolist() == ["80.00%", "20.00%"]


def test_create_model_portfolio_report_falls_back_to_entered_weights_when_market_cap_estimate_is_unavailable(monkeypatch, tmp_path):
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 11.0, 12.0],
            "BBB": [20.0, 21.0, 22.0],
            "VT": [100.0, 101.0, 102.0],
        },
        index=pd.to_datetime(["2026-04-06", "2026-04-07", "2026-04-08"]),
    )

    monkeypatch.setattr(model_portfolio, "get_polygon_prices", lambda symbols, start, end: prices[symbols].copy())
    monkeypatch.setattr(model_portfolio, "get_polygon_dividends", lambda symbols, start, end: pd.DataFrame(columns=symbols))
    monkeypatch.setattr(model_portfolio.qs.reports, "html", _fake_report_writer)
    monkeypatch.setattr(
        model_portfolio,
        "estimate_market_cap_weights",
        lambda tickers, latest_prices, as_of_prices, api_key=None: {
            "rows": [
                {"ticker": "AAA", "weight": None},
                {"ticker": "BBB", "weight": None},
            ],
            "missing": ["AAA", "BBB"],
        },
    )

    payload = model_portfolio.create_model_portfolio_report(
        {
            "reportName": "Fallback Model",
            "startDate": "2026-04-06",
            "endDate": "2026-04-08",
            "weightingMode": "market_cap_start",
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

    assert payload["warnings"] == [
        "Portfolio kept the entered weights because start-date market cap weighting was unavailable for: AAA, BBB."
    ]

    trades_path = next((tmp_path / "tool-model-portfolios").glob("trades_*.csv"))
    trades = pd.read_csv(trades_path)
    assert trades["Trade Size (% of Account)"].tolist() == ["60.00%", "40.00%"]


def test_create_model_portfolio_report_names_quantstats_benchmark(monkeypatch, tmp_path):
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 11.0, 12.0],
            "VT": [100.0, 101.0, 102.0],
        },
        index=pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03"]),
    )
    captured = {}

    monkeypatch.setattr(model_portfolio, "get_polygon_prices", lambda symbols, start, end: prices[symbols].copy())
    monkeypatch.setattr(model_portfolio, "get_polygon_dividends", lambda symbols, start, end: pd.DataFrame(columns=symbols))
    monkeypatch.setattr(model_portfolio.qs.reports, "html", _capturing_report_writer(captured))

    model_portfolio.create_model_portfolio_report(
        {
            "reportName": "Benchmark Naming",
            "startDate": "2026-07-01",
            "endDate": "2026-07-03",
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

    assert captured["portfolio_name"] == "Benchmark Naming"
    assert captured["benchmark_name"] == "VT"
    assert captured["benchmark_index_name"] is None


def test_create_model_portfolio_report_reports_symbols_that_limit_the_common_window(monkeypatch, tmp_path):
    prices = pd.DataFrame(
        {
            "AAA": [None, 10.0, 11.0, 12.0, None],
            "BBB": [20.0, 21.0, 22.0, 23.0, 24.0],
            "VT": [100.0, 101.0, 102.0, 103.0, 104.0],
        },
        index=pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]),
    )

    monkeypatch.setattr(model_portfolio, "get_polygon_prices", lambda symbols, start, end: prices[symbols].copy())
    monkeypatch.setattr(model_portfolio, "get_polygon_dividends", lambda symbols, start, end: pd.DataFrame(columns=symbols))
    monkeypatch.setattr(model_portfolio.qs.reports, "html", _fake_report_writer)

    payload = model_portfolio.create_model_portfolio_report(
        {
            "reportName": "Range Limits",
            "startDate": "2026-06-01",
            "endDate": "2026-06-05",
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

    assert payload["effectiveStartDate"] == "2026-06-02"
    assert payload["effectiveEndDate"] == "2026-06-04"
    assert payload["warnings"] == [
        "The report starts on 2026-06-02 because these symbols did not have price history on 2026-06-01: AAA.",
        "The report ends on 2026-06-04 because these symbols did not have price history on 2026-06-05: AAA.",
    ]
    assert payload["rangeInfo"] == {
        "requestedStartDate": "2026-06-01",
        "effectiveStartDate": "2026-06-02",
        "requestedEndDate": "2026-06-05",
        "effectiveEndDate": "2026-06-04",
        "startLimitedBy": ["AAA"],
        "endLimitedBy": ["AAA"],
        "symbolRanges": [
            {
                "ticker": "AAA",
                "scope": "portfolio",
                "firstDate": "2026-06-02",
                "lastDate": "2026-06-04",
                "limitsStart": True,
                "limitsEnd": True,
            },
            {
                "ticker": "BBB",
                "scope": "portfolio",
                "firstDate": "2026-06-01",
                "lastDate": "2026-06-05",
                "limitsStart": False,
                "limitsEnd": False,
            },
            {
                "ticker": "VT",
                "scope": "benchmark",
                "firstDate": "2026-06-01",
                "lastDate": "2026-06-05",
                "limitsStart": False,
                "limitsEnd": False,
            },
        ],
    }


def test_create_model_portfolio_report_can_follow_full_historical_weight_path(monkeypatch, tmp_path):
    prices = pd.DataFrame(
        {
            "AAA": [10.0, 20.0, 20.0],
            "BBB": [10.0, 10.0, 20.0],
            "VT": [100.0, 100.0, 100.0],
        },
        index=pd.to_datetime(["2026-03-03", "2026-03-04", "2026-03-05"]),
    )

    monkeypatch.setattr(model_portfolio, "get_polygon_prices", lambda symbols, start, end: prices[symbols].copy())
    monkeypatch.setattr(model_portfolio, "get_polygon_dividends", lambda symbols, start, end: pd.DataFrame(columns=symbols))
    monkeypatch.setattr(model_portfolio.qs.reports, "html", _fake_report_writer)

    payload = model_portfolio.create_model_portfolio_report(
        {
            "reportName": "Historical Weight Path",
            "startDate": "2026-01-01",
            "endDate": "2026-12-31",
            "portfolioHistoryWindow": {
                "startDate": "2026-03-03",
                "endDate": "2026-03-05",
            },
            "portfolioWeightHistory": [
                {
                    "ticker": "AAA",
                    "points": [
                        {"date": "2026-03-03", "weight": 1.0},
                        {"date": "2026-03-04", "weight": 0.0},
                        {"date": "2026-03-05", "weight": 0.0},
                    ],
                },
                {
                    "ticker": "BBB",
                    "points": [
                        {"date": "2026-03-03", "weight": 0.0},
                        {"date": "2026-03-04", "weight": 1.0},
                        {"date": "2026-03-05", "weight": 1.0},
                    ],
                },
            ],
            "holdings": [
                {"ticker": "AAA", "weight": 50},
                {"ticker": "BBB", "weight": 50},
            ],
            "benchmark": {
                "mode": "ticker",
                "ticker": "VT",
            },
        },
        out_dir=tmp_path,
    )

    interactive_path = next((tmp_path / "tool-model-portfolios").glob("report_*_interactive.json"))
    interactive_payload = json.loads(interactive_path.read_text(encoding="utf-8"))
    trades_path = next((tmp_path / "tool-model-portfolios").glob("trades_*.csv"))
    trades = pd.read_csv(trades_path)

    assert payload["effectiveStartDate"] == "2026-03-03"
    assert payload["effectiveEndDate"] == "2026-03-05"
    assert payload["warnings"] == []
    assert [point["v"] for point in interactive_payload["portfolio"]["daily"]] == pytest.approx([0.0, 1.0, 1.0])
    assert interactive_payload["weights"][0]["name"] == "AAA"
    assert interactive_payload["weights"][1]["name"] == "BBB"
    assert trades["Trade Size (% of Account)"].tolist() == ["100.00%", "100.00%", "100.00%"]
