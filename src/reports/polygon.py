import os
import json
import requests
import pandas as pd
from datetime import time
from pathlib import Path
import pytz

ET = pytz.timezone("America/New_York")
CACHE_DIR = Path("data/.cache/polygon")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _now_et():
    mock = os.getenv("POLYGON_MOCK_NOW")
    if mock:
        ts = pd.Timestamp(mock, tz="America/New_York")
    else:
        ts = pd.Timestamp.now(tz=ET)
    return ts


def _cache_path(symbol, start, end):
    return CACHE_DIR / f"{symbol}_{start}_{end}.json"


def _load_cache(symbol, start, end):
    p = _cache_path(symbol, start, end)
    if p.exists():
        try:
            return json.load(open(p)), True
        except Exception:
            pass
    return None, False


def _save_cache(symbol, start, end, data):
    p = _cache_path(symbol, start, end)
    with open(p, "w") as f:
        json.dump(data, f)


def get_polygon_prices(symbols, start, end):
    """Simplified and deterministic Polygon daily+intraday fetcher."""
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("Missing POLYGON_API_KEY")

    now = _now_et()
    today_str = now.strftime("%Y-%m-%d")

    # decide how many days back to include
    cutoff_days = 1

    all_prices = {}

    for sym in symbols:
        # compute daily range to request/cache
        fetch_end = (now - pd.Timedelta(days=cutoff_days)).strftime("%Y-%m-%d")

        cache_data, hit = _load_cache(sym, start, fetch_end)
        if not hit:
            print(f'Fetching {sym} → {start}  {fetch_end}')
            url = (
                f"https://api.polygon.io/v2/aggs/ticker/{sym}/range/1/day/"
                f"{start}/{fetch_end}?adjusted=true&sort=asc&limit=50000&apiKey={api_key}"
            )
            r = requests.get(url)
            if r.status_code != 200:
                raise RuntimeError(f"Polygon daily fetch failed for {sym}: {r.status_code}")
            cache_data = r.json()
            _save_cache(sym, start, fetch_end, cache_data)

        # build daily close series
        results = cache_data.get("results", [])
        df = pd.DataFrame(results)
        if df.empty:
            continue
        df["date_et"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert(ET).dt.normalize()
        s = df.set_index("date_et")["c"].astype(float)

        # fetch intraday (always)
        intra_url = (
            f"https://api.polygon.io/v2/aggs/ticker/{sym}/range/1/minute/"
            f"{today_str}/{today_str}?adjusted=true&sort=desc&limit=2000&apiKey={api_key}"
        )
        r_intra = requests.get(intra_url)
        if r_intra.status_code == 200:
            res = r_intra.json().get("results", [])
            if res:
                last_price = res[0]["c"]
                today_date = now.normalize()
                s.loc[today_date] = last_price

        all_prices[sym] = s.sort_index()

    for sym, s in all_prices.items():
        s.index = s.index.tz_localize(None)
    return pd.DataFrame(all_prices)
