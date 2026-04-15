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


def test_fund_source_uses_polygon_etf_constituents(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_polygon_paginated",
        lambda *args, **kwargs: [
            {
                "effective_date": "2026-04-14",
                "processed_date": "2026-04-15",
                "constituent_ticker": "AAPL",
                "constituent_name": "Apple Inc",
                "weight": 0.07,
                "asset_class": "Equity",
            },
            {
                "effective_date": "2026-04-14",
                "constituent_ticker": "MSFT",
                "constituent_name": "Microsoft Corp",
                "weight": 0.06,
                "asset_class": "Equity",
            },
        ],
    )

    payload = tools.fund_source("spy", api_key="key")

    assert payload["source"]["provider"] == "Polygon ETF Global"
    assert payload["source"]["effective_date"] == "2026-04-14"
    assert payload["tickers"] == ["AAPL", "MSFT"]
    assert payload["holdings"][0]["source_weight"] == pytest.approx(0.07)


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
    monkeypatch.setattr(tools, "_fetch_yfinance_market_value", lambda ticker: None)

    payload = tools.market_cap_weights(["aapl", "msft", "aapl", "missing"], api_key="key")

    assert payload["total_market_cap"] == pytest.approx(400)
    assert payload["rows"][0]["ticker"] == "AAPL"
    assert payload["rows"][0]["weight"] == pytest.approx(0.75)
    assert payload["rows"][0]["valuation_method"] == "Polygon market cap"
    assert payload["rows"][1]["weight"] == pytest.approx(0.25)
    assert payload["missing"] == ["MISSING"]


def test_market_cap_weights_values_etfs_with_yfinance(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_fetch_ticker_overviews",
        lambda tickers, api_key=None: {
            "SPY": {"name": "SPDR S&P 500 ETF Trust", "type": "ETF"},
            "AAPL": {"name": "Apple Inc", "market_cap": 300},
        },
    )
    monkeypatch.setattr(
        tools,
        "_fetch_yfinance_market_value",
        lambda ticker: {
            "market_cap": 700,
            "method": "Price x shares outstanding",
            "price": 500,
            "shares_outstanding": 1.4,
        } if ticker == "SPY" else None,
    )

    payload = tools.market_cap_weights(["spy", "aapl"], api_key="key")

    assert payload["total_market_cap"] == pytest.approx(1000)
    assert payload["rows"][0]["ticker"] == "SPY"
    assert payload["rows"][0]["weight"] == pytest.approx(0.7)
    assert payload["rows"][0]["valuation_method"] == "Price x shares outstanding"
    assert payload["rows"][0]["price"] == pytest.approx(500)
    assert payload["rows"][0]["shares_outstanding"] == pytest.approx(1.4)


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
