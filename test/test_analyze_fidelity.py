import pandas as pd

from src.reports.analyze_fidelity import build_remaining_lot_book


def test_build_remaining_lot_book_prefers_losses_then_fifo_gains():
    trades = pd.DataFrame(
        [
            {"Run Date": pd.Timestamp("2025-01-01"), "symbol": "ABC", "quantity": 1.0, "price": 100.0},
            {"Run Date": pd.Timestamp("2025-01-02"), "symbol": "ABC", "quantity": 1.0, "price": 90.0},
            {"Run Date": pd.Timestamp("2025-01-03"), "symbol": "ABC", "quantity": 1.0, "price": 80.0},
            {"Run Date": pd.Timestamp("2025-01-04"), "symbol": "ABC", "quantity": -2.0, "price": 85.0},
            {"Run Date": pd.Timestamp("2025-01-05"), "symbol": "ABC", "quantity": 1.0, "price": 70.0},
            {"Run Date": pd.Timestamp("2025-01-06"), "symbol": "ABC", "quantity": -1.0, "price": 95.0},
        ]
    )

    lot_book = build_remaining_lot_book(trades, ["ABC"])

    assert len(lot_book["ABC"]) == 1
    assert lot_book["ABC"][0]["qty"] == 1.0
    assert lot_book["ABC"][0]["price"] == 70.0
