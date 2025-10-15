import os
import json
import requests
import pandas as pd
from datetime import datetime, time
from pathlib import Path
from dotenv import load_dotenv
import pytz

from src.util import BASE_DIR

# ============================================================
#  Environment + cache setup
# ============================================================
load_dotenv()

CACHE_DIR = BASE_DIR / "data" / ".cache" / "polygon"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
#  Timezone helpers
# ============================================================
ET = pytz.timezone("America/New_York")

def _now_et() -> pd.Timestamp:
    """Return current ET timestamp (override via POLYGON_MOCK_NOW)."""
    mock_env = os.getenv("POLYGON_MOCK_NOW")
    if mock_env:
        ts = pd.Timestamp(mock_env)
        if ts.tzinfo is None:
            ts = ts.tz_localize("America/New_York")
        else:
            ts = ts.tz_convert("America/New_York")
        return ts
    return pd.Timestamp.now(tz=ET)

def _et_date(ts_ms: int) -> pd.Timestamp:
    """Convert Polygon ms timestamp (UTC) to ET calendar date (midnight)."""
    return (
        pd.to_datetime(ts_ms, unit="ms", utc=True)
        .tz_convert(ET)
        .normalize()
    )

# ============================================================
#  Cache helpers
# ============================================================
def _cache_path(sym: str, start: str, end: str) -> Path:
    return CACHE_DIR / f"{sym}_{start}_{end}.json"

def _find_latest_cache(sym: str, start: str) -> Path | None:
    matches = sorted(CACHE_DIR.glob(f"{sym}_{start}_*.json"))
    return matches[-1] if matches else None

def _load_cache_by_path(p: Path):
    if not p or not p.exists():
        return None, "MISS"
    try:
        data = json.load(open(p))
        return data, "HIT"
    except Exception:
        return None, "ERR"

def _save_cache(sym: str, start: str, end: str, data):
    try:
        json.dump(data, open(_cache_path(sym, start, end), "w"))
    except Exception:
        pass

def _print_table(rows, headers):
    try:
        from tabulate import tabulate
        print("\n" + tabulate(rows, headers=headers, tablefmt="github", stralign="left", numalign="right"))
        return
    except Exception:
        pass
    cols = list(zip(*([headers] + rows)))
    widths = [max(len(str(x)) for x in col) for col in cols]
    def fmt_row(r): return " | ".join(str(v).ljust(w) for v, w in zip(r, widths))
    sep = "-+-".join("-" * w for w in widths)
    print()
    print(fmt_row(headers))
    print(sep)
    for r in rows:
        print(fmt_row(r))

# ============================================================
#  Main fetcher
# ============================================================
def get_polygon_prices(symbols, start, end, api_key=None):
    """
    Fetch daily Polygon prices with per-symbol JSON cache (ET-normalized).
    - Historical daily bars are cached up to the LAST COMPLETED ET TRADING DAY.
    - Intraday (today) is appended IN-MEMORY ONLY for pre-market, regular, and after-hours.
    - If cache is behind, fetch ONLY the missing tail days.
    """
    if api_key is None:
        api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("Missing POLYGON_API_KEY in environment or .env")

    all_prices = {}
    today_et = _now_et().normalize()
    summary_rows = []

    for sym in symbols:
        # --- Load latest cache ---
        latest_cache_path = _find_latest_cache(sym, start)
        cache_json, cache_status = _load_cache_by_path(latest_cache_path)
        cached_results = cache_json.get("results", []) if cache_json else []

        last_et_day = _et_date(max(r["t"] for r in cached_results)) if cached_results else None

        # --- Determine if tail fetch needed ---
        fetch_start = None
        if not cached_results:
            fetch_start = start
            cache_status = "MISS"
        else:
            next_needed_day = (last_et_day + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            if last_et_day < today_et:
                fetch_start = next_needed_day
                cache_status = "STALE"
            else:
                cache_status = "HIT"

        # --- Fetch tail ---
        if fetch_start:
            print(f"Fetching {sym} {fetch_start} → {_now_et():%Y-%m-%d}")
            url = (
                f"https://api.polygon.io/v2/aggs/ticker/{sym}/range/1/day/"
                f"{fetch_start}/{_now_et():%Y-%m-%d}"
                f"?adjusted=true&sort=asc&limit=50000&apiKey={api_key}"
            )
            r = requests.get(url)
            if r.status_code == 200:
                new_data = r.json().get("results", [])
                if new_data:
                    seen = {r["t"] for r in cached_results}
                    merged = cached_results + [x for x in new_data if x["t"] not in seen]
                    merged.sort(key=lambda x: x["t"])
                    cache_json = {"results": merged}
                    last_ts_new = max(rr["t"] for rr in merged)
                    end_for_filename = _et_date(last_ts_new).strftime("%Y-%m-%d")
                    _save_cache(sym, start, end_for_filename, cache_json)
                    cache_status = "UPDATED"
                    # remove old cache files
                    for f in CACHE_DIR.glob(f"{sym}_{start}_*.json"):
                        if f.name != f"{sym}_{start}_{end_for_filename}.json":
                            try: f.unlink()
                            except Exception: pass
                else:
                    cache_status = "NO_NEW"
            elif cache_json:
                cache_status = "STALE(FALLBACK)"
            else:
                summary_rows.append([sym, "FAIL", "-", "-", 0, "API_ERR", 0.0])
                continue

        # --- Build daily ET close series ---
        data = cache_json.get("results", []) if cache_json else []
        if not data:
            summary_rows.append([sym, cache_status, "-", "-", 0, "NO_DATA", 0.0])
            continue

        df = pd.DataFrame(data)
        df["date_et"] = df["t"].apply(_et_date)
        s_close = df.set_index("date_et")["c"].sort_index()

        # --- Intraday append (covers pre, regular, and after-hours) ---
        updated_live = "NO"
        last_price = 0.0
        now_et = _now_et()
        # Determine session date target
        if now_et.time() < time(9, 30):
            # pre-market: use today_et but compare vs yesterday close
            session_label = today_et
            session_desc = "PRE"
        elif now_et.time() > time(16, 0):
            # after-hours: still today's ET trading day
            session_label = today_et
            session_desc = "AFTER"
        else:
            # regular hours
            session_label = today_et
            session_desc = "REG"

        intraday_url = (
            f"https://api.polygon.io/v2/aggs/ticker/{sym}/range/1/minute/"
            f"{today_et:%Y-%m-%d}/{today_et:%Y-%m-%d}"
            f"?adjusted=true&sort=desc&limit=2000&apiKey={api_key}"
        )
        r_intra = requests.get(intraday_url)
        if r_intra.status_code == 200:
            results = r_intra.json().get("results")
            if results:
                mins = pd.DataFrame(results)
                mins["ts_et"] = pd.to_datetime(mins["t"], unit="ms", utc=True).dt.tz_convert(ET)
                mins = mins[(mins["ts_et"] <= now_et)]
                if not mins.empty:
                    last_price = float(mins.iloc[0]["c"])
                    s_close.loc[session_label] = last_price
                    updated_live = session_desc

        # --- Save results per symbol ---
        all_prices[sym] = s_close
        start_s = s_close.index.min().strftime("%Y-%m-%d") if not s_close.empty else "-"
        end_s = s_close.index.max().strftime("%Y-%m-%d") if not s_close.empty else "-"
        summary_rows.append([sym, cache_status, start_s, end_s, len(s_close), updated_live, last_price])

    # --- Combine ---
    prices = pd.DataFrame(all_prices).sort_index()

    if not prices.empty:
        # Drop duplicate indices (keep the latest, usually the most recent intraday update)
        if not prices.index.is_unique:
            prices = prices[~prices.index.duplicated(keep="last")]

        prices.index = pd.to_datetime(prices.index).tz_localize(None)
        full_idx = pd.Index(sorted(set(prices.index)))
        prices = prices.reindex(full_idx).ffill()

    _print_table(
        summary_rows,
        headers=["Symbol", "Cache", "Start", "End", "Rows", "Live", "Live Price"]
    )

    return prices
