"""
BIST Index Concentration — "Weight of the top 10 in XU100" (free-float mcap).

Reproduces JPMorgan's "Weight of the top 10 companies in the S&P 500" chart,
but for Borsa Istanbul. It is a CROSS-SECTIONAL statistic recomputed each month
(NOT a tracked basket): at each month t,

    U(t)  = XU100 members with data that month
    W(t)  = sum(free-float mcap of the 10 largest on date t)
            -------------------------------------------------
                  sum(free-float mcap of all of U(t))

Weighting basis is FREE-FLOAT market cap (HAO_PD) — what BIST actually
index-weights on — reconstructed as  PD * ffill(HAO_PD / PD)  so the handful
of days where the endpoint omits HAO_PD are filled from the slow-moving
free-float ratio (PD is always present).

Inputs : data/bist_isyatirim_monthly.csv  (from fetch_bist_isyatirim.py)
Outputs: data/bist_concentration.csv       W(t) series + top-10 list per month
         bist_concentration.html           the JPM-style chart + membership strip

Survivorship note: the universe is today's XU100 applied historically, so
recently-listed names are absent early and a few delisted names are missing.
For a top-10 / total ratio the effect is small (missing names are small caps
that sit in neither the numerator nor much of the denominator). Footnoted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
TOP_N = 10

# Short-name map for symbols that actually reach the top 10 over the window.
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
    # Free-float ratio is a slow-moving fundamental. The endpoint occasionally
    # emits a single-month glitch in HAO_PD (e.g. AEFES 2025-06 reads 0.047 vs
    # its steady 0.328; ALTNY 2025-12 reads 0.135 vs 0.40) that reverts the next
    # month. A centered 3-month rolling median on the ratio removes such spikes
    # while preserving genuine level shifts (secondary offerings persist across
    # months, so 2 of 3 window points carry the new level). Raw nulls are
    # ffilled/bfilled first (PD itself is never null), then PD * ratio is used.
    df["ff_ratio_raw"] = df["ff_market_cap"] / df["market_cap"]
    df["ff_ratio_raw"] = df.groupby("symbol")["ff_ratio_raw"].ffill().bfill()
    med = df.groupby("symbol")["ff_ratio_raw"].transform(
        lambda s: s.rolling(3, center=True, min_periods=1).median())
    df["ff_ratio"] = med
    df["ff_mcap"] = df["market_cap"] * df["ff_ratio"]
    # month period key so symbols with slightly different month-end dates align
    df["ym"] = df["date"].dt.to_period("M")
    return df


def compute(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for ym, g in df.groupby("ym"):
        g = g.dropna(subset=["ff_mcap"])
        if g.empty:
            continue
        total = g["ff_mcap"].sum()
        top = g.nlargest(TOP_N, "ff_mcap")
        out.append({
            "ym": str(ym),
            "date": g["date"].max().strftime("%Y-%m-%d"),
            "n_universe": int(g["symbol"].nunique()),
            "total_ff_mcap": total,
            "top10_ff_mcap": top["ff_mcap"].sum(),
            "weight_top10": top["ff_mcap"].sum() / total,
            "top10": ",".join(top["symbol"].tolist()),
        })
    return pd.DataFrame(out).sort_values("ym").reset_index(drop=True)


def verify(df: pd.DataFrame, res: pd.DataFrame) -> None:
    print("=== VERIFICATION ===")
    # 1. THYAO free-float mcap anchor ~= 219,950 mn TL at latest date
    thy = df[df.symbol == "THYAO"].tail(1).iloc[0]
    print(f"THYAO latest {thy['date'].date()}: "
          f"ff_mcap={thy['ff_mcap']/1e6:,.0f} mn TL "
          f"(ratio {thy['ff_ratio']:.3f})  [anchor ~= 219,950]")
    # 2. universe size over time (survivorship visibility)
    print(f"Universe size: {res['n_universe'].iloc[0]} (first) -> "
          f"{res['n_universe'].iloc[-1]} (last)")
    # 3. W(t) range
    print(f"W(top10): {res['weight_top10'].min():.1%} .. "
          f"{res['weight_top10'].max():.1%}  "
          f"latest {res['weight_top10'].iloc[-1]:.1%}")
    # 4. smoothness — a bedelsiz (bonus issue) must NOT create a cap jump in
    #    float mcap. Flag any symbol whose ff_mcap jumps >40% MoM while price
    #    (close) moved <15% — that would signal a share-count artifact.
    d = df.sort_values(["symbol", "date"]).copy()
    d["mc_chg"] = d.groupby("symbol")["ff_mcap"].pct_change()
    d["px_chg"] = d.groupby("symbol")["close"].pct_change()
    art = d[(d["mc_chg"].abs() > 0.40) & (d["px_chg"].abs() < 0.15)]
    print(f"Potential share-count artifacts (mcap jump >40%, price <15%): "
          f"{len(art)} rows")
    if len(art):
        print("  (adjusted close is used, so splits/bonus issues should cancel; "
              "review if this is large)")
        print(art[["symbol", "date", "mc_chg", "px_chg"]].head(8).to_string(index=False))
    # 5. latest top 10
    print(f"\nLatest top 10 ({res['date'].iloc[-1]}): {res['top10'].iloc[-1]}")


def render(res: pd.DataFrame) -> None:
    # Line chart stays monthly (smooth W(t)); the membership strip is sampled
    # twice a year to stay readable: January (start of year) and June (end of H1).
    months = res["date"].tolist()
    weights = [round(w * 100, 2) for w in res["weight_top10"]]
    universe = res["n_universe"].tolist()

    strip_mask = res["ym"].str[5:7].isin(["01", "06"])
    strip = res[strip_mask]
    strip_labels = strip["ym"].tolist()          # "YYYY-MM" is enough here
    strip_memberships = [row.split(",") for row in strip["top10"]]

    # distinct names that appear in the shown snapshots, for the colour legend
    ever = []
    for m in strip_memberships:
        for s in m:
            if s not in ever:
                ever.append(s)

    payload = {
        "asof": months[-1],
        "months": months,
        "weights": weights,
        "universe": universe,
        "strip_labels": strip_labels,
        "memberships": strip_memberships,
        "ever": ever,
        "names": {s: NAMES.get(s, s) for s in ever},
    }
    tmpl = (BASE / "concentration_template.html").read_text()
    html = tmpl.replace("__PAYLOAD__", json.dumps(payload))
    (BASE / "bist_concentration.html").write_text(html)
    print(f"\nWrote bist_concentration.html ({len(months)} months)")


def main() -> None:
    df = load_clean()
    res = compute(df)
    res.to_csv(DATA / "bist_concentration.csv", index=False)
    print(f"Saved {len(res)} monthly rows -> data/bist_concentration.csv\n")
    verify(df, res)
    render(res)


if __name__ == "__main__":
    main()
