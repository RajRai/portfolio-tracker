import sys
import time
import os
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

def watch(scan_interval=5, rebuild_interval=600):
    """
    Scan for new or changed CSVs every `scan_interval` seconds,
    but force a full rebuild at least every `rebuild_interval` seconds.
    """
    known_mtimes = {}
    last_rebuild = 0

    while True:
        now = time.time()
        changed = False

        # --- Check for file changes ---
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

        # --- Trigger rebuild if files changed OR time exceeded ---
        if changed or (now - last_rebuild >= rebuild_interval):
            if not changed:
                print("⏰ Forced rebuild (10 minutes elapsed)")
            regenerate_reports()
            last_rebuild = now

        time.sleep(scan_interval)

if __name__ == "__main__":
    watch()
