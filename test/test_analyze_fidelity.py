import pytest
import pandas as pd

from src.reports.analyze_fidelity import build_remaining_lot_book


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
