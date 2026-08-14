"""
Stress the RRG engine: degenerate inputs, and whether the output means anything.

Two kinds of check, because they fail differently:

  * INVARIANTS — things that must hold for any input at all (no NaN/inf, the
    quadrant matches the coordinates it was derived from, a symbol that IS the
    benchmark sits exactly at the origin). A break here is a bug.
  * LOGIC — whether the numbers say something true about the prices behind them
    (a steady outperformer must read above 100 and keep reading above 100). A
    break here is worse than a bug: the chart still draws, it just lies.

Run with:  ./.venv/bin/python stress_observatory.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")

import observatory as O  # noqa: E402

WEEKS = 200
IDX = pd.bdate_range("2022-01-07", periods=WEEKS, freq="W-FRI")


def frame(**series) -> pd.DataFrame:
    return pd.DataFrame(series, index=IDX)


def run(wide: pd.DataFrame, universe: list[str]):
    """compute_rrg against a chosen universe, restoring globals afterwards."""
    old_u, old_b = O.UNIVERSE, O.BENCHMARK
    O.UNIVERSE = universe
    try:
        return O.compute_rrg(wide)
    finally:
        O.UNIVERSE, O.BENCHMARK = old_u, old_b


def geo(start: float, weekly: float) -> np.ndarray:
    return start * np.cumprod(np.full(WEEKS, 1 + weekly))


# ------------------------------------------------------------------ invariants
def check_invariants(df: pd.DataFrame, label: str) -> list[str]:
    bad = []
    if df.empty:
        return bad
    for col in ("rs_ratio", "rs_momentum"):
        v = df[col].to_numpy(dtype=float)
        if not np.isfinite(v).all():
            bad.append(f"{label}: {col} has NaN/inf")
    # the quadrant must be derivable from the coordinates it is drawn at
    for r in df.itertuples():
        want = ("Leading" if r.rs_ratio >= 100 and r.rs_momentum >= 100 else
                "Weakening" if r.rs_ratio >= 100 else
                "Improving" if r.rs_momentum >= 100 else "Lagging")
        if r.quadrant != want:
            bad.append(f"{label}: {r.symbol} at ({r.rs_ratio:.2f},"
                       f"{r.rs_momentum:.2f}) labelled {r.quadrant}, not {want}")
            break
    if (df["rs_ratio"] <= 0).any():
        bad.append(f"{label}: non-positive rs_ratio")
    return bad


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def identical_to_benchmark():
    """A symbol that IS the benchmark must sit exactly at the origin."""
    spy = geo(400, 0.002)
    df = run(frame(SPY=spy, TWIN=spy.copy()), ["TWIN"])
    bad = check_invariants(df, "identical")
    off = df[((df.rs_ratio - 100).abs() > 1e-9)
             | ((df.rs_momentum - 100).abs() > 1e-9)]
    if len(off):
        bad.append(f"identical: {len(off)} rows away from (100,100), "
                   f"worst ratio {off.rs_ratio.sub(100).abs().max():.2e}")
    return "identical_to_benchmark", bad


@case
def scaled_benchmark():
    """Price level must not matter — only the ratio's shape does."""
    spy = geo(400, 0.002)
    df = run(frame(SPY=spy, SCALED=spy * 37.5), ["SCALED"])
    bad = check_invariants(df, "scaled")
    off = df[((df.rs_ratio - 100).abs() > 1e-9)]
    if len(off):
        bad.append(f"scaled: price level leaked in, worst "
                   f"{off.rs_ratio.sub(100).abs().max():.2e}")
    return "scaled_benchmark", bad


@case
def steady_outperformer():
    """THE test. A symbol beating the benchmark every single week must read
    above 100 and STAY there — a measure that de-trends its own input would
    drift back to neutral and call a permanent winner 'neutral'."""
    spy = geo(400, 0.002)
    win = spy * np.cumprod(np.full(WEEKS, 1.002))     # +0.2%/wk relative
    df = run(frame(SPY=spy, WIN=win), ["WIN"])
    bad = check_invariants(df, "outperformer")
    below = (df.rs_ratio < 100).sum()
    if below:
        bad.append(f"outperformer: reads below 100 on {below}/{len(df)} weeks")
    if (df.rs_momentum < 100).sum():
        bad.append(f"outperformer: momentum below 100 on "
                   f"{(df.rs_momentum < 100).sum()}/{len(df)} weeks")
    return "steady_outperformer", bad


@case
def steady_underperformer():
    spy = geo(400, 0.002)
    lose = spy * np.cumprod(np.full(WEEKS, 0.998))
    df = run(frame(SPY=spy, LOSE=lose), ["LOSE"])
    bad = check_invariants(df, "underperformer")
    above = (df.rs_ratio > 100).sum()
    if above:
        bad.append(f"underperformer: reads above 100 on {above}/{len(df)} weeks")
    return "steady_underperformer", bad


@case
def flat_market():
    """Constant prices everywhere: RS is constant, so the ratio is exactly 100
    and momentum exactly 100 — not a division by zero."""
    df = run(frame(SPY=np.full(WEEKS, 400.0), FLAT=np.full(WEEKS, 50.0)), ["FLAT"])
    bad = check_invariants(df, "flat")
    off = df[((df.rs_ratio - 100).abs() > 1e-9) | ((df.rs_momentum - 100).abs() > 1e-9)]
    if len(off):
        bad.append(f"flat: {len(off)} rows not at (100,100)")
    return "flat_market", bad


@case
def step_change():
    """A one-off 20% jump (the shape of a re-rating). Must be absorbed, and the
    ratio must return toward 100 once the jump is inside the whole window."""
    spy = geo(400, 0.002)
    step = spy.copy()
    step[WEEKS // 2:] *= 1.20
    df = run(frame(SPY=spy, STEP=step), ["STEP"])
    bad = check_invariants(df, "step")
    tail = df[df.date > df.date.max() - pd.Timedelta(weeks=5)]
    if len(tail) and (tail.rs_ratio.sub(100).abs() > 3).any():
        bad.append(f"step: still {tail.rs_ratio.sub(100).abs().max():.1f} from "
                   f"neutral long after the jump left the window")
    return "step_change", bad


@case
def noisy_random_walk():
    """Pure noise should average out near neutral, not sit on one side."""
    rng = np.random.default_rng(7)
    spy = 400 * np.cumprod(1 + rng.normal(0.002, 0.02, WEEKS))
    sym = 100 * np.cumprod(1 + rng.normal(0.002, 0.025, WEEKS))
    df = run(frame(SPY=spy, NOISE=sym), ["NOISE"])
    bad = check_invariants(df, "noise")
    if abs(df.rs_ratio.mean() - 100) > 2:
        bad.append(f"noise: mean ratio {df.rs_ratio.mean():.2f}, expected ~100")
    return "noisy_random_walk", bad


@case
def short_history():
    """Fewer bars than the window: emit nothing rather than something wrong."""
    idx = IDX[:O.WINDOW - 2]
    wide = pd.DataFrame({"SPY": geo(400, .002)[:len(idx)],
                         "S": geo(100, .003)[:len(idx)]}, index=idx)
    df = run(wide, ["S"])
    bad = [] if df.empty else [f"short_history: emitted {len(df)} rows on "
                               f"{len(idx)} bars (window {O.WINDOW})"]
    return "short_history", bad


@case
def exactly_window_bars():
    idx = IDX[:O.WINDOW]
    wide = pd.DataFrame({"SPY": geo(400, .002)[:O.WINDOW],
                         "S": geo(100, .003)[:O.WINDOW]}, index=idx)
    df = run(wide, ["S"])
    return "exactly_window_bars", check_invariants(df, "exact")


@case
def gap_in_series():
    """A hole in one symbol's prices must not silently become a fake move."""
    spy = geo(400, 0.002)
    sym = geo(100, 0.002)
    sym[80:85] = np.nan
    df = run(frame(SPY=spy, GAP=sym), ["GAP"])
    return "gap_in_series", check_invariants(df, "gap")


@case
def lists_midway():
    """The MAGS shape: no prices at all until part-way through the window.

    Must contribute nothing while it did not exist — not a flat line at its
    first price, which would read as 'perfectly tracked the benchmark' for years
    it was not trading — and must warm up cleanly once it does."""
    spy = geo(400, 0.002)
    sym = np.full(WEEKS, np.nan)
    sym[100:] = geo(50, 0.004)[100:]
    df = run(frame(SPY=spy, NEW=sym), ["NEW"])
    bad = check_invariants(df, "lists_midway")
    early = df[df.date < IDX[100]]
    if len(early):
        bad.append(f"lists_midway: {len(early)} rows before the symbol existed")
    first = df.date.min() if len(df) else None
    if first is not None and first < IDX[100 + O.WINDOW - 1]:
        bad.append(f"lists_midway: first row {first.date()} precedes a full "
                   f"{O.WINDOW}-bar window after listing")
    return "lists_midway", bad


@case
def split_artifact():
    """An unadjusted 10:1 split — a 90% single-week 'drop' that never happened."""
    spy = geo(400, 0.002)
    sym = geo(1000, 0.002)
    sym[120:] /= 10.0
    df = run(frame(SPY=spy, SPLIT=sym), ["SPLIT"])
    bad = check_invariants(df, "split")
    # not a correctness failure of the engine — but it must be VISIBLE, not quiet
    if df.rs_ratio.min() > 50:
        bad.append("split: a 10:1 price break barely moved RS-Ratio "
                   f"(min {df.rs_ratio.min():.1f}) — it would pass unnoticed")
    return "split_artifact", bad


def real_data_logic() -> list[str]:
    """Does the shipped configuration say true things about the real prices?"""
    bad = []
    wide = (pd.read_csv(O.BASE / "data" / "raw_prices.csv", parse_dates=["date"])
            .pivot(index="date", columns="symbol", values="close").sort_index())
    df = run(wide, O.UNIVERSE)
    bad += check_invariants(df, "real")

    last = df[df.date == df.date.max()].set_index("symbol")
    # rank agreement between RS-Ratio and actual trailing relative return
    horizon = O.WINDOW
    rel = {}
    for s in last.index:
        rel[s] = ((wide[s].iloc[-1] / wide[s].iloc[-1 - horizon])
                  / (wide["SPY"].iloc[-1] / wide["SPY"].iloc[-1 - horizon]) - 1)
    a = pd.Series({s: last.loc[s, "rs_ratio"] for s in rel}).rank()
    b = pd.Series(rel).rank()
    rho = float(np.corrcoef(a, b)[0, 1])
    print(f"    rank corr(RS-Ratio, actual {horizon}w relative) = {rho:+.2f}")
    if rho < 0.5:
        bad.append(f"real: RS-Ratio ranking disagrees with actual "
                   f"{horizon}w relative performance (rho {rho:+.2f})")

    # the benchmark, measured against itself, must be exactly neutral
    df_b = run(wide.assign(SELF=wide["SPY"]), ["SELF"])
    if len(df_b) and ((df_b.rs_ratio - 100).abs() > 1e-9).any():
        bad.append("real: benchmark vs itself is not exactly 100")

    # sanity on spread: with 14 symbols the cross-section should straddle 100
    n_above = int((last.rs_ratio >= 100).sum())
    print(f"    cross-section: {n_above}/{len(last)} at or above 100")
    return bad


if __name__ == "__main__":
    print(f"config: WINDOW={O.WINDOW} MOM_WINDOW={O.MOM_WINDOW} "
          f"BENCHMARK={O.BENCHMARK}\n")
    failures = 0
    for fn in CASES:
        name, bad = fn()
        print(f"[{'ok' if not bad else f'{len(bad)} PROBLEM(S)':>14}] {name}"
              if not bad else f"[{len(bad)} PROBLEM(S)] {name}")
        for b in bad:
            print(f"                 - {b}")
        failures += len(bad)

    print("\n[real data]")
    bad = real_data_logic()
    for b in bad:
        print(f"                 - {b}")
    failures += len(bad)
    print(f"\ntotal problems: {failures}")
    raise SystemExit(1 if failures else 0)
