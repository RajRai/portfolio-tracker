import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

from src.util import BASE_DIR

BASE = BASE_DIR / "data"

CANONICAL_COLUMNS = [
    "Run Date",
    "Action",
    "Symbol",
    "Description",
    "Type",
    "Exchange Quantity",
    "Exchange Currency",
    "Quantity",
    "Currency",
    "Price",
    "Exchange Rate",
    "Commission",
    "Fees",
    "Accrued Interest",
    "Amount",
    "Cash Balance",
    "Settlement Date",
]

FIDELITY_COLUMN_ALIASES = {
    "Price ($)": "Price",
    "Commission ($)": "Commission",
    "Fees ($)": "Fees",
    "Accrued Interest ($)": "Accrued Interest",
    "Amount ($)": "Amount",
    "Cash Balance ($)": "Cash Balance",
}

SCHWAB_COLUMNS = {
    "Date",
    "Action",
    "Symbol",
    "Description",
    "Quantity",
    "Price",
    "Fees & Comm",
    "Amount",
}

NUMERIC_COLUMNS = [
    "Exchange Quantity",
    "Quantity",
    "Price",
    "Exchange Rate",
    "Commission",
    "Fees",
    "Accrued Interest",
    "Amount",
    "Cash Balance",
]


def _clean_numeric(value):
    if pd.isna(value):
        return pd.NA

    text = str(value).strip()
    if not text:
        return pd.NA

    is_negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace("$", "").replace(",", "")
    if is_negative:
        text = f"-{text}"

    return text


def _clean_numeric_series(series: pd.Series) -> pd.Series:
    return series.map(_clean_numeric)


def _clean_text(value) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _canonicalize_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in NUMERIC_COLUMNS:
        if column in df.columns:
            df[column] = _clean_numeric_series(df[column])
    return df


def _schwab_action(row: pd.Series) -> str:
    action = _clean_text(row.get("Action", ""))
    symbol = _clean_text(row.get("Symbol", ""))
    description = _clean_text(row.get("Description", ""))
    security = f"{description} ({symbol})".strip() if symbol else description

    if action == "Buy":
        return f"YOU BOUGHT {security} (Cash)"
    if action == "Sell":
        return f"YOU SOLD {security} (Cash)"
    if action == "Reinvest Shares":
        return f"REINVESTMENT {security} (Cash)"
    if action in {"Cash Dividend", "Reinvest Dividend"}:
        return f"DIVIDEND RECEIVED {security} (Cash)"
    if action == "Journal":
        return f"{description} (Cash)" if description else action
    return action


def _normalize_schwab_statement(df: pd.DataFrame) -> pd.DataFrame:
    normalized = pd.DataFrame(index=df.index, columns=CANONICAL_COLUMNS)
    normalized["Run Date"] = df["Date"]
    normalized["Action"] = df.apply(_schwab_action, axis=1)
    normalized["Symbol"] = df["Symbol"].fillna("").astype(str).str.strip()
    normalized["Description"] = df["Description"].map(_clean_text)
    normalized["Type"] = "Cash"
    normalized["Exchange Quantity"] = "0"
    normalized["Exchange Currency"] = ""
    normalized["Quantity"] = _clean_numeric_series(df["Quantity"])
    normalized["Currency"] = "USD"
    normalized["Price"] = _clean_numeric_series(df["Price"])
    normalized["Exchange Rate"] = "0"
    normalized["Commission"] = ""
    normalized["Fees"] = _clean_numeric_series(df["Fees & Comm"])
    normalized["Accrued Interest"] = ""
    normalized["Amount"] = _clean_numeric_series(df["Amount"])
    normalized["Cash Balance"] = ""
    normalized["Settlement Date"] = ""

    sell_mask = df["Action"].astype(str).str.strip().eq("Sell")
    normalized.loc[sell_mask, "Quantity"] = (
        pd.to_numeric(normalized.loc[sell_mask, "Quantity"], errors="coerce")
        .abs()
        .mul(-1)
        .astype("string")
    )

    return normalized


def normalize_statement_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").copy()
    df.columns = [str(column).strip() for column in df.columns]

    if SCHWAB_COLUMNS.issubset(df.columns):
        normalized = _normalize_schwab_statement(df)
    else:
        normalized = df.rename(columns=FIDELITY_COLUMN_ALIASES)
        for column in CANONICAL_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = ""
        normalized = normalized[CANONICAL_COLUMNS]
        normalized = _canonicalize_numeric_columns(normalized)

    normalized = normalized[pd.to_datetime(normalized["Run Date"], errors="coerce").notna()]
    return normalized


def merge_statements(account_dir: Path):
    statements_dir = account_dir / "statements"
    files = sorted(statements_dir.glob("*.csv"))
    if not files:
        return None

    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f)
            df = normalize_statement_df(df)
            dfs.append(df)
        except Exception as e:
            print(f"⚠️ skipping {f}: {e}")

    if not dfs:
        return None

    combined = (
        pd.concat(dfs, ignore_index=True)
        .drop_duplicates(subset=["Run Date", "Action", "Symbol", "Price", "Cash Balance", "Amount"])
    )

    combined["Run Date"] = pd.to_datetime(combined["Run Date"], errors="coerce")
    combined = combined.sort_values("Run Date").reset_index(drop=True)

    out = account_dir / "combined.csv"
    combined.to_csv(out, index=False)
    print(f"✅ merged {len(files)} files → {out}")
    return out

def regenerate_reports():
    print("▶ rebuilding all reports...")
    subprocess.run([sys.executable, BASE_DIR / "src" / "reports" / "analyze_fidelity.py"], check=False)
    print("✅ Reports updated")

def watch(scan_interval=5, rebuild_interval=600):
    """
    Scan for new or changed CSVs every `scan_interval` seconds,
    but force a full rebuild at least every `rebuild_interval` seconds.
    """
    known_mtimes = {}
    last_rebuild = 0

    while True:
        now = time.time()
        changed = False

        # --- Check for file changes ---
        for account_dir in BASE.iterdir():
            if not account_dir.is_dir():
                continue
            statements = account_dir / "statements"
            if not statements.exists():
                continue

            latest_mtime = max((f.stat().st_mtime for f in statements.glob("*.csv")), default=0)
            if known_mtimes.get(account_dir) != latest_mtime:
                changed = True
                known_mtimes[account_dir] = latest_mtime
                merge_statements(account_dir)

        # --- Trigger rebuild if files changed OR time exceeded ---
        if changed or (now - last_rebuild >= rebuild_interval):
            if not changed:
                print("⏰ Forced rebuild (10 minutes elapsed)")
            regenerate_reports()
            last_rebuild = now

        time.sleep(scan_interval)

if __name__ == "__main__":
    watch()
