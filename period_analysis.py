import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
from datetime import datetime

HOURS_PER_INTERVAL = 0.25
MW = 1
INTERVALS_PER_DAY = 96  # 24h / 0.25h

def load_data(filepath, delimiter=","):
    rows = []
    with open(filepath) as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            price_str = row["Price Surplus"].strip()
            if price_str == "":
                continue
            rows.append({
                "start": datetime.strptime(row["Timeinterval Start Loc"], "%Y-%m-%dT%H:%M"),
                "end": datetime.strptime(row["Timeinterval End Loc"], "%Y-%m-%dT%H:%M"),
                "price": float(price_str),
            })
    return rows

def analyze_periods(label, rows):
    print(f"{'='*60}")
    print(f" {label}")
    print(f" {rows[0]['start'].date()} to {rows[-1]['end'].date()}")
    print(f"{'='*60}")

    prices = [r["price"] for r in rows]

    # Average daily return
    total_return = sum(p * MW * HOURS_PER_INTERVAL for p in prices)
    n_days = len(prices) / INTERVALS_PER_DAY
    avg_daily = total_return / n_days
    print(f"\n  Average daily return: {avg_daily:,.2f} EUR")
    print()

    # Analyse rolling windows
    periods = [
        ("24 hours", INTERVALS_PER_DAY),
        ("72 hours (3 days)", INTERVALS_PER_DAY * 3),
        ("7 days", INTERVALS_PER_DAY * 7),
        ("14 days", INTERVALS_PER_DAY * 14),
    ]

    for name, window in periods:
        if window > len(prices):
            print(f"  {name}: not enough data")
            continue

        # Rolling sum using sliding window
        window_sum = sum(prices[:window])
        returns = [window_sum * MW * HOURS_PER_INTERVAL]

        for i in range(1, len(prices) - window + 1):
            window_sum += prices[i + window - 1] - prices[i - 1]
            returns.append(window_sum * MW * HOURS_PER_INTERVAL)

        n_windows = len(returns)
        n_negative = sum(1 for r in returns if r < 0)
        pct_negative = n_negative / n_windows * 100

        avg_return = sum(returns) / n_windows
        worst = min(returns)
        best = max(returns)
        worst_idx = returns.index(worst)
        best_idx = returns.index(best)

        print(f"  {name}:")
        print(f"    Probability of negative return: {pct_negative:.1f}% ({n_negative}/{n_windows} windows)")
        print(f"    Average return:  {avg_return:>10,.2f} EUR")
        print(f"    Worst return:    {worst:>10,.2f} EUR  ({rows[worst_idx]['start']})")
        print(f"    Best return:     {best:>10,.2f} EUR  ({rows[best_idx]['start']})")
        print()

print()
for label, path, delim in [
    ("2024", "data/tennet/settlement_prices_202312312300_202412312300.csv", ";"),
    ("2025", "data/tennet/settlement_prices_202412312300_202512312300_CET.csv", ","),
]:
    rows = load_data(path, delim)
    analyze_periods(label, rows)
