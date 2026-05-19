import json
import os

from pathlib import Path

import pandas as pd
import pytz
import requests

from src.util import BASE_DIR
from src.yfinance_cache import YFINANCE_CACHE_DIR, YFINANCE_HISTORY_CACHE_DIR, yf

ET = pytz.timezone("America/New_York")
BASE_CACHE_DIR = BASE_DIR / "data" / ".cache"
CACHE_DIR = BASE_CACHE_DIR / "polygon"
REFERENCE_CACHE_DIR = BASE_CACHE_DIR / "polygon-reference"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
REFERENCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _now_et():
    mock = os.getenv("POLYGON_MOCK_NOW")
    if mock:
        ts = pd.Timestamp(mock, tz="America/New_York")
    else:
        ts = pd.Timestamp.now(tz=ET)
    return ts


def _cache_path(symbol, start, end):
    return CACHE_DIR / f"{symbol}_{start}_{end}.json"


def _yfinance_cache_path(symbol, start, end):
    return YFINANCE_HISTORY_CACHE_DIR / f"{symbol}_{start}_{end}.json"


def _load_json_cache(path: Path):
    if path.exists():
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle), True
        except Exception:
            pass
    return None, False


def _load_cache(symbol, start, end):
    return _load_json_cache(_cache_path(symbol, start, end))


def _load_yfinance_cache(symbol, start, end):
    return _load_json_cache(_yfinance_cache_path(symbol, start, end))


def _save_json_cache(path: Path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def _save_cache(symbol, start, end, data):
    _save_json_cache(_cache_path(symbol, start, end), data)


def _save_yfinance_cache(symbol, start, end, data):
    _save_json_cache(_yfinance_cache_path(symbol, start, end), data)


def _reference_cache_path(kind, symbol, start, end):
    return REFERENCE_CACHE_DIR / f"{kind}_{symbol}_{start}_{end}.json"


def _daily_series_from_results(results, today_date):
    df = pd.DataFrame(results)
    if df.empty or "t" not in df or "c" not in df:
        return pd.Series(dtype=float)

    df["date_et"] = (
        pd.to_datetime(df["t"], unit="ms", utc=True)
        .dt.tz_convert(ET)
        .dt.normalize()
    )
    series = df.set_index("date_et")["c"].astype(float).sort_index()
    return series[series.index != today_date]


def _series_to_results(series: pd.Series):
    results = []
    for date, close in series.items():
        ts = pd.Timestamp(date)
        if ts.tzinfo is None:
            ts = ts.tz_localize(ET)
        else:
            ts = ts.tz_convert(ET)
        ts = ts.normalize()
        results.append({"t": int(ts.tz_convert("UTC").timestamp() * 1000), "c": float(close)})
    return {"results": results}


def _split_adjusted_close(history: pd.DataFrame):
    if history.empty or "Close" not in history:
        return pd.Series(dtype=float)

    close = pd.to_numeric(history["Close"], errors="coerce").astype(float)
    if "Stock Splits" not in history:
        return close

    split_factors = (
        pd.to_numeric(history["Stock Splits"], errors="coerce")
        .fillna(0.0)
        .replace(0.0, 1.0)
    )
    future_splits = split_factors.iloc[::-1].cumprod().iloc[::-1].shift(-1, fill_value=1.0)
    return close / future_splits


def _fetch_polygon_daily_series(symbol, start, fetch_end, api_key, today_date):
    if pd.Timestamp(start) > pd.Timestamp(fetch_end):
        return pd.Series(dtype=float)

    cache_data, hit = _load_cache(symbol, start, fetch_end)
    if not hit:
        print(f"Fetching Polygon {symbol} -> {start} {fetch_end}")
        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/"
            f"{start}/{fetch_end}?adjusted=true&sort=asc&limit=50000&apiKey={api_key}"
        )
        response = requests.get(url)
        if response.status_code != 200:
            raise RuntimeError(f"Polygon daily fetch failed for {symbol}: {response.status_code}")
        cache_data = response.json()
        _save_cache(symbol, start, fetch_end, cache_data)

    return _daily_series_from_results(cache_data.get("results", []), today_date)


def _fetch_yfinance_daily_series(symbol, start, end, today_date):
    if pd.Timestamp(start) >= pd.Timestamp(end):
        return pd.Series(dtype=float)
    if yf is None:
        raise RuntimeError("yfinance is required for history older than Polygon supports")

    cache_data, hit = _load_yfinance_cache(symbol, start, end)
    if not hit:
        print(f"Fetching yfinance {symbol} -> {start} {end}")
        history = yf.download(
            symbol,
            start=start,
            end=end,
            interval="1d",
            auto_adjust=False,
            actions=True,
            progress=False,
            threads=False,
            multi_level_index=False,
        )
        if history.empty:
            cache_data = {"results": []}
        else:
            close = _split_adjusted_close(history).dropna()
            close.index = pd.to_datetime(close.index).normalize()
            close = close[~close.index.duplicated(keep="last")]
            cache_data = _series_to_results(close)
        _save_yfinance_cache(symbol, start, end, cache_data)

    return _daily_series_from_results(cache_data.get("results", []), today_date)


def _fetch_intraday_price(symbol, today_str, api_key):
    intra_url = (
        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/minute/"
        f"{today_str}/{today_str}?adjusted=true&sort=desc&limit=2000&apiKey={api_key}"
    )
    response = requests.get(intra_url)
    if response.status_code != 200:
        return None

    results = response.json().get("results", [])
    if not results:
        return None

    return float(results[0]["c"])


def _fetch_polygon_reference_results(symbol, kind, date_field, start, end, api_key):
    cache_path = _reference_cache_path(kind, symbol, start, end)
    cache_data, hit = _load_json_cache(cache_path)
    if hit:
        return cache_data.get("results", [])

    print(f"Fetching Polygon {kind} {symbol} -> {start} {end}")
    base_url = f"https://api.polygon.io/v3/reference/{kind}"
    next_url = base_url
    params = {
        "ticker": symbol,
        f"{date_field}.gte": start,
        f"{date_field}.lte": end,
        "order": "asc",
        "limit": 1000,
        "sort": date_field,
        "apiKey": api_key,
    }
    results = []

    while next_url:
        response = requests.get(next_url, params=params if next_url == base_url else None)
        if response.status_code != 200:
            raise RuntimeError(f"Polygon {kind} fetch failed for {symbol}: {response.status_code}")

        payload = response.json()
        results.extend(payload.get("results", []))

        next_url = payload.get("next_url")
        if next_url and "apiKey=" not in next_url:
            next_url = f"{next_url}{'&' if '?' in next_url else '?'}apiKey={api_key}"
        params = None

    cache_data = {"results": results}
    _save_json_cache(cache_path, cache_data)
    return results


def get_polygon_splits(symbols, start, end):
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("Missing POLYGON_API_KEY")

    out = {}
    for sym in symbols:
        out[sym] = _fetch_polygon_reference_results(sym, "splits", "execution_date", start, end, api_key)
    return out


def future_split_factor_for_date(split_events, date_like) -> float:
    trade_date = pd.Timestamp(date_like).normalize()
    factor = 1.0
    for event in split_events or []:
        split_date = pd.Timestamp(event.get("execution_date")).normalize()
        split_from = float(event.get("split_from") or 0)
        split_to = float(event.get("split_to") or 0)
        if split_date > trade_date and split_from > 0 and split_to > 0:
            factor *= split_to / split_from
    return factor


def get_polygon_dividends(symbols, start, end):
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("Missing POLYGON_API_KEY")

    splits_by_symbol = get_polygon_splits(symbols, start, end)
    series_by_symbol = {}

    for sym in symbols:
        events = _fetch_polygon_reference_results(sym, "dividends", "ex_dividend_date", start, end, api_key)
        amounts_by_date = {}
        split_events = splits_by_symbol.get(sym, [])

        for event in events:
            ex_dividend_date = event.get("ex_dividend_date")
            cash_amount = event.get("cash_amount")
            if not ex_dividend_date:
                continue

            try:
                amount = float(cash_amount)
            except (TypeError, ValueError):
                continue
            if amount == 0:
                continue

            ex_date = pd.Timestamp(ex_dividend_date).normalize()
            adjusted_amount = amount / future_split_factor_for_date(split_events, ex_date)
            amounts_by_date[ex_date] = amounts_by_date.get(ex_date, 0.0) + adjusted_amount

        series_by_symbol[sym] = pd.Series(amounts_by_date, dtype=float)

    if not series_by_symbol:
        return pd.DataFrame()

    dividends = pd.DataFrame(series_by_symbol).sort_index()
    for sym in symbols:
        if sym not in dividends.columns:
            dividends[sym] = pd.Series(dtype=float)
    return dividends.reindex(columns=symbols)


def compute_total_return_returns(prices: pd.DataFrame, dividends: pd.DataFrame | None = None) -> pd.DataFrame:
    if prices.empty:
        return prices.copy()

    price_frame = prices.sort_index().astype(float)
    dividend_frame = pd.DataFrame(0.0, index=price_frame.index, columns=price_frame.columns)
    if dividends is not None and not dividends.empty:
        dividend_frame = dividend_frame.add(
            dividends.reindex(index=price_frame.index, columns=price_frame.columns).fillna(0.0).astype(float),
            fill_value=0.0,
        )
    previous_close = price_frame.shift(1)
    price_returns = price_frame.divide(previous_close).sub(1.0)
    dividend_returns = dividend_frame.divide(previous_close)
    total_returns = price_returns.fillna(0.0).add(dividend_returns.fillna(0.0), fill_value=0.0).fillna(0.0)
    if len(total_returns.index):
        total_returns.iloc[0] = 0.0
    return total_returns


def get_polygon_prices(symbols, start, end):
    """Simplified and deterministic daily+intraday fetcher.

    Behavior:
      - Fetches recent daily closes from Polygon for [polygon_start, fetch_end]
      - Falls back to yfinance for any prefix older than Polygon's 5-year history window
      - Only adds a shared "today" row if at least one symbol has a real intraday print today
      - When that shared row exists, symbols without intraday prints fall back to their last close
      - When no symbol has a real intraday print today, leaves the series at the last trading day
    """
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("Missing POLYGON_API_KEY")

    now = _now_et()
    today_str = now.strftime("%Y-%m-%d")
    today_date = now.normalize()
    today_date_naive = today_date.tz_localize(None)
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    effective_end_ts = min(end_ts, today_date_naive)
    polygon_history_start = (today_date_naive - pd.DateOffset(years=5)).normalize()
    polygon_start = max(start_ts, polygon_history_start).strftime("%Y-%m-%d")

    cutoff_days = 1
    fetch_end_ts = min(effective_end_ts, (now - pd.Timedelta(days=cutoff_days)).normalize().tz_localize(None))
    fetch_end = fetch_end_ts.strftime("%Y-%m-%d")

    daily_series = {}
    intraday_prices = {}

    for sym in symbols:
        series_parts = []

        yfinance_end_ts = min(polygon_history_start, effective_end_ts + pd.Timedelta(days=1))
        if start_ts < yfinance_end_ts:
            yfinance_series = _fetch_yfinance_daily_series(
                sym,
                start_ts.strftime("%Y-%m-%d"),
                yfinance_end_ts.strftime("%Y-%m-%d"),
                today_date,
            )
            if not yfinance_series.empty:
                series_parts.append(yfinance_series)

        polygon_series = _fetch_polygon_daily_series(sym, polygon_start, fetch_end, api_key, today_date)
        if not polygon_series.empty:
            series_parts.append(polygon_series)

        if not series_parts:
            continue

        series = pd.concat(series_parts).sort_index()
        series = series[~series.index.duplicated(keep="last")]

        daily_series[sym] = series
        intraday_prices[sym] = _fetch_intraday_price(sym, today_str, api_key) if effective_end_ts == today_date_naive else None

    any_intraday_today = effective_end_ts == today_date_naive and any(
        price is not None for price in intraday_prices.values()
    )
    all_prices = {}

    for sym, series in daily_series.items():
        if any_intraday_today and len(series) > 0:
            last_price = intraday_prices[sym]
            if last_price is None:
                last_price = float(series.iloc[-1])
            series.loc[today_date] = last_price
        all_prices[sym] = series.sort_index()

    for sym, series in all_prices.items():
        all_prices[sym].index = series.index.tz_localize(None)

    prices = pd.DataFrame(all_prices)
    if prices.empty:
        return prices
    return prices[(prices.index >= start_ts) & (prices.index <= effective_end_ts)]
