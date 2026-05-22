import csv
from types import SimpleNamespace

import pandas as pd
import pytest

from src import tools, yfinance_cache
from src.reports import polygon


def test_normalize_tickers_dedupes_and_splits():
    assert tools.normalize_tickers(" aapl, msft;AAPL $brk.b bad/ticker ") == ["AAPL", "MSFT", "BRK.B"]


def test_yfinance_cache_location_is_shared():
    assert yfinance_cache.YFINANCE_CACHE_DIR.name == "yfinance"
    assert yfinance_cache.YFINANCE_CACHE_DIR.parent.name == ".cache"
    assert yfinance_cache.YFINANCE_CACHE_DIR.parent.parent.name == "data"
    assert polygon.YFINANCE_CACHE_DIR == yfinance_cache.YFINANCE_CACHE_DIR
    assert polygon.YFINANCE_HISTORY_CACHE_DIR == yfinance_cache.YFINANCE_HISTORY_CACHE_DIR
    assert tools.yf is yfinance_cache.yf


def test_portfolio_source_reads_weights_file(tmp_path):
    weights_path = tmp_path / "weights_0.csv"
    with open(weights_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Ticker", "Portfolio Weight (%)", "_Quantity"])
        writer.writeheader()
        writer.writerow({"Ticker": "AAPL", "Portfolio Weight (%)": "60.00%", "_Quantity": "10"})
        writer.writerow({"Ticker": "MSFT", "Portfolio Weight (%)": "40.00%", "_Quantity": "5"})

    payload = tools.portfolio_source(
        "acct",
        [{"id": "acct", "name": "Test Portfolio", "weights": "/data/weights_0.csv"}],
        tmp_path,
    )

    assert payload["source"]["label"] == "Test Portfolio"
    assert payload["tickers"] == ["AAPL", "MSFT"]
    assert payload["holdings"][0]["source_weight"] == pytest.approx(0.6)
    assert payload["holdings"][1]["quantity"] == pytest.approx(5.0)


def test_portfolio_source_can_return_full_weight_history_and_history_window_from_report(tmp_path):
    weights_path = tmp_path / "weights_0.csv"
    interactive_path = tmp_path / "report_0_interactive.json"
    with open(weights_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Ticker", "Portfolio Weight (%)", "_Quantity"])
        writer.writeheader()
        writer.writerow({"Ticker": "AAPL", "Portfolio Weight (%)": "55.00%", "_Quantity": "10"})
        writer.writerow({"Ticker": "MSFT", "Portfolio Weight (%)": "45.00%", "_Quantity": "5"})
    interactive_path.write_text(
        """
{
  "portfolio": {
    "daily": [
      {"t": "2026-01-02", "v": 0.0},
      {"t": "2026-01-05", "v": 0.01}
    ]
  },
  "weights": [
    {
      "name": "AAPL",
      "points": [
        {"t": "2026-01-02", "v": 0.7},
        {"t": "2026-01-05", "v": 0.55}
      ]
    },
    {
      "name": "MSFT",
      "points": [
        {"t": "2026-01-02", "v": 0.3},
        {"t": "2026-01-05", "v": 0.45}
      ]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    payload = tools.portfolio_source(
        "acct",
        [{"id": "acct", "name": "Test Portfolio", "weights": "/data/weights_0.csv", "report": "/reports/report_0.html"}],
        tmp_path,
        infer_historical_weights=True,
    )

    assert payload["source"]["weightSource"] == "historical"
    assert payload["source"]["historyWindow"] == {
        "startDate": "2026-01-02",
        "endDate": "2026-01-05",
    }
    assert payload["tickers"] == ["AAPL", "MSFT"]
    assert payload["holdings"][0]["source_weight"] == pytest.approx(0.55)
    assert payload["holdings"][1]["source_weight"] == pytest.approx(0.45)
    assert payload["weightHistory"] == [
        {
            "ticker": "AAPL",
            "points": [
                {"date": "2026-01-02", "weight": pytest.approx(0.7)},
                {"date": "2026-01-05", "weight": pytest.approx(0.55)},
            ],
        },
        {
            "ticker": "MSFT",
            "points": [
                {"date": "2026-01-02", "weight": pytest.approx(0.3)},
                {"date": "2026-01-05", "weight": pytest.approx(0.45)},
            ],
        },
    ]


def test_stock_source_rejects_fund_source(tmp_path):
    with pytest.raises(tools.ToolDataError, match="Index fund loading was removed"):
        tools.stock_source({"sourceType": "fund", "fundTicker": "SPY"}, [], tmp_path, api_key="key")


def test_market_cap_weights_calculates_percentages(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_fetch_ticker_overviews",
        lambda tickers, api_key=None: {
            "AAPL": {"name": "Apple Inc", "market_cap": 300},
            "MSFT": {"name": "Microsoft Corp", "market_cap": 100},
            "MISSING": {"name": "Missing Co"},
        },
    )
    monkeypatch.setattr(tools, "_fetch_yfinance_market_caps", lambda tickers: {})

    payload = tools.market_cap_weights(["aapl", "msft", "aapl", "missing"], api_key="key")

    assert payload["total_market_cap"] == pytest.approx(400)
    assert payload["rows"][0]["ticker"] == "AAPL"
    assert payload["rows"][0]["weight"] == pytest.approx(0.75)
    assert payload["rows"][0]["valuation_method"] == "Polygon market cap"
    assert payload["rows"][1]["weight"] == pytest.approx(0.25)
    assert payload["missing"] == ["MISSING"]


def test_market_cap_weights_flags_etfs_without_market_caps(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_fetch_ticker_overviews",
        lambda tickers, api_key=None: {
            "SPY": {"name": "SPDR S&P 500 ETF Trust", "type": "ETF"},
            "AAPL": {"name": "Apple Inc", "market_cap": 300},
        },
    )
    monkeypatch.setattr(tools, "_fetch_yfinance_market_caps", lambda tickers: {})

    payload = tools.market_cap_weights(["spy", "aapl"], api_key="key")

    rows_by_ticker = {row["ticker"]: row for row in payload["rows"]}
    assert payload["total_market_cap"] == pytest.approx(300)
    assert rows_by_ticker["AAPL"]["weight"] == pytest.approx(1.0)
    assert rows_by_ticker["SPY"]["weight"] is None
    assert rows_by_ticker["SPY"]["note"] == "Market cap unavailable - ETF"
    assert rows_by_ticker["SPY"]["valuation_method"] is None
    assert payload["missing"] == ["SPY"]


def test_market_cap_weights_uses_yfinance_fallback(monkeypatch):
    yfinance_calls = []

    monkeypatch.setattr(
        tools,
        "_fetch_ticker_overviews",
        lambda tickers, api_key=None: {
            "AAPL": {"name": "Apple Inc", "market_cap": 300, "currency_name": "usd"},
            "FANUY": {"name": "Fanuc ADR"},
        },
    )

    def fake_yfinance_market_caps(tickers):
        yfinance_calls.append(tickers)
        return {
            "FANUY": {
                "name": "Fanuc Corp ADR",
                "market_cap": 100,
                "currency": "USD",
                "exchange": "PNK",
                "type": "EQUITY",
            }
        }

    monkeypatch.setattr(tools, "_fetch_yfinance_market_caps", fake_yfinance_market_caps)

    payload = tools.market_cap_weights(["aapl", "fanuy"], api_key="key")

    rows_by_ticker = {row["ticker"]: row for row in payload["rows"]}
    assert yfinance_calls == [["FANUY"]]
    assert payload["total_market_cap"] == pytest.approx(400)
    assert rows_by_ticker["AAPL"]["weight"] == pytest.approx(0.75)
    assert rows_by_ticker["FANUY"]["weight"] == pytest.approx(0.25)
    assert rows_by_ticker["FANUY"]["valuation_method"] == "Yahoo Finance market cap"
    assert rows_by_ticker["FANUY"]["exchange"] == "PNK"
    assert payload["missing"] == []


def test_estimate_market_cap_weights_scales_current_market_caps_to_start_date(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_fetch_ticker_overviews",
        lambda tickers, api_key=None: {
            "AAPL": {"name": "Apple Inc", "market_cap": 300},
            "MSFT": {"name": "Microsoft Corp", "market_cap": 100},
        },
    )
    monkeypatch.setattr(tools, "_fetch_yfinance_market_caps", lambda tickers: {})

    payload = tools.estimate_market_cap_weights(
        ["aapl", "msft"],
        latest_prices={"AAPL": 12, "MSFT": 20},
        as_of_prices={"AAPL": 10, "MSFT": 10},
        api_key="key",
    )

    rows_by_ticker = {row["ticker"]: row for row in payload["rows"]}
    assert payload["total_market_cap"] == pytest.approx(300)
    assert rows_by_ticker["AAPL"]["market_cap"] == pytest.approx(250)
    assert rows_by_ticker["AAPL"]["weight"] == pytest.approx(5 / 6)
    assert rows_by_ticker["AAPL"]["valuation_method"] == "Polygon market cap scaled by historical price ratio"
    assert rows_by_ticker["MSFT"]["market_cap"] == pytest.approx(50)
    assert rows_by_ticker["MSFT"]["weight"] == pytest.approx(1 / 6)
    assert payload["missing"] == []


def test_earnings_calendar_uses_yfinance(monkeypatch):
    calls = []

    class FakeTicker:
        def __init__(self, ticker):
            self.ticker = ticker

        def get_earnings_dates(self, limit=100):
            calls.append((self.ticker, limit))
            return pd.DataFrame(
                {
                    "EPS Estimate": [1.25],
                    "Reported EPS": [None],
                    "Surprise(%)": [None],
                },
                index=[pd.Timestamp("2026-05-01 07:00:00", tz="America/New_York")],
            )

        @property
        def calendar(self):
            return {
                "Earnings Date": [pd.Timestamp("2026-05-01").date()],
                "Revenue Average": 123000000,
            }

    monkeypatch.setattr(tools, "yf", SimpleNamespace(Ticker=FakeTicker))

    payload = tools.earnings_calendar(["AAPL", "MSFT"], "2026-04-15", "2026-05-15", api_key="key")

    assert calls == [("AAPL", 100), ("MSFT", 100)]
    assert payload["provider"] == "Yahoo Finance"
    assert payload["events"][0]["ticker"] == "AAPL"
    assert payload["events"][0]["time"] == "07:00:00"
    assert payload["events"][0]["provider"] == "Yahoo Finance"
    assert payload["events"][0]["estimated_revenue"] == pytest.approx(123000000)
    assert payload["events"][1]["ticker"] == "MSFT"
