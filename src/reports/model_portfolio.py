from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
import quantstats as qs

from src.reports.analyze_fidelity import (
    SHARE_EPSILON,
    _regression_beta,
    add_missing_zeros,
)
from src.reports.polygon import get_polygon_prices
from src.tools import ToolDataError, normalize_tickers
from src.util import BASE_DIR

qs.extend_pandas()

OUT_DIR = BASE_DIR / "out"


def _to_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(str(value).replace(",", "").replace("$", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _parse_date(value: str | None, label: str) -> pd.Timestamp:
    if not value:
        raise ToolDataError(f"Choose a {label.lower()}", 400)
    try:
        parsed = pd.Timestamp(value).normalize()
    except Exception as exc:  # pragma: no cover - pandas error text is unstable
        raise ToolDataError(f"Invalid {label.lower()}", 400) from exc
    if pd.isna(parsed):
        raise ToolDataError(f"Invalid {label.lower()}", 400)
    return parsed


def _normalize_weighted_holdings(rows, label: str) -> list[dict]:
    if not isinstance(rows, list):
        raise ToolDataError(f"Add at least one {label.lower()} holding", 400)

    totals: dict[str, float] = {}
    order: list[str] = []

    for row in rows:
        ticker = normalize_tickers((row or {}).get("ticker"))[:1]
        weight = _to_float((row or {}).get("weight"))
        if not ticker or weight is None or weight <= 0:
            continue
        symbol = ticker[0]
        if symbol not in totals:
            totals[symbol] = 0.0
            order.append(symbol)
        totals[symbol] += weight

    total_weight = sum(totals.values())
    if total_weight <= 0:
        raise ToolDataError(f"Add at least one {label.lower()} holding", 400)

    return [
        {
            "ticker": ticker,
            "weight": totals[ticker] / total_weight,
        }
        for ticker in order
    ]


def _parse_benchmark_config(benchmark: dict) -> dict:
    benchmark = benchmark or {}
    mode = str(benchmark.get("mode") or "ticker").strip().lower()
    if mode == "ticker":
        ticker = normalize_tickers(benchmark.get("ticker"))[:1]
        if not ticker:
            raise ToolDataError("Choose a benchmark ticker", 400)
        return {
            "mode": "ticker",
            "ticker": ticker[0],
            "label": ticker[0],
            "symbols": [ticker[0]],
        }

    if mode == "portfolio":
        holdings = _normalize_weighted_holdings(benchmark.get("holdings"), "benchmark portfolio")
        label = str(benchmark.get("label") or "Benchmark Portfolio").strip() or "Benchmark Portfolio"
        return {
            "mode": "portfolio",
            "label": label,
            "holdings": holdings,
            "symbols": [holding["ticker"] for holding in holdings],
        }

    raise ToolDataError("Choose a benchmark ticker or portfolio", 400)


def _price_matrix(symbols: list[str], start_date: pd.Timestamp) -> pd.DataFrame:
    end_date = datetime.now().strftime("%Y-%m-%d")
    fetch_start = min(start_date, pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=7))
    prices = get_polygon_prices(symbols, fetch_start.strftime("%Y-%m-%d"), end_date)
    if prices.empty:
        raise ToolDataError(
            "No price history was found for the selected holdings. "
            "Try an earlier start date.",
            502,
        )
    prices = prices.reindex(columns=symbols).sort_index()
    prices.index = pd.to_datetime(prices.index).normalize()
    prices = prices[~prices.index.duplicated(keep="last")]
    return prices


def _first_common_start_date(prices: pd.DataFrame, symbols: list[str], requested_start: pd.Timestamp) -> pd.Timestamp:
    future_prices = prices[prices.index >= requested_start]
    if future_prices.empty:
        latest_available = prices.index.max() if not prices.empty else None
        latest_text = (
            f" Latest available market date was {pd.Timestamp(latest_available).strftime('%Y-%m-%d')}."
            if latest_available is not None and not pd.isna(latest_available)
            else ""
        )
        raise ToolDataError(
            "No price history was found on or after the selected start date. "
            "Try an earlier trading day."
            f"{latest_text}",
            400,
        )

    eligible = future_prices.dropna(subset=symbols, how="any")
    if eligible.empty:
        missing = [symbol for symbol in symbols if future_prices[symbol].dropna().empty]
        if missing:
            raise ToolDataError(
                f"Missing price history on or after the start date for: {', '.join(missing)}",
                400,
            )
        raise ToolDataError("No common start date was found for every selected symbol", 400)

    return pd.Timestamp(eligible.index[0]).normalize()


def _start_date_warning(prices: pd.DataFrame, symbols: list[str], requested_start: pd.Timestamp, effective_start: pd.Timestamp) -> str | None:
    if effective_start <= requested_start:
        return None

    requested_text = requested_start.strftime("%Y-%m-%d")
    effective_text = effective_start.strftime("%Y-%m-%d")

    if requested_start not in prices.index:
        return (
            f"The selected start date, {requested_text}, was not a market trading day, "
            f"so the report starts on {effective_text}."
        )

    requested_row = prices.loc[requested_start, symbols]
    missing_symbols = [
        symbol
        for symbol, value in requested_row.items()
        if pd.isna(value)
    ]
    if missing_symbols:
        return (
            f"The report starts on {effective_text} because these symbols did not have "
            f"price history on {requested_text}: {', '.join(missing_symbols)}."
        )

    return (
        f"The requested start date was adjusted from {requested_text} to {effective_text} "
        "based on the first common pricing date."
    )


def _build_buy_and_hold_basket(prices: pd.DataFrame, holdings: list[dict], start_date: pd.Timestamp) -> dict:
    symbols = [holding["ticker"] for holding in holdings]
    basket_prices = prices.reindex(columns=symbols)
    basket_prices = basket_prices[basket_prices.index >= start_date].copy()
    basket_prices = basket_prices.ffill().dropna(subset=symbols, how="any")
    if basket_prices.empty:
        raise ToolDataError("No price history was found after the effective start date", 400)

    entry_prices = basket_prices.loc[start_date, symbols].astype(float)
    quantities = pd.Series(
        {
            holding["ticker"]: float(holding["weight"]) / float(entry_prices[holding["ticker"]])
            for holding in holdings
        },
        dtype=float,
    )
    position_df = pd.DataFrame(
        {ticker: quantities[ticker] for ticker in symbols},
        index=basket_prices.index,
    )
    value_df = position_df.mul(basket_prices, axis=1)
    total_value = value_df.sum(axis=1)
    returns = total_value.pct_change().fillna(0.0)
    weights_df = value_df.div(total_value.replace(0, pd.NA), axis=0).fillna(0.0)
    basis = quantities * entry_prices

    return {
        "symbols": symbols,
        "prices": basket_prices,
        "entry_prices": entry_prices,
        "quantities": quantities,
        "value_df": value_df,
        "weights_df": weights_df,
        "returns": returns,
        "basis": basis,
    }


def _series_to_pairs(series: pd.Series) -> list[dict]:
    series = series.dropna()
    return [{"t": date.strftime("%Y-%m-%d"), "v": float(value)} for date, value in series.items()]


def _frame_to_stacked_list(frame: pd.DataFrame) -> list[dict]:
    out = []
    for column in frame.columns:
        series = frame[column].dropna().copy()
        series[series.abs() < SHARE_EPSILON] = None
        if series.isna().all():
            continue
        out.append(
            {
                "name": column,
                "points": [
                    {
                        "t": date.strftime("%Y-%m-%d"),
                        "v": (None if pd.isna(value) else float(value)),
                    }
                    for date, value in series.items()
                ],
            }
        )
    return out


def _build_chart_payload(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    weights_df: pd.DataFrame,
    benchmark_config: dict,
    requested_start_date: pd.Timestamp,
    effective_start_date: pd.Timestamp,
) -> dict:
    portfolio_returns = add_missing_zeros(portfolio_returns)
    benchmark_returns = add_missing_zeros(benchmark_returns).reindex(portfolio_returns.index, fill_value=0.0)

    shared_index = portfolio_returns.index.intersection(benchmark_returns.index)
    portfolio_returns = portfolio_returns.loc[shared_index].astype(float)
    benchmark_returns = benchmark_returns.loc[shared_index].astype(float)

    portfolio_equity = (1 + portfolio_returns).cumprod()
    benchmark_equity = (1 + benchmark_returns).cumprod()
    daily_spread = portfolio_returns - benchmark_returns
    cumulative_spread = (1 + daily_spread).cumprod() - 1.0
    beta = _regression_beta(portfolio_returns, benchmark_returns)
    daily_alpha = portfolio_returns - beta * benchmark_returns
    cumulative_alpha = (1 + daily_alpha).cumprod() - 1.0

    normalized_weights = (
        weights_df.clip(lower=0)
        .div(weights_df.sum(axis=1).replace(0, pd.NA), axis=0)
        .fillna(0.0)
    )

    benchmark_payload = {
        "type": benchmark_config["mode"],
        "label": benchmark_config["label"],
        "daily": _series_to_pairs(benchmark_returns),
        "equity": _series_to_pairs(benchmark_equity),
    }
    if benchmark_config["mode"] == "ticker":
        benchmark_payload["ticker"] = benchmark_config["ticker"]

    return {
        "meta": {
            "requested_start_date": requested_start_date.strftime("%Y-%m-%d"),
            "effective_start_date": effective_start_date.strftime("%Y-%m-%d"),
            "disable_live": True,
        },
        "portfolio": {
            "daily": _series_to_pairs(portfolio_returns),
            "equity": _series_to_pairs(portfolio_equity),
        },
        "benchmark": benchmark_payload,
        "spread": {
            "daily": _series_to_pairs(daily_spread),
            "cumulative": _series_to_pairs(cumulative_spread),
        },
        "alpha": {
            "beta": beta,
            "daily": _series_to_pairs(daily_alpha),
            "cumulative": _series_to_pairs(cumulative_alpha),
        },
        "weights": _frame_to_stacked_list(normalized_weights),
    }


def _format_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value) * 100:+.2f}%"


def _current_weights_frame(basket: dict) -> pd.DataFrame:
    weights_df = basket["weights_df"]
    latest_date = weights_df.index[-1]
    current_weights = weights_df.loc[latest_date]
    current_weights = current_weights[current_weights.abs() > SHARE_EPSILON].sort_values(ascending=False)
    current_values = basket["value_df"].loc[latest_date].reindex(current_weights.index)
    today_gl = basket["prices"].pct_change().loc[latest_date].reindex(current_weights.index)
    total_gl = current_values.div(basket["basis"].reindex(current_weights.index).replace(0, pd.NA)) - 1.0

    current_weights_df = (
        current_weights.reset_index()
        .rename(columns={"index": "Ticker", latest_date: "Portfolio Weight (%)"})
    )
    current_weights_df["Portfolio Weight (%)"] = (
        current_weights_df["Portfolio Weight (%)"] * 100
    ).map(lambda value: f"{value:.2f}%")
    current_weights_df["Today G/L"] = current_weights.index.map(today_gl.get).map(_format_pct)
    current_weights_df["Total G/L (approx.)"] = current_weights.index.map(total_gl.get).map(_format_pct)
    current_weights_df["_Quantity"] = current_weights.index.map(basket["quantities"].get).map(
        lambda value: "" if pd.isna(value) else f"{float(value):.10f}"
    )
    current_weights_df["_BasisApprox"] = current_weights.index.map(basket["basis"].get).map(
        lambda value: "" if pd.isna(value) else f"{float(value):.10f}"
    )
    return current_weights_df


def _trade_history_frame(basket: dict, start_date: pd.Timestamp, holdings: list[dict]) -> pd.DataFrame:
    rows = []
    for holding in holdings:
        ticker = holding["ticker"]
        rows.append(
            {
                "Date": start_date.strftime("%Y-%m-%d"),
                "Ticker": ticker,
                "Action": "BUY",
                "Trade Price ($)": float(basket["entry_prices"][ticker]),
                "Trade Size (% of Account)": f"{holding['weight'] * 100:.2f}%",
            }
        )
    return pd.DataFrame(rows)


def _append_tables_to_report(report_path: Path, weights_df: pd.DataFrame, trades_df: pd.DataFrame):
    display_weights = weights_df[[column for column in weights_df.columns if not column.startswith("_")]]
    with open(report_path, "a", encoding="utf-8") as handle:
        handle.write(
            """
            <!-- ================= CUSTOM PORTFOLIO SECTION ================= -->
            <div style="clear:both; width:100%; padding-top:40px;">
              <hr style="margin:40px 0;">
              <h1 style="text-align:center;">Portfolio Composition & Trade History</h1>
              <p style="text-align:center; font-style:italic;">Supplemental data generated from model weights</p>

              <h2 style="text-align:center; margin-top:30px;">Current Portfolio Weights</h2>
              <p style="text-align:center;">Latest portfolio composition based on the most recent available close.</p>
              {weights_table}

              <h2 style="text-align:center; margin-top:50px;">Trade History (as % of Account Value)</h2>
              <p style="text-align:center;">Synthetic opening buys used to seed the model portfolio.</p>
              {trades_table}
            </div>
            """.format(
                weights_table=display_weights.to_html(
                    index=False,
                    justify="center",
                    border=0,
                    classes="dataframe",
                    float_format="%.2f",
                ),
                trades_table=trades_df.to_html(
                    index=False,
                    justify="center",
                    border=0,
                    classes="dataframe",
                    float_format="%.2f",
                ),
            )
        )


def _slug_token(value: str) -> str:
    token = re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")
    return token or "MODEL_PORTFOLIO"


def create_model_portfolio_report(
    body: dict,
    out_dir: Path = OUT_DIR,
) -> dict:
    report_name = str(body.get("reportName") or "Model Portfolio").strip() or "Model Portfolio"
    requested_start_date = _parse_date(body.get("startDate"), "Start date")
    portfolio_holdings = _normalize_weighted_holdings(body.get("holdings"), "portfolio")
    benchmark_config = _parse_benchmark_config(body.get("benchmark") or {})

    symbols = list(
        dict.fromkeys(
            [holding["ticker"] for holding in portfolio_holdings] + benchmark_config["symbols"]
        )
    )
    prices = _price_matrix(symbols, requested_start_date)
    effective_start_date = _first_common_start_date(prices, symbols, requested_start_date)
    working_prices = prices[prices.index >= effective_start_date].copy().ffill()

    portfolio_basket = _build_buy_and_hold_basket(working_prices, portfolio_holdings, effective_start_date)
    if benchmark_config["mode"] == "ticker":
        benchmark_basket = _build_buy_and_hold_basket(
            working_prices,
            [{"ticker": benchmark_config["ticker"], "weight": 1.0}],
            effective_start_date,
        )
    else:
        benchmark_basket = _build_buy_and_hold_basket(
            working_prices,
            benchmark_config["holdings"],
            effective_start_date,
        )

    portfolio_returns = portfolio_basket["returns"]
    benchmark_returns = benchmark_basket["returns"]

    tool_dir = out_dir / "tool-model-portfolios"
    tool_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug_token(report_name)
    file_slug = f"{slug.lower()}_{uuid4().hex[:10]}"
    report_path = tool_dir / f"report_{file_slug}.html"
    interactive_json_path = tool_dir / f"report_{file_slug}_interactive.json"
    weights_csv_path = tool_dir / f"weights_{file_slug}.csv"
    trades_csv_path = tool_dir / f"trades_{file_slug}.csv"

    benchmark_series = add_missing_zeros(benchmark_returns).reindex(
        add_missing_zeros(portfolio_returns).index,
        fill_value=0.0,
    )
    qs.reports.html(
        add_missing_zeros(portfolio_returns),
        rf=0.0396,
        benchmark=benchmark_series,
        output=report_path,
        title=f"Portfolio Analysis - {report_name}",
    )

    current_weights_df = _current_weights_frame(portfolio_basket)
    trades_df = _trade_history_frame(portfolio_basket, effective_start_date, portfolio_holdings)
    current_weights_df.to_csv(weights_csv_path, index=False)
    trades_df.to_csv(trades_csv_path, index=False)
    _append_tables_to_report(report_path, current_weights_df, trades_df)

    chart_payload = _build_chart_payload(
        portfolio_returns,
        benchmark_returns,
        portfolio_basket["weights_df"],
        benchmark_config,
        requested_start_date,
        effective_start_date,
    )
    interactive_json_path.write_text(json.dumps(chart_payload, indent=2), encoding="utf-8")

    viewer_account = {
        "id": f"TOOL_MODEL_{uuid4().hex[:12].upper()}",
        "name": report_name,
        "report": f"/reports/tool-model-portfolios/{report_path.name}",
        "weights": f"/data/tool-model-portfolios/{weights_csv_path.name}",
        "trades": f"/data/tool-model-portfolios/{trades_csv_path.name}",
        "disable_live": True,
    }

    warnings = []
    start_date_warning = _start_date_warning(
        working_prices,
        symbols,
        requested_start_date,
        effective_start_date,
    )
    if start_date_warning:
        warnings.append(start_date_warning)

    return {
        "account": viewer_account,
        "effectiveStartDate": effective_start_date.strftime("%Y-%m-%d"),
        "warnings": warnings,
    }
