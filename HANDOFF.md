# Rotation Observatory + BIST Concentration — Project Handoff

Context for a coding agent picking this up. Two related deliverables live in
`~/Desktop/compstrategy/rotation_observatory/`. Part A (US sector/factor rotation
dashboard) is **done and working**. Part B (Borsa İstanbul index-concentration
chart) is **mid-build, blocked on a data pull** — that's where you come in.

---

## Part A — US Rotation Observatory (COMPLETE, reference implementation)

A descriptive, no-signals dashboard for spotting US sector/factor rotation.

**Files**
- `observatory.py` — engine. Reads `data/raw_prices.csv` (weekly closes),
  computes JdK-style RS-Ratio / RS-Momentum vs SPY, writes `observatory.db`
  (SQLite snapshot history) and `report.html` (from `template.html`).
- `template.html` — the view: dual-axis-safe stacked panels, RRG quadrant chart
  with trails, multi-timeframe relative-strength heatmap, quadrant timeline,
  market-context panel (SPY+QQQ indexed / sector ratio lines / cap-vs-equalweight
  spread) with user date pickers.
- `fetch_prices.py` — the data pull. `./.venv/bin/python fetch_prices.py [--years N]`.
- `data/raw_prices.csv` — weekly closes, now **260 bars (5y, 2021-08 → present)**
  for 20 tickers: SPY, QQQ, **all 11 GICS sector SPDRs**, 4 equal-weight twins
  RSPT/RSPG/RSPF/RSPH, 3 factor ETFs IWD/IWF/MTUM. `observatory.py` still plots
  only 4 sectors (`SECTORS`); the other 7 are already in the CSV, so extending
  is a config edit, not another fetch.

**Key methodology decisions (keep these)**
- RS-Ratio = 100 · RS / SMA(RS, 26) where RS = 100·sector/benchmark — the
  relative-strength line as a PERCENT of its own 26-week average.
  RS-Momentum = 100 + (RS-Ratio − RS-Ratio 8 weeks ago), i.e. the derivative of
  the X axis. Quadrants: Leading/Weakening/Lagging/Improving.
  **Replaced (2026-08-14) `100 + zscore(rs, 10)` / `100 + zscore(diff(zscore), 10)`**
  for two measured reasons: (a) the z-score divided each symbol by its own
  volatility, and the RS line's sd ran 0.370 (XLF) to 2.215 (MTUM) — a 6x
  spread — so equal positions on a chart built for cross-symbol comparison
  meant unequal moves; (b) w=10 was the worst window tested, rank agreement
  with actual trailing relative performance 0.53 vs 0.83 at w=26. The momentum
  axis was three transformations deep and mostly noise.
- **The quadrants have not led anything.** Over 227 weeks × 7 symbols, forward
  13-week relative return averaged −0.7pp from *Leading* and +0.7pp from
  *Lagging* — mild mean reversion, stable in sign across every momentum window
  tried (4/8/13). Small effect, one 5-year sample, overlapping windows. It is
  stated in the dashboard's caveat box. Keep the tool descriptive; do not bolt
  a signal onto it without testing far more than this.
- Snapshots are stamped with the method (`meta` table). Changing WINDOW /
  MOM_WINDOW / normalization wipes and rebuilds the history, because a longer
  warm-up otherwise leaves old-formula rows under new ones in the same table —
  which is exactly what happened on this change (14 weeks survived).
- Weekly bars. Persist computed signals (not prices) — history is the asset.
- SQLite on a network-mounted folder throws "disk I/O error"; the code works on
  a `/tmp` copy and syncs back (see `db_connection`). Preserve that.

**Stress harness.** `./.venv/bin/python stress_observatory.py` — 11 synthetic
cases plus a real-data logic check. It separates *invariants* (must hold for any
input: no NaN/inf, the quadrant must be derivable from the plotted coordinates,
a symbol that IS the benchmark sits exactly at the origin) from *logic* (a
steady outperformer must read above 100 and stay there). Run it after touching
`compute_rrg`. It caught the rounding-order bug described below.

**Horizon labelling (added 2026-08-14).** Every panel states its own lookback,
read from `D.config` in the payload — change `WINDOW`/`HEATMAP_PERIODS` in
`observatory.py` and the labels follow, so they cannot drift out of date. This
exists because the RRG (rolling `WINDOW`-week normalisation) and the heatmap
(plain 1/4/13-week cumulative) measure different horizons and *will* rank
sectors differently whenever relative strength turns — which reads as a bug
unless the page says otherwise. The RRG also carries a standing caveat that 100
means "in line with its own last N weeks", not "in line with SPY", since a
per-symbol z-score sits above its mean ~half the time whatever the symbol does
outright. The quadrant strip is capped at `TIMELINE_WEEKS` (52) and scrolls
inside its own box; at 241 weeks it was ~2,400px wide.

**Known simplifications / TODO for Part A**
- **Thematic ETFs were tried and removed (2026-08-15).** MAGS / SMH / IGV were
  added, then taken out: they crowded the chart. x and y share one range, and
  SMH's momentum of 70.8 (a real −14.3% relative 8-week move) stretched it to
  ~70–120, squashing the eleven sectors into the middle. Equal scaling is
  deliberate — a trail's rotation only reads correctly if both axes scale alike
  — so the outlier costs space rather than being clipped. If revisiting: MAGS
  (102.6) and IGV (115.1) sat inside the normal range and did NOT cause the
  problem; SMH alone did. Note also that these overlap the sectors (SMH/IGV are
  slices of XLK, MAGS straddles XLK/XLY/XLC), so the cross-section stops being
  a partition and must not be averaged across.
- ~~Only 4 sectors plotted~~ — all 11 GICS sectors now in `SECTORS`
  (14 series with the factor ETFs). Equal-weight twins still only exist for
  XLK/XLE/XLF/XLV, so the cap-vs-EW spread panel still covers those four; add
  RSPN/RSPD/RSPS/RSPU/RSPM/RSPR/RSPC to `fetch_prices.py` to widen it.
- ~~Short normalization window makes early quadrants jumpy~~ — fixed (w=26).
  Quadrant membership still turns over ~23% of weeks; that is the nature of a
  7-symbol cross-section, not a parameter problem.
- Add the "dual RRG" (fast daily + slow weekly) discussed but not built.
- Optional: daily ~23:30 TRT scheduled refresh; dispersion gauge; rate overlay.

**Data provenance (changed 2026-08-14).** Prices no longer come from `Borsa_MCP`.
`fetch_prices.py` pulls them from yfinance into `./.venv` — self-contained, no
MCP, no API key, re-runnable. Three choices baked into it, all deliberate:
  * pulls DAILY and resamples to W-FRI locally, so every bar is a Friday close
    and the in-progress week is dropped (an RRG reads the newest bar, so a
    half-week there is the one place a partial number does real damage);
  * `auto_adjust=True` — total-return series. On price-only data the high-yield
    sectors (XLE, XLF) look permanently weaker than they are, and every RRG
    number is a ratio of two such series;
  * fetches a superset of what the engine plots, so widening the universe never
    needs another fetch.

---

## Part B — BIST Index Concentration (COMPLETE as of 2026-07-21)

**Status: built and verified.** `fetch_bist_isyatirim.py` pulls all 100 XU100
names (now **10y** daily via `YEARS_BACK=10`, 0 failures), `bist_concentration.py`
computes W(t) + renders `bist_concentration.html`. Latest reading **48.6%**.
See the "RESOLUTION LOG" at the bottom of this file for exactly what was fixed.

**10-year survivorship caveat (important):** the universe (today's XU100 applied
historically) grows from **65 to 100** members over the 10y window because current
constituents listed over time. A thinner early pool mechanically inflates the
top-10 share (10-of-65 > 10-of-100), so pre-2021 readings (~58–63%) overstate true
concentration and the decline toward ~48% is partly the universe filling out. The
chart now plots universe size (dashed gold, right axis) so this is visible; the
caveat text spells it out. Recent (near-100-member) years are the clean signal.
Revert to 5y anytime by setting `YEARS_BACK=5` and re-running both scripts.

---

## Part B — BIST Index Concentration (original brief, for reference)

Goal: reproduce JPMorgan's "Weight of the top 10 companies in the S&P 500" chart
(`% of total market cap`) but for **Borsa İstanbul / XU100**, ~5 years, monthly.
**Market cap only** for now (earnings-share version explicitly deferred — Turkish
inflation accounting TMS-29 makes earnings a regime-break minefield).

### The formula (settled)
It is a **cross-sectional statistic recomputed each date** — NOT a tracked basket.
No entry/exit logic. At each month t:
1. Universe U(t) = XU100 members.
2. mcap_i(t) for each.
3. Sort desc, take the 10 largest **on that date**.
4. **W(t) = Σ mcap(top-10 on date t) / Σ mcap(all U(t))**.

Also store per-date top-10 identities (a "who was in the top 10" timeline strip —
BIST's banks→defense/aviation shift over 5y is half the story).

### Weighting basis (settled)
Use **free-float market cap** (what BIST actually index-weights on), not full
mcap. This is the crucial correction — it's why the naive approach was unreliable.

### Data source (settled after investigation)
**İş Yatırım** (isyatirim.com.tr) — free, the Turkish-analyst standard. Its
company endpoint returns market cap AND free-float market cap as columns, with
history. Validated on THYAO: Piyasa Değeri 438,150 mn TL, float 50.2%, paid
capital 1,380 mn → free-float mcap ≈ 219,950 mn TL. Internally consistent
(share count 1.38bn matched an independent MCP derivation).

Rejected alternatives: Borsa İstanbul official (authoritative but historical
archive is paid); TradingView/Investing.com (current only, no clean history);
the `Borsa_MCP` tool (mixes non-XU100 names, full mcap not float, snapshot only,
reverse-engineered shares — four stacked approximations).

### THE BLOCKER (your first task)
`fetch_bist_isyatirim.py` pulls 5y for all 100 XU100 names from İş Yatırım's
`HisseTekSirket` AJAX endpoint. Current status of the endpoint call:
- First attempt: `401 Unauthorized`.
- Diagnosis: it's an ASP.NET AJAX page-method — needs `X-Requested-With:
  XMLHttpRequest` **and** session cookies from a prior real page visit.
- Latest edit added a `requests.Session`, a `prime_session()` that GETs a normal
  page first for cookies, the AJAX header, and a 401-retry-after-reprime. **This
  has NOT been re-run/confirmed yet** — verifying it clears the 401 is step one.

If the session+header fix still 401s, fallbacks in priority order:
1. Inspect a real browser request to the endpoint (DevTools → Network) and copy
   the exact headers/cookies it sends; replicate.
2. Use the `isyatirimhisse` PyPI library's own request path as reference (it was
   updated Feb 2026, so a working method exists).
3. Borsa İstanbul official daily files for a shorter/again window.

The script saves **every column** the endpoint returns to
`data/bist_isyatirim_raw.csv` (audit trail) plus a tidy month-end
`data/bist_isyatirim_monthly.csv`. Column auto-map guesses:
date=`HGDG_TARIH`, close=`HGDG_KAPANIS`, capital=`SERMAYE`,
market_cap=`PD`, free_float_mcap=`HAO_PD`. **Verify these names against the
printed `Raw columns` list** — they're educated guesses, not confirmed.

Environment note: user's Mac has `python3`/`pip3` (not `python`/`pip`). Harmless
LibreSSL urllib3 warning appears. Be polite to İş Yatırım (the script sleeps
~1.2s/request; ~5–10 min total; don't parallelize aggressively → IP-block risk).

### After the data lands (remaining Part B build)
1. Compute W(t) monthly from free-float mcap; store top-10 identities per date.
2. **Verify**: THYAO free-float mcap anchor ≈ 219,950 mn TL at latest date;
   sum-of-XU100 sanity; check a known bedelsiz event doesn't create a cap jump
   (share adjustments should be smooth in float mcap).
3. Render: W(t) line (5y) + top-10 membership timeline strip. Match the JPM look
   (single clean line, % axis). Reuse `template.html` patterns.
4. Footnote survivorship (using today's XU100 list historically — small effect
   on a top-10/total ratio, but state it).

### Deferred (do NOT build yet)
Earnings-share version (TMS-29 inflation-accounting break; banks exempt →
apples-to-oranges). Free-float vs full-cap toggle. HHI. Banks-vs-rest split.

---

## File inventory
```
observatory.py               Part A engine (done)
template.html                Part A view (done)
report.html                  Part A generated output
observatory.db               Part A SQLite history
data/raw_prices.csv          Part A US weekly closes
fetch_bist_isyatirim.py      Part B extractor (WORKING — HisseTekil endpoint)
bist_concentration.py        Part B compute + render (done)
concentration_template.html  Part B view template (done)
bist_concentration.html      Part B generated output — the deliverable
data/bist_isyatirim_raw.csv      112k raw daily rows, all 32 endpoint columns
data/bist_isyatirim_monthly.csv  5,479 month-end rows, tidy
data/bist_concentration.csv      61 monthly W(t) rows + top-10 identities
HANDOFF.md                   this file
```

## XU100 constituents (pull date reference)
Embedded in `fetch_bist_isyatirim.py` as the `XU100` list (100 tickers).
Source: Borsa_MCP `get_index_data(XU100, include_components=True)`.

---

## RESOLUTION LOG (2026-07-21) — how Part B was unblocked and finished

**1. The 401 was the wrong endpoint name, not an auth problem.**
The script was calling `HisseTekSirket`, which returns `401 UNAUTHORIZED` even
from a real browser session with valid cookies (confirmed via DevTools). The
correct endpoint is **`HisseTekil`** — the same path the maintained
`isyatirimhisse` PyPI lib uses. It is a **plain public GET**: no session, no
cookies, no `X-Requested-With`. All the priming/session machinery was deleted.
A single 5-year request per symbol returns ~1,250 daily rows in <1s, so date
chunking was also removed.

**2. Columns confirmed from a live pull (the earlier guesses were right):**
`HGDG_TARIH`=date, `HGDG_KAPANIS`=adjusted close, `SERMAYE`=paid capital,
`PD`=full mcap, **`HAO_PD`=free-float mcap** (the weighting basis). Also present:
`PD_USD`, `HAO_PD_USD`, `HG_KAPANIS` (raw close; note `PD = SERMAYE × HG_KAPANIS`).

**3. Free-float mcap reconstruction (important correctness fix).**
`HAO_PD` is occasionally null on a given day (196/5,479 month-ends, ~3.6%) — and
critically it was null on the **latest** date for some mega-caps incl. **ASELS**
(the single largest free-float name, ~424 bn TL) and EREGL. Naively taking raw
`HAO_PD` would have dropped ASELS from the latest top 10 entirely. Fix: compute
`ff_ratio = HAO_PD/PD`, forward/back-fill it per symbol, then
`ff_mcap = PD × ff_ratio` (PD is never null). The free-float *ratio* is the
slow-moving fundamental; PD carries the daily price move.

**4. Single-month HAO_PD glitches removed with a 3-month centered rolling median
on the ratio.** Some symbols show a one-month spike that reverts (e.g. AEFES
2025-06 float-ratio reads 0.047 vs its steady 0.328; ALTNY 2025-12 reads 0.135
vs 0.40). A centered `rolling(3).median()` on the ratio kills these while
preserving genuine sustained level shifts (real secondary offerings persist
across ≥2 of 3 window points, e.g. GLRMK 0.12→0.32 in 2026-04). None of the
symbols with residual ratio jumps is ever in the top 10, so the numerator is
clean and only the denominator is marginally affected.

**Verification passed:** THYAO latest ff-mcap = 219,842 mn TL (anchor ≈219,950 ✓);
universe grows 72→100 (survivorship, footnoted in the HTML); W(t) 44.8–52.1%,
latest 48.6%; DSTKF legitimately top-10 (huge full cap, stable 0.25 float);
distinct 5y top-10 members are all mega-caps (banks + ASELS/THYAO/TUPRS/ASTOR/
SASA/EREGL/KCHOL…), showing the banks→defence/aviation/industrials shift.

**To regenerate:** `python3 fetch_bist_isyatirim.py` (~4 min, polite) then
`python3 bist_concentration.py`. View: serve the folder
(`python3 -m http.server 8731`) and open `bist_concentration.html` — it loads
Chart.js from CDN, so `file://` won't work; use the local server.

### Remaining polish (optional, all deferred items still stand)
- Month labels under the membership strip are sparse/clipped; the line-chart
  x-axis carries the dates, so it's cosmetic.
- Deferred as before: earnings-share version (TMS-29), full-cap toggle, HHI,
  banks-vs-rest split. Part A TODOs (all 11 sectors, dual RRG) also unchanged.
