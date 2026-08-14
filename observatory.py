"""
Rotation Observatory - v0 prototype
Reads weekly closes from data/raw_prices.csv, computes JdK-style
RS-Ratio / RS-Momentum vs benchmark, stores history in SQLite,
renders an HTML report (RRG + heatmap + quadrant timeline).

Descriptive only - no signals. Extend SECTORS to grow the universe.
"""

import json
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
BENCHMARK = "SPY"
BENCHMARKS = ["SPY", "QQQ"]              # context panel top chart
SECTORS = ["XLK", "XLE", "XLF", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB",
           "XLRE", "XLC"]               # all 11 GICS sectors
FACTORS = ["IWD", "IWF", "MTUM"]         # value / growth / momentum ETFs
UNIVERSE = SECTORS + FACTORS             # everything measured vs BENCHMARK
EW_PAIRS = {"XLK": "RSPT", "XLE": "RSPG", "XLF": "RSPF", "XLV": "RSPH"}
# Normalization window for RS-Ratio, in bars. 26 rather than the original 10:
# measured over 5y of weekly data, agreement between the RS-Ratio ranking and
# actual trailing relative performance rises from 0.53 (w=10) to 0.83 (w=26).
# 10 weeks was the worst setting tested — it reads swing moves as rotation.
WINDOW = 26
# Lookback for RS-Momentum, the rate of change of RS-Ratio. Short enough to lead
# the ratio, long enough not to churn: quadrant membership flips 29.5% of weeks
# at 4, 22.9% at 8, 21.3% at 13, and past 8 the axis stops leading anything.
MOM_WINDOW = 8
TRAIL = 6            # RRG trail length (bars)
# Lookbacks for the relative-performance heatmap, in bars. Defined once and sent
# to the template so the column headers and the RRG's stated horizon both come
# from the config: the two panels measure DIFFERENT horizons and will disagree
# whenever a sector's relative strength turns, which is not a bug and is very
# easy to misread as one.
HEATMAP_PERIODS = [("1w", 1), ("4w", 4), ("13w", 13)]
# How many recent weeks the quadrant timeline draws. The DB keeps everything;
# this only bounds the strip, which is one 22px cell per week per symbol and so
# ran to ~5,300px once the history went from 26 weeks to 241.
TIMELINE_WEEKS = 52

SECTOR_NAMES = {
    "XLK": "Technology", "XLE": "Energy", "XLF": "Financials",
    "XLV": "Health Care", "XLI": "Industrials", "XLY": "Cons. Discretionary",
    "XLP": "Cons. Staples", "XLU": "Utilities", "XLB": "Materials",
    "XLRE": "Real Estate", "XLC": "Comm. Services",
    "IWD": "Value", "IWF": "Growth", "MTUM": "Momentum",
}

QUADRANTS = {
    ("hi", "hi"): "Leading", ("hi", "lo"): "Weakening",
    ("lo", "lo"): "Lagging", ("lo", "hi"): "Improving",
}
QCOLORS = {"Leading": "#2e9e4f", "Weakening": "#e0a800",
           "Lagging": "#d9534f", "Improving": "#3b7dd8"}


def load_prices() -> pd.DataFrame:
    df = pd.read_csv(BASE / "data" / "raw_prices.csv", parse_dates=["date"])
    wide = df.pivot(index="date", columns="symbol", values="close").sort_index()
    return wide


def compute_rrg(wide: pd.DataFrame) -> pd.DataFrame:
    """Long dataframe: date, symbol, rs_ratio, rs_momentum, quadrant.

    RS-Ratio is the relative-strength line as a PERCENTAGE of its own rolling
    average — 103 means 3% above it. It replaced `100 + zscore(rs, WINDOW)`,
    which divided each symbol by its own volatility and so made the two axes
    mean different things per symbol: over this sample the RS line's standard
    deviation ran from 0.370 (XLF) to 2.215 (MTUM), a 6x spread, so two dots
    sitting together on the chart represented very different-sized moves. That
    is fatal for a picture whose entire premise is cross-symbol comparison.
    Percent-of-own-average is scale-free in the same units for everyone, and it
    also ranks relative performance better (0.83 vs 0.75 against trailing 13w).

    RS-Momentum is the change in RS-Ratio over MOM_WINDOW bars — the derivative
    of the X axis, which is what the Y axis of an RRG is defined to be. The old
    `zscore(diff(zscore(rs)))` was a z-score of a difference of a z-score, three
    transformations deep, and mostly noise at a 10-bar window.
    """
    out = []
    for sym in UNIVERSE:
        rs = 100 * wide[sym] / wide[BENCHMARK]
        rs_ratio = 100 * rs / rs.rolling(WINDOW).mean()
        rs_mom = 100 + (rs_ratio - rs_ratio.shift(MOM_WINDOW))
        # Round BEFORE classifying, so the quadrant is always derivable from the
        # coordinates actually plotted. Classifying the raw values and rounding
        # afterwards let a dot drawn at exactly (100.00, 100.00) be labelled
        # Lagging: a symbol identical to the benchmark has a constant RS line,
        # but pandas' rolling mean accumulates a running sum, so its average came
        # back as 100.00000000000001 and the ratio landed a hair under the line.
        # Real data rarely lands that close — the label contradicting the dot is
        # the kind of thing nobody would ever track down from the chart.
        rs_ratio = rs_ratio.round(3)
        rs_mom = rs_mom.round(3)
        q = pd.Series(
            [QUADRANTS[("hi" if r >= 100 else "lo", "hi" if m >= 100 else "lo")]
             if pd.notna(r) and pd.notna(m) else None
             for r, m in zip(rs_ratio, rs_mom)],
            index=rs_ratio.index,
        )
        out.append(pd.DataFrame({
            "date": rs_ratio.index, "symbol": sym,
            "rs_ratio": rs_ratio.values, "rs_momentum": rs_mom.values,
            "quadrant": q.values,
        }))
    df = pd.concat(out, ignore_index=True).dropna(subset=["quadrant"])
    df["rs_ratio"] = df["rs_ratio"].round(3)
    df["rs_momentum"] = df["rs_momentum"].round(3)
    return df


def compute_heatmap(wide: pd.DataFrame) -> list[dict]:
    """Relative return vs benchmark over 1w / 4w / 13w (in %-points)."""
    rows = []
    for sym in UNIVERSE:
        row = {"symbol": sym, "name": SECTOR_NAMES.get(sym, sym)}
        for label, bars in HEATMAP_PERIODS:
            if len(wide) > bars:
                sec = wide[sym].iloc[-1] / wide[sym].iloc[-1 - bars] - 1
                ben = wide[BENCHMARK].iloc[-1] / wide[BENCHMARK].iloc[-1 - bars] - 1
                row[label] = round(100 * (sec - ben), 2)
            else:
                row[label] = None
        rows.append(row)
    return rows


@contextmanager
def db_connection(write: bool = False):
    """SQLite on network-mounted folders can fail to lock; work on a local
    temp copy and sync back after writes."""
    db = BASE / "observatory.db"
    tmp = Path(tempfile.gettempdir()) / "observatory_work.db"
    if db.exists():
        shutil.copy2(db, tmp)
    elif tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    try:
        yield con
        if write:
            con.commit()
    finally:
        con.close()
        if write:
            shutil.copy2(tmp, db)


def persist(df: pd.DataFrame) -> None:
    """Store the computed signals, discarding history built a different way.

    Rows are keyed (date, symbol) and rewritten in place, which quietly assumes
    every row was produced by the same formula. Changing WINDOW broke that: the
    longer warm-up meant the first 14 weeks of the previous run were never
    overwritten, leaving z-score-era quadrants sitting under RS/SMA-era ones in
    the same table with nothing to tell them apart. Stamp the method and wipe
    when it changes — two normalizations are not a comparable time series.
    """
    method = json.dumps({"norm": "rs_over_sma", "window": WINDOW,
                         "mom_window": MOM_WINDOW, "benchmark": BENCHMARK},
                        sort_keys=True)
    with db_connection(write=True) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS snapshots (
            date TEXT NOT NULL, symbol TEXT NOT NULL,
            rs_ratio REAL, rs_momentum REAL, quadrant TEXT,
            PRIMARY KEY (date, symbol))""")
        con.execute("CREATE TABLE IF NOT EXISTS meta ("
                    "key TEXT PRIMARY KEY, value TEXT)")
        stored = con.execute("SELECT value FROM meta WHERE key = 'method'").fetchone()
        if stored and stored[0] != method:
            con.execute("DELETE FROM snapshots")
            print("methodology changed -> rebuilt snapshot history from scratch")
        con.execute("INSERT OR REPLACE INTO meta VALUES ('method', ?)", (method,))
        con.executemany(
            "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?)",
            [(d.strftime("%Y-%m-%d"), s, r, m, q) for d, s, r, m, q in
             df[["date", "symbol", "rs_ratio", "rs_momentum", "quadrant"]].itertuples(index=False)],
        )


def timeline_from_db(weeks: int = TIMELINE_WEEKS) -> dict:
    with db_connection() as con:
        rows = con.execute(
            "SELECT date, symbol, quadrant FROM snapshots ORDER BY date").fetchall()
    dates = sorted({r[0] for r in rows})[-weeks:]
    keep = set(dates)
    rows = [r for r in rows if r[0] in keep]
    grid = {s: {d: None for d in dates} for s in UNIVERSE}
    for d, s, q in rows:
        if s in grid:
            grid[s][d] = q
    return {"dates": dates,
            "rows": [{"symbol": s, "cells": [grid[s][d] for d in dates]}
                     for s in UNIVERSE]}


def series_payload(wide: pd.DataFrame) -> dict:
    """Raw close series for the market-context panel; JS re-bases to the
    user-selected date window."""
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in wide.index],
        "benchmarks": BENCHMARKS,
        "closes": {sym: [None if pd.isna(v) else round(float(v), 2)
                         for v in wide[sym]]
                   for sym in [*BENCHMARKS, *UNIVERSE, *EW_PAIRS.values()]
                   if sym in wide.columns},
        "ewpairs": EW_PAIRS,
        "factors": FACTORS,
    }


def render_html(rrg: pd.DataFrame, heatmap: list[dict], timeline: dict,
                series: dict) -> str:
    last_date = rrg["date"].max()
    trails = {}
    for sym in UNIVERSE:
        sub = rrg[rrg["symbol"] == sym].sort_values("date").tail(TRAIL)
        trails[sym] = {
            "name": SECTOR_NAMES.get(sym, sym),
            "points": [{"x": r, "y": m, "d": d.strftime("%m-%d")}
                       for d, r, m in sub[["date", "rs_ratio", "rs_momentum"]].itertuples(index=False)],
            "quadrant": sub.iloc[-1]["quadrant"],
        }
    payload = json.dumps({"trails": trails, "heatmap": heatmap,
                          "timeline": timeline, "series": series,
                          "names": SECTOR_NAMES, "qcolors": QCOLORS,
                          "asof": last_date.strftime("%Y-%m-%d"),
                          # every horizon the view states is read from here, so a
                          # change to WINDOW can never leave the labels lying
                          "config": {"window": WINDOW, "trail": TRAIL,
                                     "mom_window": MOM_WINDOW,
                                     "benchmark": BENCHMARK,
                                     "heatmap": [l for l, _ in HEATMAP_PERIODS],
                                     "bars": len(rrg["date"].unique()),
                                     "timeline_weeks": len(timeline["dates"])}})
    template = (BASE / "template.html").read_text()
    return template.replace("__PAYLOAD__", payload)


def main() -> None:
    global UNIVERSE, EW_PAIRS
    wide = load_prices()
    # The benchmark is load-bearing — every number is relative to it, so its
    # absence is fatal. A missing member of the universe is not: a thematic ETF
    # can be launched or wound up between runs, and dying on that would take the
    # whole dashboard down over one row. Drop it loudly and carry on.
    missing_bm = [s for s in BENCHMARKS if s not in wide.columns]
    if missing_bm:
        raise SystemExit(f"Benchmark missing from raw_prices.csv: {missing_bm}")
    dropped = [s for s in UNIVERSE if s not in wide.columns]
    if dropped:
        print(f"WARNING: not in raw_prices.csv, skipping: {', '.join(dropped)}")
        UNIVERSE = [s for s in UNIVERSE if s in wide.columns]
    EW_PAIRS = {k: v for k, v in EW_PAIRS.items()
                if k in wide.columns and v in wide.columns}
    rrg = compute_rrg(wide)
    persist(rrg)
    html = render_html(rrg, compute_heatmap(wide), timeline_from_db(),
                       series_payload(wide))
    out = BASE / "report.html"
    out.write_text(html)
    print(f"OK: {len(rrg)} snapshot rows -> observatory.db; report -> {out.name}")
    print(rrg.groupby("symbol").tail(1)[["symbol", "rs_ratio", "rs_momentum", "quadrant"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
