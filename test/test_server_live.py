import pytest

from src import server


def test_compute_live_snapshot_falls_back_from_zero_price_to_prev_close(monkeypatch):
    monkeypatch.setattr(server, "_ny_date_string", lambda: "2026-04-09")

    snapshot = server._compute_live_snapshot(
        holdings=[{"ticker": "AAA", "quantity": 10.0, "basis_approx": 80.0}],
        benchmark_ticker="SPY",
        quotes={
            "AAA": {"price": 0.0, "prev_close": 10.0},
            "SPY": {"price": 0.0, "prev_close": 100.0},
        },
    )

    assert snapshot is not None
    assert snapshot["portfolio_return"] == pytest.approx(0.0)
    assert snapshot["benchmark_return"] == pytest.approx(0.0)
    assert snapshot["total_live_value"] == pytest.approx(100.0)


def test_compute_live_snapshot_uses_prev_close_for_holdings_without_today_quote(monkeypatch):
    same_day_trade_ms = 1775678340000  # 2026-04-08 15:59:00 ET
    prior_day_trade_ms = 1775591940000  # 2026-04-07 15:59:00 ET
    monkeypatch.setattr(server, "_ny_date_string", lambda: "2026-04-08")

    snapshot = server._compute_live_snapshot(
        holdings=[
            {"ticker": "AAA", "quantity": 10.0, "basis_approx": 80.0},
            {"ticker": "BBB", "quantity": 10.0, "basis_approx": 80.0},
        ],
        benchmark_ticker="SPY",
        quotes={
            "AAA": {"price": 12.0, "updated": same_day_trade_ms, "prev_close": 10.0},
            "BBB": {"price": 8.0, "updated": prior_day_trade_ms, "prev_close": 10.0},
            "SPY": {"price": 101.0, "updated": same_day_trade_ms, "prev_close": 100.0},
        },
    )

    assert snapshot is not None
    assert snapshot["portfolio_return"] == pytest.approx(0.1)
    assert snapshot["live_value_by_ticker"]["AAA"] == pytest.approx(120.0)
    assert snapshot["live_value_by_ticker"]["BBB"] == pytest.approx(100.0)


def test_merge_quote_preserves_existing_valid_price_when_incoming_price_is_blank():
    merged = server._merge_quote(
        {"price": 11.5, "prev_close": 10.0, "updated": 100},
        {"price": None, "prev_close": 10.0, "updated": 101},
    )

    assert merged["price"] == pytest.approx(11.5)
    assert merged["prev_close"] == pytest.approx(10.0)
    assert merged["updated"] == 101


def test_stream_trade_updated_at_uses_event_timestamp():
    assert server._stream_trade_updated_at({"t": 1775678340000}) == 1775678340000
    assert server._stream_trade_updated_at({"sip_timestamp": "1775678340000000000"}) == "1775678340000000000"


def test_stream_trade_updated_at_falls_back_to_receive_time(monkeypatch):
    monkeypatch.setattr(server, "_now_timestamp_ms", lambda: 1775678340000)

    assert server._stream_trade_updated_at({"ev": "T", "sym": "AAA", "p": 10.0}) == 1775678340000


def test_fetch_stock_snapshots_ignores_zero_snapshot_price(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "tickers": [
                    {
                        "ticker": "AAA",
                        "lastTrade": {},
                        "min": {"c": 0},
                        "day": {"c": 0},
                        "prevDay": {"c": 10},
                        "updated": 123,
                    }
                ]
            }

    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    monkeypatch.setattr(server.requests, "get", lambda *args, **kwargs: FakeResponse())

    quotes = server._fetch_stock_snapshots(["AAA"])

    assert quotes["AAA"]["price"] is None
    assert quotes["AAA"]["prev_close"] == pytest.approx(10.0)


def test_fetch_stock_snapshots_keeps_prior_day_last_trade_before_first_trade(monkeypatch):
    previous_trade_ms = 1776110340000  # 2026-04-13 15:59:00 ET

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "tickers": [
                    {
                        "ticker": "AAA",
                        "lastTrade": {"p": 11.0, "t": previous_trade_ms},
                        "min": {"c": 11.0, "t": previous_trade_ms},
                        "day": {"c": 11.0, "t": previous_trade_ms},
                        "prevDay": {"c": 10.0},
                        "updated": 1776268800000,
                    }
                ]
            }

    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    monkeypatch.setattr(server.requests, "get", lambda *args, **kwargs: FakeResponse())

    quotes = server._fetch_stock_snapshots(["AAA"])

    assert quotes["AAA"]["price"] == pytest.approx(11.0)
    assert quotes["AAA"]["prev_close"] == pytest.approx(10.0)
    assert quotes["AAA"]["updated"] == previous_trade_ms


def test_apply_live_payload_updates_latest_points(monkeypatch):
    monkeypatch.setattr(server, "_ny_date_string", lambda: "2026-04-08")
    same_day_trade_ms = 1775678340000  # 2026-04-08 15:59:00 ET

    payload = {
        "portfolio": {
            "daily": [{"t": "2026-04-07", "v": 0.01}],
            "equity": [{"t": "2026-04-07", "v": 1.01}],
        },
        "benchmark": {
            "ticker": "SPY",
            "daily": [{"t": "2026-04-07", "v": 0.02}],
            "equity": [{"t": "2026-04-07", "v": 1.02}],
        },
        "spread": {
            "daily": [{"t": "2026-04-07", "v": -0.01}],
            "cumulative": [{"t": "2026-04-07", "v": -0.01}],
        },
        "multiple": {
            "daily": [{"t": "2026-04-07", "v": 0.5}],
        },
        "weights": [
            {"name": "AAA", "points": [{"t": "2026-04-07", "v": 1.0}]},
        ],
    }
    holdings = [{"ticker": "AAA", "quantity": 10.0, "basis_approx": 80.0}]
    quotes = {
        "AAA": {"price": 11.0, "updated": same_day_trade_ms, "prev_close": 10.0},
        "SPY": {"price": 102.0, "updated": same_day_trade_ms, "prev_close": 100.0},
    }

    refreshed = server._apply_live_payload(payload, holdings, "SPY", quotes)

    assert refreshed["portfolio"]["daily"][-1]["t"] == "2026-04-08"
    assert refreshed["portfolio"]["daily"][-1]["v"] == pytest.approx(0.1)
    assert refreshed["benchmark"]["daily"][-1]["t"] == "2026-04-08"
    assert refreshed["benchmark"]["daily"][-1]["v"] == pytest.approx(0.02)
    assert refreshed["spread"]["daily"][-1]["t"] == "2026-04-08"
    assert refreshed["spread"]["daily"][-1]["v"] == pytest.approx(0.08)
    assert refreshed["multiple"]["daily"][-1]["t"] == "2026-04-08"
    assert refreshed["multiple"]["daily"][-1]["v"] == pytest.approx(5.0)
    assert refreshed["portfolio"]["equity"][-1]["t"] == "2026-04-08"
    assert refreshed["portfolio"]["equity"][-1]["v"] == pytest.approx(1.111)
    assert refreshed["weights"][0]["points"][-1] == {"t": "2026-04-08", "v": 1.0}


def test_apply_live_payload_rolls_forward_equity_without_recompounding(monkeypatch):
    monkeypatch.setattr(server, "_ny_date_string", lambda: "2026-04-08")

    payload = {
        "portfolio": {
            "daily": [{"t": "2026-04-07", "v": 0.1}],
            "equity": [{"t": "2026-04-07", "v": 1.1}],
        },
        "benchmark": {
            "ticker": "SPY",
            "daily": [{"t": "2026-04-07", "v": 0.02}],
            "equity": [{"t": "2026-04-07", "v": 1.02}],
        },
        "spread": {
            "daily": [{"t": "2026-04-07", "v": 0.08}],
            "cumulative": [{"t": "2026-04-07", "v": 0.08}],
        },
        "multiple": {
            "daily": [{"t": "2026-04-07", "v": 5.0}],
        },
        "weights": [
            {"name": "AAA", "points": [{"t": "2026-04-07", "v": 1.0}]},
        ],
    }
    holdings = [{"ticker": "AAA", "quantity": 10.0, "basis_approx": 80.0}]
    quotes = {
        "AAA": {"price": 11.0, "updated": 1776110340000, "prev_close": 10.0},
        "SPY": {"price": 102.0, "updated": 1776110340000, "prev_close": 100.0},
    }

    refreshed = server._apply_live_payload(payload, holdings, "SPY", quotes)

    assert refreshed["portfolio"]["daily"] == [{"t": "2026-04-08", "v": pytest.approx(0.1)}]
    assert refreshed["portfolio"]["equity"][-1] == {"t": "2026-04-08", "v": pytest.approx(1.1)}
    assert refreshed["benchmark"]["daily"] == [{"t": "2026-04-08", "v": pytest.approx(0.02)}]
    assert refreshed["benchmark"]["equity"][-1] == {"t": "2026-04-08", "v": pytest.approx(1.02)}
    assert refreshed["spread"]["daily"] == [{"t": "2026-04-08", "v": pytest.approx(0.08)}]
    assert refreshed["spread"]["cumulative"][-1] == {"t": "2026-04-08", "v": pytest.approx(0.08)}
    assert refreshed["multiple"]["daily"] == [{"t": "2026-04-08", "v": pytest.approx(5.0)}]


def test_apply_live_payload_fills_non_trading_days_between_last_trade_and_today(monkeypatch):
    monkeypatch.setattr(server, "_ny_date_string", lambda: "2026-04-12")

    payload = {
        "portfolio": {
            "daily": [{"t": "2026-04-10", "v": 0.1}],
            "equity": [{"t": "2026-04-10", "v": 1.1}],
        },
        "benchmark": {
            "ticker": "SPY",
            "daily": [{"t": "2026-04-10", "v": 0.02}],
            "equity": [{"t": "2026-04-10", "v": 1.02}],
        },
        "spread": {
            "daily": [{"t": "2026-04-10", "v": 0.08}],
            "cumulative": [{"t": "2026-04-10", "v": 0.08}],
        },
        "multiple": {
            "daily": [{"t": "2026-04-10", "v": 5.0}],
        },
        "weights": [
            {"name": "AAA", "points": [{"t": "2026-04-10", "v": 1.0}]},
        ],
    }
    holdings = [{"ticker": "AAA", "quantity": 10.0, "basis_approx": 80.0}]
    quotes = {
        "AAA": {"price": 11.0, "updated": 1776110340000, "prev_close": 10.0},
        "SPY": {"price": 102.0, "updated": 1776110340000, "prev_close": 100.0},
    }

    refreshed = server._apply_live_payload(payload, holdings, "SPY", quotes)

    assert refreshed["portfolio"]["equity"][-2:] == [
        {"t": "2026-04-11", "v": pytest.approx(1.1)},
        {"t": "2026-04-12", "v": pytest.approx(1.1)},
    ]
    assert refreshed["portfolio"]["daily"][-2:] == [
        {"t": "2026-04-11", "v": pytest.approx(0.1)},
        {"t": "2026-04-12", "v": pytest.approx(0.1)},
    ]
    assert refreshed["benchmark"]["daily"] == [
        {"t": "2026-04-11", "v": pytest.approx(0.02)},
        {"t": "2026-04-12", "v": pytest.approx(0.02)},
    ]
    assert refreshed["spread"]["daily"] == [
        {"t": "2026-04-11", "v": pytest.approx(0.08)},
        {"t": "2026-04-12", "v": pytest.approx(0.08)},
    ]
    assert refreshed["multiple"]["daily"] == [
        {"t": "2026-04-11", "v": pytest.approx(5.0)},
        {"t": "2026-04-12", "v": pytest.approx(5.0)},
    ]
    assert refreshed["weights"][0]["points"][-2:] == [
        {"t": "2026-04-11", "v": pytest.approx(1.0)},
        {"t": "2026-04-12", "v": pytest.approx(1.0)},
    ]


def test_refresh_weights_rows_updates_live_columns(monkeypatch):
    same_day_trade_ms = 1775678340000  # 2026-04-08 15:59:00 ET
    monkeypatch.setattr(server, "_ny_date_string", lambda: "2026-04-08")

    rows = [
        {
            "Ticker": "AAA",
            "Portfolio Weight (%)": "50.00%",
            "Today G/L": "—",
            "Total G/L (approx.)": "—",
            "_Quantity": "10",
            "_BasisApprox": "80",
        },
        {
            "Ticker": "BBB",
            "Portfolio Weight (%)": "50.00%",
            "Today G/L": "—",
            "Total G/L (approx.)": "—",
            "_Quantity": "10",
            "_BasisApprox": "50",
        },
    ]
    quotes = {
        "AAA": {"price": 11.0, "updated": same_day_trade_ms, "prev_close": 10.0},
        "BBB": {"price": 8.0, "updated": same_day_trade_ms, "prev_close": 10.0},
    }

    refreshed = server._refresh_weights_rows(rows, quotes)

    assert refreshed[0]["Portfolio Weight (%)"] == "57.89%"
    assert refreshed[1]["Portfolio Weight (%)"] == "42.11%"
    assert refreshed[0]["Today G/L"] == "+10.00%"
    assert refreshed[1]["Today G/L"] == "-20.00%"
    assert refreshed[0]["Total G/L (approx.)"] == "+37.50%"
    assert refreshed[1]["Total G/L (approx.)"] == "+60.00%"


def test_refresh_weights_rows_keeps_report_values_when_quotes_are_stale(monkeypatch):
    prior_day_trade_ms = 1775591940000  # 2026-04-07 15:59:00 ET
    monkeypatch.setattr(server, "_ny_date_string", lambda: "2026-04-08")

    rows = [
        {
            "Ticker": "AAA",
            "Portfolio Weight (%)": "50.00%",
            "Today G/L": "+10.00%",
            "Total G/L (approx.)": "+37.50%",
            "_Quantity": "10",
            "_BasisApprox": "80",
        },
        {
            "Ticker": "BBB",
            "Portfolio Weight (%)": "50.00%",
            "Today G/L": "-20.00%",
            "Total G/L (approx.)": "+60.00%",
            "_Quantity": "10",
            "_BasisApprox": "50",
        },
    ]
    quotes = {
        "AAA": {"price": 11.0, "updated": prior_day_trade_ms, "prev_close": 10.0},
        "BBB": {"price": 8.0, "updated": prior_day_trade_ms, "prev_close": 10.0},
    }

    refreshed = server._refresh_weights_rows(rows, quotes)

    assert refreshed == rows
