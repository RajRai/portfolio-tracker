import os
import json
import pandas as pd
import pytest
import src.reports.polygon as pf

# ============================================================
#  Basic response helper
# ============================================================
def make_response(json_data, status_code=200):
    from types import SimpleNamespace
    return SimpleNamespace(status_code=status_code, json=lambda: json_data)

# ============================================================
#  Fake Polygon mock: simple progression
# ============================================================
def fake_polygon_get(url, *args, **kwargs):
    """Simulate Polygon behavior for 2025-10-13 → 2025-10-15."""
    mock_now = os.getenv("POLYGON_MOCK_NOW")
    include_today = os.getenv("POLYGON_INCLUDE_TODAY_DAILY") == "1"
    now_et = pd.Timestamp(mock_now, tz="America/New_York")

    # --- daily ---
    if "/range/1/day/" in url:
        results = []
        base = pd.Timestamp("2025-10-13", tz="America/New_York")
        results.append({"t": int(base.tz_convert("UTC").timestamp() * 1000), "c": 100})
        if "2025-10-14" in url or "2025-10-15" in url:
            next_day = base + pd.Timedelta(days=1)
            results.append({"t": int(next_day.tz_convert("UTC").timestamp() * 1000), "c": 103})
        if include_today and "2025-10-15" in url:
            today_day = base + pd.Timedelta(days=2)
            results.append({"t": int(today_day.tz_convert("UTC").timestamp() * 1000), "c": 105})
        return make_response({"results": results})

    # --- intraday (1-min) ---
    elif "/range/1/minute/" in url:
        if now_et.date() == pd.Timestamp("2025-10-14").date():
            if now_et.time() < pd.Timestamp("09:30").time():
                price = 100
            elif now_et.time() > pd.Timestamp("16:00").time():
                price = 110
            else:
                price = 105
        elif now_et.date() == pd.Timestamp("2025-10-15").date():
            if now_et.time() < pd.Timestamp("09:30").time():
                price = 110
            else:
                price = 115
        else:
            price = 100
        ts_ms = int(now_et.tz_convert("UTC").timestamp() * 1000)
        return make_response({"results": [{"t": ts_ms, "c": price}]})

    return make_response({}, 404)


@pytest.fixture(autouse=True)
def patch_requests(monkeypatch):
    """Patch requests.get to use our deterministic fake Polygon responses."""
    monkeypatch.setattr("requests.get", fake_polygon_get)

# ============================================================
#  Helpers
# ============================================================
def seed_cache_only_1013(symbol, start):
    ts = int(pd.Timestamp("2025-10-13", tz="America/New_York")
             .tz_convert("UTC").timestamp() * 1000)
    pf._save_cache(symbol, start, "2025-10-13", {"results": [{"t": ts, "c": 100}]})


def run_and_print(monkeypatch, symbol, start, end, mock_now, expected_last, expected_series):
    monkeypatch.setenv("POLYGON_MOCK_NOW", mock_now)
    prices = pf.get_polygon_prices([symbol], start, end)
    s = prices[symbol]
    vals = list(map(float, s.values))
    print(f"\n[{mock_now}] → last={vals[-1]}, full={vals}")
    assert abs(vals[-1] - expected_last) < 1e-9
    assert vals == expected_series


# ============================================================
#  Test 1: progression without "today" daily (clean history)
# ============================================================
def test_progression_without_today_daily(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache" / ".cache" / "polygon"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pf, "CACHE_DIR", cache_dir)
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    symbol = "AAPL"
    start, end = "2025-10-13", "2025-10-15"
    seed_cache_only_1013(symbol, start)

    run_and_print(monkeypatch, symbol, start, end, "2025-10-14 10:00:00", 105, [100.0, 105.0])
    run_and_print(monkeypatch, symbol, start, end, "2025-10-14 18:00:00", 110, [100.0, 110.0])
    run_and_print(monkeypatch, symbol, start, end, "2025-10-15 08:00:00", 110, [100.0, 103.0, 110.0])
    run_and_print(monkeypatch, symbol, start, end, "2025-10-15 10:00:00", 115, [100.0, 103.0, 115.0])


# ============================================================
#  Test 2: progression with today's daily present (kept historically)
# ============================================================
def test_progression_with_today_daily_dropped(tmp_path, monkeypatch):
    """Even if Polygon includes a partial 'today' daily, it’s cached as historical and later visible."""
    cache_dir = tmp_path / "cache" / ".cache" / "polygon"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pf, "CACHE_DIR", cache_dir)
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    monkeypatch.setenv("POLYGON_INCLUDE_TODAY_DAILY", "1")
    symbol = "AAPL"
    start, end = "2025-10-13", "2025-10-15"
    seed_cache_only_1013(symbol, start)

    run_and_print(monkeypatch, symbol, start, end, "2025-10-14 10:00:00", 105, [100.0, 105.0])
    run_and_print(monkeypatch, symbol, start, end, "2025-10-14 18:00:00", 110, [100.0, 110.0])
    run_and_print(monkeypatch, symbol, start, end, "2025-10-15 08:00:00", 110, [100.0, 103.0, 110.0])
    run_and_print(monkeypatch, symbol, start, end, "2025-10-15 10:00:00", 115, [100.0, 103.0, 115.0])


# ============================================================
#  Test 3: verify historical visibility transition
# ============================================================
def test_current_day_historical_handling(tmp_path, monkeypatch):
    """Ensure T-2/T-1 fetch logic: before 9:30 uses two days back, after 9:30 uses one day back."""
    cache_dir = tmp_path / "cache" / ".cache" / "polygon"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pf, "CACHE_DIR", cache_dir)
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    monkeypatch.setenv("POLYGON_INCLUDE_TODAY_DAILY", "1")

    symbol = "AAPL"
    start, end = "2025-10-13", "2025-10-15"
    seed_cache_only_1013(symbol, start)

    # 10/14 AFTER (yesterday=10/13 → today=10/14)
    monkeypatch.setenv("POLYGON_MOCK_NOW", "2025-10-14 18:00:00")
    prices_after = pf.get_polygon_prices([symbol], start, end)
    vals_after = list(map(float, prices_after[symbol].values))
    print("\n[2025-10-14 18:00] AFTER →", vals_after)
    assert vals_after == [100.0, 110.0]

    # 10/15 PRE (compare vs 10/14 market hours close)
    monkeypatch.setenv("POLYGON_MOCK_NOW", "2025-10-15 08:00:00")
    prices_pre = pf.get_polygon_prices([symbol], start, end)
    vals_pre = list(map(float, prices_pre[symbol].values))
    print("\n[2025-10-15 08:00] PRE →", vals_pre)
    assert vals_pre == [100.0, 103.0, 110.0]

    # 10/15 REG (market open → yesterday visible)
    monkeypatch.setenv("POLYGON_MOCK_NOW", "2025-10-15 10:00:00")
    prices_reg = pf.get_polygon_prices([symbol], start, end)
    vals_reg = list(map(float, prices_reg[symbol].values))
    print("\n[2025-10-15 10:00] REG →", vals_reg)
    assert vals_reg == [100.0, 103.0, 115.0]


# ============================================================
#  Test 4: cache reuse verification
# ============================================================
class CallRecorder:
    def __init__(self):
        self.calls = []

    def __call__(self, url, *args, **kwargs):
        self.calls.append(url)
        if "/range/1/day/" in url:
            results = [
                {"t": int(pd.Timestamp("2025-10-13", tz="America/New_York")
                          .tz_convert("UTC").timestamp() * 1000), "c": 100},
                {"t": int(pd.Timestamp("2025-10-14", tz="America/New_York")
                          .tz_convert("UTC").timestamp() * 1000), "c": 105}
            ]
            return make_response({"results": results})
        elif "/range/1/minute/" in url:
            ts = int(pd.Timestamp("2025-10-14T10:00:00", tz="America/New_York")
                     .tz_convert("UTC").timestamp() * 1000)
            return make_response({"results": [{"t": ts, "c": 105}]})
        return make_response({}, 404)


def test_cache_miss_then_tail_then_stable(tmp_path, monkeypatch):
    """Ensure cache file reused and tail fetch happens only once."""
    rec = CallRecorder()
    monkeypatch.setattr("requests.get", rec)
    cache_dir = tmp_path / "cache" / ".cache" / "polygon"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pf, "CACHE_DIR", cache_dir)
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    monkeypatch.setenv("POLYGON_MOCK_NOW", "2025-10-14 10:00:00")

    sym = "AAPL"
    start, end = "2025-10-13", "2025-10-15"

    pf.get_polygon_prices([sym], start, end)
    assert any("/range/1/day/" in c for c in rec.calls)
    rec.calls.clear()

    pf.get_polygon_prices([sym], start, end)
    assert not any("/range/1/day/" in c for c in rec.calls), "Unexpected re-fetch"
