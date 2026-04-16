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

    payload = tools.market_cap_weights(["spy", "aapl"], api_key="key")

    rows_by_ticker = {row["ticker"]: row for row in payload["rows"]}
    assert payload["total_market_cap"] == pytest.approx(300)
    assert rows_by_ticker["AAPL"]["weight"] == pytest.approx(1.0)
    assert rows_by_ticker["SPY"]["weight"] is None
    assert rows_by_ticker["SPY"]["note"] == "Market cap unavailable - ETF"
    assert rows_by_ticker["SPY"]["valuation_method"] is None
    assert payload["missing"] == ["SPY"]


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
