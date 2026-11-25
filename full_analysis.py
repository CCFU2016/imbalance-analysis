import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
from datetime import datetime
import json

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

def load_data(filepath, delimiter):
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
    return best_i, best_j, best_length

def analyze_periods(rows):
    prices = [r["price"] for r in rows]
    periods = [
        ("24h", INTERVALS_PER_DAY),
        ("72h", INTERVALS_PER_DAY * 3),
        ("7d", INTERVALS_PER_DAY * 7),
        ("14d", INTERVALS_PER_DAY * 14),
    ]
    results = {}
    for name, window in periods:
        if window > len(prices):
            continue
        window_sum = sum(prices[:window])
        returns = [window_sum * MW * HOURS_PER_INTERVAL]
        for i in range(1, len(prices) - window + 1):
            window_sum += prices[i + window - 1] - prices[i - 1]
            returns.append(window_sum * MW * HOURS_PER_INTERVAL)
        n_negative = sum(1 for r in returns if r < 0)
        pct = n_negative / len(returns) * 100
        worst = min(returns)
        best = max(returns)
        worst_idx = returns.index(worst)
        best_idx = returns.index(best)
        results[name] = {
            "pct_negative": round(pct, 1),
            "avg_return": round(sum(returns) / len(returns), 2),
            "worst": round(worst, 2),
            "worst_date": rows[worst_idx]["start"].strftime("%Y-%m-%d"),
            "best": round(best, 2),
            "best_date": rows[best_idx]["start"].strftime("%Y-%m-%d"),
        }
    return results

# Run all analysis
all_data = {}
for label, path, delim in FILES:
    rows = load_data(path, delim)
    prices = [r["price"] for r in rows]

    # Average daily return
    total_return = sum(p * MW * HOURS_PER_INTERVAL for p in prices)
    n_days = len(prices) / INTERVALS_PER_DAY
    avg_daily = total_return / n_days

    # Max loss
    ml_i, ml_j, ml_price = find_max_loss(rows)
    ml_eur = ml_price * MW * HOURS_PER_INTERVAL
    ml_hours = (ml_j + 1 - ml_i) * 0.25

    # Longest negative
    ln_i, ln_j, ln_len = find_longest_negative(rows)
    ln_hours = ln_len * 0.25
    ln_eur = sum(r["price"] * MW * HOURS_PER_INTERVAL for r in rows[ln_i:ln_j + 1]) if ln_len > 0 else 0

    # Period probabilities
    period_data = analyze_periods(rows)

    year_data = {
        "total_return": round(total_return, 2),
        "avg_daily": round(avg_daily, 2),
        "max_loss_eur": round(ml_eur, 2),
        "max_loss_hours": round(ml_hours, 1),
        "max_loss_start": rows[ml_i]["start"].strftime("%Y-%m-%d"),
        "max_loss_end": rows[ml_j]["end"].strftime("%Y-%m-%d"),
        "longest_neg_hours": round(ln_hours, 1),
        "longest_neg_days": round(ln_hours / 24, 1),
        "longest_neg_eur": round(ln_eur, 2),
        "longest_neg_start": rows[ln_i]["start"].strftime("%Y-%m-%d") if ln_len > 0 else "",
        "longest_neg_end": rows[ln_j]["end"].strftime("%Y-%m-%d") if ln_len > 0 else "",
        "periods": period_data,
    }
    all_data[label] = year_data

    print(f"\n{'='*60}")
    print(f" {label} | Annual return: {total_return:,.0f} EUR | Avg daily: {avg_daily:,.0f} EUR")
    print(f"{'='*60}")
    print(f"  Max loss: {ml_eur:,.0f} EUR over {ml_hours:.0f}h ({rows[ml_i]['start'].date()} to {rows[ml_j]['end'].date()})")
    print(f"  Longest negative: {ln_hours:.0f}h ({ln_hours/24:.1f}d), loss: {ln_eur:,.0f} EUR")
    for pname, pdata in period_data.items():
        print(f"  {pname}: {pdata['pct_negative']}% negative | worst: {pdata['worst']:,.0f} EUR | best: {pdata['best']:,.0f} EUR")

# Save JSON for infographic
with open("results.json", "w") as f:
    json.dump(all_data, f, indent=2)
print("\nResults saved to results.json")
