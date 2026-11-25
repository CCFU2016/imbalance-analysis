import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
import glob
from datetime import datetime, timedelta

HOURS_PER_INTERVAL = 0.25
MW = 1
INTERVALS_PER_DAY = 96

# Load NL day-ahead
da_prices = {}
for fp in sorted(glob.glob("data/entsoe/*EnergyPrices*.csv")):
    with open(fp) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("MapCode") != "NL":
                continue
            try:
                dt = datetime.strptime(row["DateTime(UTC)"], "%Y-%m-%d %H:%M:%S")
                price = float(row["Price[Currency/MWh]"])
                da_prices[dt] = price
            except (ValueError, KeyError):
                continue

print(f"Loaded {len(da_prices)} NL day-ahead price points\n")

def da_lookup(dt_local):
    dt_utc = dt_local - timedelta(hours=1)
    dt_hour = dt_utc.replace(minute=0, second=0, microsecond=0)
    return da_prices.get(dt_hour)


IMBALANCE_FILES = [
    ("2021", "data/tennet/settlement_prices_202012312300_202112312300.csv", ";"),
    ("2022", "data/tennet/settlement_prices_202112312300_202212312300.csv", ";"),
    ("2023", "data/tennet/settlement_prices_202212312300_202312312300.csv", ";"),
    ("2024", "data/tennet/settlement_prices_202312312300_202412312300.csv", ";"),
    ("2025", "data/tennet/settlement_prices_202412312300_202512312300_CET.csv", ","),
]

def load_imbalance(filepath, delimiter):
    rows = []
    with open(filepath) as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            ps = row["Price Surplus"].strip()
            if ps == "":
                continue
            rows.append({
                "start": datetime.strptime(row["Timeinterval Start Loc"], "%Y-%m-%dT%H:%M"),
                "price": float(ps),
            })
    return rows

results = {}
for year, path, delim in IMBALANCE_FILES:
    rows = load_imbalance(path, delim)
    # Build aligned imbalance and day-ahead price arrays at 15-min level
    imb_prices = []
    da_at_imb = []
    for r in rows:
        v = da_lookup(r["start"])
        imb_prices.append(r["price"])
        da_at_imb.append(v if v is not None else 0)

    print(f"{'='*70}")
    print(f" {year}")
    print(f"{'='*70}")

    # Annual avg
    n = len(imb_prices)
    imb_annual = sum(imb_prices) / n
    da_annual = sum(da_at_imb) / n
    print(f"  Annual avg: imb={imb_annual:.2f} | DA={da_annual:.2f} | diff={imb_annual-da_annual:+.2f}")

    year_data = {
        "imb_annual_avg": round(imb_annual, 2),
        "da_annual_avg": round(da_annual, 2),
        "periods": {},
    }

    for name, window in [("24h", 96), ("72h", 288), ("7d", 672), ("14d", 1344)]:
        if window > n:
            continue
        # Rolling sums
        imb_sum = sum(imb_prices[:window])
        da_sum = sum(da_at_imb[:window])
        imb_returns = [imb_sum]
        da_returns = [da_sum]
        for i in range(1, n - window + 1):
            imb_sum += imb_prices[i + window - 1] - imb_prices[i - 1]
            da_sum += da_at_imb[i + window - 1] - da_at_imb[i - 1]
            imb_returns.append(imb_sum)
            da_returns.append(da_sum)

        n_windows = len(imb_returns)
        # imbalance return per window in EUR for 1 MW = sum(prices) * 0.25 (since each interval is 0.25h)
        # negative return = sum(prices) < 0
        n_neg = sum(1 for r in imb_returns if r < 0)
        pct_neg = n_neg / n_windows * 100

        # For negative-return windows, compute avg imbalance and avg DA prices (per MWh)
        # Avg price per MWh = sum / window (because each interval contributes equally per MW basis)
        if n_neg > 0:
            neg_imb_avgs = [imb_returns[k] / window for k in range(n_windows) if imb_returns[k] < 0]
            neg_da_avgs = [da_returns[k] / window for k in range(n_windows) if imb_returns[k] < 0]
            avg_imb_neg = sum(neg_imb_avgs) / len(neg_imb_avgs)
            avg_da_neg = sum(neg_da_avgs) / len(neg_da_avgs)
            diff = avg_imb_neg - avg_da_neg
        else:
            avg_imb_neg = avg_da_neg = diff = 0

        # Total EUR sums (1 MW * 0.25h per interval)
        # In a negative-return window: total EUR loss = imbalance_return * 0.25
        # We want avg total cost over those windows
        if n_neg > 0:
            avg_total_imb = sum(imb_returns[k] * MW * HOURS_PER_INTERVAL for k in range(n_windows) if imb_returns[k] < 0) / n_neg
            avg_total_da = sum(da_returns[k] * MW * HOURS_PER_INTERVAL for k in range(n_windows) if imb_returns[k] < 0) / n_neg
        else:
            avg_total_imb = avg_total_da = 0

        year_data["periods"][name] = {
            "n_windows": n_windows,
            "n_negative": n_neg,
            "pct_negative": round(pct_neg, 1),
            "avg_imb_per_mwh_in_neg": round(avg_imb_neg, 2),
            "avg_da_per_mwh_in_neg": round(avg_da_neg, 2),
            "diff_per_mwh_in_neg": round(diff, 2),
            "avg_total_imb_in_neg": round(avg_total_imb, 0),
            "avg_total_da_in_neg": round(avg_total_da, 0),
        }
        print(f"  {name}: {n_neg}/{n_windows} neg ({pct_neg:.1f}%) | avg in neg: imb={avg_imb_neg:+.2f} DA={avg_da_neg:+.2f} diff={diff:+.2f} EUR/MWh | total imb={avg_total_imb:+,.0f} DA={avg_total_da:+,.0f}")

    results[year] = year_data
    print()

import json
with open("dayahead_periods.json", "w") as f:
    json.dump(results, f, indent=2)
print("Saved dayahead_periods.json")
