# Imbalance Analysis

Analysis of Dutch (TenneT) and French (RTE) imbalance prices against day-ahead prices, plus consumption and solar
profiles, delivered as static HTML infographics with a built-in test page and PNG/PPTX export. Not an app: a folder
of Python scripts, JSON results and static pages. All data ends 31 Dec 2025.

## Run

```bash
cd imbalance_analysis
python3 serve.py              # http://localhost:8765/infographic_dayahead.html
python3 test_infographic.py   # recomputes the checked page values from the raw CSVs; expect 912/912
```

- Python 3.9+ standard library only, except `nl_daily_export.py`, which needs numpy (`requirements.txt`).
- Every script switches to its own folder on start-up, so it can be run from anywhere.
- `serve.py` is a small threaded `http.server` (threaded on purpose: Chrome's idle pre-opened sockets hang a
  single-threaded one). Its `POST /run-tests` powers the page's "Run Tests Now" button.
- The page's PNG/PPTX export buttons load html2canvas and pptxgenjs from a CDN, so they need internet.

## Data

- `data/tennet/settlement_prices_*.csv`: NL imbalance, TenneT settlement prices, one file per year, 15-minute ISPs.
  Price Surplus = feed-in (long), Price Shortage = offtake (short). 2021–24 are `;`-delimited, 2025 `,`.
  Times are Dutch local time including summer time (92/100 ISPs on the DST days).
- `data/entsoe/YYYY_MM_EnergyPrices_12.1.D_r3.csv`: day-ahead prices from the ENTSO-E File Library (table 12.1.D),
  cut down to the NL and FR rows (the originals cover all of Europe; the format is unchanged). Hourly until
  30 Sep 2025, 15-minute (PT15M) from 1 Oct 2025.
- `FR_imbalance_data_YYYY_MM.csv`, `FR_prices_YYYY_MM.csv` (this folder): French imbalance data from the RTE API.

### Adding newer data

- NL imbalance: export settlement prices from tennet.eu (Transparency data Netherlands → Settlement prices) into
  `data/tennet/`, or run `python3 fetch_tennet_nl.py` with a free TenneT API key (developer.tennet.eu) in env
  `TENNET_API_KEY` or a `.tennet-key` file (git-ignored). Never write the key into docs or commits.
- Day-ahead: monthly 12.1.D files from the ENTSO-E File Library (login needed) into `data/entsoe/`; full-Europe
  files work too, only NL/FR rows are read. energy-charts.info is a keyless alternative (used by `test_external.py`).
- FR: `fetch_rte_france.py` needs RTE API client id/secret (not included).
- Then rerun `python3 nl_percentiles.py` and `python3 test_infographic.py`. `nl_percentiles.py` adds "YTD" and
  rolling-12-month rows by itself when the latest year is incomplete.

## Key files

- `infographic_dayahead.html`: the main page (tabs NL · Periods, NL · Probabilities, France · Periods,
  France · Probabilities, Portfolio Benefits, Tests). The other `infographic*.html` files are earlier pages.
- `nl_percentiles.py`: imbalance-price percentiles and imbalance − day-ahead spread percentiles (P50–P99 plus lower
  tail) → `nl_percentiles.json`, and rewrites both tables on the NL · Periods tab between
  `<!-- NL PERCENTILES START/END -->` (keep the markers). The PPTX export reads those tables from the page.
- `nl_daily_export.py [year]`: daily averages, spreads and tail percentiles →
  `exports/nl_<year>_daily_imbalance.csv` (input for the Direct+ limit calculator's open-position buffer).
- `test_infographic.py`: the test suite; recomputes every checked page value from the raw CSVs → `test_results.js`,
  shown on the Tests tab.
- `build_fr_pages.py` → `fr_pages_fragment.html` (France tabs); `analyze*.py`, `dayahead_*.py`,
  `consumption_analysis.py`, `solar_analysis.py`, `max_loss.py`, `full_analysis.py`, `period_analysis.py`: analyses,
  each writing a `*.json` result.

## Gotchas

- The spread table matches day-ahead to each ISP in exact UTC. The older `dayahead_*.py` scripts and `da_lookup`
  in the tests treat local time as UTC+1 all year (summer is 1 h off); the measured effect on spread percentiles is
  a few EUR/MWh, so it was left as is.
- 4 ISPs (the first hour of 2021) have no day-ahead price and are left out of the spreads.
- After changing data or numbers, run `nl_percentiles.py` and then `test_infographic.py` so the page and its
  Tests tab stay in step.
