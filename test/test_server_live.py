import pytest

from src import server


def test_apply_live_payload_updates_latest_points(monkeypatch):
    monkeypatch.setattr(server, "_ny_date_string", lambda: "2026-04-08")

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
        "AAA": {"price": 11.0, "prev_close": 10.0},
        "SPY": {"price": 102.0, "prev_close": 100.0},
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


def test_refresh_weights_rows_updates_live_columns():
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
        "AAA": {"price": 11.0, "prev_close": 10.0},
        "BBB": {"price": 8.0, "prev_close": 10.0},
    }

    refreshed = server._refresh_weights_rows(rows, quotes)

    assert refreshed[0]["Portfolio Weight (%)"] == "57.89%"
    assert refreshed[1]["Portfolio Weight (%)"] == "42.11%"
    assert refreshed[0]["Today G/L"] == "+10.00%"
    assert refreshed[1]["Today G/L"] == "-20.00%"
    assert refreshed[0]["Total G/L (approx.)"] == "+37.50%"
    assert refreshed[1]["Total G/L (approx.)"] == "+60.00%"
