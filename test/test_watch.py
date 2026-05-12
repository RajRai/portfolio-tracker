import pandas as pd

from src.reports.watch import CANONICAL_COLUMNS, merge_statements, normalize_statement_df


def test_normalize_statement_df_maps_schwab_rows_to_canonical_columns():
    schwab = pd.DataFrame(
        [
            {
                "Date": "03/25/2026",
                "Action": "Buy",
                "Symbol": "VT",
                "Description": "VANGUARD TOTAL WORLD STOCK INDEX FUND ETF SHARES",
                "Quantity": "3",
                "Price": "$139.522",
                "Fees & Comm": "",
                "Amount": "-$418.57",
            },
            {
                "Date": "03/02/2026",
                "Action": "Sell",
                "Symbol": "IYW",
                "Description": "ISHARES US TECHNOLOGY ETF",
                "Quantity": "80.0183",
                "Price": "$190.9401",
                "Fees & Comm": "$0.02",
                "Amount": "$15,278.68",
            },
            {
                "Date": "12/19/2025",
                "Action": "Reinvest Shares",
                "Symbol": "IYW",
                "Description": "ISHARES US TECHNOLOGY ETF",
                "Quantity": "0.0103",
                "Price": "$198.8976",
                "Fees & Comm": "",
                "Amount": "-$2.05",
            },
        ]
    )

    normalized = normalize_statement_df(schwab)

    assert list(normalized.columns) == CANONICAL_COLUMNS
    assert normalized.loc[0, "Action"] == (
        "YOU BOUGHT VANGUARD TOTAL WORLD STOCK INDEX FUND ETF SHARES (VT) (Cash)"
    )
    assert normalized.loc[1, "Action"] == "YOU SOLD ISHARES US TECHNOLOGY ETF (IYW) (Cash)"
    assert normalized.loc[1, "Quantity"] == "-80.0183"
    assert normalized.loc[1, "Price"] == "190.9401"
    assert normalized.loc[1, "Fees"] == "0.02"
    assert normalized.loc[1, "Amount"] == "15278.68"
    assert normalized.loc[2, "Action"] == "REINVESTMENT ISHARES US TECHNOLOGY ETF (IYW) (Cash)"
    assert normalized.loc[2, "Type"] == "Cash"


def test_normalize_statement_df_accepts_fidelity_dollar_header_variant():
    fidelity = pd.DataFrame(
        [
            {
                "Run Date": "04/08/2026",
                "Action": "YOU BOUGHT VANGUARD INTL EQUITY INDEX FDS TT WR... (VT) (Cash)",
                "Symbol": "VT",
                "Description": "VANGUARD INTL EQUITY INDEX FDS TT WRLD",
                "Type": "Cash",
                "Price ($)": "144.62",
                "Quantity": "7",
                "Commission ($)": "",
                "Fees ($)": "",
                "Accrued Interest ($)": "",
                "Amount ($)": "-1012.34",
                "Cash Balance ($)": "0.01",
                "Settlement Date": "04/09/2026",
            }
        ]
    )

    normalized = normalize_statement_df(fidelity)

    assert list(normalized.columns) == CANONICAL_COLUMNS
    assert normalized.loc[0, "Price"] == "144.62"
    assert normalized.loc[0, "Amount"] == "-1012.34"
    assert normalized.loc[0, "Cash Balance"] == "0.01"


def test_merge_statements_accepts_schwab_statement(tmp_path):
    account_dir = tmp_path / "ACCOUNT"
    statements_dir = account_dir / "statements"
    statements_dir.mkdir(parents=True)
    (statements_dir / "schwab.csv").write_text(
        "\n".join(
            [
                '"Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount"',
                '"03/25/2026","Buy","VT","VANGUARD TOTAL WORLD STOCK INDEX FUND ETF SHARES","3","$139.522","","-$418.57"',
                '"03/02/2026","Sell","IYW","ISHARES US TECHNOLOGY ETF","80.0183","$190.9401","$0.02","$15,278.68"',
            ]
        ),
        encoding="utf-8",
    )

    combined_path = merge_statements(account_dir)

    combined = pd.read_csv(combined_path)
    assert combined_path == account_dir / "combined.csv"
    assert len(combined) == 2
    assert list(combined.columns) == CANONICAL_COLUMNS
    assert combined.loc[0, "Action"] == "YOU SOLD ISHARES US TECHNOLOGY ETF (IYW) (Cash)"
    assert combined.loc[0, "Quantity"] == -80.0183
    assert combined.loc[1, "Action"] == (
        "YOU BOUGHT VANGUARD TOTAL WORLD STOCK INDEX FUND ETF SHARES (VT) (Cash)"
    )


def test_merge_statements_dedupes_overlapping_exports_from_same_source_account(tmp_path):
    account_dir = tmp_path / "ACCOUNT"
    statements_dir = account_dir / "statements"
    statements_dir.mkdir(parents=True)

    overlapping_rows = [
        "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date",
        '05/11/2026,"YOU SOLD ADVANCED MICRO DEVICES INC (AMD) (Cash)",AMD,"ADVANCED MICRO DEVICES INC",Cash,462.47,-1,,,,"462.47","Processing",05/12/2026',
    ]
    settled_rows = [
        "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date",
        '05/11/2026,"YOU SOLD ADVANCED MICRO DEVICES INC (AMD) (Cash)",AMD,"ADVANCED MICRO DEVICES INC",Cash,462.47,-1,,,,"462.47","3019.29",05/12/2026',
    ]

    (statements_dir / "History_for_Account_123.csv").write_text(
        "\n".join(overlapping_rows),
        encoding="utf-8",
    )
    (statements_dir / "History_for_Account_123 (1).csv").write_text(
        "\n".join(settled_rows),
        encoding="utf-8",
    )

    combined = pd.read_csv(merge_statements(account_dir))

    assert len(combined) == 1
    assert combined.loc[0, "Symbol"] == "AMD"
    assert combined.loc[0, "Quantity"] == -1.0
    assert combined.loc[0, "Amount"] == 462.47


def test_merge_statements_preserves_identical_rows_from_different_source_accounts(tmp_path):
    account_dir = tmp_path / "ACCOUNT"
    statements_dir = account_dir / "statements"
    statements_dir.mkdir(parents=True)

    trade_rows = [
        "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date",
        '05/11/2026,"YOU SOLD ADVANCED MICRO DEVICES INC (AMD) (Cash)",AMD,"ADVANCED MICRO DEVICES INC",Cash,462.47,-1,,,,"462.47","3019.29",05/12/2026',
    ]

    (statements_dir / "History_for_Account_123.csv").write_text(
        "\n".join(trade_rows),
        encoding="utf-8",
    )
    (statements_dir / "History_for_Account_456.csv").write_text(
        "\n".join(trade_rows),
        encoding="utf-8",
    )

    combined = pd.read_csv(merge_statements(account_dir))

    assert len(combined) == 2
    assert combined["Symbol"].tolist() == ["AMD", "AMD"]
