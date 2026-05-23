import pandas as pd
import pytest

from src.reports import analyze_fidelity
from src.reports.analyze_fidelity import (
    _apply_future_split_adjustments,
    _apply_inception_day_return_override,
    _estimate_inception_day_return,
    _expand_fetch_start_for_short_report_window,
    _fetch_polygon_prices_with_minimum_history,
    _holding_today_gl_series,
    _is_invalid_sell_post_quantity,
    _statement_cash_income_series,
    _write_quantstats_report,
    _upsert_accounts_index_entry,
    build_remaining_lot_book,
)


def test_build_remaining_lot_book_prefers_long_term_lots_before_short_term():
    trades = pd.DataFrame(
        [
            {"Run Date": pd.Timestamp("2024-01-01"), "symbol": "ABC", "quantity": 1.0, "price": 80.0},
            {"Run Date": pd.Timestamp("2025-01-15"), "symbol": "ABC", "quantity": 1.0, "price": 100.0},
            {"Run Date": pd.Timestamp("2025-06-01"), "symbol": "ABC", "quantity": -1.0, "price": 90.0},
        ]
    )

    lot_book = build_remaining_lot_book(trades, ["ABC"])

    assert len(lot_book["ABC"]) == 1
    assert lot_book["ABC"][0]["qty"] == 1.0
    assert lot_book["ABC"][0]["price"] == 100.0


@pytest.mark.parametrize(
    ("buy_dates", "sale_date"),
    [
        (
            [
                pd.Timestamp("2023-01-01"),
                pd.Timestamp("2023-02-01"),
                pd.Timestamp("2023-03-01"),
            ],
            pd.Timestamp("2025-03-01"),
        ),
        (
            [
                pd.Timestamp("2025-01-01"),
                pd.Timestamp("2025-02-01"),
                pd.Timestamp("2025-02-15"),
            ],
            pd.Timestamp("2025-03-01"),
        ),
    ],
)
def test_build_remaining_lot_book_prefers_smallest_realized_gain_within_each_classification(
    buy_dates: list[pd.Timestamp], sale_date: pd.Timestamp
):
    trades = pd.DataFrame(
        [
            {"Run Date": buy_dates[0], "symbol": "ABC", "quantity": 1.0, "price": 70.0},
            {"Run Date": buy_dates[1], "symbol": "ABC", "quantity": 1.0, "price": 110.0},
            {"Run Date": buy_dates[2], "symbol": "ABC", "quantity": 1.0, "price": 95.0},
            {"Run Date": sale_date, "symbol": "ABC", "quantity": -2.0, "price": 100.0},
        ]
    )

    lot_book = build_remaining_lot_book(trades, ["ABC"])

    assert len(lot_book["ABC"]) == 1
    assert lot_book["ABC"][0]["qty"] == 1.0
    assert lot_book["ABC"][0]["price"] == 70.0


def test_build_remaining_lot_book_applies_wash_sale_to_future_replacement_buy():
    trades = pd.DataFrame(
        [
            {"Run Date": pd.Timestamp("2025-01-01"), "symbol": "ABC", "quantity": 1.0, "price": 100.0},
            {"Run Date": pd.Timestamp("2025-01-15"), "symbol": "ABC", "quantity": -1.0, "price": 90.0},
            {"Run Date": pd.Timestamp("2025-01-20"), "symbol": "ABC", "quantity": 1.0, "price": 80.0},
        ]
    )

    lot_book = build_remaining_lot_book(trades, ["ABC"])

    assert len(lot_book["ABC"]) == 1
    assert lot_book["ABC"][0]["qty"] == 1.0
    assert lot_book["ABC"][0]["price"] == 90.0
    assert lot_book["ABC"][0]["tax_date"] == pd.Timestamp("2025-01-01")


def test_build_remaining_lot_book_applies_wash_sale_to_prior_replacement_buy():
    trades = pd.DataFrame(
        [
            {"Run Date": pd.Timestamp("2024-12-01"), "symbol": "ABC", "quantity": 1.0, "price": 100.0},
            {"Run Date": pd.Timestamp("2024-12-20"), "symbol": "ABC", "quantity": 1.0, "price": 80.0},
            {"Run Date": pd.Timestamp("2025-01-10"), "symbol": "ABC", "quantity": -1.0, "price": 90.0},
        ]
    )

    lot_book = build_remaining_lot_book(trades, ["ABC"])

    assert len(lot_book["ABC"]) == 1
    assert lot_book["ABC"][0]["qty"] == 1.0
    assert lot_book["ABC"][0]["price"] == 90.0
    assert lot_book["ABC"][0]["tax_date"] == pd.Timestamp("2024-12-01")


def test_build_remaining_lot_book_uses_wash_sale_holding_period_for_later_classification():
    trades = pd.DataFrame(
        [
            {"Run Date": pd.Timestamp("2024-01-01"), "symbol": "ABC", "quantity": 1.0, "price": 100.0},
            {"Run Date": pd.Timestamp("2024-01-20"), "symbol": "ABC", "quantity": -1.0, "price": 90.0},
            {"Run Date": pd.Timestamp("2024-02-15"), "symbol": "ABC", "quantity": 1.0, "price": 80.0},
            {"Run Date": pd.Timestamp("2025-01-20"), "symbol": "ABC", "quantity": 1.0, "price": 85.0},
            {"Run Date": pd.Timestamp("2025-02-01"), "symbol": "ABC", "quantity": -1.0, "price": 95.0},
        ]
    )

    lot_book = build_remaining_lot_book(trades, ["ABC"])

    assert len(lot_book["ABC"]) == 1
    assert lot_book["ABC"][0]["qty"] == 1.0
    assert lot_book["ABC"][0]["price"] == 85.0


def test_is_invalid_sell_post_quantity_ignores_floating_point_dust():
    assert not _is_invalid_sell_post_quantity(-2.7755575615628914e-16)
    assert _is_invalid_sell_post_quantity(-0.001)


def test_upsert_accounts_index_entry_restores_canonical_account_order():
    canonical_accounts = [
        {"id": "OPTICAL", "name": "Optical Computing"},
        {"id": "CLOUD", "name": "Cloud"},
        {"id": "RETIREMENT", "name": "Retirement"},
    ]
    accounts_list = [
        {"id": "RETIREMENT", "name": "Retirement", "report": "/reports/report_2.html"},
        {"id": "OPTICAL", "name": "Optical Computing", "report": "/reports/report_0.html"},
        {"id": "CLOUD", "name": "Cloud", "report": "/reports/report_1.html"},
    ]
    updated_entry = {"id": "RETIREMENT", "name": "Retirement", "report": "/reports/report_9.html"}

    ordered_accounts = _upsert_accounts_index_entry(accounts_list, updated_entry, canonical_accounts)

    assert [account["id"] for account in ordered_accounts] == ["OPTICAL", "CLOUD", "RETIREMENT"]
    assert ordered_accounts[-1]["report"] == "/reports/report_9.html"


def test_statement_cash_income_series_excludes_reinvestments():
    df = pd.DataFrame(
        [
            {"Run Date": "2025-01-01", "Action": "DIVIDEND RECEIVED", "Quantity": "", "Amount": "5.00"},
            {"Run Date": "2025-01-02", "Action": "REINVESTMENT", "Quantity": "0.1", "Amount": "5.00"},
            {"Run Date": "2025-01-03", "Action": "INTEREST PAID", "Quantity": "", "Amount": "1.50"},
        ]
    )
    index = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])

    income = _statement_cash_income_series(df, index)

    assert income.loc[pd.Timestamp("2025-01-01")] == pytest.approx(5.0)
    assert income.loc[pd.Timestamp("2025-01-02")] == pytest.approx(0.0)
    assert income.loc[pd.Timestamp("2025-01-03")] == pytest.approx(1.5)


def test_apply_future_split_adjustments_converts_trades_to_current_share_basis():
    trades = pd.DataFrame(
        [
            {"Run Date": pd.Timestamp("2020-01-01"), "symbol": "AAA", "quantity": 1.0, "price": 100.0},
            {"Run Date": pd.Timestamp("2025-01-01"), "symbol": "AAA", "quantity": 1.0, "price": 50.0},
        ]
    )
    split_events = {
        "AAA": [
            {"execution_date": "2021-07-20", "split_from": 1, "split_to": 4},
            {"execution_date": "2024-06-10", "split_from": 1, "split_to": 10},
        ]
    }

    adjusted = _apply_future_split_adjustments(trades, split_events)

    assert adjusted.loc[0, "quantity"] == pytest.approx(40.0)
    assert adjusted.loc[0, "price"] == pytest.approx(2.5)
    assert adjusted.loc[0, "display_price"] == pytest.approx(100.0)
    assert adjusted.loc[1, "quantity"] == pytest.approx(1.0)
    assert adjusted.loc[1, "price"] == pytest.approx(50.0)


def test_expand_fetch_start_for_short_report_window_adds_previous_business_day():
    start = pd.Timestamp("2026-05-22")
    end = pd.Timestamp("2026-05-22")

    expanded = _expand_fetch_start_for_short_report_window(start, end)

    assert expanded == pd.Timestamp("2026-05-21")


def test_expand_fetch_start_for_short_report_window_adds_previous_business_day_when_only_one_business_day_is_in_range():
    start = pd.Timestamp("2026-05-22")
    end = pd.Timestamp("2026-05-23")

    expanded = _expand_fetch_start_for_short_report_window(start, end)

    assert expanded == pd.Timestamp("2026-05-21")


def test_fetch_polygon_prices_with_minimum_history_backfills_when_initial_window_has_one_trading_row(monkeypatch):
    first_pass = pd.DataFrame(
        {"AAA": [110.0], "VT": [100.0]},
        index=pd.to_datetime(["2026-05-22"]),
    )
    second_pass = pd.DataFrame(
        {"AAA": [100.0, 110.0], "VT": [99.0, 100.0]},
        index=pd.to_datetime(["2026-05-21", "2026-05-22"]),
    )
    calls = []

    def fake_get_polygon_prices(symbols, start, end):
        calls.append((tuple(symbols), start, end))
        return first_pass.copy() if len(calls) == 1 else second_pass.copy()

    monkeypatch.setattr(analyze_fidelity, "get_polygon_prices", fake_get_polygon_prices)

    fetch_start, prices = _fetch_polygon_prices_with_minimum_history(
        ["AAA", "VT"],
        pd.Timestamp("2026-05-22"),
        pd.Timestamp("2026-05-25"),
    )

    assert calls == [
        (("AAA", "VT"), "2026-05-22", "2026-05-25"),
        (("AAA", "VT"), "2026-05-21", "2026-05-25"),
    ]
    assert fetch_start == pd.Timestamp("2026-05-21")
    assert list(prices.index) == list(pd.to_datetime(["2026-05-21", "2026-05-22"]))


def test_estimate_inception_day_return_uses_basis_and_open_fallback():
    lot_book = {
        "AAA": [{"qty": 2.0, "price": 10.0}],
        "BBB": [{"qty": 1.0, "price": 0.0}],
    }
    current_prices = pd.Series({"AAA": 11.0, "BBB": 21.0})
    session_prices = {"BBB": {"open": 20.0}}

    estimated = _estimate_inception_day_return(
        lot_book,
        current_prices,
        session_prices=session_prices,
    )

    expected_basis = 2.0 * 10.0 + 1.0 * 20.0
    expected_current = 2.0 * 11.0 + 1.0 * 21.0
    assert estimated == pytest.approx(expected_current / expected_basis - 1.0)


def test_apply_inception_day_return_override_updates_today_when_portfolio_has_no_prior_value(monkeypatch):
    monkeypatch.setattr(
        "src.reports.analyze_fidelity.datetime",
        type(
            "FixedDateTime",
            (),
            {"now": staticmethod(lambda: pd.Timestamp("2026-05-22 15:30:00").to_pydatetime())},
        ),
    )

    returns = pd.Series(
        [0.0, 0.0],
        index=pd.to_datetime(["2026-05-21", "2026-05-22"]),
    )
    value_df = pd.DataFrame(
        {"AAA": [0.0, 110.0]},
        index=returns.index,
    )
    prices = pd.DataFrame(
        {"AAA": [100.0, 110.0]},
        index=returns.index,
    )
    lot_book = {"AAA": [{"qty": 1.0, "price": 100.0}]}

    adjusted = _apply_inception_day_return_override(returns, value_df, lot_book, prices)

    assert adjusted.loc[pd.Timestamp("2026-05-22")] == pytest.approx(0.1)


def test_apply_inception_day_return_override_updates_latest_trading_day_when_today_is_non_market_day(monkeypatch):
    monkeypatch.setattr(
        "src.reports.analyze_fidelity.datetime",
        type(
            "FixedDateTime",
            (),
            {"now": staticmethod(lambda: pd.Timestamp("2026-05-23 12:00:00").to_pydatetime())},
        ),
    )

    returns = pd.Series(
        [0.0, 0.0],
        index=pd.to_datetime(["2026-05-21", "2026-05-22"]),
    )
    value_df = pd.DataFrame(
        {"AAA": [0.0, 110.0]},
        index=returns.index,
    )
    prices = pd.DataFrame(
        {"AAA": [100.0, 110.0]},
        index=returns.index,
    )
    lot_book = {"AAA": [{"qty": 1.0, "price": 100.0}]}

    adjusted = _apply_inception_day_return_override(returns, value_df, lot_book, prices)

    assert adjusted.loc[pd.Timestamp("2026-05-22")] == pytest.approx(0.1)


def test_holding_today_gl_series_uses_inception_logic_for_new_position_instead_of_inf():
    prices = pd.DataFrame(
        {"AAA": [100.0, 110.0]},
        index=pd.to_datetime(["2026-05-21", "2026-05-22"]),
    )
    quantities = pd.DataFrame(
        {"AAA": [0.0, 1.0]},
        index=prices.index,
    )
    lot_book = {"AAA": [{"qty": 1.0, "price": 100.0}]}

    today_gl = _holding_today_gl_series(prices, quantities, lot_book)

    assert today_gl.loc["AAA"] == pytest.approx(0.1)


def test_write_quantstats_report_falls_back_for_flat_short_history(tmp_path, monkeypatch):
    called = {"value": False}

    def fake_html(*args, **kwargs):
        called["value"] = True

    monkeypatch.setattr("src.reports.analyze_fidelity.qs.reports.html", fake_html)

    report_path = tmp_path / "report.html"
    generated = _write_quantstats_report(
        pd.Series([0.0, 0.0], index=pd.to_datetime(["2026-05-21", "2026-05-22"])),
        pd.Series([0.0, 0.0], index=pd.to_datetime(["2026-05-21", "2026-05-22"])),
        report_path,
        title="Portfolio Analysis - Short History",
        rf=0.0396,
        short_history_message="Too short",
    )

    assert generated is False
    assert called["value"] is False
    assert "Too short" in report_path.read_text(encoding="utf-8")
