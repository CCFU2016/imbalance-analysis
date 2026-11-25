import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
import glob
import math
from datetime import datetime, timedelta

HOURS_PER_INTERVAL = 0.25
MW = 1
INTERVALS_PER_DAY = 96
LATITUDE = 52.1
LONGITUDE = 5.3

# --- Load NL day-ahead ---
da_prices = {}
for fp in sorted(glob.glob("data/entsoe/*EnergyPrices*.csv")):
    with open(fp) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("MapCode") != "NL":
                continue
            try:
                dt = datetime.strptime(row["DateTime(UTC)"], "%Y-%m-%d %H:%M:%S")
                da_prices[dt] = float(row["Price[Currency/MWh]"])
            except (ValueError, KeyError):
                continue

def da_lookup(dt_local):
    dt_utc = dt_local - timedelta(hours=1)
    dt_hour = dt_utc.replace(minute=0, second=0, microsecond=0)
    return da_prices.get(dt_hour)

# --- Solar daylight calc ---
def calc_sunrise_sunset(date):
    day_of_year = date.timetuple().tm_yday
    lat_rad = math.radians(LATITUDE)
    gamma = 2 * math.pi * (day_of_year - 1) / 365
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2*gamma) + 0.000907 * math.sin(2*gamma)
            - 0.002697 * math.cos(3*gamma) + 0.00148 * math.sin(3*gamma))
    zenith = math.radians(90.833)
    cos_hour = (math.cos(zenith) - math.sin(lat_rad) * math.sin(decl)) / (math.cos(lat_rad) * math.cos(decl))
    cos_hour = max(-1, min(1, cos_hour))
    hour_angle = math.degrees(math.acos(cos_hour))
    eqtime = (229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
              - 0.014615 * math.cos(2*gamma) - 0.04089 * math.sin(2*gamma)))
    solar_noon_min = 720 - 4 * LONGITUDE - eqtime
    sunrise = (solar_noon_min - hour_angle * 4) / 60 + 1
    sunset = (solar_noon_min + hour_angle * 4) / 60 + 1
    return sunrise, sunset

def is_daylight(dt):
    sr, ss = calc_sunrise_sunset(dt.date())
    h = dt.hour + dt.minute / 60
    return sr <= h <= ss

# --- Residential profile ---
def residential_profile(hour, month):
    hourly = [0.40,0.35,0.32,0.30,0.30,0.35,0.50,1.10,1.40,1.30,0.90,0.80,
              0.75,0.70,0.70,0.75,0.90,1.40,1.70,1.80,1.60,1.30,1.00,0.65]
    avg = sum(hourly)/len(hourly)
    base = hourly[int(hour)] / avg
    seasonal = {1:1.30,2:1.25,3:1.10,4:0.95,5:0.88,6:0.85,7:0.85,8:0.88,9:0.95,10:1.10,11:1.20,12:1.30}
    return base * seasonal[month]

# --- Load imbalance ---
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
            start = datetime.strptime(row["Timeinterval Start Loc"], "%Y-%m-%dT%H:%M")
            rows.append({
                "start": start,
                "price": float(ps),
                "hour": start.hour + start.minute/60,
                "month": start.month,
            })
    return rows

def rolling_pct_negative(values, window):
    """Returns (pct_negative, n_total, n_negative, list of returns)"""
    if window > len(values):
        return None, 0, 0, []
    s = sum(values[:window])
    returns = [s]
    for i in range(1, len(values) - window + 1):
        s += values[i + window - 1] - values[i - 1]
        returns.append(s)
    n = sum(1 for r in returns if r < 0)
    return n / len(returns) * 100, len(returns), n, returns

print("="*80)
print("Day-ahead vs Imbalance: % negative return by window — both price types")
print("="*80)

results_simple = {}
results_profile = {}

for year, path, delim in IMBALANCE_FILES:
    rows = load_imbalance(path, delim)
    n = len(rows)

    # 1) BASELINE: pure prices (1 MW baseload, no profile)
    imb_prices = [r["price"] for r in rows]
    da_prices_aligned = [da_lookup(r["start"]) or 0 for r in rows]

    # 2) SOLAR profile (only daylight)
    solar_imb = [r["price"] if is_daylight(r["start"]) else 0 for r in rows]
    solar_da = [(da_lookup(r["start"]) or 0) if is_daylight(r["start"]) else 0 for r in rows]

    # 3) RESIDENTIAL consumption profile (cost = price * profile, NEGATIVE return = cost is negative = earning)
    # For consumption, we want probability of EARNING (negative cost)
    res_imb = [r["price"] * residential_profile(r["hour"], r["month"]) for r in rows]
    res_da = [(da_lookup(r["start"]) or 0) * residential_profile(r["hour"], r["month"]) for r in rows]

    print(f"\n{'='*80}")
    print(f" {year}")
    print(f"{'='*80}")

    # Annual averages for baseline
    imb_avg = sum(imb_prices) / n
    da_avg = sum(da_prices_aligned) / n
    print(f"  Annual avg: imb={imb_avg:.2f} | DA={da_avg:.2f}")

    year_simple = {"imb_annual": round(imb_avg, 2), "da_annual": round(da_avg, 2), "windows": {}}
    year_profile = {"baseload": {}, "solar": {}, "residential": {}}

    for name, window in [("24h", 96), ("72h", 288), ("7d", 672), ("14d", 1344)]:
        # Baseline (1 MW flat injection)
        imb_pct, _, _, imb_rets = rolling_pct_negative(imb_prices, window)
        da_pct, _, _, da_rets = rolling_pct_negative(da_prices_aligned, window)

        year_simple["windows"][name] = {
            "imb_pct": round(imb_pct, 1),
            "da_pct": round(da_pct, 1),
        }
        print(f"  {name} BASELOAD: imb={imb_pct:.1f}% neg | DA={da_pct:.1f}% neg")

        # Solar
        solar_imb_pct, _, _, _ = rolling_pct_negative(solar_imb, window)
        solar_da_pct, _, _, _ = rolling_pct_negative(solar_da, window)
        year_profile["solar"][name] = {
            "imb_pct": round(solar_imb_pct, 1),
            "da_pct": round(solar_da_pct, 1),
        }
        print(f"  {name} SOLAR:    imb={solar_imb_pct:.1f}% neg | DA={solar_da_pct:.1f}% neg")

        # Residential consumption — probability of negative cost (earning)
        res_imb_pct, _, _, _ = rolling_pct_negative(res_imb, window)
        res_da_pct, _, _, _ = rolling_pct_negative(res_da, window)
        year_profile["residential"][name] = {
            "imb_pct": round(res_imb_pct, 1),
            "da_pct": round(res_da_pct, 1),
        }
        print(f"  {name} RESI:     imb={res_imb_pct:.1f}% earning | DA={res_da_pct:.1f}% earning")

        year_profile["baseload"][name] = year_simple["windows"][name]

    results_simple[year] = year_simple
    results_profile[year] = year_profile

import json
with open("dayahead_full.json", "w") as f:
    json.dump({"baseline": results_simple, "profiles": results_profile}, f, indent=2)
print("\nSaved dayahead_full.json")
