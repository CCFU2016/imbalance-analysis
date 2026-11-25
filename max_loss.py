import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
from datetime import datetime

HOURS_PER_INTERVAL = 0.25
MW = 1

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

def find_max_loss(rows):
    """Find the contiguous period with the most negative total return (maximum loss)."""
    # Kadane's algorithm adapted for minimum subarray sum
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

    return best_i, best_j, best_loss

def analyze(label, filepath, delimiter=","):
    rows = load_data(filepath, delimiter)
    print(f"{'='*60}")
    print(f" {label}")
    print(f" {rows[0]['start'].date()} to {rows[-1]['end'].date()} | {len(rows)} intervals")
    print(f"{'='*60}")

    best_i, best_j, best_loss_price = find_max_loss(rows)
    best_loss_eur = best_loss_price * MW * HOURS_PER_INTERVAL

    start_time = rows[best_i]["start"]
    end_time = rows[best_j]["end"]
    n_intervals = best_j + 1 - best_i
    total_hours = n_intervals * 0.25
    total_days = total_hours / 24

    prices = [r["price"] for r in rows[best_i:best_j + 1]]

    print(f"\n  MAXIMUM LOSS PERIOD")
    print(f"  Start:        {start_time}")
    print(f"  End:          {end_time}")
    print(f"  Duration:     {total_days:.1f} days ({total_hours:.1f} hours / {n_intervals} intervals)")
    print(f"  Maximum loss: {best_loss_eur:,.2f} EUR")
    print(f"  Avg price:    {sum(prices)/len(prices):.2f} EUR/MWh")
    print(f"  Min price:    {min(prices):.2f} EUR/MWh")
    print(f"  Max price:    {max(prices):.2f} EUR/MWh")

    # Also show top 5 worst individual intervals in this period
    print(f"\n  5 WORST INTERVALS IN THIS PERIOD:")
    worst = sorted(rows[best_i:best_j + 1], key=lambda r: r["price"])[:5]
    for r in worst:
        eur = r["price"] * MW * HOURS_PER_INTERVAL
        print(f"    {r['start']}  price: {r['price']:>10.2f} EUR/MWh  loss: {eur:>8.2f} EUR")

    # Cumulative return for the full year
    total_year = sum(r["price"] * MW * HOURS_PER_INTERVAL for r in rows)
    print(f"\n  FULL YEAR TOTAL RETURN: {total_year:,.2f} EUR")
    print()

print()
analyze("2024", "data/tennet/settlement_prices_202312312300_202412312300.csv", delimiter=";")
analyze("2025", "data/tennet/settlement_prices_202412312300_202512312300_CET.csv", delimiter=",")
