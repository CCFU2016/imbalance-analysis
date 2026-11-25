#!/usr/bin/env python3
"""
External cross-check test for infographic_dayahead.html.

Validates the day-ahead annual averages shown in the infographic against an
INDEPENDENT third-party data source. The other test script
(test_infographic.py) verifies the infographic against our own local CSVs;
this one verifies that those CSVs themselves agree with a second, separately
cleaned publication of the same underlying ENTSO-E data.

External source
---------------
Fraunhofer ISE — energy-charts.info open API
    https://api.energy-charts.info/price?bzn={NL,FR}&start=YYYY-01-01&end=YYYY-12-31

The endpoint returns hourly day-ahead prices for any European bidding zone
and requires no API key. Attribution string returned by the API is:
    "CC BY 4.0 (creativecommons.org/licenses/by/4.0)
     from Bundesnetzagentur | SMARD.de"
The data ultimately originates from the ENTSO-E Transparency Platform but
flows through SMARD.de's cleaning pipeline before reaching us — so a match
proves our local pipeline is consistent with an independent processor of the
same upstream data.

Usage
-----
    python3 test_external.py

Tolerance is generous (±1.0 EUR/MWh) because DST handling, rounding, and
edge-of-year UTC vs CET conventions can produce sub-EUR differences between
publishers.
"""
import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import json
import re
import sys
import urllib.request
from datetime import datetime

INFOGRAPHIC = "infographic_dayahead.html"
OUTPUT_JSON = "test_results_external.json"
OUTPUT_JS = "test_results_external.js"
TOLERANCE = 1.0  # EUR/MWh
YEARS = ["2021", "2022", "2023", "2024", "2025"]
ENERGY_CHARTS_URL = (
    "https://api.energy-charts.info/price?bzn={bzn}&start={year}-01-01&end={year}-12-31"
)


def fetch_annual_avg(bzn, year):
    """Fetch all hourly day-ahead prices for a bidding zone and year.

    Returns (mean_eur_per_mwh, n_hours) or (None, 0) if no data.
    """
    url = ENERGY_CHARTS_URL.format(bzn=bzn, year=year)
    with urllib.request.urlopen(url, timeout=120) as r:
        data = json.loads(r.read())
    prices = [p for p in data.get("price", []) if p is not None]
    if not prices:
        return None, 0
    return sum(prices) / len(prices), len(prices)


def parse_html(path):
    with open(path) as f:
        return f.read()


def extract_annual_avgs_at(html, position):
    """Extract one of the 'Annual Average Price Comparison' tables.

    The infographic contains two such tables: page 1 (NL, position=0) and
    page 3 (FR, position=1). Returns {year: {'imb': float, 'da': float}}.
    """
    matches = list(re.finditer(
        r"Annual Average Price Comparison.*?</tbody>",
        html, re.DOTALL,
    ))
    if len(matches) <= position:
        return {}
    block = matches[position].group(0)
    rows = re.findall(
        r'<td>(\d{4})</td>\s*<td class="val-imb">([\-\d\.]+)</td>\s*<td class="val-da">([\-\d\.]+)</td>',
        block,
    )
    return {y: {"imb": float(i), "da": float(d)} for y, i, d in rows}


def main():
    print(f"Reading infographic: {INFOGRAPHIC}")
    html = parse_html(INFOGRAPHIC)

    nl_avgs = extract_annual_avgs_at(html, 0)
    fr_avgs = extract_annual_avgs_at(html, 1)
    print(f"  Infographic NL years: {sorted(nl_avgs.keys())}")
    print(f"  Infographic FR years: {sorted(fr_avgs.keys())}")

    print("\nFetching independent reference data from Fraunhofer ISE energy-charts.info")
    print("  (CC BY 4.0 — Bundesnetzagentur | SMARD.de, ultimately ENTSO-E)")

    tests = []
    for bzn, infographic in (("NL", nl_avgs), ("FR", fr_avgs)):
        for year in YEARS:
            if year not in infographic:
                print(f"  {bzn} {year}: SKIP (not in infographic)")
                continue
            try:
                ref_avg, n_hours = fetch_annual_avg(bzn, year)
            except Exception as e:  # network/parse failures
                print(f"  {bzn} {year}: FETCH FAILED — {e}")
                tests.append({
                    "name": f"{bzn} {year} day-ahead annual avg vs Fraunhofer/SMARD",
                    "country": bzn,
                    "year": year,
                    "error": str(e),
                    "passed": False,
                })
                continue
            if ref_avg is None:
                print(f"  {bzn} {year}: NO DATA from reference")
                continue
            our_avg = infographic[year]["da"]
            diff = abs(ref_avg - our_avg)
            passed = diff <= TOLERANCE
            mark = "✓" if passed else "✗"
            print(
                f"  {mark} {bzn} {year}: infographic={our_avg:8.2f}  "
                f"reference={ref_avg:8.2f}  diff={diff:5.2f} EUR/MWh  (n={n_hours})"
            )
            tests.append({
                "name": f"{bzn} {year} day-ahead annual avg vs Fraunhofer/SMARD",
                "country": bzn,
                "year": year,
                "infographic": round(our_avg, 4),
                "reference": round(ref_avg, 4),
                "diff": round(diff, 4),
                "tolerance": TOLERANCE,
                "unit": "EUR/MWh",
                "reference_n_hours": n_hours,
                "passed": passed,
            })

    n_total = len(tests)
    n_pass = sum(1 for t in tests if t["passed"])
    n_fail = n_total - n_pass

    summary = {
        "source": "Fraunhofer ISE — energy-charts.info",
        "source_url": "https://api.energy-charts.info/price",
        "source_attribution": "CC BY 4.0 — Bundesnetzagentur | SMARD.de (originally ENTSO-E)",
        "tolerance_eur_per_mwh": TOLERANCE,
        "total": n_total,
        "passed": n_pass,
        "failed": n_fail,
        "pass_rate": round(n_pass / n_total * 100, 1) if n_total else 0.0,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tests": tests,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(summary, f, indent=2)

    # Also write a JS file the infographic test page can load directly.
    with open(OUTPUT_JS, "w") as f:
        f.write("window.externalTestResults = " + json.dumps(summary, indent=2) + ";\n")

    print(f"\n{'=' * 60}")
    print(" EXTERNAL CROSS-CHECK RESULTS")
    print(f"{'=' * 60}")
    print(f"  Source:    Fraunhofer ISE energy-charts.info (CC BY 4.0)")
    print(f"  Total:     {n_total}")
    print(f"  Passed:    {n_pass}")
    print(f"  Failed:    {n_fail}")
    print(f"  Pass rate: {summary['pass_rate']}%")
    print(f"  Tolerance: ±{TOLERANCE} EUR/MWh")
    print(f"\nResults written to:")
    print(f"  {OUTPUT_JSON}")
    print(f"  {OUTPUT_JS}  (loaded by infographic test page)")

    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
