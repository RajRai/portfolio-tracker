import sys
import time, os
import pandas as pd
from pathlib import Path
import subprocess

BASE = Path("data")

def merge_statements(account_dir: Path):
    statements_dir = account_dir / "statements"
    files = sorted(statements_dir.glob("*.csv"))
    if not files:
        return None

    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f)
            df = df[pd.to_datetime(df["Run Date"], errors="coerce").notna()]
            dfs.append(df)
        except Exception as e:
            print(f"⚠️ skipping {f}: {e}")

    if not dfs:
        return None

    combined = (
        pd.concat(dfs, ignore_index=True)
        .drop_duplicates(subset=["Run Date", "Action", "Symbol", "Price", "Cash Balance", "Amount"])
    )

    # Convert before sorting
    combined["Run Date"] = pd.to_datetime(combined["Run Date"], errors="coerce", infer_datetime_format=True)
    combined = combined.sort_values("Run Date").reset_index(drop=True)

    out = account_dir / "combined.csv"
    combined.to_csv(out, index=False)
    print(f"✅ merged {len(files)} files → {out}")
    return out

def regenerate_reports():
    print("▶ rebuilding all reports...")
    subprocess.run([sys.executable, "analyze_fidelity.py"], check=False)
    print("✅ Reports updated")

def watch(interval=5):
    known_mtimes = {}
    while True:
        changed = False
        for account_dir in BASE.iterdir():
            if not account_dir.is_dir():
                continue
            statements = account_dir / "statements"
            if not statements.exists():
                continue
            latest_mtime = max((f.stat().st_mtime for f in statements.glob("*.csv")), default=0)
            if known_mtimes.get(account_dir) != latest_mtime:
                changed = True
                known_mtimes[account_dir] = latest_mtime
                merge_statements(account_dir)
        if changed:
            regenerate_reports()
        time.sleep(interval)

if __name__ == "__main__":
    watch()
