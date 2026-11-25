import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
import math
import json
from datetime import datetime

HOURS_PER_INTERVAL = 0.25
MW = 1
INTERVALS_PER_DAY = 96

# Netherlands approximate coordinates (center of country)
LATITUDE = 52.1
LONGITUDE = 5.3

FILES = [
    ("2021", "data/tennet/settlement_prices_202012312300_202112312300.csv", ";"),
    ("2022", "data/tennet/settlement_prices_202112312300_202212312300.csv", ";"),
    ("2023", "data/tennet/settlement_prices_202212312300_202312312300.csv", ";"),
    ("2024", "data/tennet/settlement_prices_202312312300_202412312300.csv", ";"),
    ("2025", "data/tennet/settlement_prices_202412312300_202512312300_CET.csv", ","),
]

def calc_sunrise_sunset(date):
    """
    Calculate sunrise and sunset times for the Netherlands (52.1°N, 5.3°E).
    Uses the NOAA solar calculator algorithm (simplified).
    Returns (sunrise_hour, sunset_hour) as decimal hours in local time (CET = UTC+1).
    """
    day_of_year = date.timetuple().tm_yday
    lat_rad = math.radians(LATITUDE)

    # Solar declination (Spencer formula approximation)
    gamma = 2 * math.pi * (day_of_year - 1) / 365
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2*gamma) + 0.000907 * math.sin(2*gamma)
            - 0.002697 * math.cos(3*gamma) + 0.00148 * math.sin(3*gamma))

    # Hour angle at sunrise/sunset (solar zenith = 90.833° for atmospheric refraction)
    zenith = math.radians(90.833)
    cos_hour = (math.cos(zenith) - math.sin(lat_rad) * math.sin(decl)) / (math.cos(lat_rad) * math.cos(decl))
    cos_hour = max(-1, min(1, cos_hour))  # clamp for polar edge cases

    hour_angle = math.degrees(math.acos(cos_hour))

    # Equation of time (minutes)
    eqtime = (229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
              - 0.014615 * math.cos(2*gamma) - 0.04089 * math.sin(2*gamma)))

    # Solar noon in UTC minutes
    solar_noon_min = 720 - 4 * LONGITUDE - eqtime

    # Sunrise/sunset in UTC minutes
    sunrise_utc = solar_noon_min - hour_angle * 4
    sunset_utc = solar_noon_min + hour_angle * 4

    # Convert to CET (UTC+1) hours
    sunrise_cet = sunrise_utc / 60 + 1
    sunset_cet = sunset_utc / 60 + 1

    return sunrise_cet, sunset_cet

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

def filter_solar(rows):
    """Keep only intervals where the sun is up."""
    solar_rows = []
    cache = {}
    for r in rows:
        d = r["start"].date()
        if d not in cache:
            cache[d] = calc_sunrise_sunset(r["start"])
        sunrise, sunset = cache[d]
        interval_start_h = r["start"].hour + r["start"].minute / 60
        interval_end_h = r["end"].hour + r["end"].minute / 60
        if interval_end_h == 0:
            interval_end_h = 24
        # Include interval if its midpoint is during daylight
        midpoint = (interval_start_h + interval_end_h) / 2
        if midpoint >= sunrise and midpoint <= sunset:
            solar_rows.append(r)
    return solar_rows

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

def analyze_periods_solar(rows):
    """
    For solar, rolling windows are based on calendar days, not continuous intervals.
    Group by date, then use rolling windows of N days.
    """
    from collections import defaultdict
    daily = defaultdict(float)
    for r in rows:
        d = r["start"].date()
        daily[d] += r["price"] * MW * HOURS_PER_INTERVAL

    dates = sorted(daily.keys())
    daily_returns = [daily[d] for d in dates]

    periods = [
        ("24h", 1),
        ("72h", 3),
        ("7d", 7),
        ("14d", 14),
    ]
    results = {}
    for name, window_days in periods:
        if window_days > len(daily_returns):
            continue
        returns = []
        window_sum = sum(daily_returns[:window_days])
        returns.append(window_sum)
        for i in range(1, len(daily_returns) - window_days + 1):
            window_sum += daily_returns[i + window_days - 1] - daily_returns[i - 1]
            returns.append(window_sum)

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
            "worst_date": str(dates[worst_idx]),
            "best": round(best, 2),
            "best_date": str(dates[best_idx]),
        }
    return results

# Show sunrise/sunset samples
print("Sample sunrise/sunset times (CET) for the Netherlands:\n")
for m in range(1, 13):
    d = datetime(2024, m, 15)
    sr, ss = calc_sunrise_sunset(d)
    sr_h, sr_m = int(sr), int((sr % 1) * 60)
    ss_h, ss_m = int(ss), int((ss % 1) * 60)
    daylight = ss - sr
    print(f"  {d.strftime('%B'):>12} 15: sunrise {sr_h:02d}:{sr_m:02d} | sunset {ss_h:02d}:{ss_m:02d} | {daylight:.1f}h daylight")

print()

# Run analysis
all_data = {}
for label, path, delim in FILES:
    rows_all = load_data(path, delim)
    rows_solar = filter_solar(rows_all)

    pct_solar = len(rows_solar) / len(rows_all) * 100
    prices = [r["price"] for r in rows_solar]

    total_return = sum(p * MW * HOURS_PER_INTERVAL for p in prices)
    n_days = len(set(r["start"].date() for r in rows_solar))
    avg_daily = total_return / n_days

    # Max loss (over contiguous solar intervals)
    ml_i, ml_j, ml_price = find_max_loss(rows_solar)
    ml_eur = ml_price * MW * HOURS_PER_INTERVAL
    ml_hours = (ml_j + 1 - ml_i) * 0.25

    # Longest negative
    ln_i, ln_j, ln_len = find_longest_negative(rows_solar)
    ln_hours = ln_len * 0.25
    ln_eur = sum(r["price"] * MW * HOURS_PER_INTERVAL for r in rows_solar[ln_i:ln_j + 1]) if ln_len > 0 else 0

    # Calendar-based period probabilities
    period_data = analyze_periods_solar(rows_solar)

    year_data = {
        "total_return": round(total_return, 2),
        "avg_daily": round(avg_daily, 2),
        "solar_intervals": len(rows_solar),
        "total_intervals": len(rows_all),
        "pct_solar": round(pct_solar, 1),
        "max_loss_eur": round(ml_eur, 2),
        "max_loss_hours": round(ml_hours, 1),
        "max_loss_start": rows_solar[ml_i]["start"].strftime("%Y-%m-%d"),
        "max_loss_end": rows_solar[ml_j]["end"].strftime("%Y-%m-%d"),
        "longest_neg_hours": round(ln_hours, 1),
        "longest_neg_days": round(ln_hours / 24, 1),
        "longest_neg_eur": round(ln_eur, 2),
        "longest_neg_start": rows_solar[ln_i]["start"].strftime("%Y-%m-%d") if ln_len > 0 else "",
        "longest_neg_end": rows_solar[ln_j]["end"].strftime("%Y-%m-%d") if ln_len > 0 else "",
        "periods": period_data,
    }
    all_data[label] = year_data

    print(f"{'='*60}")
    print(f" {label} SOLAR | {len(rows_solar)} daylight intervals ({pct_solar:.0f}% of total)")
    print(f" Annual return: {total_return:,.0f} EUR | Avg daily: {avg_daily:,.0f} EUR")
    print(f"{'='*60}")
    print(f"  Max loss: {ml_eur:,.0f} EUR over {ml_hours:.0f}h ({rows_solar[ml_i]['start'].date()} to {rows_solar[ml_j]['end'].date()})")
    print(f"  Longest negative: {ln_hours:.0f}h ({ln_hours/24:.1f}d solar hours), loss: {ln_eur:,.0f} EUR")
    for pname, pdata in period_data.items():
        print(f"  {pname}: {pdata['pct_negative']}% negative | worst: {pdata['worst']:,.0f} EUR | best: {pdata['best']:,.0f} EUR")
    print()

with open("solar_results.json", "w") as f:
    json.dump(all_data, f, indent=2)
print("Solar results saved to solar_results.json")
