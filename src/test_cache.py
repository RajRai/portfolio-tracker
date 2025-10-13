import json
import pandas as pd
from pathlib import Path
from cache_polygon import get_polygon_prices, CACHE_DIR

if __name__ == "__main__":
    TEST_SYMBOLS = ["AAPL", "MSFT"]
    START = "2024-01-01"
    END = "2024-12-31"

    print("\n=== First run: should FETCH and create cache ===")
    prices1 = get_polygon_prices(TEST_SYMBOLS, START, END)
    print(prices1.tail())

    print("\n=== Second run: should use CACHE (no API calls) ===")
    prices2 = get_polygon_prices(TEST_SYMBOLS, START, END)
    print(prices2.tail())

    print("\n=== Third run: simulate STALE (next market day) ===")

    today = pd.Timestamp.now(tz="America/New_York").normalize()
    yesterday = today - pd.Timedelta(days=1)

    for sym in TEST_SYMBOLS:
        # find latest cache file
        matches = sorted(CACHE_DIR.glob(f"{sym}_*_*.json"))
        if not matches:
            print(f"No cache file for {sym}, skipping")
            continue

        cache_path = matches[-1]
        parts = cache_path.stem.split("_")
        if len(parts) < 3:
            print(f"Unexpected cache filename format: {cache_path.name}")
            continue

        start, old_end = parts[1], parts[2]
        new_end = yesterday.strftime("%Y-%m-%d")
        new_path = CACHE_DIR / f"{sym}_{start}_{new_end}.json"

        # remove any existing backdated version
        if new_path.exists():
            try:
                new_path.unlink()
            except Exception as e:
                print(f"⚠️ Could not remove {new_path.name}: {e}")

        # rename file to simulate being a day behind
        try:
            cache_path.rename(new_path)
            print(f"Backdated cache file for {sym}: {cache_path.name} → {new_path.name}")
        except Exception as e:
            print(f"⚠️ Rename failed for {sym}: {e}")
            continue

        # also backdate last bar to stay consistent
        try:
            data = json.load(open(new_path))
            results = data.get("results", [])
            if results:
                results[-1]["t"] = int(
                    (yesterday - pd.Timestamp("1970-01-01", tz="UTC")).total_seconds() * 1000
                )
                json.dump(data, open(new_path, "w"))
        except Exception as e:
            print(f"⚠️ Failed to backdate JSON for {sym}: {e}")

    prices3 = get_polygon_prices(TEST_SYMBOLS, START, END)
    print(prices3.tail())
