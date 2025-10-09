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

    # Support multiple CSVs
    if len(sys.argv) > 1:
        csv_paths = [Path(p) for p in sys.argv[1:]]
    else:
        csv_paths = [
            (Path("Y:\\History_for_Account_ZREDACTED.csv"), 'Cloud, Semiconductors, Energy, Utilities'),
            (Path("Y:\\History_for_Account_ZREDACTED.csv"), 'Optical Computing'),
        ]

    # ============================================================
    #  Process each CSV
    # ============================================================

    for i, (csv_path, report_name) in enumerate(csv_paths):
        print(f"\n===============================")
        print(f"Processing {csv_path.name}")
        print(f"===============================")

        df = pd.read_csv(csv_path)
        df = df[pd.to_datetime(df["Run Date"], errors="coerce").notna()].copy()
        df["Run Date"] = pd.to_datetime(df["Run Date"])
        df = df.sort_values("Run Date")

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
            print(f"⚠️ No pricing data for {csv_path.name}, skipping.")
            continue

        # ============================================================
        #  4. Reconstruct daily portfolio weights and compute returns
        # ============================================================

        position_df = pd.DataFrame(0.0, index=prices.index, columns=symbols)

        # Track valid (executed) trades for later reporting
        valid_trades = []

        for _, row in trades.iterrows():
            qty = row.quantity
            sym = row.symbol
            trade_date = prices.index[prices.index >= row["Run Date"]].min()
            if pd.isna(trade_date) or sym not in position_df.columns:
                continue

            # Determine current holdings before trade
            current_qty = (
                position_df.loc[:trade_date, sym].iloc[-1]
                if position_df.loc[:trade_date, sym].any()
                else 0
            )

            # Skip invalid sells that exceed holdings
            if current_qty + qty < 0:
                print(f"⚠️ Ignoring invalid sell of {abs(qty)} {sym} on {row['Run Date'].date()} (no holdings)")
                continue

            # Apply trade
            position_df.loc[trade_date:, sym] += qty

            # Record only valid ones
            valid_trades.append(row)

        # Replace trades DataFrame with only valid trades
        trades = pd.DataFrame(valid_trades)

        position_df = position_df.ffill().fillna(0)
        value_df = position_df * prices
        weights = value_df.div(value_df.sum(axis=1), axis=0).fillna(0)
        asset_returns = prices.pct_change().fillna(0)
        returns = (weights.shift(1) * asset_returns).sum(axis=1).fillna(0)

        # --- Current Weights (latest available day) ---
        latest_date = weights.index[-1]
        current_weights = weights.loc[latest_date]
        current_weights = current_weights[current_weights.abs() > 1e-6]  # drop zeros / dust
        current_weights = current_weights.sort_values(ascending=False)
        current_weights_df = (
            current_weights.reset_index()
            .rename(columns={"index": "Symbol", latest_date: "Weight"})
        )
        current_weights_df["Weight"] = (current_weights_df["Weight"] * 100).map(lambda x: f"{x:.2f}%")

        # --- Normalize trades by portfolio value at trade date ---
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

        trades_pct["PercentOfAccount"] = [f'{round(x, 2)}%' for x in trade_values]

        # ============================================================
        #  5. Generate QuantStats Report
        # ============================================================

        print("Getting benchmark data...")
        spy_df = get_polygon_prices([BENCHMARK], start, end)

        print("Generating QuantStats report...")
        spy_returns = spy_df["SPY"].pct_change().fillna(0)

        out_dir = Path("out")
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"report_{i}.html"

        qs.reports.html(returns, benchmark=spy_returns, output=out_path, title=f"Portfolio Analysis - {report_name}")

        # ============================================================
        #  6. Append weights + trades to the QuantStats report
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


        print(f"✅ Report generated: {out_path}")

        # ============================================================
        #  7. Write CSV data for API server
        # ============================================================

        weights_csv_path = out_dir / f"weights_{i}.csv"
        trades_csv_path = out_dir / f"trades_{i}.csv"

        current_weights_df.to_csv(weights_csv_path, index=False)
        trades_pct[["Date", "Ticker", "Action", "Trade Price ($)", "Trade Size (% of Account)"]].to_csv(trades_csv_path, index=False)

        accounts_entry = {
            "id": i,
            "name": report_name,
            "report": f"/reports/report_{i}.html",
            "weights": f"/data/weights_{i}.csv",
            "trades": f"/data/trades_{i}.csv"
        }

        index_path = out_dir / "accounts.json"
        if index_path.exists():
            accounts = pd.read_json(index_path).to_dict(orient="records")
        else:
            accounts = []
        accounts = [a for a in accounts if a["id"] != i]
        accounts.append(accounts_entry)
        pd.DataFrame(accounts).to_json(index_path, orient="records", indent=2)

        print(f"✅ CSV written: {weights_csv_path}, {trades_csv_path}")

if __name__ == "__main__":
    main()
