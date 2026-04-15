import csv

import pytest

from src import tools


def test_normalize_tickers_dedupes_and_splits():
    assert tools.normalize_tickers(" aapl, msft;AAPL $brk.b bad/ticker ") == ["AAPL", "MSFT", "BRK.B"]


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

    payload = tools.market_cap_weights(["aapl", "msft", "aapl", "missing"], api_key="key")

    assert payload["total_market_cap"] == pytest.approx(400)
    assert payload["rows"][0]["ticker"] == "AAPL"
    assert payload["rows"][0]["weight"] == pytest.approx(0.75)
    assert payload["rows"][1]["weight"] == pytest.approx(0.25)
    assert payload["missing"] == ["MISSING"]


def test_earnings_calendar_fetches_each_ticker(monkeypatch):
    calls = []

    def fake_polygon_get(path, params, api_key=None):
        calls.append((path, params, api_key))
        return {
            "results": [
                {
                    "ticker": params["ticker"],
                    "company_name": f"{params['ticker']} Corp",
                    "date": "2026-05-01",
                    "time": "07:00:00",
                    "estimated_eps": 1.25,
                }
            ]
        }

    monkeypatch.setattr(tools, "_polygon_get", fake_polygon_get)

    payload = tools.earnings_calendar(["AAPL", "MSFT"], "2026-04-15", "2026-05-15", api_key="key")

    assert [call[1]["ticker"] for call in calls] == ["AAPL", "MSFT"]
    assert calls[0][1]["date.gte"] == "2026-04-15"
    assert payload["events"][0]["ticker"] == "AAPL"
    assert payload["events"][1]["ticker"] == "MSFT"
