#!/usr/bin/env python3
"""
Analyse French imbalance data (from RTE API) and compare with day-ahead.

Run fetch_rte_france.py first to download the data, then run this script.

If RTE imbalance data is not yet available, this script will still produce
the French day-ahead analysis and the NL vs FR day-ahead comparison.
"""
import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
import glob
import json
import os
import statistics
from datetime import datetime, timedelta
from collections import defaultdict

DIR = os.path.dirname(os.path.abspath(__file__))
NL_HOURS_PER_INTERVAL = 0.25  # TenneT settles in 15-min ISPs
FR_HOURS_PER_INTERVAL = 0.5   # RTE settles in 30-min half-hours

NL_FILES = [
    ("data/tennet/settlement_prices_202012312300_202112312300.csv", ";"),
    ("data/tennet/settlement_prices_202112312300_202212312300.csv", ";"),
    ("data/tennet/settlement_prices_202212312300_202312312300.csv", ";"),
    ("data/tennet/settlement_prices_202312312300_202412312300.csv", ";"),
    ("data/tennet/settlement_prices_202412312300_202512312300_CET.csv", ","),
]

# ============================================================
# LOAD FRENCH DAY-AHEAD (from ENTSO-E files — always available)
# ============================================================
def load_fr_dayahead():
    da = {}
    for fp in sorted(glob.glob("data/entsoe/*EnergyPrices*.csv")):
        with open(fp) as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if row.get("MapCode") != "FR":
                    continue
                try:
                    dt = datetime.strptime(row["DateTime(UTC)"], "%Y-%m-%d %H:%M:%S")
                    da[dt] = float(row["Price[Currency/MWh]"])
                except (ValueError, KeyError):
                    continue
    return da


def load_nl_dayahead():
    da = {}
    for fp in sorted(glob.glob("data/entsoe/*EnergyPrices*.csv")):
        with open(fp) as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if row.get("MapCode") != "NL":
                    continue
                try:
                    dt = datetime.strptime(row["DateTime(UTC)"], "%Y-%m-%d %H:%M:%S")
                    da[dt] = float(row["Price[Currency/MWh]"])
                except (ValueError, KeyError):
                    continue
    return da


# ============================================================
# LOAD FRENCH IMBALANCE DATA (from RTE API downloads)
# ============================================================
def load_fr_imbalance():
    """Load French imbalance data from RTE CSV downloads.

    RTE switched from 30-min to 15-min settlement intervals on 2025-01-01, so
    each row carries its own hpi (hours-per-interval) derived from start/end."""
    csv_files = sorted(glob.glob(os.path.join(DIR, "FR_imbalance_data_*.csv")))
    rows = []
    if not csv_files:
        return rows

    print(f"  Found {len(csv_files)} French imbalance CSV files")
    for fp in csv_files:
        with open(fp, encoding="utf-8-sig") as f:
            f.readline()  # skip title row
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                try:
                    dt_s = datetime.strptime(row["Heure de début"], "%d/%m/%Y %H:%M")
                    dt_e = datetime.strptime(row["Heure de fin"], "%d/%m/%Y %H:%M")
                    pos = float(row["Prix de Règlements des Ecarts Positifs (Euros/MWh)"])
                    neg = float(row["Prix de Règlements des Ecarts Négatifs (Euros/MWh)"])
                except (KeyError, ValueError, TypeError):
                    continue
                hpi = (dt_e - dt_s).total_seconds() / 3600.0
                rows.append({"start": dt_s, "price_pos": pos, "price_neg": neg, "hpi": hpi})
    return rows


def load_nl_imbalance():
    """Load Dutch TenneT settlement prices (Price Surplus / Price Shortage)."""
    rows = []
    for fp, delim in NL_FILES:
        if not os.path.exists(fp):
            print(f"  Missing NL file: {fp}")
            continue
        with open(fp) as f:
            reader = csv.DictReader(f, delimiter=delim)
            for row in reader:
                surplus = row.get("Price Surplus", "").strip()
                shortage = row.get("Price Shortage", "").strip()
                if not surplus or not shortage:
                    continue
                try:
                    dt = datetime.strptime(row["Timeinterval Start Loc"], "%Y-%m-%dT%H:%M")
                    pos = float(surplus)
                    neg = float(shortage)
                except (KeyError, ValueError):
                    continue
                rows.append({"start": dt, "price_pos": pos, "price_neg": neg})
    print(f"  Loaded {len(rows)} NL imbalance intervals")
    return rows


def spread_stats(rows, hours_per_interval=None):
    """Return per-year spread statistics from a list of {start, price_pos, price_neg}.

    If rows carry an 'hpi' field, it is used per-row (handles the 2025 RTE
    resolution change); otherwise `hours_per_interval` is used for all rows."""
    per_year = defaultdict(list)  # list of (spread, hpi)
    for r in rows:
        spread = abs(r["price_pos"] - r["price_neg"])
        hpi = r.get("hpi", hours_per_interval)
        per_year[r["start"].year].append((spread, hpi))
    out = {}
    for year, entries in sorted(per_year.items()):
        spreads = [s for s, _ in entries]
        n = len(spreads)
        if n == 0:
            continue
        out[year] = {
            "intervals": n,
            "avg": sum(spreads) / n,
            "median": statistics.median(spreads),
            "p90": sorted(spreads)[int(n * 0.9)] if n >= 10 else max(spreads),
            "max": max(spreads),
            # Theoretical arbitrage revenue for a 1 MW asset perfectly timing
            # every interval (captures |pos − neg| each settlement).
            "total_eur_1mw": sum(s * h for s, h in entries),
        }
    return out


# ============================================================
# ANALYSIS
# ============================================================
def annual_stats(prices_by_year):
    results = {}
    for year, prices in sorted(prices_by_year.items()):
        avg = sum(prices) / len(prices)
        results[year] = {
            "avg": round(avg, 2),
            "count": len(prices),
            "min": round(min(prices), 2),
            "max": round(max(prices), 2),
            "median": round(statistics.median(prices), 2),
        }
    return results


def main():
    print("=" * 60)
    print(" French Market Analysis")
    print("=" * 60)

    # --- Load day-ahead data ---
    print("\nLoading French day-ahead (ENTSO-E)...")
    fr_da = load_fr_dayahead()
    print(f"  Loaded {len(fr_da)} FR day-ahead price points")

    print("Loading Dutch day-ahead (ENTSO-E)...")
    nl_da = load_nl_dayahead()
    print(f"  Loaded {len(nl_da)} NL day-ahead price points")

    # --- Day-ahead comparison ---
    print("\n--- Day-Ahead Annual Averages ---")
    fr_by_year = defaultdict(list)
    nl_by_year = defaultdict(list)
    for dt, price in fr_da.items():
        fr_by_year[dt.year].append(price)
    for dt, price in nl_da.items():
        nl_by_year[dt.year].append(price)

    print(f"{'Year':<6}{'FR DA avg':>12}{'NL DA avg':>12}{'Diff (FR-NL)':>14}")
    print("-" * 44)
    for year in sorted(set(fr_by_year.keys()) & set(nl_by_year.keys())):
        fr_avg = sum(fr_by_year[year]) / len(fr_by_year[year])
        nl_avg = sum(nl_by_year[year]) / len(nl_by_year[year])
        diff = fr_avg - nl_avg
        print(f"{year:<6}{fr_avg:>12.2f}{nl_avg:>12.2f}{diff:>+14.2f}")

    # --- Load imbalance data for both markets ---
    print("\nLoading French imbalance data (RTE)...")
    fr_imb = load_fr_imbalance()
    print(f"  Loaded {len(fr_imb)} FR imbalance intervals")

    print("Loading Dutch imbalance data (TenneT)...")
    nl_imb = load_nl_imbalance()

    fr_spreads = spread_stats(fr_imb, FR_HOURS_PER_INTERVAL)
    nl_spreads = spread_stats(nl_imb, NL_HOURS_PER_INTERVAL)

    # --- NL vs FR imbalance spread comparison ---
    print("\n--- Imbalance Price Spread: NL vs FR ---")
    print("(spread = |surplus − shortage| per settlement interval)")
    print(f"{'Year':<6}{'NL avg':>10}{'FR avg':>10}{'NL med':>10}{'FR med':>10}"
          f"{'NL p90':>10}{'FR p90':>10}{'NL 1MW €':>14}{'FR 1MW €':>14}")
    print("-" * 94)
    years = sorted(set(nl_spreads.keys()) | set(fr_spreads.keys()))
    for year in years:
        n = nl_spreads.get(year)
        f_ = fr_spreads.get(year)
        def fmt(d, k, w=10, money=False):
            if d is None or k not in d:
                return "—".rjust(w)
            v = d[k]
            return f"{v:>{w},.0f}" if money else f"{v:>{w}.2f}"
        print(
            f"{year:<6}"
            f"{fmt(n,'avg')}{fmt(f_,'avg')}"
            f"{fmt(n,'median')}{fmt(f_,'median')}"
            f"{fmt(n,'p90')}{fmt(f_,'p90')}"
            f"{fmt(n,'total_eur_1mw',14,True)}{fmt(f_,'total_eur_1mw',14,True)}"
        )

    results = {
        "status": "complete" if fr_imb else "partial_fr_missing",
        "fr_da_annual": annual_stats(fr_by_year),
        "nl_da_annual": annual_stats(nl_by_year),
        "nl_imbalance_spread": {y: {k: round(v, 2) for k, v in d.items()}
                                for y, d in nl_spreads.items()},
        "fr_imbalance_spread": {y: {k: round(v, 2) for k, v in d.items()}
                                for y, d in fr_spreads.items()},
    }

    # Save results
    outpath = os.path.join(DIR, "france_results.json")
    with open(outpath, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {outpath}")


if __name__ == "__main__":
    main()
