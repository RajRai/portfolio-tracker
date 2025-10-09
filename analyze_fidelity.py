import os
import re
import sys
import pandas as pd
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import quantstats as qs

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
    BASE = Path("data")
    accounts = [
        ("ZREDACTED", "Cloud, Semiconductors, Energy, Utilities"),
        ("ZREDACTED", "Optical Computing"),
        ("ALL", "All Trading History"),
    ]

    # You can override with command-line arguments like:
    # python analyze_portfolio.py ZREDACTED ZREDACTED
    if len(sys.argv) > 1:
        account_ids = sys.argv[1:]
        accounts = [a for a in accounts if a[0] in account_ids]

    # ============================================================
    #  Process each account
    # ============================================================

    for i, (account_id, report_name) in enumerate(accounts):
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
        symbols = trades["symbol"].dropna().unique().tolist()

        print(f"Detected symbols: {symbols}")

        # ============================================================
        #  3. Get daily prices from Polygon.io
        # ============================================================

        def get_polygon_prices(symbols, start, end):
            all_prices = {}
            for sym in symbols:
                url = (
                    f"https://api.polygon.io/v2/aggs/ticker/{sym}/range/1/day/"
                    f"{start}/{end}?adjusted=true&sort=asc&limit=50000&apiKey={POLYGON_KEY}"
                )
                r = requests.get(url)
                if r.status_code != 200:
                    print(f"Error fetching {sym}: {r.text}")
                    continue
                data = r.json().get("results", [])
                if not data:
                    print(f"No price data for {sym}")
                    continue
                df = pd.DataFrame(data)
                df["date"] = pd.to_datetime(df["t"], unit="ms")
                df = df.set_index("date")["c"]
                all_prices[sym] = df
            return pd.DataFrame(all_prices)

        start = df["Run Date"].min().strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")

        print(f"Fetching Polygon prices {start} → {end}")
        prices = get_polygon_prices(symbols, start, end)
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

            if current_qty + qty < 0:
                print(f"⚠️ Ignoring invalid sell of {abs(qty)} {sym} on {row['Run Date'].date()} (no holdings)")
                continue

            position_df.loc[trade_date:, sym] += qty
            valid_trades.append(row)

        trades = pd.DataFrame(valid_trades)

        position_df = position_df.ffill().fillna(0)
        value_df = position_df * prices
        weights = value_df.div(value_df.sum(axis=1), axis=0).fillna(0)
        asset_returns = prices.pct_change().fillna(0)
        returns = (weights.shift(1) * asset_returns).sum(axis=1).fillna(0)

        # ============================================================
        #  5. QuantStats report generation
        # ============================================================

        out_dir = Path("out")
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"report_{i}.html"

        spy_df = get_polygon_prices([BENCHMARK], start, end)
        spy_returns = spy_df["SPY"].pct_change().fillna(0)

        qs.reports.html(
            returns,
            benchmark=spy_returns,
            output=out_path,
            title=f"Portfolio Analysis - {report_name}",
        )

        print(f"✅ Report generated for {account_id}")

        # ============================================================
        #  6. Write weights/trades CSVs + index
        # ============================================================

        latest_date = weights.index[-1]
        current_weights = weights.loc[latest_date].sort_values(ascending=False)
        current_weights_df = (
            current_weights.reset_index()
            .rename(columns={"index": "Ticker", latest_date: "Portfolio Weight (%)"})
        )
        current_weights_df["Portfolio Weight (%)"] = (
                current_weights_df["Portfolio Weight (%)"] * 100
        ).map(lambda x: f"{x:.2f}%")

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
            "report": f"/reports/report_{i}.html",
            "weights": f"/data/weights_{i}.csv",
            "trades": f"/data/trades_{i}.csv",
        }

        index_path = out_dir / "accounts.json"
        if index_path.exists():
            accounts_list = pd.read_json(index_path).to_dict(orient="records")
        else:
            accounts_list = []
        accounts_list = [a for a in accounts_list if a["id"] != account_id]
        accounts_list.append(accounts_entry)
        pd.DataFrame(accounts_list).to_json(index_path, orient="records", indent=2)

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
                weights_table=current_weights_df.to_html(
                    index=False, justify="center", border=0,
                    classes="dataframe", float_format="%.2f"
                ),
                trades_table=trades_pct[["Date", "Ticker", "Action", "Trade Price ($)", "Trade Size (% of Account)"]]
                .sort_values("Date")
                .to_html(index=False, justify="center", border=0,
                         classes="dataframe", float_format="%.2f")
            ))


        print(f"✅ Report modified: {out_path}")

if __name__ == "__main__":
    main()
