"""
Fetch weekly closes for the Rotation Observatory universe.

Replaces the ad-hoc MCP pulls that produced the original 26-bar raw_prices.csv.
Self-contained: one dependency (yfinance), no MCP, no API key, re-runnable.

    ./.venv/bin/python fetch_prices.py            # 5 years (default)
    ./.venv/bin/python fetch_prices.py --years 10

Writes data/raw_prices.csv in the schema observatory.py already reads:
`date,symbol,close`. The previous file is backed up alongside it.

Three deliberate choices:

* DAILY download, resampled to W-FRI here. Asking the provider for weekly bars
  gives you its week convention (Monday-labelled, and a partial bar for the week
  in progress). Resampling locally means every bar is a Friday close and the
  final, still-open week is dropped rather than silently compared against
  complete ones — an RRG reads the newest bar, so a half-week there is the one
  place a stale/partial number does real damage.

* auto_adjust=True — total-return series. Relative strength between sectors is
  distorted by ignoring dividends: XLE and XLF yield multiples of XLK, so on
  price-only series they look permanently weaker than they are. Every number
  downstream is a RATIO of two of these, which is exactly where the drift shows.

* The universe here is a SUPERSET of what observatory.py currently plots — all
  11 GICS sector SPDRs, not the 4 wired up today. Extra columns are ignored by
  the engine (it selects the symbols it needs), so this costs nothing now and
  means extending SECTORS later is a config edit rather than another fetch.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

BASE = Path(__file__).resolve().parent
OUT = BASE / "data" / "raw_prices.csv"

BENCHMARKS = ["SPY", "QQQ"]
# all 11 GICS sectors; observatory.py currently plots the first four
SECTORS = ["XLK", "XLE", "XLF", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB",
           "XLRE", "XLC"]
# equal-weight twins, for the cap-vs-equal-weight breadth spread
EQUAL_WEIGHT = ["RSPT", "RSPG", "RSPF", "RSPH"]
FACTORS = ["IWD", "IWF", "MTUM"]
SYMBOLS = BENCHMARKS + SECTORS + EQUAL_WEIGHT + FACTORS

# What observatory.py will refuse to run without — reported separately, because
# losing one of these is fatal while losing XLRE is merely a smaller universe.
REQUIRED = set(BENCHMARKS + ["XLK", "XLE", "XLF", "XLV"] + EQUAL_WEIGHT + FACTORS)


def weekly_closes(daily: pd.DataFrame) -> pd.DataFrame:
    """Friday-stamped weekly closes, with the in-progress week removed."""
    weekly = daily.resample("W-FRI").last().dropna(how="all")
    if weekly.empty:
        return weekly
    # The last bucket is only complete once its Friday has actually traded. The
    # daily series ending before that Friday means the week is still running.
    last_friday = weekly.index[-1]
    if daily.index.max() < last_friday:
        weekly = weekly.iloc[:-1]
    return weekly


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    args = ap.parse_args()

    print(f"Fetching {len(SYMBOLS)} symbols, {args.years}y daily -> weekly (W-FRI)")
    raw = yf.download(SYMBOLS, period=f"{args.years}y", interval="1d",
                      auto_adjust=True, progress=False, group_by="column")
    if raw.empty:
        print("ERROR: provider returned nothing", file=sys.stderr)
        return 1

    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    close = close.dropna(how="all")
    weekly = weekly_closes(close)

    got = [s for s in SYMBOLS if s in weekly.columns and weekly[s].notna().any()]
    missing = sorted(set(SYMBOLS) - set(got))
    if missing:
        print(f"  no data for: {', '.join(missing)}")
    fatal = REQUIRED - set(got)
    if fatal:
        print(f"ERROR: required symbols missing: {sorted(fatal)}", file=sys.stderr)
        return 1

    tidy = (weekly[got].reset_index()
            .melt(id_vars=weekly.index.name or "Date",
                  var_name="symbol", value_name="close")
            .rename(columns={weekly.index.name or "Date": "date"})
            .dropna(subset=["close"])
            .sort_values(["symbol", "date"]))
    tidy["date"] = pd.to_datetime(tidy["date"]).dt.strftime("%Y-%m-%d")
    tidy["close"] = tidy["close"].round(4)

    if OUT.exists():
        backup = OUT.with_suffix(f".csv.bak-{date.today():%Y%m%d}")
        shutil.copy2(OUT, backup)
        print(f"  backed up existing -> {backup.name}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tidy.to_csv(OUT, index=False)

    per = tidy.groupby("symbol")["date"].agg(["count", "min", "max"])
    print(f"\nWrote {len(tidy):,} rows -> {OUT.relative_to(BASE)}")
    print(f"Weekly bars: {per['count'].min()}–{per['count'].max()} per symbol, "
          f"{per['min'].min()} .. {per['max'].max()}")
    short = per[per["count"] < per["count"].max() * 0.9]
    if len(short):
        print("\nShorter history (listed later) — fine, but they warm up late:")
        print(short.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
