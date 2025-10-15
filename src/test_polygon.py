import os
import json
import pandas as pd
import pytest
import cache_polygon as pf  # ✅ your actual module name

# ============================================================
#  Basic response helper
# ============================================================
def make_response(json_data, status_code=200):
    from types import SimpleNamespace
    return SimpleNamespace(status_code=status_code, json=lambda: json_data)

# ============================================================
#  Main fake Polygon mock for progression tests
# ============================================================
def custom_fake_polygon_get(url, *args, **kwargs):
    """Simulate 10/13–10/15 price sequence for test progression."""
    mock_now = os.getenv("POLYGON_MOCK_NOW")
    now_et = pd.Timestamp(mock_now, tz="America/New_York")

    # --- baseline (daily historical) ---
    if "/range/1/day/" in url:
        base_day = pd.Timestamp("2025-10-13", tz="America/New_York")
        ts_ms = int(base_day.tz_convert("UTC").timestamp() * 1000)
        return make_response({"results": [{"t": ts_ms, "c": 100}]})

    # --- intraday (minute) ---
    elif "/range/1/minute/" in url:
        if now_et.date() == pd.Timestamp("2025-10-14").date():
            if now_et.time() < pd.Timestamp("09:30").time():
                price = 100  # pre-market (not used)
            elif now_et.time() > pd.Timestamp("16:00").time():
                price = 110  # after-hours 10/14
            else:
                price = 105  # regular hours 10/14
        elif now_et.date() == pd.Timestamp("2025-10-15").date():
            if now_et.time() < pd.Timestamp("09:30").time():
                price = 110  # pre-market 10/15
            else:
                price = 115  # regular hours 10/15
        else:
            price = 100
        ts_ms = int(now_et.tz_convert("UTC").timestamp() * 1000)
        return make_response({"results": [{"t": ts_ms, "c": price}]})

    return make_response({}, 404)

@pytest.fixture(autouse=True)
def patch_requests(monkeypatch):
    """Patch requests.get to use our custom fake Polygon responses by default."""
    monkeypatch.setattr("requests.get", custom_fake_polygon_get)

# ============================================================
#  Test 1: Progressive intraday updates
# ============================================================
def test_price_progression(tmp_path, monkeypatch):
    """Validate progressive price updates and state after each simulated session."""
    cache_dir = tmp_path / "cache" / ".cache" / "polygon"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pf, "CACHE_DIR", cache_dir)
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")

    symbol = "AAPL"
    start = "2025-10-13"
    end = "2025-10-15"

    # --- seed initial cache with 10/13 close = 100 ---
    day_1013 = pd.Timestamp("2025-10-13", tz="America/New_York")
    ts_ms = int(day_1013.tz_convert("UTC").timestamp() * 1000)
    pf._save_cache(symbol, start, "2025-10-13", {"results": [{"t": ts_ms, "c": 100}]})

    def run_at(mock_now, expected_price, expected_series):
        """Run fetcher at simulated time and verify both last and cumulative series."""
        monkeypatch.setenv("POLYGON_MOCK_NOW", mock_now)
        prices = pf.get_polygon_prices([symbol], start, end)
        s = prices[symbol]
        vals = list(map(float, s.values))
        print(f"\n[{mock_now}] → last={vals[-1]}, full={vals}")
        assert abs(vals[-1] - expected_price) < 1e-9, f"expected {expected_price}, got {vals[-1]}"
        assert vals == expected_series, f"series mismatch: {vals} vs {expected_series}"

    # progressive validation
    run_at("2025-10-14 10:00:00", 105, [100.0, 105.0])  # regular 10/14
    run_at("2025-10-14 18:00:00", 110, [100.0, 110.0])  # after-hours 10/14
    run_at("2025-10-15 08:00:00", 110, [100.0, 110.0])  # pre-market 10/15
    run_at("2025-10-15 10:00:00", 115, [100.0, 115.0])  # regular 10/15

    # final check after all steps
    prices = pf.get_polygon_prices([symbol], start, end)
    s = prices[symbol]
    print("\nFinal series:", list(s.values))
    assert list(s.values) == [100.0, 115.0]
    assert s.iloc[-1] == 115

# ============================================================
#  Helper class for cache tests
# ============================================================
class CallRecorder:
    def __init__(self):
        self.calls = []
    def __call__(self, url, *args, **kwargs):
        self.calls.append(url)
        # Daily: two days of data
        if "/range/1/day/" in url:
            today = pd.Timestamp("2025-10-14", tz="America/New_York")
            prev = today - pd.Timedelta(days=1)
            results = []
            for d, c in [(prev, 100), (today, 105)]:
                ts = int(d.tz_convert("UTC").timestamp() * 1000)
                results.append({"t": ts, "c": c})
            return make_response({"results": results})
        # Intraday placeholder
        elif "/range/1/minute/" in url:
            ts = int(pd.Timestamp("2025-10-14T10:00:00", tz="America/New_York")
                     .tz_convert("UTC").timestamp() * 1000)
            return make_response({"results": [{"t": ts, "c": 105}]})
        return make_response({}, 404)

# ============================================================
#  Test 2: Cache miss → hit
# ============================================================
def test_cache_miss_then_hit(tmp_path, monkeypatch):
    rec = CallRecorder()
    monkeypatch.setattr("requests.get", rec)
    cache_dir = tmp_path / "cache" / ".cache" / "polygon"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pf, "CACHE_DIR", cache_dir)
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")
    monkeypatch.setenv("POLYGON_MOCK_NOW", "2025-10-14 10:00:00")

    sym = "AAPL"
    start = "2025-10-13"
    end = "2025-10-15"

    # 1️⃣ First call: no cache → should fetch and create file
    prices = pf.get_polygon_prices([sym], start, end)
    files = list(cache_dir.glob(f"{sym}_{start}_*.json"))
    assert len(files) == 1
    assert any("/range/1/day/" in c for c in rec.calls)

    # Cache file should have 2 daily bars
    data = json.load(open(files[0]))
    assert len(data["results"]) == 2

    # 2️⃣ Second call: cache hit → should NOT call /day/
    rec.calls.clear()
    prices2 = pf.get_polygon_prices([sym], start, end)
    assert not any("/range/1/day/" in c for c in rec.calls), "Unexpected refetch"
    assert prices2.equals(prices)

# ============================================================
#  Test 3: Cache stale → tail fetch
# ============================================================
def test_cache_stale_fetch(tmp_path, monkeypatch):
    rec = CallRecorder()
    monkeypatch.setattr("requests.get", rec)
    cache_dir = tmp_path / "cache" / ".cache" / "polygon"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pf, "CACHE_DIR", cache_dir)
    monkeypatch.setenv("POLYGON_API_KEY", "dummy")

    sym = "AAPL"
    start = "2025-10-13"
    end = "2025-10-15"

    # Seed cache up to 10/13 only
    ts = int(pd.Timestamp("2025-10-13", tz="America/New_York")
             .tz_convert("UTC").timestamp() * 1000)
    pf._save_cache(sym, start, "2025-10-13", {"results": [{"t": ts, "c": 100}]})

    # Now "today" is 10/14 → should be considered stale
    monkeypatch.setenv("POLYGON_MOCK_NOW", "2025-10-14 10:00:00")
    rec.calls.clear()
    pf.get_polygon_prices([sym], start, end)

    # Expect one daily tail fetch
    day_calls = [c for c in rec.calls if "/range/1/day/" in c]
    assert len(day_calls) == 1, "Expected one tail fetch"
    files = list(cache_dir.glob(f"{sym}_{start}_2025-10-14.json"))
    assert files, "Updated cache file missing"
