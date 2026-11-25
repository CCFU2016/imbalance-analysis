import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
from datetime import datetime

# Load data
rows = []
with open("data/tennet/settlement_prices_202412312300_202512312300_CET.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        price_str = row["Price Surplus"].strip()
        if price_str == "":
            continue
        rows.append({
            "start": datetime.strptime(row["Timeinterval Start Loc"], "%Y-%m-%dT%H:%M"),
            "end": datetime.strptime(row["Timeinterval End Loc"], "%Y-%m-%dT%H:%M"),
            "price": float(price_str),
        })

print(f"Loaded {len(rows)} intervals")
print(f"Date range: {rows[0]['start']} to {rows[-1]['end']}")
print()

# Each interval is 15 min = 0.25 hours
# Revenue per interval for 1 MW asset = price (EUR/MWh) * 1 MW * 0.25 h = price * 0.25 EUR
HOURS_PER_INTERVAL = 0.25
MW = 1

# Find longest contiguous period with total negative return
# We need the longest subarray [i..j] where sum of prices is < 0
# Approach: for each end index j, we want the earliest i such that
# prefix_sum[j+1] - prefix_sum[i] < 0, i.e. prefix_sum[i] > prefix_sum[j+1]
# Track the running maximum of prefix sums and the index where it occurred.

# Build prefix sums
prefix = [0.0]  # prefix[0] = 0, prefix[k] = sum of first k prices
for r in rows:
    prefix.append(prefix[-1] + r["price"])

best_length = 0
best_i = 0
best_j = 0

# For each j, find earliest i where prefix[i] > prefix[j+1]
# We track the running max of prefix[0..j] and where it first occurred
max_prefix = prefix[0]
max_prefix_idx = 0

for j in range(len(rows)):
    # Update running max prefix (considering indices 0..j)
    if prefix[j] > max_prefix:
        max_prefix = prefix[j]
        max_prefix_idx = j

    # Check if period [max_prefix_idx .. j] has negative return
    total = prefix[j + 1] - prefix[max_prefix_idx]
    if total < 0:
        length = j + 1 - max_prefix_idx
        if length > best_length:
            best_length = length
            best_i = max_prefix_idx
            best_j = j

if best_length > 0:
    start_time = rows[best_i]["start"]
    end_time = rows[best_j]["end"]
    total_hours = best_length * 0.25
    total_days = total_hours / 24
    total_revenue = sum(r["price"] * MW * HOURS_PER_INTERVAL for r in rows[best_i:best_j + 1])

    print("=== LONGEST CONTINUOUS PERIOD WITH NEGATIVE TOTAL RETURN ===")
    print(f"Start:       {start_time}")
    print(f"End:         {end_time}")
    print(f"Duration:    {best_length} intervals = {total_hours:.1f} hours = {total_days:.1f} days")
    print(f"Total return: {total_revenue:,.2f} EUR (for 1 MW constant injection)")
    print()

    # Show some stats for this period
    prices = [r["price"] for r in rows[best_i:best_j + 1]]
    pos = sum(1 for p in prices if p >= 0)
    neg = sum(1 for p in prices if p < 0)
    print(f"Intervals with positive price: {pos}")
    print(f"Intervals with negative price: {neg}")
    print(f"Average price: {sum(prices)/len(prices):.2f} EUR/MWh")
    print(f"Min price:     {min(prices):.2f} EUR/MWh")
    print(f"Max price:     {max(prices):.2f} EUR/MWh")
else:
    print("No continuous period with negative total return found.")
