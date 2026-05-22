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
from src.reports.polygon import compute_total_return_returns, get_polygon_dividends, get_polygon_prices
from src.tools import ToolDataError, estimate_market_cap_weights, normalize_tickers
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


def _parse_history_window(value: dict | None) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    if not isinstance(value, dict):
        return None
    start_date = value.get("startDate")
    end_date = value.get("endDate")
    if not start_date or not end_date:
        return None
    parsed_start = _parse_date(start_date, "Start date")
    parsed_end = _parse_date(end_date, "End date")
    if parsed_end < parsed_start:
        raise ToolDataError("End date must be on or after the start date", 400)
    return parsed_start, parsed_end


def _today_date() -> pd.Timestamp:
    return pd.Timestamp(datetime.now().date()).normalize()


def _format_date(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _normalize_weighted_holdings(rows, label: str) -> list[dict]:
    if not isinstance(rows, list):
        raise ToolDataError(f"Add at least one {label.lower()} holding", 400)

    totals: dict[str, float] = {}
    order: list[str] = []

    for row in rows:
        ticker = normalize_tickers((row or {}).get("ticker"))[:1]
        weight = _to_float((row or {}).get("weight"))
        if weight is None:
            weight = 1.0
        if not ticker or weight <= 0:
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


def _weighting_mode(value, fallback: str = "manual") -> str:
    mode = str(value or fallback).strip().lower()
    return "market_cap_start" if mode == "market_cap_start" else "manual"


def _rebalance_period(value, fallback: str = "none") -> str:
    mode = str(value or fallback).strip().lower().replace("-", "_")
    if mode in {"none", "daily", "weekly", "monthly", "quarterly"}:
        return mode
    return fallback


def _weight_history_frame(value) -> pd.DataFrame | None:
    if not isinstance(value, list):
        return None

    series_by_symbol = {}
    for row in value:
        ticker = normalize_tickers((row or {}).get("ticker") or (row or {}).get("name"))[:1]
        if not ticker:
            continue

        points = {}
        for point in (row or {}).get("points") or []:
            date_value = point.get("date") or point.get("t")
            if not date_value:
                continue
            try:
                point_date = pd.Timestamp(date_value).normalize()
            except Exception:
                continue

            weight = _to_float(point.get("weight") if "weight" in point else point.get("v"))
            points[point_date] = 0.0 if weight is None else max(weight, 0.0)

        if points:
            series_by_symbol[ticker[0]] = pd.Series(points, dtype=float)

    if not series_by_symbol:
        return None

    history = pd.DataFrame(series_by_symbol).sort_index().fillna(0.0)
    history.index = pd.to_datetime(history.index).normalize()
    history = history[~history.index.duplicated(keep="last")]
    row_totals = history.sum(axis=1)
    history = history.div(row_totals.replace(0, pd.NA), axis=0).fillna(0.0)
    return history


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
            "weighting_mode": _weighting_mode(benchmark.get("weightingMode")),
        }

    raise ToolDataError("Choose a benchmark ticker or portfolio", 400)


def _price_matrix(symbols: list[str], start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    fetch_start = min(start_date, end_date - pd.Timedelta(days=7))
    prices = get_polygon_prices(symbols, fetch_start.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
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


def _current_price_matrix(symbols: list[str]) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame(columns=symbols)

    end_date = _today_date()
    start_date = end_date - pd.Timedelta(days=21)
    prices = get_polygon_prices(symbols, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
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


def _last_common_end_date(prices: pd.DataFrame, symbols: list[str], requested_end: pd.Timestamp) -> pd.Timestamp:
    past_prices = prices[prices.index <= requested_end]
    if past_prices.empty:
        earliest_available = prices.index.min() if not prices.empty else None
        earliest_text = (
            f" Earliest available market date was {pd.Timestamp(earliest_available).strftime('%Y-%m-%d')}."
            if earliest_available is not None and not pd.isna(earliest_available)
            else ""
        )
        raise ToolDataError(
            "No price history was found on or before the selected end date. "
            "Try a later trading day."
            f"{earliest_text}",
            400,
        )

    eligible = past_prices.dropna(subset=symbols, how="any")
    if eligible.empty:
        missing = [symbol for symbol in symbols if past_prices[symbol].dropna().empty]
        if missing:
            raise ToolDataError(
                f"Missing price history on or before the end date for: {', '.join(missing)}",
                400,
            )
        raise ToolDataError("No common end date was found for every selected symbol", 400)

    return pd.Timestamp(eligible.index[-1]).normalize()


def _boundary_limiting_symbols(prices: pd.DataFrame, symbols: list[str], requested_date: pd.Timestamp) -> list[str]:
    if requested_date not in prices.index:
        return []

    requested_row = prices.loc[requested_date, symbols]
    return [
        symbol
        for symbol, value in requested_row.items()
        if pd.isna(value)
    ]


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

    if requested_start > prices.index.max():
        return (
            f"The selected start date, {requested_text}, was after the latest available market date, "
            f"so the report starts on {effective_text}."
        )

    missing_symbols = _boundary_limiting_symbols(prices, symbols, requested_start)
    if missing_symbols:
        return (
            f"The report starts on {effective_text} because these symbols did not have "
            f"price history on {requested_text}: {', '.join(missing_symbols)}."
        )

    return (
        f"The requested start date was adjusted from {requested_text} to {effective_text} "
        "based on the first common pricing date."
    )


def _end_date_warning(prices: pd.DataFrame, symbols: list[str], requested_end: pd.Timestamp, effective_end: pd.Timestamp) -> str | None:
    if effective_end >= requested_end:
        return None

    requested_text = requested_end.strftime("%Y-%m-%d")
    effective_text = effective_end.strftime("%Y-%m-%d")

    if requested_end > prices.index.max():
        return (
            f"The selected end date, {requested_text}, was after the latest available market date, "
            f"so the report ends on {effective_text}."
        )

    if requested_end not in prices.index:
        return (
            f"The selected end date, {requested_text}, was not a market trading day, "
            f"so the report ends on {effective_text}."
        )

    missing_symbols = _boundary_limiting_symbols(prices, symbols, requested_end)
    if missing_symbols:
        return (
            f"The report ends on {effective_text} because these symbols did not have "
            f"price history on {requested_text}: {', '.join(missing_symbols)}."
        )

    return (
        f"The requested end date was adjusted from {requested_text} to {effective_text} "
        "based on the last common pricing date."
    )


def _symbol_range_rows(
    prices: pd.DataFrame,
    portfolio_symbols: list[str],
    benchmark_symbols: list[str],
    effective_start: pd.Timestamp,
    effective_end: pd.Timestamp,
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp,
) -> dict:
    portfolio_set = set(portfolio_symbols)
    benchmark_set = set(benchmark_symbols)
    ordered_symbols = list(dict.fromkeys(portfolio_symbols + benchmark_symbols))
    bounded_prices = prices[(prices.index >= requested_start) & (prices.index <= requested_end)]
    start_limited_by = set(_boundary_limiting_symbols(prices, ordered_symbols, requested_start)) if effective_start > requested_start else set()
    end_limited_by = set(_boundary_limiting_symbols(prices, ordered_symbols, requested_end)) if effective_end < requested_end else set()
    rows = []

    for symbol in ordered_symbols:
        series = bounded_prices[symbol].dropna() if symbol in bounded_prices.columns else pd.Series(dtype=float)
        if symbol in portfolio_set and symbol in benchmark_set:
            scope = "both"
        elif symbol in portfolio_set:
            scope = "portfolio"
        else:
            scope = "benchmark"

        rows.append(
            {
                "ticker": symbol,
                "scope": scope,
                "firstDate": _format_date(series.index.min() if not series.empty else None),
                "lastDate": _format_date(series.index.max() if not series.empty else None),
                "limitsStart": symbol in start_limited_by,
                "limitsEnd": symbol in end_limited_by,
            }
        )

    return {
        "requestedStartDate": requested_start.strftime("%Y-%m-%d"),
        "effectiveStartDate": effective_start.strftime("%Y-%m-%d"),
        "requestedEndDate": requested_end.strftime("%Y-%m-%d"),
        "effectiveEndDate": effective_end.strftime("%Y-%m-%d"),
        "startLimitedBy": sorted(start_limited_by),
        "endLimitedBy": sorted(end_limited_by),
        "symbolRanges": rows,
    }


def _apply_start_date_market_cap_weights(
    holdings: list[dict],
    prices: pd.DataFrame,
    current_prices: pd.DataFrame,
    effective_start_date: pd.Timestamp,
    label: str,
) -> tuple[list[dict], str]:
    tickers = [holding["ticker"] for holding in holdings]
    latest_prices = {}
    as_of_prices = {}
    for ticker in tickers:
        current_series = current_prices[ticker].dropna() if ticker in current_prices.columns else pd.Series(dtype=float)
        latest_prices[ticker] = current_series.iloc[-1] if not current_series.empty else None
        as_of_prices[ticker] = prices.at[effective_start_date, ticker] if ticker in prices.columns else None

    payload = estimate_market_cap_weights(tickers, latest_prices, as_of_prices)
    if payload["missing"]:
        return holdings, (
            f"{label} kept the entered weights because start-date market cap weighting was unavailable for: "
            f"{', '.join(payload['missing'])}."
        )

    weight_by_ticker = {
        row["ticker"]: row["weight"]
        for row in payload["rows"]
        if row.get("weight") is not None
    }
    if any(holding["ticker"] not in weight_by_ticker for holding in holdings):
        return holdings, (
            f"{label} kept the entered weights because start-date market cap weighting was incomplete."
        )
    weighted_holdings = [
        {
            "ticker": holding["ticker"],
            "weight": weight_by_ticker[holding["ticker"]],
        }
        for holding in holdings
    ]
    return weighted_holdings, (
        f"{label} weights were estimated from current market caps scaled to {effective_start_date.strftime('%Y-%m-%d')} "
        "using the historical/current price ratio."
    )


def _rebalance_close_flags(index: pd.Index, rebalance_period: str) -> pd.Series:
    date_index = pd.DatetimeIndex(index)
    if len(date_index) == 0:
        return pd.Series(dtype=bool)

    period = _rebalance_period(rebalance_period)
    if period == "none":
        return pd.Series(False, index=date_index, dtype=bool)
    if period == "daily":
        return pd.Series(True, index=date_index, dtype=bool)

    if period == "weekly":
        groups = date_index.to_period("W-FRI")
    elif period == "monthly":
        groups = date_index.to_period("M")
    else:
        groups = date_index.to_period("Q")

    flags = pd.Series(groups, index=date_index).ne(pd.Series(groups, index=date_index).shift(-1))
    return flags.fillna(True).astype(bool)


def _build_buy_and_hold_basket(
    prices: pd.DataFrame,
    holdings: list[dict],
    asset_total_returns: pd.DataFrame,
    start_date: pd.Timestamp,
    rebalance_period: str = "none",
) -> dict:
    symbols = [holding["ticker"] for holding in holdings]
    basket_prices = prices.reindex(columns=symbols)
    basket_prices = basket_prices[basket_prices.index >= start_date].copy()
    basket_prices = basket_prices.ffill().dropna(subset=symbols, how="any")
    if basket_prices.empty:
        raise ToolDataError("No price history was found after the effective start date", 400)

    entry_prices = basket_prices.loc[start_date, symbols].astype(float)
    basket_asset_returns = (
        asset_total_returns
        .reindex(index=basket_prices.index, columns=symbols)
        .fillna(0.0)
        .astype(float)
    )
    if len(basket_asset_returns.index):
        basket_asset_returns.iloc[0] = 0.0

    basis = pd.Series({holding["ticker"]: float(holding["weight"]) for holding in holdings}, dtype=float)
    rebalance_flags = _rebalance_close_flags(basket_asset_returns.index, rebalance_period)
    current_values = basis.copy()
    previous_total = float(current_values.sum())
    value_rows = []
    weight_rows = []
    return_rows = []

    for idx, date in enumerate(basket_asset_returns.index):
        if idx > 0:
            current_values = current_values * (1.0 + basket_asset_returns.loc[date])
            pre_rebalance_total = float(current_values.sum())
            daily_return = 0.0 if previous_total == 0 else pre_rebalance_total / previous_total - 1.0
        else:
            pre_rebalance_total = previous_total
            daily_return = 0.0

        if bool(rebalance_flags.loc[date]):
            current_values = basis * pre_rebalance_total

        close_total = float(current_values.sum())
        close_weights = (
            current_values / close_total
            if close_total
            else pd.Series(0.0, index=symbols, dtype=float)
        )
        value_rows.append(current_values.copy())
        weight_rows.append(close_weights)
        return_rows.append(daily_return)
        previous_total = close_total

    value_df = pd.DataFrame(value_rows, index=basket_asset_returns.index, columns=symbols, dtype=float)
    weights_df = pd.DataFrame(weight_rows, index=basket_asset_returns.index, columns=symbols, dtype=float)
    returns = pd.Series(return_rows, index=basket_asset_returns.index, dtype=float)

    return {
        "symbols": symbols,
        "prices": basket_prices,
        "entry_prices": entry_prices,
        "asset_returns": basket_asset_returns,
        "value_df": value_df,
        "weights_df": weights_df,
        "returns": returns,
        "basis": basis,
        "strategy_mode": "static",
    }


def _build_weight_history_basket(
    prices: pd.DataFrame,
    asset_total_returns: pd.DataFrame,
    weight_history: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> dict:
    symbols = list(weight_history.columns)
    basket_prices = prices.reindex(columns=symbols)
    basket_prices = basket_prices[(basket_prices.index >= start_date) & (basket_prices.index <= end_date)].copy().ffill()
    if basket_prices.empty:
        raise ToolDataError("No price history was found after the effective start date", 400)

    target_weights = (
        weight_history.reindex(columns=symbols, fill_value=0.0)
        .reindex(basket_prices.index)
        .ffill()
        .fillna(0.0)
    )
    row_totals = target_weights.sum(axis=1)
    target_weights = target_weights.div(row_totals.replace(0, pd.NA), axis=0).fillna(0.0)

    basket_asset_returns = (
        asset_total_returns
        .reindex(index=basket_prices.index, columns=symbols)
        .fillna(0.0)
        .astype(float)
    )
    if len(basket_asset_returns.index):
        basket_asset_returns.iloc[0] = 0.0

    returns = (target_weights.shift(1).fillna(0.0) * basket_asset_returns).sum(axis=1).fillna(0.0)
    if len(returns.index):
        returns.iloc[0] = 0.0

    equity = (1.0 + returns).cumprod()
    value_df = target_weights.mul(equity, axis=0)
    entry_prices = basket_prices.loc[basket_prices.index[0], symbols].astype(float)
    basis = pd.Series(float("nan"), index=symbols, dtype=float)

    return {
        "symbols": symbols,
        "prices": basket_prices,
        "entry_prices": entry_prices,
        "asset_returns": basket_asset_returns,
        "value_df": value_df,
        "weights_df": target_weights,
        "returns": returns,
        "basis": basis,
        "strategy_mode": "historical_weight_history",
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
    requested_end_date: pd.Timestamp,
    effective_end_date: pd.Timestamp,
    portfolio_rebalance_period: str,
    benchmark_rebalance_period: str,
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
            "requested_end_date": requested_end_date.strftime("%Y-%m-%d"),
            "effective_end_date": effective_end_date.strftime("%Y-%m-%d"),
            "portfolio_rebalance_period": portfolio_rebalance_period,
            "benchmark_rebalance_period": benchmark_rebalance_period,
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
    today_gl = basket["asset_returns"].loc[latest_date].reindex(current_weights.index)
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
    current_weights_df["_Quantity"] = ""
    current_weights_df["_BasisApprox"] = current_weights.index.map(basket["basis"].get).map(
        lambda value: "" if pd.isna(value) else f"{float(value):.10f}"
    )
    return current_weights_df


def _trade_history_frame(basket: dict, start_date: pd.Timestamp, holdings: list[dict]) -> pd.DataFrame:
    if basket.get("strategy_mode") == "historical_weight_history":
        rows = []
        previous_weights = pd.Series(0.0, index=basket["weights_df"].columns, dtype=float)
        for date, weights in basket["weights_df"].iterrows():
            deltas = weights.fillna(0.0) - previous_weights.reindex(weights.index).fillna(0.0)
            changed = deltas[deltas.abs() > SHARE_EPSILON]
            for ticker, delta in changed.items():
                rows.append(
                    {
                        "Date": date.strftime("%Y-%m-%d"),
                        "Ticker": ticker,
                        "Action": "BUY" if delta > 0 else "SELL",
                        "Trade Price ($)": float(basket["prices"].at[date, ticker]),
                        "Trade Size (% of Account)": f"{abs(float(delta)) * 100:.2f}%",
                    }
                )
            previous_weights = weights.fillna(0.0)
        return pd.DataFrame(rows)

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


def _append_tables_to_report(
    report_path: Path,
    weights_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    trade_history_description: str = "Synthetic opening buys used to seed the model portfolio.",
):
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
              <p style="text-align:center;">{trade_history_description}</p>
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
                trade_history_description=trade_history_description,
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
    requested_end_date = _parse_date(body.get("endDate") or _today_date().strftime("%Y-%m-%d"), "End date")
    portfolio_history_window = _parse_history_window(body.get("portfolioHistoryWindow"))
    portfolio_weight_history = _weight_history_frame(body.get("portfolioWeightHistory"))
    if portfolio_weight_history is not None and portfolio_history_window is not None:
        requested_start_date, requested_end_date = portfolio_history_window
    if requested_end_date < requested_start_date:
        raise ToolDataError("End date must be on or after the start date", 400)
    portfolio_rebalance_period = _rebalance_period(body.get("portfolioRebalancePeriod"))
    benchmark_rebalance_period = _rebalance_period(body.get("benchmarkRebalancePeriod"))
    portfolio_holdings = _normalize_weighted_holdings(body.get("holdings"), "portfolio")
    portfolio_weighting_mode = _weighting_mode(body.get("weightingMode"))
    benchmark_config = _parse_benchmark_config(body.get("benchmark") or {})
    portfolio_symbols = (
        list(portfolio_weight_history.columns)
        if portfolio_weight_history is not None
        else [holding["ticker"] for holding in portfolio_holdings]
    )

    symbols = list(
        dict.fromkeys(
            portfolio_symbols + benchmark_config["symbols"]
        )
    )
    prices = _price_matrix(symbols, requested_start_date, requested_end_date)
    effective_start_date = _first_common_start_date(prices, symbols, requested_start_date)
    effective_end_date = _last_common_end_date(prices, symbols, requested_end_date)
    if effective_end_date < effective_start_date:
        raise ToolDataError("No common date range was found between the selected start and end dates", 400)

    working_prices = prices[
        (prices.index >= effective_start_date) & (prices.index <= effective_end_date)
    ].copy().ffill()
    weighting_warnings = []
    needs_market_cap_weighting = (
        portfolio_weight_history is None and portfolio_weighting_mode == "market_cap_start"
        or (
            benchmark_config["mode"] == "portfolio"
            and benchmark_config.get("weighting_mode") == "market_cap_start"
        )
    )
    current_prices = pd.DataFrame()
    if needs_market_cap_weighting:
        market_cap_symbols = list(
            dict.fromkeys(
                [holding["ticker"] for holding in portfolio_holdings]
                + (
                    [holding["ticker"] for holding in benchmark_config["holdings"]]
                    if benchmark_config["mode"] == "portfolio"
                    else []
                )
            )
        )
        current_prices = _current_price_matrix(market_cap_symbols)
    if portfolio_weighting_mode == "market_cap_start":
        portfolio_holdings, portfolio_weighting_warning = _apply_start_date_market_cap_weights(
            portfolio_holdings,
            working_prices,
            current_prices,
            effective_start_date,
            "Portfolio",
        )
        weighting_warnings.append(portfolio_weighting_warning)
    if benchmark_config["mode"] == "portfolio" and benchmark_config.get("weighting_mode") == "market_cap_start":
        benchmark_config["holdings"], benchmark_weighting_warning = _apply_start_date_market_cap_weights(
            benchmark_config["holdings"],
            working_prices,
            current_prices,
            effective_start_date,
            "Benchmark",
        )
        weighting_warnings.append(benchmark_weighting_warning)
    dividends = get_polygon_dividends(
        symbols,
        working_prices.index.min().strftime("%Y-%m-%d"),
        effective_end_date.strftime("%Y-%m-%d"),
    )
    asset_total_returns = compute_total_return_returns(working_prices, dividends)

    if portfolio_weight_history is not None:
        portfolio_basket = _build_weight_history_basket(
            working_prices,
            asset_total_returns,
            portfolio_weight_history,
            effective_start_date,
            effective_end_date,
        )
    else:
        portfolio_basket = _build_buy_and_hold_basket(
            working_prices,
            portfolio_holdings,
            asset_total_returns,
            effective_start_date,
            rebalance_period=portfolio_rebalance_period,
        )
    if benchmark_config["mode"] == "ticker":
        benchmark_basket = _build_buy_and_hold_basket(
            working_prices,
            [{"ticker": benchmark_config["ticker"], "weight": 1.0}],
            asset_total_returns,
            effective_start_date,
        )
    else:
        benchmark_basket = _build_buy_and_hold_basket(
            working_prices,
            benchmark_config["holdings"],
            asset_total_returns,
            effective_start_date,
            rebalance_period=benchmark_rebalance_period,
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

    portfolio_series = add_missing_zeros(portfolio_returns).rename(report_name)
    portfolio_series.index.name = None
    benchmark_series = add_missing_zeros(benchmark_returns).reindex(
        portfolio_series.index,
        fill_value=0.0,
    ).rename(benchmark_config["label"])
    benchmark_series.index.name = None
    qs.reports.html(
        portfolio_series,
        rf=0.0396,
        benchmark=benchmark_series,
        output=report_path,
        title=f"Portfolio Analysis - {report_name}",
    )

    current_weights_df = _current_weights_frame(portfolio_basket)
    trades_df = _trade_history_frame(portfolio_basket, effective_start_date, portfolio_holdings)
    current_weights_df.to_csv(weights_csv_path, index=False)
    trades_df.to_csv(trades_csv_path, index=False)
    _append_tables_to_report(
        report_path,
        current_weights_df,
        trades_df,
        trade_history_description=(
            "Target weight changes inferred from the source portfolio history."
            if portfolio_basket.get("strategy_mode") == "historical_weight_history"
            else "Synthetic opening buys used to seed the model portfolio."
        ),
    )

    chart_payload = _build_chart_payload(
        portfolio_returns,
        benchmark_returns,
        portfolio_basket["weights_df"],
        benchmark_config,
        requested_start_date,
        effective_start_date,
        requested_end_date,
        effective_end_date,
        portfolio_rebalance_period,
        benchmark_rebalance_period,
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
        prices,
        symbols,
        requested_start_date,
        effective_start_date,
    )
    if start_date_warning:
        warnings.append(start_date_warning)
    end_date_warning = _end_date_warning(
        prices,
        symbols,
        requested_end_date,
        effective_end_date,
    )
    if end_date_warning:
        warnings.append(end_date_warning)
    warnings.extend(weighting_warnings)
    range_info = _symbol_range_rows(
        prices,
        portfolio_symbols,
        benchmark_config["symbols"],
        effective_start_date,
        effective_end_date,
        requested_start_date,
        requested_end_date,
    )

    return {
        "account": viewer_account,
        "effectiveStartDate": effective_start_date.strftime("%Y-%m-%d"),
        "effectiveEndDate": effective_end_date.strftime("%Y-%m-%d"),
        "portfolioRebalancePeriod": portfolio_rebalance_period,
        "benchmarkRebalancePeriod": benchmark_rebalance_period,
        "rangeInfo": range_info,
        "warnings": warnings,
    }
