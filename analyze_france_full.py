#!/usr/bin/env python3
"""Full French market analysis — mirrors the NL pages 1 & 2 of infographic_dayahead.

Produces france_full_results.json with everything the new FR infographic pages need:
  - Longest continuous negative return period (producer baseload)
  - Max single-period loss (producer baseload + solar)
  - Worst 24h consumer cost
  - Rolling-window probability of negative return (baseload, solar)
  - Imbalance vs DA during imbalance neg-return windows
  - Annual average price comparison
  - Profile probability tables (baseload/solar producer, flat/residential consumer,
    at €100 and €150 thresholds)
  - Most expensive periods identified on imbalance / DA (consumer, flat profile)

Price conventions for France (RTE):
  - Prix des Ecarts Positifs  = price paid for positive imbalance (over-production)
                                → producer-baseload revenue per MWh
  - Prix des Ecarts Négatifs  = price paid for negative imbalance (under-production)
                                → consumer-flat cost per MWh
"""
import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
import glob
import json
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(DIR, "france_full_results.json")

# RTE switched from 30-minute to 15-minute settlement intervals on 2025-01-01.
# The loader stores the per-row hpi and the main loop picks a year-level hpi
# (years are internally consistent).
MW = 1

# Paris coordinates for the solar scenario
LAT_FR = 48.85
LON_FR = 2.35

ENTSOE_GLOB = "data/entsoe/*EnergyPrices*.csv"
FR_IMB_GLOB = os.path.join(DIR, "FR_imbalance_data_*.csv")


# ----------------------------------------------------------------------------
# Loaders
# ----------------------------------------------------------------------------
def load_fr_imbalance():
    """Return list of {start, pos, neg, hpi} dicts sorted by start time."""
    rows = []
    for fp in sorted(glob.glob(FR_IMB_GLOB)):
        with open(fp, encoding="utf-8-sig") as f:
            f.readline()  # skip title row
            reader = csv.DictReader(f, delimiter=";")
            for r in reader:
                try:
                    dt_s = datetime.strptime(r["Heure de début"], "%d/%m/%Y %H:%M")
                    dt_e = datetime.strptime(r["Heure de fin"], "%d/%m/%Y %H:%M")
                    pos = float(r["Prix de Règlements des Ecarts Positifs (Euros/MWh)"])
                    neg = float(r["Prix de Règlements des Ecarts Négatifs (Euros/MWh)"])
                except (KeyError, ValueError, TypeError):
                    continue
                hpi = (dt_e - dt_s).total_seconds() / 3600.0
                rows.append({"start": dt_s, "pos": pos, "neg": neg, "hpi": hpi})
    rows.sort(key=lambda r: r["start"])
    return rows


def load_fr_dayahead():
    """Return dict hour_start_local → price, where hour_start_local is a naive
    CET datetime (CET=UTC+1; DST treated as constant CET, matching NL script)."""
    da = {}
    for fp in sorted(glob.glob(ENTSOE_GLOB)):
        with open(fp) as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if row.get("MapCode") != "FR":
                    continue
                try:
                    dt_utc = datetime.strptime(row["DateTime(UTC)"], "%Y-%m-%d %H:%M:%S")
                    price = float(row["Price[Currency/MWh]"])
                except (ValueError, KeyError):
                    continue
                dt_local = dt_utc + timedelta(hours=1)
                da[dt_local] = price
    return da


# ----------------------------------------------------------------------------
# Sunrise / sunset for Paris (NOAA solar calculator, simplified)
# ----------------------------------------------------------------------------
def calc_sunrise_sunset(d):
    day_of_year = d.timetuple().tm_yday
    lat_rad = math.radians(LAT_FR)
    gamma = 2 * math.pi * (day_of_year - 1) / 365
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    zenith = math.radians(90.833)
    cos_hour = (math.cos(zenith) - math.sin(lat_rad) * math.sin(decl)) / (math.cos(lat_rad) * math.cos(decl))
    cos_hour = max(-1, min(1, cos_hour))
    hour_angle = math.degrees(math.acos(cos_hour))
    eqtime = (229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
              - 0.014615 * math.cos(2 * gamma) - 0.04089 * math.sin(2 * gamma)))
    solar_noon_min = 720 - 4 * LON_FR - eqtime
    sunrise_utc = solar_noon_min - hour_angle * 4
    sunset_utc = solar_noon_min + hour_angle * 4
    sunrise_cet = sunrise_utc / 60 + 1
    sunset_cet = sunset_utc / 60 + 1
    return sunrise_cet, sunset_cet


def is_daylight(dt_start, dt_end_hour):
    sr, ss = calc_sunrise_sunset(dt_start)
    start_h = dt_start.hour + dt_start.minute / 60
    end_h = dt_end_hour
    if end_h == 0:
        end_h = 24
    midpoint = (start_h + end_h) / 2
    return sr <= midpoint <= ss


# ----------------------------------------------------------------------------
# French residential profile (Enedis RES1-style — strong evening peak, high winter lift)
# ----------------------------------------------------------------------------
def residential_profile_fr(hour, month):
    """Multiplier vs 1 MW average for a French residential consumer.

    Shape characteristics vs NL:
      - Weaker morning peak (French mornings are quieter)
      - Small lunch bump around 12-13h (French midday meal culture)
      - Very pronounced evening peak 19-21h
      - Much larger winter lift because ~35% of French homes use electric heating
    """
    hourly = [
        0.45, 0.40, 0.35, 0.32, 0.30, 0.32,   # 00-05: night base
        0.45, 0.85, 1.15, 1.00, 0.85, 0.90,   # 06-11: modest morning ramp
        1.10, 1.05, 0.80, 0.75, 0.85, 1.15,   # 12-17: lunch bump, quiet afternoon
        1.55, 1.75, 1.65, 1.35, 1.00, 0.65,   # 18-23: strong evening peak
    ]
    avg = sum(hourly) / len(hourly)
    base = hourly[int(hour)] / avg
    seasonal = {
        1: 1.55, 2: 1.50, 3: 1.20, 4: 0.95,
        5: 0.78, 6: 0.72, 7: 0.70, 8: 0.72,
        9: 0.88, 10: 1.10, 11: 1.35, 12: 1.55,
    }
    return base * seasonal[month]


# ----------------------------------------------------------------------------
# DA lookup (FR imbalance interval → hourly DA price)
# ----------------------------------------------------------------------------
def make_da_lookup(da_map):
    def lookup(dt_start):
        dt_hour = dt_start.replace(minute=0, second=0, microsecond=0)
        return da_map.get(dt_hour)
    return lookup


# ----------------------------------------------------------------------------
# Core algorithms (Kadane-style)
# ----------------------------------------------------------------------------
def find_longest_negative(values):
    """Longest contiguous subarray with negative sum."""
    prefix = [0.0]
    for v in values:
        prefix.append(prefix[-1] + v)
    best_length = 0
    best_i = 0
    best_j = -1
    max_prefix = prefix[0]
    max_idx = 0
    for j in range(len(values)):
        if prefix[j] > max_prefix:
            max_prefix = prefix[j]
            max_idx = j
        total = prefix[j + 1] - prefix[max_idx]
        if total < 0:
            length = j + 1 - max_idx
            if length > best_length:
                best_length = length
                best_i = max_idx
                best_j = j
    return best_i, best_j, best_length


def find_min_subarray(values):
    """Most negative contiguous sum."""
    prefix = [0.0]
    for v in values:
        prefix.append(prefix[-1] + v)
    best_loss = 0.0
    best_i = 0
    best_j = -1
    max_prefix = prefix[0]
    max_idx = 0
    for j in range(len(values)):
        if prefix[j] > max_prefix:
            max_prefix = prefix[j]
            max_idx = j
        loss = prefix[j + 1] - prefix[max_idx]
        if loss < best_loss:
            best_loss = loss
            best_i = max_idx
            best_j = j
    return best_i, best_j, best_loss


def find_max_subarray(values):
    """Highest contiguous sum (worst consumer cost)."""
    prefix = [0.0]
    for v in values:
        prefix.append(prefix[-1] + v)
    best = 0.0
    best_i = 0
    best_j = -1
    min_prefix = prefix[0]
    min_idx = 0
    for j in range(len(values)):
        if prefix[j] < min_prefix:
            min_prefix = prefix[j]
            min_idx = j
        gain = prefix[j + 1] - prefix[min_idx]
        if gain > best:
            best = gain
            best_i = min_idx
            best_j = j
    return best_i, best_j, best


def rolling_sums(values, window):
    """Return list of rolling-window sums (len = len(values) - window + 1)."""
    if window > len(values):
        return []
    s = sum(values[:window])
    out = [s]
    for i in range(1, len(values) - window + 1):
        s += values[i + window - 1] - values[i - 1]
        out.append(s)
    return out


# ----------------------------------------------------------------------------
# Compare helper: for a contiguous FR imbalance range, compute imb & DA stats
# ----------------------------------------------------------------------------
def compare_period(rows, i, j, da_lookup, use_neg=False):
    sub = rows[i:j + 1]
    n_intervals = len(sub)
    hpi = sub[0]["hpi"]
    n_hours = n_intervals * hpi
    n_days = n_hours / 24
    price_key = "neg" if use_neg else "pos"
    imb_prices = [r[price_key] for r in sub]
    imb_avg = sum(imb_prices) / n_intervals
    imb_total = sum(p * MW * hpi for p in imb_prices)

    da_vals = [da_lookup(r["start"]) for r in sub]
    da_vals = [v for v in da_vals if v is not None]
    if not da_vals:
        da_avg = None
        da_total = None
    else:
        da_avg = sum(da_vals) / len(da_vals)
        da_total = da_avg * MW * n_hours

    end_dt = sub[-1]["start"] + timedelta(hours=hpi)
    return {
        "start": sub[0]["start"].strftime("%Y-%m-%d %H:%M"),
        "end": end_dt.strftime("%Y-%m-%d %H:%M"),
        "n_intervals": n_intervals,
        "hours": round(n_hours, 1),
        "days": round(n_days, 2),
        "imb_avg": round(imb_avg, 2),
        "imb_total": round(imb_total, 0),
        "da_avg": round(da_avg, 2) if da_avg is not None else None,
        "da_total": round(da_total, 0) if da_total is not None else None,
        "diff_avg": round(imb_avg - da_avg, 2) if da_avg is not None else None,
        "diff_total": round(imb_total - da_total, 0) if da_total is not None else None,
    }


# ----------------------------------------------------------------------------
# Rolling probabilities — baseload producer (interval-based)
# ----------------------------------------------------------------------------
WINDOWS_HOURS = [("24h", 24), ("72h", 72), ("7d", 168), ("14d", 336), ("21d", 504), ("50d", 1200)]


def baseload_neg_probability(imb_prices_per_interval, da_hourly_aligned, hpi):
    """Return {window: {imb_pct_neg, da_pct_neg}} for a year's worth of
    interval prices. da_hourly_aligned is the DA price for the hour
    containing each interval (so len matches)."""
    out = {}
    for name, hrs in WINDOWS_HOURS:
        window = int(hrs / hpi)
        imb_sums = rolling_sums(imb_prices_per_interval, window)
        da_sums = rolling_sums(da_hourly_aligned, window)
        if not imb_sums:
            out[name] = {"imb": None, "da": None}
            continue
        imb_pct = sum(1 for s in imb_sums if s * hpi < 0) / len(imb_sums) * 100
        da_pct = sum(1 for s in da_sums if s * hpi < 0) / len(da_sums) * 100
        out[name] = {"imb": round(imb_pct, 1), "da": round(da_pct, 1)}
    return out


# ----------------------------------------------------------------------------
# Rolling probabilities — consumer (above-threshold)
# ----------------------------------------------------------------------------
def consumer_threshold_probability(weighted_prices, weights, threshold, hpi):
    """weighted_prices[i] = price_i * weight_i (cost per interval)
       weights[i]         = weight_i (the MWh consumed in interval i)
       Returns {window: {pct}} where pct is the probability the window's
       weighted average price exceeded `threshold`.
    """
    out = {}
    for name, hrs in WINDOWS_HOURS:
        window = int(hrs / hpi)
        cost_sums = rolling_sums(weighted_prices, window)
        w_sums = rolling_sums(weights, window)
        if not cost_sums:
            out[name] = None
            continue
        n_over = 0
        for cs, ws in zip(cost_sums, w_sums):
            if ws > 0 and (cs / ws) > threshold:
                n_over += 1
        pct = n_over / len(cost_sums) * 100
        out[name] = round(pct, 1)
    return out


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    print("Loading FR imbalance data …")
    imb = load_fr_imbalance()
    print(f"  {len(imb)} imbalance intervals")

    print("Loading FR day-ahead …")
    da = load_fr_dayahead()
    print(f"  {len(da)} DA hourly prices")
    da_lookup = make_da_lookup(da)

    # Split by year
    by_year = defaultdict(list)
    for r in imb:
        by_year[r["start"].year].append(r)

    results = {}
    for year in sorted(by_year):
        rows = by_year[year]
        n = len(rows)
        year_hpi = rows[0]["hpi"]
        year_ipd = int(round(24 / year_hpi))
        print(f"\n=== {year} ({n} intervals, {year_hpi*60:.0f}-min resolution) ===")

        pos_prices = [r["pos"] for r in rows]
        neg_prices = [r["neg"] for r in rows]

        # --- Annual averages
        imb_pos_avg = sum(pos_prices) / n
        imb_neg_avg = sum(neg_prices) / n

        da_vals_year = [da_lookup(r["start"]) for r in rows]
        da_vals_year_clean = [v for v in da_vals_year if v is not None]
        da_avg_year = sum(da_vals_year_clean) / len(da_vals_year_clean)

        # --- Totals for 1 MW baseload
        imb_total_baseload = sum(pos_prices) * MW * year_hpi  # using Prix Positif
        da_total_baseload = da_avg_year * MW * n * year_hpi

        # --- Longest continuous negative return (producer baseload)
        li, lj, ll = find_longest_negative(pos_prices)
        longest_neg = compare_period(rows, li, lj, da_lookup, use_neg=False) if ll > 0 else None

        # --- Max single-period loss (producer baseload)
        mi, mj, _ = find_min_subarray(pos_prices)
        max_loss = compare_period(rows, mi, mj, da_lookup, use_neg=False) if mj >= mi else None

        # --- Max single-period loss — SOLAR
        # Filter by daylight; operate on the contiguous solar subsequence
        solar_rows = []
        solar_prices = []
        for r in rows:
            end_hour = r["start"].hour + r["start"].minute / 60 + year_hpi
            if end_hour > 24:
                end_hour = 24
            if is_daylight(r["start"], end_hour):
                solar_rows.append(r)
                solar_prices.append(r["pos"])
        if solar_rows:
            smi, smj, _ = find_min_subarray(solar_prices)
            max_loss_solar = compare_period(solar_rows, smi, smj, da_lookup, use_neg=False) if smj >= smi else None
            # Total solar return
            solar_total = sum(solar_prices) * MW * year_hpi
        else:
            max_loss_solar = None
            solar_total = 0

        # --- Worst consumer cost for multiple windows (uses Prix Négatif = shortage equivalent)
        costs = [p * MW * year_hpi for p in neg_prices]
        worst_consumer = {}
        for wname, whrs in WINDOWS_HOURS:
            window = int(whrs / year_hpi)
            if n < window:
                worst_consumer[wname] = None
                continue
            csum = sum(costs[:window])
            best_sum = csum
            best_start = 0
            for k in range(1, len(costs) - window + 1):
                csum += costs[k + window - 1] - costs[k - 1]
                if csum > best_sum:
                    best_sum = csum
                    best_start = k
            wc = compare_period(rows, best_start, best_start + window - 1, da_lookup, use_neg=True)
            if wc["da_avg"]:
                premium_pct = ((wc["imb_avg"] - wc["da_avg"]) / wc["da_avg"] * 100)
                wc["premium_pct"] = round(premium_pct, 0)
            worst_consumer[wname] = wc
        worst_24h = worst_consumer.get("24h")

        # --- Probability of negative return — baseload
        # Build per-interval DA-aligned price series
        da_aligned = []
        for r in rows:
            v = da_lookup(r["start"])
            da_aligned.append(v if v is not None else 0.0)
        baseload_probs = baseload_neg_probability(pos_prices, da_aligned, year_hpi)

        # --- Imbalance vs DA during imbalance negative-return windows
        imb_vs_da_neg = {}
        for name, hrs in WINDOWS_HOURS:
            window = int(hrs / year_hpi)
            imb_sums = rolling_sums(pos_prices, window)
            da_sums = rolling_sums(da_aligned, window)
            if not imb_sums:
                imb_vs_da_neg[name] = None
                continue
            neg_idxs = [k for k, s in enumerate(imb_sums) if s < 0]
            if not neg_idxs:
                imb_vs_da_neg[name] = {"never_neg": True}
                continue
            avg_imb = sum(imb_sums[k] for k in neg_idxs) / len(neg_idxs) * year_hpi / hrs
            avg_da = sum(da_sums[k] for k in neg_idxs) / len(neg_idxs) * year_hpi / hrs
            imb_vs_da_neg[name] = {
                "n_windows": len(neg_idxs),
                "imb_avg": round(avg_imb, 0),
                "da_avg": round(avg_da, 0),
                "delta": round(avg_imb - avg_da, 0),
            }

        # --- Producer solar % negative return (daily-aggregated)
        daily_solar = defaultdict(float)
        daily_solar_da = defaultdict(float)
        for r, da_v in zip(rows, da_aligned):
            end_hour = r["start"].hour + r["start"].minute / 60 + year_hpi
            if end_hour > 24:
                end_hour = 24
            if not is_daylight(r["start"], end_hour):
                continue
            d = r["start"].date()
            daily_solar[d] += r["pos"] * MW * year_hpi
            daily_solar_da[d] += da_v * MW * year_hpi
        dates_solar = sorted(daily_solar)
        imb_daily = [daily_solar[d] for d in dates_solar]
        da_daily = [daily_solar_da[d] for d in dates_solar]

        # --- Longest negative return — solar (interval-level, daylight only)
        if solar_prices:
            sln_i, sln_j, sln_len = find_longest_negative(solar_prices)
            longest_neg_solar = compare_period(solar_rows, sln_i, sln_j, da_lookup, use_neg=False) if sln_len > 0 else None
        else:
            longest_neg_solar = None

        solar_probs = {}
        for name, days in [("24h", 1), ("72h", 3), ("7d", 7), ("14d", 14), ("21d", 21), ("50d", 50)]:
            if days > len(imb_daily):
                solar_probs[name] = {"imb": None, "da": None}
                continue
            i_sums = rolling_sums(imb_daily, days)
            d_sums = rolling_sums(da_daily, days)
            imb_pct = sum(1 for s in i_sums if s < 0) / len(i_sums) * 100
            da_pct = sum(1 for s in d_sums if s < 0) / len(d_sums) * 100
            solar_probs[name] = {"imb": round(imb_pct, 1), "da": round(da_pct, 1)}

        # --- Consumer thresholds (flat & residential)
        flat_weights = [MW * year_hpi] * n
        flat_costs_imb = [r["neg"] * w for r, w in zip(rows, flat_weights)]
        flat_costs_da = [da_aligned[k] * flat_weights[k] for k in range(n)]

        res_weights = []
        for r in rows:
            mult = residential_profile_fr(r["start"].hour, r["start"].month)
            res_weights.append(MW * mult * year_hpi)
        res_costs_imb = [r["neg"] * w for r, w in zip(rows, res_weights)]
        res_costs_da = [da_aligned[k] * res_weights[k] for k in range(n)]

        cons_flat_100 = {
            "imb": consumer_threshold_probability(flat_costs_imb, flat_weights, 100, year_hpi),
            "da": consumer_threshold_probability(flat_costs_da, flat_weights, 100, year_hpi),
        }
        cons_flat_150 = {
            "imb": consumer_threshold_probability(flat_costs_imb, flat_weights, 150, year_hpi),
            "da": consumer_threshold_probability(flat_costs_da, flat_weights, 150, year_hpi),
        }
        cons_res_100 = {
            "imb": consumer_threshold_probability(res_costs_imb, res_weights, 100, year_hpi),
            "da": consumer_threshold_probability(res_costs_da, res_weights, 100, year_hpi),
        }
        cons_res_150 = {
            "imb": consumer_threshold_probability(res_costs_imb, res_weights, 150, year_hpi),
            "da": consumer_threshold_probability(res_costs_da, res_weights, 150, year_hpi),
        }

        # --- Most expensive periods identified on imbalance vs DA (flat, 24h)
        # These are the worst-24h windows identified separately on each series.
        def worst_window(costs, window):
            if len(costs) < window:
                return None
            s = sum(costs[:window])
            best = s
            best_idx = 0
            for k in range(1, len(costs) - window + 1):
                s += costs[k + window - 1] - costs[k - 1]
                if s > best:
                    best = s
                    best_idx = k
            return best_idx, best

        w_imb = worst_window(flat_costs_imb, year_ipd)
        w_da = worst_window(flat_costs_da, year_ipd)
        exp_imb = None
        exp_da = None
        if w_imb:
            idx, total = w_imb
            exp_imb = {
                "date": rows[idx]["start"].strftime("%Y-%m-%d"),
                "imb_total": round(total, 0),
                "imb_avg": round(sum(r["neg"] for r in rows[idx:idx + year_ipd]) / year_ipd, 0),
                "da_avg": round(sum(da_aligned[idx:idx + year_ipd]) / year_ipd, 0),
            }
        if w_da:
            idx, total = w_da
            exp_da = {
                "date": rows[idx]["start"].strftime("%Y-%m-%d"),
                "da_total": round(total, 0),
                "da_avg": round(sum(da_aligned[idx:idx + year_ipd]) / year_ipd, 0),
                "imb_avg": round(sum(r["neg"] for r in rows[idx:idx + year_ipd]) / year_ipd, 0),
            }

        results[str(year)] = {
            "annual": {
                "imb_pos_avg": round(imb_pos_avg, 2),
                "imb_neg_avg": round(imb_neg_avg, 2),
                "da_avg": round(da_avg_year, 2),
                "imb_total_baseload": round(imb_total_baseload, 0),
                "da_total_baseload": round(da_total_baseload, 0),
                "solar_total_baseload": round(solar_total, 0),
            },
            "longest_negative": longest_neg,
            "max_loss_baseload": max_loss,
            "max_loss_solar": max_loss_solar,
            "longest_neg_solar": longest_neg_solar,
            "worst_24h_consumer": worst_24h,
            "worst_consumer": worst_consumer,
            "baseload_neg_prob": baseload_probs,
            "solar_neg_prob": solar_probs,
            "imb_vs_da_during_neg": imb_vs_da_neg,
            "consumer_flat_over_100": cons_flat_100,
            "consumer_flat_over_150": cons_flat_150,
            "consumer_res_over_100": cons_res_100,
            "consumer_res_over_150": cons_res_150,
            "expensive_period_on_imbalance": exp_imb,
            "expensive_period_on_da": exp_da,
        }

        print(f"  longest neg: {longest_neg}")
        print(f"  max loss:    {max_loss}")
        print(f"  worst 24h:   {worst_24h}")
        print(f"  baseload probs: {baseload_probs}")

    with open(OUT, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved → {OUT}")


if __name__ == "__main__":
    main()
