import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
import glob
from datetime import datetime, timedelta
from collections import defaultdict

HOURS_PER_INTERVAL = 0.25
MW = 1

# --- Load NL day-ahead prices ---
da_prices = {}  # datetime (UTC) -> price
da_files = sorted(glob.glob("data/entsoe/*EnergyPrices*.csv"))
for fp in da_files:
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

print(f"Loaded {len(da_prices)} NL day-ahead price points")
print(f"Range: {min(da_prices)} to {max(da_prices)} (UTC)")
print()

def da_lookup(dt_local):
    """
    Look up day-ahead price for a local CET timestamp.
    Day-ahead is hourly. CET = UTC + 1 (CEST = UTC + 2 — we approximate as UTC+1).
    Round down to the hour.
    """
    dt_utc = dt_local - timedelta(hours=1)
    dt_hour = dt_utc.replace(minute=0, second=0, microsecond=0)
    return da_prices.get(dt_hour)


# --- Load imbalance data ---
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
                "end": datetime.strptime(row["Timeinterval End Loc"], "%Y-%m-%dT%H:%M"),
                "price": float(ps),
            })
    return rows

# --- Identified periods to compare ---
# These are the periods identified in earlier analysis
PERIODS = [
    # (label, year, start_date, end_date, type)
    # Longest continuous negative return periods
    ("Longest negative streak", "2021", "2021-01-01", "2021-01-04"),  # placeholder, will use actual
    # Maximum loss periods
]

# Actually, let me dynamically recompute the periods to be precise about start/end times
def find_max_loss(rows):
    prefix = [0.0]
    for r in rows:
        prefix.append(prefix[-1] + r["price"])
    best_loss = 0
    best_i = 0
    best_j = 0
    max_prefix = prefix[0]
    max_prefix_idx = 0
    for j in range(len(rows)):
        if prefix[j] > max_prefix:
            max_prefix = prefix[j]
            max_prefix_idx = j
        loss = prefix[j + 1] - prefix[max_prefix_idx]
        if loss < best_loss:
            best_loss = loss
            best_i = max_prefix_idx
            best_j = j
    return best_i, best_j

def find_longest_negative(rows):
    prefix = [0.0]
    for r in rows:
        prefix.append(prefix[-1] + r["price"])
    best_length = 0
    best_i = 0
    best_j = 0
    max_prefix = prefix[0]
    max_prefix_idx = 0
    for j in range(len(rows)):
        if prefix[j] > max_prefix:
            max_prefix = prefix[j]
            max_prefix_idx = j
        total = prefix[j + 1] - prefix[max_prefix_idx]
        if total < 0:
            length = j + 1 - max_prefix_idx
            if length > best_length:
                best_length = length
                best_i = max_prefix_idx
                best_j = j
    return best_i, best_j

def find_max_cost(costs):
    """Highest contiguous cost (worst for consumer)."""
    prefix = [0.0]
    for c in costs:
        prefix.append(prefix[-1] + c)
    best = 0
    best_i = 0
    best_j = 0
    min_prefix = prefix[0]
    min_idx = 0
    for j in range(len(costs)):
        if prefix[j] < min_prefix:
            min_prefix = prefix[j]
            min_idx = j
        gain = prefix[j + 1] - prefix[min_idx]
        if gain > best:
            best = gain
            best_i = min_idx
            best_j = j
    return best_i, best_j

def compare(rows, i, j, label):
    """Print imbalance vs day-ahead comparison for a period [i..j]."""
    period = rows[i:j + 1]
    n_intervals = len(period)
    n_hours = n_intervals * 0.25
    n_days = n_hours / 24

    imb_avg = sum(r["price"] for r in period) / n_intervals
    imb_total_eur = sum(r["price"] * MW * HOURS_PER_INTERVAL for r in period)

    # Day-ahead lookups
    da_vals = []
    missing = 0
    for r in period:
        v = da_lookup(r["start"])
        if v is None:
            missing += 1
        else:
            da_vals.append(v)

    if not da_vals:
        print(f"  {label}: NO day-ahead data available")
        return

    da_avg = sum(da_vals) / len(da_vals)
    # For day-ahead total return, day-ahead is hourly so each hour applies to 4 intervals
    # Average price * MWh consumed/produced in period
    da_total_eur = da_avg * MW * n_hours

    diff = imb_avg - da_avg
    diff_pct = (diff / da_avg * 100) if da_avg != 0 else 0

    start = period[0]["start"]
    end = period[-1]["end"]
    print(f"  {label}")
    print(f"    Period:        {start} to {end} ({n_days:.1f} days, {n_hours:.0f}h)")
    print(f"    Imbalance avg: {imb_avg:>9.2f} EUR/MWh  | total: {imb_total_eur:>12,.0f} EUR")
    print(f"    Day-ahead avg: {da_avg:>9.2f} EUR/MWh  | total: {da_total_eur:>12,.0f} EUR")
    print(f"    Difference:    {diff:>+9.2f} EUR/MWh  ({diff_pct:+.1f}%)")
    if missing:
        print(f"    (Note: {missing} intervals missing day-ahead data)")
    print()
    return {
        "label": label,
        "start": start.strftime("%Y-%m-%d %H:%M"),
        "end": end.strftime("%Y-%m-%d %H:%M"),
        "days": round(n_days, 1),
        "hours": round(n_hours, 1),
        "imb_avg": round(imb_avg, 2),
        "imb_total": round(imb_total_eur, 0),
        "da_avg": round(da_avg, 2),
        "da_total": round(da_total_eur, 0),
        "diff": round(diff, 2),
        "diff_pct": round(diff_pct, 1),
    }


results = {}
for year, path, delim in IMBALANCE_FILES:
    rows = load_imbalance(path, delim)
    print(f"{'='*70}")
    print(f" {year}")
    print(f"{'='*70}")

    # Longest continuous negative return (injection)
    li, lj = find_longest_negative(rows)
    r1 = compare(rows, li, lj, "Longest continuous negative return (injection)")

    # Maximum loss period (injection)
    mi, mj = find_max_loss(rows)
    r2 = compare(rows, mi, mj, "Maximum single-period loss (injection)")

    # Maximum cost period for consumption (flat) — this typically spans the whole year
    # but the worst 24h is the more interesting one for comparison
    # Let's also do worst 24h (96 intervals) cost — the most expensive day
    if len(rows) >= 96:
        costs = [r["price"] * MW * HOURS_PER_INTERVAL for r in rows]
        # Find the 96-interval window with the highest sum
        window_sum = sum(costs[:96])
        best_sum = window_sum
        best_start = 0
        for k in range(1, len(costs) - 95):
            window_sum += costs[k + 95] - costs[k - 1]
            if window_sum > best_sum:
                best_sum = window_sum
                best_start = k
        r3 = compare(rows, best_start, best_start + 95, "Worst 24h consumption cost")
    else:
        r3 = None

    results[year] = {
        "longest_negative": r1,
        "max_loss": r2,
        "worst_24h_cost": r3,
    }

import json
with open("dayahead_comparison.json", "w") as f:
    json.dump(results, f, indent=2)
print("Saved dayahead_comparison.json")
