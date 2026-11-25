import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
import math
import json
from datetime import datetime
from collections import defaultdict

HOURS_PER_INTERVAL = 0.25
MW = 1
INTERVALS_PER_DAY = 96

FILES = [
    ("2021", "data/tennet/settlement_prices_202012312300_202112312300.csv", ";"),
    ("2022", "data/tennet/settlement_prices_202112312300_202212312300.csv", ";"),
    ("2023", "data/tennet/settlement_prices_202212312300_202312312300.csv", ";"),
    ("2024", "data/tennet/settlement_prices_202312312300_202412312300.csv", ";"),
    ("2025", "data/tennet/settlement_prices_202412312300_202512312300_CET.csv", ","),
]

def residential_profile(hour, month):
    """
    Generate a residential consumption multiplier for a given hour and month.
    Based on typical Dutch residential load profiles (NEDU E1A style).

    Returns a multiplier where 1.0 = average consumption.
    The profile is normalized so that the daily average = 1.0 MW.

    Key characteristics:
    - Night (00-06): low base load (~0.4-0.5x)
    - Morning peak (07-09): ~1.3-1.5x (breakfast, getting ready)
    - Midday (10-15): moderate ~0.7-0.9x (many people at work)
    - Evening peak (17-21): highest ~1.5-1.8x (cooking, heating, TV, lighting)
    - Late evening (22-23): declining ~0.8-1.0x

    Seasonal adjustment:
    - Winter (Dec-Feb): +30% (heating, lighting)
    - Spring/Autumn: baseline
    - Summer (Jun-Aug): -15% (less heating/lighting)
    """
    # Hourly shape (24 values, index = hour)
    hourly = [
        0.40, 0.35, 0.32, 0.30, 0.30, 0.35,  # 00-05: night
        0.50, 1.10, 1.40, 1.30, 0.90, 0.80,  # 06-11: morning ramp + peak
        0.75, 0.70, 0.70, 0.75, 0.90, 1.40,  # 12-17: midday + evening ramp
        1.70, 1.80, 1.60, 1.30, 1.00, 0.65,  # 18-23: evening peak + decline
    ]

    # Normalize so daily average = 1.0
    avg = sum(hourly) / len(hourly)
    base = hourly[int(hour)] / avg

    # Seasonal multiplier
    seasonal = {
        1: 1.30, 2: 1.25, 3: 1.10, 4: 0.95,
        5: 0.88, 6: 0.85, 7: 0.85, 8: 0.88,
        9: 0.95, 10: 1.10, 11: 1.20, 12: 1.30,
    }

    return base * seasonal[month]


def load_data(filepath, delimiter):
    rows = []
    with open(filepath) as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            price_str = row["Price Surplus"].strip()
            if price_str == "":
                continue
            start = datetime.strptime(row["Timeinterval Start Loc"], "%Y-%m-%dT%H:%M")
            rows.append({
                "start": start,
                "end": datetime.strptime(row["Timeinterval End Loc"], "%Y-%m-%dT%H:%M"),
                "price": float(price_str),
                "hour": start.hour + start.minute / 60,
                "month": start.month,
            })
    return rows


def find_max_cost(costs):
    """Find contiguous period with maximum total cost (worst for consumer)."""
    # Kadane's for max subarray
    prefix = [0.0]
    for c in costs:
        prefix.append(prefix[-1] + c)

    best_cost = 0
    best_i = 0
    best_j = 0
    min_prefix = prefix[0]
    min_prefix_idx = 0

    for j in range(len(costs)):
        if prefix[j] < min_prefix:
            min_prefix = prefix[j]
            min_prefix_idx = j
        gain = prefix[j + 1] - prefix[min_prefix_idx]
        if gain > best_cost:
            best_cost = gain
            best_i = min_prefix_idx
            best_j = j

    return best_i, best_j, best_cost


def find_longest_positive_cost(costs):
    """Find longest contiguous period with positive total cost."""
    prefix = [0.0]
    for c in costs:
        prefix.append(prefix[-1] + c)

    best_length = 0
    best_i = 0
    best_j = 0
    min_prefix = prefix[0]
    min_prefix_idx = 0

    for j in range(len(costs)):
        if prefix[j] < min_prefix:
            min_prefix = prefix[j]
            min_prefix_idx = j
        total = prefix[j + 1] - prefix[min_prefix_idx]
        if total > 0:
            length = j + 1 - min_prefix_idx
            if length > best_length:
                best_length = length
                best_i = min_prefix_idx
                best_j = j

    return best_i, best_j, best_length


def analyze_rolling_costs(daily_costs):
    """Rolling window analysis on daily costs."""
    periods = [
        ("24h", 1),
        ("72h", 3),
        ("7d", 7),
        ("14d", 14),
    ]
    results = {}
    dates = sorted(daily_costs.keys())
    vals = [daily_costs[d] for d in dates]

    for name, window in periods:
        if window > len(vals):
            continue
        window_sum = sum(vals[:window])
        returns = [window_sum]
        for i in range(1, len(vals) - window + 1):
            window_sum += vals[i + window - 1] - vals[i - 1]
            returns.append(window_sum)

        # For consumption, "negative cost" means you earn money (prices were negative)
        # We want probability of positive cost (you actually pay)
        # Wait - all costs will mostly be positive. We want probability of "above average" or
        # actually for consumption the interesting metric is: when is cost highest?
        # Let's report: average cost, worst (highest) cost, best (lowest/most negative) cost
        # And probability of negative cost (you get paid to consume)

        n_negative = sum(1 for r in returns if r < 0)
        pct_negative = n_negative / len(returns) * 100

        worst = max(returns)  # highest cost
        best = min(returns)   # lowest cost (or negative = earning)
        worst_idx = returns.index(worst)
        best_idx = returns.index(best)
        avg = sum(returns) / len(returns)

        results[name] = {
            "pct_earning": round(pct_negative, 1),
            "avg_cost": round(avg, 2),
            "worst_cost": round(worst, 2),
            "worst_date": str(dates[worst_idx]),
            "best_cost": round(best, 2),
            "best_date": str(dates[best_idx]),
        }
    return results


# Show residential profile sample
print("Residential consumption profile (multiplier vs 1 MW average):\n")
print(f"  {'Hour':>5}  {'Jan':>5}  {'Apr':>5}  {'Jul':>5}  {'Oct':>5}")
for h in range(0, 24, 2):
    vals = [residential_profile(h, m) for m in [1, 4, 7, 10]]
    print(f"  {h:02d}:00  " + "  ".join(f"{v:5.2f}" for v in vals))
print()

# Run analysis for both profiles
all_data = {}

for label, path, delim in FILES:
    rows = load_data(path, delim)

    # --- FLAT CONSUMPTION ---
    # Cost = price * 1 MW * 0.25h per interval
    flat_costs = [r["price"] * MW * HOURS_PER_INTERVAL for r in rows]

    flat_total = sum(flat_costs)
    flat_n_days = len(rows) / INTERVALS_PER_DAY
    flat_avg_daily = flat_total / flat_n_days

    # Daily costs for rolling window
    flat_daily = defaultdict(float)
    for r, c in zip(rows, flat_costs):
        flat_daily[r["start"].date()] += c

    # Max cost period
    fi, fj, fmax = find_max_cost(flat_costs)
    fmax_hours = (fj + 1 - fi) * 0.25

    # Longest positive cost streak
    fli, flj, fl_len = find_longest_positive_cost(flat_costs)
    fl_hours = fl_len * 0.25
    fl_cost = sum(flat_costs[fli:flj + 1]) if fl_len > 0 else 0

    flat_rolling = analyze_rolling_costs(flat_daily)

    # --- RESIDENTIAL CONSUMPTION ---
    res_costs = []
    for r in rows:
        multiplier = residential_profile(r["hour"], r["month"])
        res_costs.append(r["price"] * MW * multiplier * HOURS_PER_INTERVAL)

    res_total = sum(res_costs)
    # Residential total energy is not same as flat (seasonal adjustment)
    # Calculate total MWh for comparison
    res_mwh = sum(residential_profile(r["hour"], r["month"]) * HOURS_PER_INTERVAL for r in rows)
    flat_mwh = len(rows) * HOURS_PER_INTERVAL
    res_avg_daily = res_total / flat_n_days

    res_daily = defaultdict(float)
    for r, c in zip(rows, res_costs):
        res_daily[r["start"].date()] += c

    ri, rj, rmax = find_max_cost(res_costs)
    rmax_hours = (rj + 1 - ri) * 0.25

    rli, rlj, rl_len = find_longest_positive_cost(res_costs)
    rl_hours = rl_len * 0.25
    rl_cost = sum(res_costs[rli:rlj + 1]) if rl_len > 0 else 0

    res_rolling = analyze_rolling_costs(res_daily)

    # Avg price paid
    flat_avg_price = flat_total / flat_mwh
    res_avg_price = res_total / res_mwh

    year_data = {
        "flat": {
            "total_cost": round(flat_total, 2),
            "avg_daily": round(flat_avg_daily, 2),
            "avg_price": round(flat_avg_price, 2),
            "total_mwh": round(flat_mwh, 1),
            "max_cost_eur": round(fmax, 2),
            "max_cost_hours": round(fmax_hours, 1),
            "max_cost_start": rows[fi]["start"].strftime("%Y-%m-%d"),
            "max_cost_end": rows[fj]["end"].strftime("%Y-%m-%d"),
            "longest_pos_hours": round(fl_hours, 1),
            "longest_pos_days": round(fl_hours / 24, 1),
            "longest_pos_cost": round(fl_cost, 2),
            "periods": flat_rolling,
        },
        "residential": {
            "total_cost": round(res_total, 2),
            "avg_daily": round(res_avg_daily, 2),
            "avg_price": round(res_avg_price, 2),
            "total_mwh": round(res_mwh, 1),
            "max_cost_eur": round(rmax, 2),
            "max_cost_hours": round(rmax_hours, 1),
            "max_cost_start": rows[ri]["start"].strftime("%Y-%m-%d"),
            "max_cost_end": rows[rj]["end"].strftime("%Y-%m-%d"),
            "longest_pos_hours": round(rl_hours, 1),
            "longest_pos_days": round(rl_hours / 24, 1),
            "longest_pos_cost": round(rl_cost, 2),
            "periods": res_rolling,
        },
    }
    all_data[label] = year_data

    pct_diff = ((res_total - flat_total) / flat_total) * 100

    print(f"{'='*65}")
    print(f" {label}")
    print(f"{'='*65}")
    print(f"  FLAT:        total cost {flat_total:>12,.0f} EUR | avg daily {flat_avg_daily:>8,.0f} EUR | avg price {flat_avg_price:>6.1f} EUR/MWh")
    print(f"  RESIDENTIAL: total cost {res_total:>12,.0f} EUR | avg daily {res_avg_daily:>8,.0f} EUR | avg price {res_avg_price:>6.1f} EUR/MWh | {pct_diff:+.0f}% vs flat")
    print(f"  Flat max cost:  {fmax:>8,.0f} EUR over {fmax_hours:.0f}h ({rows[fi]['start'].date()} to {rows[fj]['end'].date()})")
    print(f"  Resi max cost:  {rmax:>8,.0f} EUR over {rmax_hours:.0f}h ({rows[ri]['start'].date()} to {rows[rj]['end'].date()})")
    for pname in ["24h", "72h", "7d", "14d"]:
        fp = flat_rolling[pname]
        rp = res_rolling[pname]
        print(f"  {pname}: flat earn {fp['pct_earning']:.1f}% | resi earn {rp['pct_earning']:.1f}% | flat worst {fp['worst_cost']:,.0f} | resi worst {rp['worst_cost']:,.0f}")
    print()

with open("consumption_results.json", "w") as f:
    json.dump(all_data, f, indent=2)
print("Results saved to consumption_results.json")
