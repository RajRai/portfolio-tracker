import json
import os
import re
import sys
import pandas as pd
import pytz
import requests
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
import quantstats as qs

import pandas as pd
import numpy as np

from src.reports.polygon import get_polygon_prices
from src.util import BASE_DIR

qs.extend_pandas()

ny_tz = pytz.timezone("America/New_York")

def add_missing_zeros(returns: pd.Series) -> pd.Series:
    """
    For all days between min and max date:
      - If day exists in returns, keep its value.
      - If missing, insert 0.0.
    No assumptions about weekends or holidays.
    """
    r = returns.copy()
    r.index = pd.to_datetime(r.index).normalize()
    r = r[~r.index.duplicated()].sort_index().astype(float)

    if r.empty:
        return r

    start, end = r.index.min(), r.index.max()
    full_range = pd.date_range(start, end, freq="D")

    # Build dict for fast lookup
    r_map = r.to_dict()

    out_vals = [r_map.get(day, 0.0) for day in full_range]
    return pd.Series(out_vals, index=full_range, name="Date")


def build_remaining_lot_book(trades: pd.DataFrame, symbols: list[str]) -> dict[str, list[dict]]:
    lot_book = {sym: [] for sym in symbols}
    eps = sys.float_info.epsilon

    for _, row in trades.sort_values("Run Date").iterrows():
        sym = row["symbol"]
        qty = float(row["quantity"])
        price = float(row["price"])

        if sym not in lot_book or abs(qty) <= eps:
            continue

        if qty > 0:
            lot_book[sym].append({
                "date": row["Run Date"],
                "qty": qty,
                "price": price,
            })
            continue

        sell_qty = -qty
        lots = lot_book[sym]
        loss_lots = sorted(
            [lot for lot in lots if lot["price"] > price + eps],
            key=lambda lot: (-lot["price"], lot["date"]),
        )
        gain_lots = sorted(
            [lot for lot in lots if lot["price"] <= price + eps],
            key=lambda lot: lot["date"],
        )

        for lot in [*loss_lots, *gain_lots]:
            if sell_qty <= eps:
                break
            matched = min(sell_qty, lot["qty"])
            lot["qty"] -= matched
            sell_qty -= matched

        lot_book[sym] = [lot for lot in lots if lot["qty"] > eps]

    return lot_book


ACCOUNTS_FILE = BASE_DIR / "data" / "accounts.json"  # or just Path("accounts.json")

def load_accounts():
    if not ACCOUNTS_FILE.exists():
        print(f"⚠️  Warning: {ACCOUNTS_FILE} not found.")
        exit()

    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Error reading {ACCOUNTS_FILE}: {e}")
        return []

def main():
    # ============================================================
    #  1. Configuration
    # ============================================================

    load_dotenv()
    POLYGON_KEY = os.getenv("POLYGON_API_KEY")
    BENCHMARK = "SPY"

    if not POLYGON_KEY:
        raise RuntimeError("Missing POLYGON_API_KEY in .env")

    # --- Use merged CSVs instead of raw Fidelity exports ---
    BASE = BASE_DIR / "data"
    accounts = load_accounts()

    # You can override with command-line arguments like:
    # python analyze_portfolio.py REDACTED REDACTED
    if len(sys.argv) > 1:
        account_ids = sys.argv[1:]
        accounts = [a for a in accounts if a["id"] in account_ids]

    # ============================================================
    #  Process each account
    # ============================================================

    for i, account in enumerate(accounts):
        account_id = account["id"]
        report_name = account["name"]
        merged_csv = BASE / account_id / "combined.csv"
        if not merged_csv.exists():
            print(f"⚠️ Skipping {account_id} (no merged CSV found)")
            continue

        print(f"\n===============================")
        print(f"Processing {account_id} → {report_name}")
        print(f"===============================")

        df = pd.read_csv(merged_csv)
        df = df[pd.to_datetime(df["Run Date"], errors="coerce").notna()].copy()
        df["Run Date"] = pd.to_datetime(df["Run Date"])
        df = df.sort_values("Run Date")

        # ============================================================
        #  2. Parse trades
        # ============================================================

        mask = df["Action"].str.contains(r"YOU (BOUGHT|SOLD)", flags=re.I, na=False)
        trades = df[mask].copy()
        reinvest_mask = (
            df["Action"].str.contains(r"REINVEST", flags=re.I, na=False)
            & pd.to_numeric(df["Quantity"], errors="coerce").fillna(0).abs().gt(sys.float_info.epsilon)
            & pd.to_numeric(df["Price"], errors="coerce").notna()
        )
        reinvestments = df[reinvest_mask].copy()

        def parse_side(x):
            if re.search("BOUGHT", x, re.I):
                return "BUY"
            elif re.search("SOLD", x, re.I):
                return "SELL"
            return None

        trades["side"] = trades["Action"].apply(parse_side)
        trades["symbol"] = trades["Symbol"].fillna("").str.strip()
        trades["quantity"] = trades["Quantity"].astype(float)
        trades["price"] = trades["Price"].astype(float)
        trades["amount"] = trades["Amount"].astype(float)
        trades = trades[["Run Date", "symbol", "side", "quantity", "price", "amount"]]

        if not reinvestments.empty:
            reinvestments["Run Date"] = pd.to_datetime(reinvestments["Run Date"])
            reinvestments["side"] = "BUY"
            reinvestments["symbol"] = reinvestments["Symbol"].fillna("").str.strip()
            reinvestments["quantity"] = reinvestments["Quantity"].astype(float)
            reinvestments["price"] = reinvestments["Price"].astype(float)
            reinvestments["amount"] = reinvestments["Amount"].astype(float)
            reinvestments = reinvestments[["Run Date", "symbol", "side", "quantity", "price", "amount"]]

        # --- Detect distributions (dividends, interest, etc.) ---
        dist_mask = (
            df["Action"].str.contains(r"DIVIDEND|INTEREST|DISTRIBUTION|REINVEST", flags=re.I, na=False)
            & df["Type"].str.contains("Shares")
        )
        distributions = df[dist_mask].copy()

        trade_frames = [trades]
        if not reinvestments.empty:
            print(f"Detected {len(reinvestments)} reinvestments.")
            trade_frames.append(reinvestments)

        if not distributions.empty:
            distributions["Run Date"] = pd.to_datetime(distributions["Run Date"])
            distributions["side"] = "BUY"
            distributions["symbol"] = distributions['Symbol']
            distributions["price"] = 0.0
            distributions["amount"] = 0.0
            distributions['quantity'] = distributions['Quantity']
            print(f"Detected {len(distributions)} distributions.")
            trade_frames.append(distributions[["Run Date", "symbol", "side", "quantity", "price", "amount"]])

        trades = (
            pd.concat(trade_frames, ignore_index=True)
            .sort_values("Run Date")
            .reset_index(drop=True)
        )
        symbols = trades["symbol"].dropna()
        symbols = symbols[symbols.ne("")].unique().tolist()

        print(f"Detected symbols: {symbols}")

        # ============================================================
        #  3. Get daily prices from Polygon.io or cache
        # ============================================================
        start = df["Run Date"].min().strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
        all_symbols = list(dict.fromkeys([*symbols, BENCHMARK]))

        print(f"Fetching Polygon prices {start} → {end}")
        all_prices = get_polygon_prices(all_symbols, start, end)
        prices = all_prices.reindex(columns=symbols)
        if prices.empty:
            print(f"⚠️ No pricing data for {account_id}, skipping.")
            continue

        # ============================================================
        #  4. Portfolio reconstruction and returns
        # ============================================================

        position_df = pd.DataFrame(0.0, index=prices.index, columns=symbols)
        valid_trades = []

        for _, row in trades.iterrows():
            qty = row.quantity
            sym = row.symbol
            trade_date = prices.index[prices.index >= row["Run Date"]].min()
            if pd.isna(trade_date) or sym not in position_df.columns:
                continue

            current_qty = (
                position_df.loc[:trade_date, sym].iloc[-1]
                if position_df.loc[:trade_date, sym].any()
                else 0
            )

            if current_qty + qty < -sys.float_info.epsilon:
                print(f"⚠️ Ignoring invalid sell of {abs(qty)} {sym} on {row['Run Date'].date()} ({current_qty + qty} after transaction)")
                continue

            position_df.loc[trade_date:, sym] = (position_df.loc[trade_date:, sym] + qty).clip(lower=0)
            valid_trades.append(row)

        trades = pd.DataFrame(valid_trades)
        lot_book = build_remaining_lot_book(trades, symbols)

        position_df = position_df.ffill().fillna(0)
        position_df[(position_df.abs() < 1e-6)] = 0.0
        value_df = position_df * prices
        weights = value_df.div(value_df.sum(axis=1), axis=0).fillna(0)
        asset_returns = prices.pct_change().fillna(0)
        returns = (weights.shift(1) * asset_returns).sum(axis=1).fillna(0)
        returns = add_missing_zeros(returns)

        # ============================================================
        #  5. QuantStats report generation
        # ============================================================

        out_dir = BASE_DIR / "out"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"report_{i}.html"

        spy_df = all_prices[[BENCHMARK]]
        spy_returns = spy_df[BENCHMARK].pct_change().fillna(0)

        qs.reports.html(
            returns,
            rf=.0396,
            benchmark=spy_returns,
            output=out_path,
            title=f"Portfolio Analysis - {report_name}",
        )

        print(f"✅ Report generated for {account_id}")

        # =====================  A) Prep series for charts  =====================
        # Normalize both to midnight (no time component) for exact matching
        returns.index = pd.to_datetime(returns.index).normalize()
        spy_returns.index = pd.to_datetime(spy_returns.index).normalize()

        # Align on shared days
        shared_index = returns.index.intersection(spy_returns.index)
        port_ret = returns.loc[shared_index].astype(float)
        bench_ret = spy_returns.loc[shared_index].astype(float)

        # Compute equities
        port_eq = (1 + port_ret).cumprod()
        bench_eq = (1 + bench_ret).cumprod()

        # Daily relative-to-benchmark series
        daily_spread = (port_ret - bench_ret)
        cum_spread   = (1.0 + daily_spread).cumprod() - 1.0  # relative cumulative out/under-performance

        def _clamp_for_multiple(s: pd.Series):
            s = s.mask((s < 0) & (s > -0.001), -0.001)
            s = s.mask((s >= 0) & (s < 0.001), 0.001)
            return s

        daily_multiple = _clamp_for_multiple(port_ret).div(_clamp_for_multiple(bench_ret))

        # Weights time series (already computed): `weights`
        weights_top = weights.copy()
        weights_top = weights_top.clip(lower=0).div(weights_top.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)

        # Export a single dict for JSON-less inline embedding (we’ll embed arrays directly)
        def _series_to_pairs(s: pd.Series):
            s = s.dropna()
            return [{"t": d.strftime("%Y-%m-%d"), "v": float(v)} for d, v in s.items()]

        def _frame_to_stacked_list(df: pd.DataFrame):
            out = []
            for col in df.columns:
                s = df[col].dropna().copy()
                # Keep alignment but replace zero weights with None
                s[s.abs() < 1e-6] = None
                if s.isna().all():
                    continue
                pts = [{"t": d.strftime("%Y-%m-%d"), "v": (None if pd.isna(v) else float(v))} for d, v in s.items()]
                out.append({"name": col, "points": pts})
            return out

        chart_payload = {
            "portfolio": {
                "daily": _series_to_pairs(port_ret),
                "equity": _series_to_pairs(port_eq),
            },
            "benchmark": {
                "ticker": BENCHMARK,
                "daily": _series_to_pairs(bench_ret),
                "equity": _series_to_pairs(bench_eq),
            },
            "spread": {
                "daily": _series_to_pairs(daily_spread),
                "cumulative": _series_to_pairs(cum_spread),
            },
            "multiple": {
                "daily": _series_to_pairs(daily_multiple),
            },
            "weights": _frame_to_stacked_list(weights_top),
        }

        # ============================================================
        #  6. Write weights/trades CSVs + index
        # ============================================================

        latest_date = weights.index[-1]
        current_weights = weights.loc[latest_date]
        current_weights = current_weights[current_weights.abs() > sys.float_info.epsilon]
        current_weights = current_weights.sort_values(ascending=False)
        current_lot_qty_df = pd.DataFrame(0.0, index=prices.index, columns=symbols)
        current_lot_basis = pd.Series(0.0, index=symbols, dtype=float)
        eps = sys.float_info.epsilon

        for sym in symbols:
            sym_prices = prices[sym].dropna()
            if sym_prices.empty:
                continue

            for lot in lot_book.get(sym, []):
                lot_date = sym_prices.index[sym_prices.index >= lot["date"]].min()
                if pd.isna(lot_date):
                    continue

                current_lot_qty_df.loc[lot_date:, sym] += lot["qty"]
                if lot["price"] > eps:
                    current_lot_basis.loc[sym] += lot["qty"] * float(sym_prices.loc[lot_date])

        current_lot_value_df = current_lot_qty_df * prices.reindex(current_lot_qty_df.index)
        current_quantities = current_lot_qty_df.loc[latest_date].reindex(current_weights.index)
        current_values = current_lot_value_df.loc[latest_date].reindex(current_weights.index)
        today_gl = current_lot_value_df.pct_change().loc[latest_date].reindex(current_weights.index)
        total_gl = current_values.div(current_lot_basis.reindex(current_weights.index).replace(0, np.nan)) - 1.0

        def _fmt_pct(v):
            return "—" if pd.isna(v) else f"{v * 100:+.2f}%"

        current_weights_df = (
            current_weights.reset_index()
            .rename(columns={"index": "Ticker", latest_date: "Portfolio Weight (%)"})
        )
        current_weights_df["Portfolio Weight (%)"] = (
                current_weights_df["Portfolio Weight (%)"] * 100
        ).map(lambda x: f"{x:.2f}%")
        current_weights_df["Today G/L"] = current_weights.index.map(today_gl.get).map(_fmt_pct)
        current_weights_df["Total G/L (approx.)"] = current_weights.index.map(total_gl.get).map(_fmt_pct)
        current_weights_df["_Quantity"] = current_weights.index.map(current_quantities.get).map(
            lambda x: "" if pd.isna(x) else f"{float(x):.10f}"
        )
        current_weights_df["_BasisApprox"] = current_weights.index.map(
            current_lot_basis.reindex(current_weights.index).get
        ).map(lambda x: "" if pd.isna(x) else f"{float(x):.10f}")

        portfolio_value = value_df.sum(axis=1)
        trades_pct = trades.copy()
        trade_values = []
        for _, row in trades.iterrows():
            trade_date = portfolio_value.index[portfolio_value.index >= row["Run Date"]].min()
            if pd.isna(trade_date):
                trade_values.append(float("nan"))
                continue
            account_val = portfolio_value.loc[trade_date]
            trade_val = abs(row["quantity"] * row["price"])
            pct_of_account = 100 * trade_val / account_val if account_val > 0 else float("nan")
            trade_values.append(pct_of_account)

        trades_pct["Trade Size (% of Account)"] = [f"{round(x, 2)}%" for x in trade_values]

        weights_csv_path = out_dir / f"weights_{i}.csv"
        trades_csv_path = out_dir / f"trades_{i}.csv"

        current_weights_df.to_csv(weights_csv_path, index=False)
        trades_pct[["Run Date", "symbol", "side", "price", "Trade Size (% of Account)"]].rename(
            columns={
                "Run Date": "Date",
                "symbol": "Ticker",
                "side": "Action",
                "price": "Trade Price ($)",
            }
        ).to_csv(trades_csv_path, index=False)

        accounts_entry = {
            "id": account_id,
            "name": report_name,
            "about": account.get("about"),
            "report": f"/reports/report_{i}.html",
            "weights": f"/data/weights_{i}.csv",
            "trades": f"/data/trades_{i}.csv",
        }

        index_path = out_dir / "accounts.json"
        if index_path.exists():
            with open(index_path, "r", encoding="utf-8") as f:
                accounts_list = json.load(f)
        else:
            accounts_list = []
        accounts_list = [a for a in accounts_list if a["id"] != account_id]
        accounts_list.append(accounts_entry)
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(accounts_list, f, indent=2)

        print(f"✅ CSVs generated for {account_id}")

        # ============================================================
        #  7. Append weights + trades to the QuantStats report
        # ============================================================

        current_weights_df = current_weights_df.rename(columns={
            "Symbol": "Ticker",
            "Weight": "Portfolio Weight (%)"
        })
        trades_pct = trades_pct.rename(columns={
            "Run Date": "Date",
            "symbol": "Ticker",
            "side": "Action",
            "price": "Trade Price ($)",
            "PercentOfAccount": "Trade Size (% of Account)"
        })
        trades_pct["Date"] = trades_pct["Date"].dt.strftime("%Y-%m-%d")

        with open(out_path, "a", encoding="utf-8") as f:
            f.write("""
            <!-- ================= CUSTOM PORTFOLIO SECTION ================= -->
            <div style="clear:both; width:100%; padding-top:40px;">
              <hr style="margin:40px 0;">
              <h1 style="text-align:center;">Portfolio Composition & Trade History</h1>
              <p style="text-align:center; font-style:italic;">Supplemental data generated from Fidelity export</p>
        
              <h2 style="text-align:center; margin-top:30px;">Current Portfolio Weights</h2>
              <p style="text-align:center;">Latest portfolio composition based on most recent trading day.</p>
              {weights_table}
        
              <h2 style="text-align:center; margin-top:50px;">Trade History (as % of Account Value)</h2>
              <p style="text-align:center;">Each trade's notional value relative to total portfolio value at time of execution.</p>
              {trades_table}
            </div>
            """.format(
                weights_table=current_weights_df[
                    [col for col in current_weights_df.columns if not col.startswith("_")]
                ].to_html(
                    index=False, justify="center", border=0,
                    classes="dataframe", float_format="%.2f"
                ),
                trades_table=trades_pct[["Date", "Ticker", "Action", "Trade Price ($)", "Trade Size (% of Account)"]]
                .sort_values("Date")
                .to_html(index=False, justify="center", border=0,
                         classes="dataframe", float_format="%.2f")
            ))


        print(f"✅ Report modified: {out_path}")

        # =====================  B) Emit self-contained Plotly JSON =====================
        interactive_json_path = out_dir / f"report_{i}_interactive.json"
        interactive_json_path.write_text(
            json.dumps(chart_payload, indent=2),
            encoding="utf-8"
        )
        print(f"✅ Interactive JSON written: {interactive_json_path}")

if __name__ == "__main__":
    main()
