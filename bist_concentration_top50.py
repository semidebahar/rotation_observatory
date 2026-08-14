"""
BIST Index Concentration — TOP-10-OF-TOP-50 (survivorship-robust variant).

Parallel to bist_concentration.py (the top-10-of-TOTAL version). Same data, same
free-float basis, same cross-sectional recompute — only the DENOMINATOR changes:

    W50(t) = sum(free-float mcap of the 10 largest on date t)
             -------------------------------------------------
             sum(free-float mcap of the 50 largest on date t)

Why: over a 10y window the universe (today's XU100 applied historically) grows
from ~65 to 100 members, and a variable-size denominator mechanically inflates
the top-10 share in the thin early years. Fixing the denominator at a constant
TOP-50 puts every date on identical footing.

Why 50 and not 65 (the min universe): the top 50 leaves a ~15-name BENCH in the
worst year (universe 65). When a name that truly belonged in the top 50 is one of
the survivorship-missing tickers, its slot is filled by the next survivor down —
SUBSTITUTION (second-order error) instead of OMISSION (first-order). At N=65 the
bench is zero and the omission bias returns exactly where it hurts. Trade-off:
larger N = more market coverage but thinner bench; smaller N = fatter bench but
more "tail-blindness". ~50 balances both; tune empirically if desired (see the
console validation, which prints W50 vs W100 on the recent complete-universe years).

Numerator (top 10) is essentially error-free in every year — 2016's top-10 names
(GARAN, AKBNK, ISCTR, TUPRS, THYAO, EREGL, KCHOL...) are all still in today's list.
Residual error lives only in the denominator and is bounded, one-sided, decaying.

Definitional caveat: W50 is blind to ranks 51-100 (~10-15% of total cap). When
that tail swells (e.g. the 2021-22 retail small-cap episode) true W100 falls while
W50 barely moves. Read W50 as "concentration within the large/mid-cap core".

Inputs : data/bist_isyatirim_monthly.csv  (from fetch_bist_isyatirim.py — shared)
Outputs: data/bist_concentration_top50.csv
         bist_concentration_top50.html
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
TOP_N = 10        # numerator
TOP_DENOM = 50    # fixed denominator basis

# Short-name map for symbols that reach the top 10 over the window.
NAMES = {
    "GARAN": "Garanti", "AKBNK": "Akbank", "ISCTR": "İş Bankası",
    "YKBNK": "Yapı Kredi", "VAKBN": "Vakıfbank", "HALKB": "Halkbank",
    "KCHOL": "Koç Holding", "SAHOL": "Sabancı Holding", "THYAO": "T. Hava Yolları",
    "ASELS": "Aselsan", "BIMAS": "BİM", "EREGL": "Ereğli D. Çelik",
    "TUPRS": "Tüpraş", "FROTO": "Ford Otosan", "TCELL": "Turkcell",
    "SISE": "Şişecam", "SASA": "Sasa Polyester", "PGSUS": "Pegasus",
    "TOASO": "Tofaş", "ENKAI": "Enka İnşaat", "TTKOM": "Türk Telekom",
    "ASTOR": "Astor Enerji", "CCOLA": "Coca-Cola İçecek", "MGROS": "Migros",
    "DSTKF": "Destek Faktoring", "KLRHO": "Kiler Holding",
}


def load_clean() -> pd.DataFrame:
    df = pd.read_csv(DATA / "bist_isyatirim_monthly.csv", parse_dates=["date"])
    df = df.sort_values(["symbol", "date"])
    # Free-float ratio is a slow-moving fundamental; a centered 3-month rolling
    # median on the ratio removes single-month HAO_PD glitches while preserving
    # genuine level shifts. Raw nulls ffilled/bfilled first (PD is never null).
    df["ff_ratio_raw"] = df["ff_market_cap"] / df["market_cap"]
    df["ff_ratio_raw"] = df.groupby("symbol")["ff_ratio_raw"].ffill().bfill()
    med = df.groupby("symbol")["ff_ratio_raw"].transform(
        lambda s: s.rolling(3, center=True, min_periods=1).median())
    df["ff_ratio"] = med
    df["ff_mcap"] = df["market_cap"] * df["ff_ratio"]
    df["ym"] = df["date"].dt.to_period("M")
    return df


def compute(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for ym, g in df.groupby("ym"):
        g = g.dropna(subset=["ff_mcap"])
        n = g["symbol"].nunique()
        if n < TOP_DENOM:            # need a full top-50 to keep footing constant
            continue
        total = g["ff_mcap"].sum()                     # all members (for W100)
        d50 = g.nlargest(TOP_DENOM, "ff_mcap")         # denominator basis
        denom = d50["ff_mcap"].sum()
        top = g.nlargest(TOP_N, "ff_mcap")             # numerator
        num = top["ff_mcap"].sum()
        out.append({
            "ym": str(ym),
            "date": g["date"].max().strftime("%Y-%m-%d"),
            "n_universe": int(n),
            "top50_ff_mcap": denom,
            "total_ff_mcap": total,
            "top10_ff_mcap": num,
            "weight_top10_of_top50": num / denom,
            "weight_top10_of_total": num / total,      # the old, biased ratio
            "rho_top50_over_total": denom / total,      # T50 / T100
            "top10": ",".join(top["symbol"].tolist()),
        })
    return pd.DataFrame(out).sort_values("ym").reset_index(drop=True)


def verify(df: pd.DataFrame, res: pd.DataFrame) -> None:
    print("=== VERIFICATION (top-10-of-top-50) ===")
    thy = df[df.symbol == "THYAO"].tail(1).iloc[0]
    print(f"THYAO latest {thy['date'].date()}: ff_mcap={thy['ff_mcap']/1e6:,.0f} "
          f"mn TL (ratio {thy['ff_ratio']:.3f})  [anchor ~= 219,950]")
    print(f"Universe size: {res['n_universe'].iloc[0]} (first) -> "
          f"{res['n_universe'].iloc[-1]} (last); bench in worst year = "
          f"{res['n_universe'].min() - TOP_DENOM}")
    w50 = res["weight_top10_of_top50"]
    print(f"W50 (top10/top50): {w50.min():.1%} .. {w50.max():.1%}  "
          f"latest {w50.iloc[-1]:.1%}")
    # Survivorship-bias demonstration: W50 vs the old W100, by year.
    # In recent years (universe ~100) they should sit at a stable ratio rho;
    # in thin early years the OLD W100 balloons while W50 stays disciplined.
    r = res.copy()
    r["year"] = r["ym"].str[:4]
    by = r.groupby("year").agg(
        uni=("n_universe", "max"),
        w50=("weight_top10_of_top50", "mean"),
        w100=("weight_top10_of_total", "mean"),
        rho=("rho_top50_over_total", "mean")).reset_index()
    print("\n  year  universe   W50     W100    gap(W100-W50)   rho=T50/T100")
    for _, x in by.iterrows():
        print(f"  {x.year}    {int(x.uni):>3}    {x.w50:6.1%}  {x.w100:6.1%}   "
              f"{(x.w100 - x.w50):+6.1%}         {x.rho:.3f}")
    print("\n  READ CAREFULLY — the empirics corrected the a-priori story:")
    print("  * The W50/W100 gap = W50*(1-rho) = the VISIBLE 51+ tail weight, NOT")
    print("    survivorship. It is ~0 in 2016-19 (we see only ~65 names, so the")
    print("    top-50 is ~99% of visible cap) and widens to ~7pp by 2025 as the")
    print("    small-cap tail fills in. So the grey line does NOT run hot early.")
    print("  * W50 STILL shows the ~62% (2016-19) -> ~55% peak-and-fade: fixing")
    print("    the denominator did NOT erase it => the early concentration is")
    print("    LARGELY REAL, not a denominator-size artifact.")
    print("  * True survivorship bias lives in the ~35 names missing in 2016 (a")
    print("    tail we cannot see). It inflates the OLD of-total reading upward,")
    print("    but is NOT the visible gap. Estimate of the true 2016 of-total")
    print("    value = W50(2016) * rho_recent ~= 0.62 * 0.88 ~= 0.545, vs the")
    print("    naive 0.614 -> the old chart's 2016 point was ~6pp too high.")
    print(f"\nLatest top 10 ({res['date'].iloc[-1]}): {res['top10'].iloc[-1]}")


def render(res: pd.DataFrame) -> None:
    months = res["date"].tolist()
    w50 = [round(w * 100, 2) for w in res["weight_top10_of_top50"]]
    w100 = [round(w * 100, 2) for w in res["weight_top10_of_total"]]
    universe = res["n_universe"].tolist()

    strip_mask = res["ym"].str[5:7].isin(["01", "06"])
    strip = res[strip_mask]
    strip_labels = strip["ym"].tolist()
    strip_memberships = [row.split(",") for row in strip["top10"]]

    ever = []
    for m in strip_memberships:
        for s in m:
            if s not in ever:
                ever.append(s)

    payload = {
        "asof": months[-1],
        "months": months,
        "weights": w50,
        "weights_of_total": w100,
        "universe": universe,
        "strip_labels": strip_labels,
        "memberships": strip_memberships,
        "ever": ever,
        "names": {s: NAMES.get(s, s) for s in ever},
    }
    tmpl = (BASE / "concentration_top50_template.html").read_text()
    html = tmpl.replace("__PAYLOAD__", json.dumps(payload))
    (BASE / "bist_concentration_top50.html").write_text(html)
    print(f"\nWrote bist_concentration_top50.html ({len(months)} months)")


def main() -> None:
    df = load_clean()
    res = compute(df)
    res.to_csv(DATA / "bist_concentration_top50.csv", index=False)
    print(f"Saved {len(res)} monthly rows -> data/bist_concentration_top50.csv\n")
    verify(df, res)
    render(res)


if __name__ == "__main__":
    main()
