"""
BIST concentration data extractor — run this LOCALLY on your machine.

Pulls ~5 years of daily data for every current XU100 constituent from
Isyatirim's public company endpoint (HisseTekil), which returns market cap
(PD) AND free-float market cap (HAO_PD) as columns. Saves two files into
./data/:

  data/bist_isyatirim_raw.csv     every column the endpoint returns (audit trail)
  data/bist_isyatirim_monthly.csv month-end rows, tidy, ready for the dashboard

Endpoint notes
- The correct endpoint is HisseTekil (NOT HisseTekSirket, which 401s). It is a
  plain public GET — no session, cookies, or X-Requested-With header needed.
  This is the same path the maintained `isyatirimhisse` PyPI library uses.
- A single 5-year request per symbol returns ~1250 daily rows in <1s, so no
  date chunking is necessary.
- Columns confirmed from a live pull:
    HGDG_TARIH   date (dd-mm-yyyy)
    HGDG_KAPANIS split/dividend-adjusted close
    HG_KAPANIS   raw close (PD = SERMAYE * HG_KAPANIS)
    SERMAYE      paid capital (share count)
    PD           full market cap
    HAO_PD       free-float market cap  <-- the weighting basis we want
    PD_USD, HAO_PD_USD  USD equivalents

USAGE
    pip3 install requests pandas
    python3 fetch_bist_isyatirim.py

- Be polite: there is a deliberate delay between requests. Do not lower it a lot.
- Isyatirim has had SSL quirks; if you hit SSL errors, `pip3 install truststore`
  and the script will verify properly; otherwise it falls back to unverified.
- If a few symbols fail, the script keeps going and lists them at the end.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

try:  # optional: fixes Isyatirim SSL chain on some systems
    import truststore
    truststore.inject_into_ssl()
    SSL_VERIFY = True
except Exception:
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    SSL_VERIFY = False

import pandas as pd

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)

ENDPOINT = ("https://www.isyatirim.com.tr/_layouts/15/Isyatirim.Website/"
            "Common/Data.aspx/HisseTekil")
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
}

YEARS_BACK = 10
SLEEP_BETWEEN = 1.2       # seconds between symbols — keep this polite
RETRIES = 3

# Current XU100 constituents (as of the pull date). Survivorship is footnoted
# in the dashboard; for a top-10 concentration measure the effect is small.
XU100 = [
    "AEFES","AKBNK","AKSA","AKSEN","ALARK","ALTNY","ANSGR","ARCLK","ASELS","ASTOR",
    "BALSU","BERA","BIMAS","BRSAN","BRYAT","BSOKE","BTCIM","CANTE","CCOLA","CIMSA",
    "CVKMD","CWENE","DAPGM","DOAS","DOHOL","DSTKF","ECILC","EFOR","EKGYO","ENERY",
    "ENJSA","ENKAI","EREGL","ESEN","EUPWR","EUREN","FENER","FROTO","GARAN","GENIL",
    "GESAN","GLRMK","GRSEL","GRTHO","GSRAY","GUBRF","HALKB","HEKTS","IEYHO","ISCTR",
    "ISMEN","IZENR","KCHOL","KLRHO","KRDMD","KTLEV","KUYAS","MAGEN","MAVI","MGROS",
    "MIATK","MPARK","OBAMS","ODAS","ODINE","OTKAR","OYAKC","PAHOL","PASEU","PATEK",
    "PETKM","PGSUS","PSGYO","QUAGR","RALYH","REEDR","SAHOL","SARKY","SASA","SISE",
    "SKBNK","SOKM","TAVHL","TCELL","THYAO","TKFEN","TOASO","TRALT","TRENJ","TRMET",
    "TSKB","TTKOM","TUKAS","TUPRS","TURSG","ULKER","VAKBN","VESTL","YKBNK","ZOREN",
]


def fetch_symbol(sym: str) -> pd.DataFrame:
    end = datetime.today()
    start = end - timedelta(days=365 * YEARS_BACK)
    params = {
        "hisse": sym,
        "startdate": start.strftime("%d-%m-%Y"),
        "enddate": end.strftime("%d-%m-%Y"),
    }
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(ENDPOINT, params=params, headers=HEADERS,
                             timeout=60, verify=SSL_VERIFY)
            r.raise_for_status()
            rows = r.json().get("value", [])
            df = pd.DataFrame(rows)
            if not df.empty:
                df.insert(0, "symbol", sym)
            return df
        except Exception as e:
            if attempt == RETRIES:
                print(f"  ! {sym} failed: {e}")
                return pd.DataFrame()
            time.sleep(SLEEP_BETWEEN * attempt)
    return pd.DataFrame()


def main() -> None:
    all_frames, failed = [], []
    for i, sym in enumerate(XU100, 1):
        print(f"[{i:>3}/{len(XU100)}] {sym} ...", flush=True)
        df = fetch_symbol(sym)
        if df.empty:
            failed.append(sym)
        else:
            all_frames.append(df)
        time.sleep(SLEEP_BETWEEN)

    if not all_frames:
        sys.exit("No data fetched — check network / endpoint reachability.")

    raw = pd.concat(all_frames, ignore_index=True)
    raw.to_csv(DATA / "bist_isyatirim_raw.csv", index=False)
    print(f"\nRaw columns returned by endpoint:\n  {list(raw.columns)}")
    print(f"Saved {len(raw)} raw rows -> data/bist_isyatirim_raw.csv "
          f"({raw.symbol.nunique()} symbols)")

    # --- tidy pass; column names confirmed from a live pull ---
    colmap = {c.upper(): c for c in raw.columns}
    def pick(*cands):
        for c in cands:
            if c in colmap:
                return colmap[c]
        return None

    date_c = pick("HGDG_TARIH", "TARIH")
    close_c = pick("HGDG_KAPANIS", "KAPANIS")
    pd_c = pick("PD", "PIYASADEGERI")
    haopd_c = pick("HAO_PD", "HAOPD")
    cap_c = pick("SERMAYE")

    if date_c and (pd_c or haopd_c):
        keep = [c for c in (close_c, cap_c, pd_c, haopd_c) if c]
        t = raw[["symbol", date_c] + keep].copy()
        t.columns = (["symbol", "date"] +
                     [n for n, c in (("close", close_c), ("paid_capital", cap_c),
                                     ("market_cap", pd_c), ("ff_market_cap", haopd_c))
                      if c])
        t["date"] = pd.to_datetime(t["date"], format="%d-%m-%Y", errors="coerce")
        t = t.dropna(subset=["date"]).sort_values(["symbol", "date"])
        # month-end snapshot per symbol
        t["ym"] = t["date"].dt.to_period("M")
        monthly = t.groupby(["symbol", "ym"]).tail(1).drop(columns="ym")
        monthly.to_csv(DATA / "bist_isyatirim_monthly.csv", index=False)
        print(f"Saved {len(monthly)} month-end rows -> "
              f"data/bist_isyatirim_monthly.csv")
        # sanity print — THYAO free-float mcap anchor ~= 219,950 mn TL
        for s in ("THYAO", "ASELS", "GARAN"):
            last = monthly[monthly.symbol == s].tail(1)
            if not last.empty:
                rec = last.to_dict("records")[0]
                ff_mn = rec.get("ff_market_cap", float("nan")) / 1e6
                print(f"  {s} latest {rec['date'].date()}: "
                      f"ff_mcap={ff_mn:,.0f} mn TL")
    else:
        print("!! Could not auto-map columns — check the raw column list above.")

    if failed:
        print(f"\nFailed symbols ({len(failed)}): {failed}")
        print("Re-run to retry (single request per symbol, safe to repeat).")


if __name__ == "__main__":
    main()
