import os
import json
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# ============================================================
#  Environment + cache setup
# ============================================================
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / ".." / "data" / ".cache" / "polygon"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------
#  Helpers
# ------------------------------------------------------------
def _cache_path(sym: str, start: str, end: str) -> Path:
    """Return cache path for a symbol/start/end tuple."""
    return CACHE_DIR / f"{sym}_{start}_{end}.json"


def _find_latest_cache(sym: str, start: str) -> Path | None:
    """Return the most recent cache file for a symbol."""
    matches = sorted(CACHE_DIR.glob(f"{sym}_{start}_*.json"))
    return matches[-1] if matches else None


def _load_cache(sym: str, start: str, end: str):
    """Load cache contents and detect freshness."""
    p = _cache_path(sym, start, end)
    if not p.exists():
        return None, "MISS", None
    try:
        data = json.load(open(p))
    except Exception:
        return None, "ERR", None

    results = data.get("results", [])
    if not results:
        return data, "EMPTY", None

    last_ts = max(r["t"] for r in results)
    last_dt = pd.Timestamp(last_ts, unit="ms", tz="America/New_York").normalize()
    today_dt = pd.Timestamp.now(tz="America/New_York").normalize()
    if last_dt < today_dt:
        return data, "STALE", None
    return data, "HIT", None


def _save_cache(sym: str, start: str, end: str, data):
    """Write cache safely."""
    try:
        json.dump(data, open(_cache_path(sym, start, end), "w"))
    except Exception:
        pass


def _print_table(rows, headers):
    """Pretty-print summary."""
    try:
        from tabulate import tabulate
        print("\n" + tabulate(rows, headers=headers, tablefmt="github", stralign="left", numalign="right"))
        return
    except Exception:
        pass
    # fallback
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
    """Fetch daily Polygon prices with per-symbol JSON cache."""
    if api_key is None:
        api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("Missing POLYGON_API_KEY in environment or .env")

    all_prices = {}
    today = pd.Timestamp.now(tz="America/New_York").normalize()
    summary_rows = []

    for sym in symbols:
        # --- Load latest available cache file ---
        latest_cache = _find_latest_cache(sym, start)
        if latest_cache:
            _, _, cached_end = latest_cache.stem.split("_")
            cache_json, cache_status, _ = _load_cache(sym, start, cached_end)
            end = cached_end  # adjust to actual end
        else:
            cache_json, cache_status, _ = _load_cache(sym, start, end)

        cached_results = cache_json.get("results", []) if cache_json else []
        newest_cached = max((r["t"] for r in cached_results), default=None)

        # --- Determine fetch range ---
        fetch_start = None
        if not cached_results:
            fetch_start = start
            cache_status = "MISS"
        else:
            last_dt = pd.to_datetime(newest_cached, unit="ms", utc=True).tz_convert("America/New_York").normalize()
            today_dt = pd.Timestamp.now(tz="America/New_York").normalize()
            if last_dt >= today_dt:
                fetch_start = None
                cache_status = "HIT"
            else:
                fetch_start = last_dt.strftime("%Y-%m-%d")
                cache_status = "STALE"

        # --- Fetch only if needed ---
        if fetch_start:
            print(f"Fetching {sym} {fetch_start} → {today.strftime('%Y-%m-%d')}")
            url = (
                f"https://api.polygon.io/v2/aggs/ticker/{sym}/range/1/day/"
                f"{fetch_start}/{today:%Y-%m-%d}?adjusted=false&sort=asc&limit=50000&apiKey={api_key}"
            )
            r = requests.get(url)
            if r.status_code == 200:
                new_data = r.json().get("results", [])
                if new_data:
                    seen = {r["t"] for r in cached_results}
                    merged = cached_results + [x for x in new_data if x["t"] not in seen]
                    merged.sort(key=lambda x: x["t"])
                    cache_json = {"results": merged}
                    _save_cache(sym, start, today.strftime("%Y-%m-%d"), cache_json)
                    cache_status = "UPDATED"
                else:
                    cache_status = "NO_NEW"
            elif cache_json:
                cache_status = "STALE(FALLBACK)"
            else:
                summary_rows.append([sym, "FAIL", "-", "-", 0, "API_ERR"])
                continue

        # --- Build DataFrame ---
        data = cache_json.get("results", []) if cache_json else []
        if not data:
            summary_rows.append([sym, cache_status, "-", "-", 0, "NO_DATA"])
            continue

        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["t"], unit="ms")
        df = df.set_index("date")["c"].sort_index()

        # --- Intraday live update ---
        updated_live = "NO"
        intraday_url = (
            f"https://api.polygon.io/v2/aggs/ticker/{sym}/range/1/minute/"
            f"{today:%Y-%m-%d}/{today:%Y-%m-%d}"
            f"?adjusted=false&sort=desc&limit=1&apiKey={api_key}"
        )
        r_intra = requests.get(intraday_url)
        if r_intra.status_code == 200:
            results = r_intra.json().get("results")
            if results:
                last_time = datetime.fromtimestamp(results[0]["t"] / 1000)
                last_price = results[0]["c"]
                df.loc[last_time] = last_price
                updated_live = "YES"

        # --- Record results ---
        all_prices[sym] = df
        start_s = df.index.min().strftime("%Y-%m-%d") if not df.empty else "-"
        end_s = df.index.max().strftime("%Y-%m-%d") if not df.empty else "-"
        summary_rows.append([sym, cache_status, start_s, end_s, len(df), updated_live])

        # --- Clean old cache & rename current ---
        old_files = list(CACHE_DIR.glob(f"{sym}_{start}_*.json"))
        today_str = today.strftime("%Y-%m-%d")
        new_path = _cache_path(sym, start, today_str)
        for f in old_files:
            if f != new_path and f.exists():
                try:
                    f.unlink()
                except Exception:
                    pass
        if not new_path.exists() and (latest_cache := _find_latest_cache(sym, start)):
            try:
                latest_cache.rename(new_path)
                print(f"Renamed cache → {new_path.name}")
            except Exception as e:
                print(f"⚠️ Rename failed for {sym}: {e}")

    # --- Combine ---
    prices = pd.DataFrame(all_prices).sort_index()
    if not prices.empty:
        prices.index = pd.to_datetime(prices.index).tz_localize(None)
        latest_time = prices.index.max()
        last_valid_row = prices.ffill().iloc[-1]
        prices.loc[latest_time] = last_valid_row
        prices = prices[~prices.index.duplicated(keep="last")].sort_index()

    _print_table(
        summary_rows,
        headers=["Symbol", "Cache", "Start", "End", "Rows", "Live"]
    )

    return prices
