# Rotation Observatory

A descriptive US sector/factor rotation dashboard: JdK-style Relative Rotation
Graph, a relative-performance heatmap, a market-context panel and a quadrant
timeline — all measured against SPY on weekly bars.

**No signals.** See "How to read it" below; the quadrants have not been leading
indicators over the measured sample, and the page says so.

Live: published as a Render static site from `public/index.html`.

---

## Deploying (one-time)

1. **Create the GitHub repo** and push this folder:
   ```bash
   git remote add origin git@github.com:<you>/rotation-observatory.git
   git push -u origin main
   ```
2. **On Render:** New + → *Blueprint* → connect the repo. It reads `render.yaml`
   and creates a **static site**, which is free and separate from the Takibimde
   web service — no new instance cost. There is no build step: Render only
   serves the committed `public/index.html`.
3. **Enable the weekly refresh:** nothing to do — `.github/workflows/refresh.yml`
   runs every Saturday 06:00 UTC, regenerates the page, and pushes. Render
   auto-deploys on that push. Trigger it by hand any time from the repo's
   *Actions* tab → *refresh* → *Run workflow*.

Deliberately **not** a Render Cron Job: those are a paid service type, and the
same job runs free in Actions.

## Rebuilding locally

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python fetch_prices.py --years 5   # ~30s, writes data/raw_prices.csv
./.venv/bin/python observatory.py              # writes report.html + observatory.db
./.venv/bin/python stress_observatory.py       # 12 checks, must pass
cp report.html public/index.html               # what actually gets served
```

`report.html` loads Chart.js from a CDN, so opening it via `file://` will not
render. Serve the folder instead:

```bash
python3 -m http.server 8731
```

## How to read it

* **RS-Ratio (x)** — the SPY-relative strength line as a *percent of its own
  26-week average*. 103 = 3% above it. It is **not** "3% ahead of SPY": a sector
  can sit above 100 while still trailing SPY outright.
* **RS-Momentum (y)** — the change in RS-Ratio over 8 weeks.
* **Quadrants** — Leading (strong, improving), Weakening (strong, fading),
  Lagging (weak, still falling), Improving (weak, turning up).
* **The heatmap is the literal panel.** It is plain cumulative return minus
  SPY's over 1/4/13 weeks, with no normalisation. When it and the RRG rank
  sectors differently, they are answering different questions over different
  horizons — neither is wrong.

**Measured caveat:** over 227 weeks × 7 symbols, sectors in *Leading* went on to
underperform SPY over the following 13 weeks by ~0.7pp on average, and *Lagging*
ones outperformed by about the same — mild mean reversion, stable in sign across
every momentum window tried. Small effect, one 5-year sample. Treat this as a
map of what has already happened, not a forecast.

## Files

| File | Role |
|---|---|
| `fetch_prices.py` | Pulls daily closes (yfinance), resamples to Friday weekly, drops the in-progress week |
| `observatory.py` | Engine: RS-Ratio / RS-Momentum, SQLite snapshot store, renders `report.html` |
| `template.html` | The view — RRG, heatmap, context panel, quadrant timeline |
| `stress_observatory.py` | 12 checks: invariants + whether the output means anything |
| `public/index.html` | The published page (a copy of `report.html`) |
| `HANDOFF.md` | Full methodology history and why each decision was made |

`bist_concentration*.py` and `fetch_bist_isyatirim.py` are a separate, finished
project (BIST index concentration) that shares this folder. They are not part of
the published site.
