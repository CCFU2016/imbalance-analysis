#!/usr/bin/env python3
"""
Standalone test script for infographic_dayahead.html.

Reads sample values from the infographic HTML, recomputes them from the
source CSVs (imbalance + ENTSO-E day-ahead), and verifies they match.

Outputs test_results.js which is loaded by the infographic to render
the "Test Results" page (Page 3).

Usage:
    python3 test_infographic.py
"""
import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
import glob
import json
import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LATITUDE = 52.1
LONGITUDE = 5.3

# ============================================================
# CONFIG
# ============================================================
INFOGRAPHIC = "infographic_dayahead.html"
OUTPUT_JS = "test_results.js"

DA_GLOB = "data/entsoe/*EnergyPrices*.csv"
IMBALANCE_FILES = {
    "2021": ("data/tennet/settlement_prices_202012312300_202112312300.csv", ";"),
    "2022": ("data/tennet/settlement_prices_202112312300_202212312300.csv", ";"),
    "2023": ("data/tennet/settlement_prices_202212312300_202312312300.csv", ";"),
    "2024": ("data/tennet/settlement_prices_202312312300_202412312300.csv", ";"),
    "2025": ("data/tennet/settlement_prices_202412312300_202512312300_CET.csv", ","),
}

HOURS_PER_INTERVAL = 0.25
MW = 1
INTERVALS_PER_DAY = 96


# ============================================================
# DATA LOADING
# ============================================================
def load_da_prices():
    da = {}
    for fp in sorted(glob.glob(DA_GLOB)):
        with open(fp) as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if row.get("MapCode") != "NL":
                    continue
                try:
                    dt = datetime.strptime(row["DateTime(UTC)"], "%Y-%m-%d %H:%M:%S")
                    da[dt] = float(row["Price[Currency/MWh]"])
                except (ValueError, KeyError):
                    continue
    return da


def da_lookup(da_prices, dt_local):
    dt_utc = dt_local - timedelta(hours=1)
    return da_prices.get(dt_utc.replace(minute=0, second=0, microsecond=0))


def load_imbalance(filepath, delimiter):
    """Load Price Surplus, Price Shortage, AND Regulation State (for Page 5 tests)."""
    rows = []
    with open(filepath) as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        for row in reader:
            sh = row.get("Price Shortage", "").strip()
            su = row.get("Price Surplus", "").strip()
            if not sh and not su:
                continue
            start = datetime.strptime(row["Timeinterval Start Loc"], "%Y-%m-%dT%H:%M")
            state_raw = row.get("Regulation State", "").strip()
            try:
                state = int(state_raw) if state_raw else None
            except ValueError:
                state = None
            rows.append({
                "start": start,
                "price": float(su) if su else 0.0,           # Producer price (Surplus)
                "shortage": float(sh) if sh else 0.0,        # Consumer price (Shortage)
                "state": state,                               # Regulation State (-1, 0, 1, 2)
                "hour": start.hour + start.minute / 60,
                "month": start.month,
            })
    return rows


def load_fr_imbalance(year):
    """Load all 12 monthly RTE imbalance files for a year.

    File format: line 1 is a French title (skip), line 2 is the CSV header.
    Columns: Heure de début;Heure de fin;Déséquilibre(MWh);Tendance;
             Prix de Règlements des Ecarts Positifs (Euros/MWh);
             Prix de Règlements des Ecarts Négatifs (Euros/MWh)

    Interval length: 30 min for 2021–2024, 15 min for 2025+.
    """
    import io
    rows = []
    for month in range(1, 13):
        path = f"FR_imbalance_data_{year}_{month:02d}.csv"
        try:
            with open(path, encoding="utf-8-sig") as f:
                lines = f.readlines()
        except FileNotFoundError:
            continue
        if len(lines) < 2:
            continue
        # Drop the title line, keep header + data
        reader = csv.DictReader(io.StringIO("".join(lines[1:])), delimiter=";")
        for row in reader:
            start_str = (row.get("Heure de début") or "").strip()
            if not start_str:
                continue
            try:
                start = datetime.strptime(start_str, "%d/%m/%Y %H:%M")
            except ValueError:
                continue
            pos_raw = (row.get("Prix de Règlements des Ecarts Positifs (Euros/MWh)") or "").strip()
            neg_raw = (row.get("Prix de Règlements des Ecarts Négatifs (Euros/MWh)") or "").strip()
            if not pos_raw or not neg_raw or pos_raw == "N/A" or neg_raw == "N/A":
                continue
            try:
                pos_v = float(pos_raw.replace(",", "."))
                neg_v = float(neg_raw.replace(",", "."))
            except ValueError:
                continue
            rows.append({
                "start": start,
                "positive": pos_v,   # producer price (RTE Prix Positifs)
                "negative": neg_v,   # consumer price (RTE Prix Négatifs)
            })
    rows.sort(key=lambda r: r["start"])
    return rows


def fr_interval_hours(year):
    """RTE moved from 30-min to 15-min settlement intervals on 2025-01-01."""
    return 0.25 if int(year) >= 2025 else 0.5


def calc_sunrise_sunset(date):
    day_of_year = date.timetuple().tm_yday
    lat_rad = math.radians(LATITUDE)
    gamma = 2 * math.pi * (day_of_year - 1) / 365
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    zenith = math.radians(90.833)
    cos_h = (math.cos(zenith) - math.sin(lat_rad) * math.sin(decl)) / (math.cos(lat_rad) * math.cos(decl))
    cos_h = max(-1, min(1, cos_h))
    h_angle = math.degrees(math.acos(cos_h))
    eqtime = (229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
              - 0.014615 * math.cos(2 * gamma) - 0.04089 * math.sin(2 * gamma)))
    sn = 720 - 4 * LONGITUDE - eqtime
    return (sn - h_angle * 4) / 60 + 1, (sn + h_angle * 4) / 60 + 1


def is_daylight(dt):
    sr, ss = calc_sunrise_sunset(dt.date())
    h = dt.hour + dt.minute / 60
    return sr <= h <= ss


def residential_profile(hour, month):
    hourly = [0.40, 0.35, 0.32, 0.30, 0.30, 0.35, 0.50, 1.10, 1.40, 1.30, 0.90, 0.80,
              0.75, 0.70, 0.70, 0.75, 0.90, 1.40, 1.70, 1.80, 1.60, 1.30, 1.00, 0.65]
    avg = sum(hourly) / len(hourly)
    base = hourly[int(hour)] / avg
    seasonal = {1: 1.30, 2: 1.25, 3: 1.10, 4: 0.95, 5: 0.88, 6: 0.85,
                7: 0.85, 8: 0.88, 9: 0.95, 10: 1.10, 11: 1.20, 12: 1.30}
    return base * seasonal[month]


# ============================================================
# RECOMPUTATIONS
# ============================================================
def annual_avg(prices):
    return sum(prices) / len(prices)


def find_longest_negative(prices):
    """Returns (start_idx, end_idx_inclusive, length)."""
    prefix = [0.0]
    for p in prices:
        prefix.append(prefix[-1] + p)
    best_len = 0
    best_i = best_j = 0
    max_pref = prefix[0]
    max_idx = 0
    for j in range(len(prices)):
        if prefix[j] > max_pref:
            max_pref = prefix[j]
            max_idx = j
        if prefix[j + 1] - prefix[max_idx] < 0:
            length = j + 1 - max_idx
            if length > best_len:
                best_len = length
                best_i = max_idx
                best_j = j
    return best_i, best_j, best_len


def find_max_loss(prices):
    """Returns (start_idx, end_idx_inclusive, loss)."""
    prefix = [0.0]
    for p in prices:
        prefix.append(prefix[-1] + p)
    best_loss = 0
    best_i = best_j = 0
    max_pref = prefix[0]
    max_idx = 0
    for j in range(len(prices)):
        if prefix[j] > max_pref:
            max_pref = prefix[j]
            max_idx = j
        loss = prefix[j + 1] - prefix[max_idx]
        if loss < best_loss:
            best_loss = loss
            best_i = max_idx
            best_j = j
    return best_i, best_j, best_loss


def find_max_window(values, window):
    """Returns (start_idx, sum) for the contiguous window with the highest sum."""
    s = sum(values[:window])
    best = s
    best_i = 0
    for i in range(1, len(values) - window + 1):
        s += values[i + window - 1] - values[i - 1]
        if s > best:
            best = s
            best_i = i
    return best_i, best


def pct_negative_rolling(prices, window):
    if window > len(prices):
        return None
    s = sum(prices[:window])
    n_neg = 1 if s < 0 else 0
    n = 1
    for i in range(1, len(prices) - window + 1):
        s += prices[i + window - 1] - prices[i - 1]
        n += 1
        if s < 0:
            n_neg += 1
    return n_neg / n * 100


def pct_above_threshold(prices, window, threshold):
    """% of rolling windows where the simple average exceeds threshold."""
    if window > len(prices):
        return None
    s = sum(prices[:window])
    n_above = 1 if s / window > threshold else 0
    n = 1
    for i in range(1, len(prices) - window + 1):
        s += prices[i + window - 1] - prices[i - 1]
        n += 1
        if s / window > threshold:
            n_above += 1
    return n_above / n * 100


def percentile(values, p):
    """Linear-interpolation percentile (0–100). Matches numpy default."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def median(values):
    return percentile(values, 50)


def pct_above_weighted(values, weights, window, threshold):
    """% of rolling windows where the weighted average exceeds threshold.
    values[i] = price[i] * weight[i]
    """
    if window > len(values):
        return None
    s_v = sum(values[:window])
    s_w = sum(weights[:window])
    n_above = 1 if s_v / s_w > threshold else 0
    n = 1
    for i in range(1, len(values) - window + 1):
        s_v += values[i + window - 1] - values[i - 1]
        s_w += weights[i + window - 1] - weights[i - 1]
        n += 1
        if s_v / s_w > threshold:
            n_above += 1
    return n_above / n * 100


# ============================================================
# HTML PARSING — extract sample values
# ============================================================
def parse_html(path):
    with open(path) as f:
        return f.read()


def extract_annual_avgs(html):
    """Extracts the annual average prices from the 'Annual Average Price Comparison' table.
    Returns dict: {year: {'imb': float, 'da': float}}
    """
    # Look for the section after 'Annual Average Price Comparison'
    section_match = re.search(
        r'Annual Average Price Comparison.*?</tbody>',
        html, re.DOTALL,
    )
    if not section_match:
        return {}
    block = section_match.group(0)

    # Pattern: <td>YEAR</td>...<td class="val-imb">VALUE</td>...<td class="val-da">VALUE</td>
    rows = re.findall(
        r'<td>(\d{4})</td>\s*<td class="val-imb">([\d\.\-]+)</td>\s*<td class="val-da">([\d\.\-]+)</td>',
        block,
    )
    return {y: {"imb": float(i), "da": float(d)} for y, i, d in rows}


def extract_max_loss_table(html):
    """Extract values from 'Maximum Single-Period Loss' table.
    Returns dict: {year: {'imb_per_mwh': float, 'imb_total': int, 'da_per_mwh': float, 'duration': str, 'period': str}}
    """
    section_match = re.search(
        r'Producer: Maximum Single-Period Loss.*?</tbody>',
        html, re.DOTALL,
    )
    if not section_match:
        return {}
    block = section_match.group(0)

    rows = re.findall(
        r'<td>(\d{4})</td>\s*'
        r'<td style="font-size:11px">([^<]+)</td>\s*'
        r'<td>(\d+h)</td>\s*'
        r'<td class="val-imb">([\-\d\.]+)<br>\s*<span[^>]*>\(([\-\d,]+)\)</span></td>\s*'
        r'<td class="val-da">([\+\-\d\.]+)<br>',
        block,
    )
    out = {}
    for year, period, dur, imb_pmwh, imb_total, da_pmwh in rows:
        out[year] = {
            "period": period.strip(),
            "duration": dur,
            "imb_per_mwh": float(imb_pmwh),
            "imb_total": int(imb_total.replace(",", "")),
            "da_per_mwh": float(da_pmwh),
        }
    return out


def extract_longest_negative(html):
    """Extract longest continuous negative return periods (one per year)."""
    section = re.search(
        r"Producer \(Injection\): Longest Continuous Negative Return.*?</tbody>",
        html, re.DOTALL,
    )
    if not section:
        return {}
    block = section.group(0)
    rows = re.findall(
        r'<td>(\d{4})</td>\s*'
        r'<td style="font-size:11px">([^<]+)</td>\s*'
        r'<td>([\d\.]+)d / (\d+)h</td>\s*'
        r'<td class="val-imb">([\-\d\.]+)<br>\s*<span[^>]*>\(([\-\d,]+)\)</span></td>\s*'
        r'<td class="val-da">([\+\-\d\.]+)<br>',
        block,
    )
    out = {}
    for year, period, days, hours, imb_pmwh, imb_total, da_pmwh in rows:
        out[year] = {
            "period": period.strip(),
            "days": float(days),
            "hours": int(hours),
            "imb_per_mwh": float(imb_pmwh),
            "imb_total": int(imb_total.replace(",", "")),
            "da_per_mwh": float(da_pmwh),
        }
    return out


def extract_worst_consumer_24h(html):
    """Extract Consumer: Worst 24h Cost values per year (page 1)."""
    section = re.search(
        r"Consumer: Worst 24-Hour Cost.*?</tbody>",
        html, re.DOTALL,
    )
    if not section:
        return {}
    block = section.group(0)
    rows = re.findall(
        r'<td>(\d{4})</td>\s*'
        r'<td style="font-size:11px">[^<]+</td>\s*'
        r'<td class="val-imb">([\+\-\d\.]+)<br>\s*<span[^>]*>\(([\+\-\d,]+)\)</span></td>\s*'
        r'<td class="val-da">([\+\-\d\.]+)<br>',
        block,
    )
    out = {}
    for year, imb_pmwh, imb_total, da_pmwh in rows:
        out[year] = {
            "imb_per_mwh": float(imb_pmwh),
            "imb_total": int(imb_total.replace("+", "").replace(",", "")),
            "da_per_mwh": float(da_pmwh),
        }
    return out


def extract_pct_table(html, section_title):
    """Generic parser for any 5-year × 2-column probability table.
    Returns: {window: {year: {imb_pct, da_pct}}}
    """
    section = re.search(
        re.escape(section_title) + r".*?</tbody>",
        html, re.DOTALL,
    )
    if not section:
        return {}
    block = section.group(0)
    rows = re.findall(
        r'<td>(24h|72h|7d|14d|21d)</td>\s*'
        r'<td class="val-imb">([\d\.]+)%</td><td class="val-da">([\d\.]+)%</td>\s*'
        r'<td class="val-imb">([\d\.]+)%</td><td class="val-da">([\d\.]+)%</td>\s*'
        r'<td class="val-imb">([\d\.]+)%</td><td class="val-da">([\d\.]+)%</td>\s*'
        r'<td class="val-imb">([\d\.]+)%</td><td class="val-da">([\d\.]+)%</td>\s*'
        r'<td class="val-imb">([\d\.]+)%</td><td class="val-da">([\d\.]+)%</td>',
        block,
    )
    years = ["2021", "2022", "2023", "2024", "2025"]
    out = {}
    for r in rows:
        window = r[0]
        out[window] = {}
        for i, year in enumerate(years):
            out[window][year] = {
                "imb_pct": float(r[1 + i * 2]),
                "da_pct": float(r[2 + i * 2]),
            }
    return out


def extract_baseload_pct_table(html):
    return extract_pct_table(html, "Producer — Baseload (1 MW 24/7): % Negative Return")


def extract_consumer_expensive(html, section_title):
    """Parse a 'most expensive periods' table. Returns list of dicts with
    year, window, period, primary_total, primary_pmwh, secondary_total, secondary_pmwh.
    Walks through rows tracking current year (because the year cell only appears
    on the first row of each 5-row group via rowspan).
    """
    section = re.search(
        re.escape(section_title) + r".*?</tbody>",
        html, re.DOTALL,
    )
    if not section:
        return []
    block = section.group(0)

    # Split into individual <tr>...</tr>
    tr_re = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
    out = []
    current_year = None
    for tr_match in tr_re.finditer(block):
        tr = tr_match.group(1)
        # Try to find year (only present on first row of each group)
        year_m = re.search(r'<td rowspan="5">(\d{4})</td>', tr)
        if year_m:
            current_year = year_m.group(1)

        # Try to find window
        window_m = re.search(r"<td>(24h|72h|7d|14d|21d)</td>", tr)
        if not window_m:
            continue
        window = window_m.group(1)

        # Find period
        period_m = re.search(r'<td style="font-size:10px">([^<]+)</td>', tr)
        if not period_m:
            continue
        period = period_m.group(1).strip()

        # Find the two value cells: each has total and (per-MWh) in parens
        value_cells = re.findall(
            r'<td class="(?:val-imb|val-da)">([\d,\.]+)\s*<span[^>]*>\(([\d,]+)\)</span></td>',
            tr,
        )
        if len(value_cells) < 2:
            continue
        primary_total, primary_pmwh = value_cells[0]
        secondary_total, secondary_pmwh = value_cells[1]

        out.append({
            "year": current_year,
            "window": window,
            "period": period,
            "primary_total": int(primary_total.replace(",", "")),
            "primary_pmwh": int(primary_pmwh.replace(",", "")),
            "secondary_total": int(secondary_total.replace(",", "")),
            "secondary_pmwh": int(secondary_pmwh.replace(",", "")),
        })
    return out


# ============================================================
# PAGE 5 EXTRACTORS — Portfolio Benefits / Regulation State 2
# ============================================================
def extract_state_distribution(html):
    """Regulation State Distribution table.
    Returns: {year: {-1|0|1|2: (count, pct), 'total': int}}
    """
    section = re.search(r"Regulation State Distribution.*?</tbody>", html, re.DOTALL)
    if not section:
        return {}
    rows = re.findall(
        r'<tr>\s*<td>(\d{4})</td>\s*'
        r'<td>([\d,]+)\s*\(([\d\.]+)%\)</td>\s*'
        r'<td>([\d,]+)\s*\(([\d\.]+)%\)</td>\s*'
        r'<td>([\d,]+)\s*\(([\d\.]+)%\)</td>\s*'
        r'<td class="val-imb">([\d,]+)\s*\(([\d\.]+)%\)</td>\s*'
        r'<td>([\d,]+)</td>',
        section.group(0),
    )
    out = {}
    for r in rows:
        out[r[0]] = {
            -1: (int(r[1].replace(",", "")), float(r[2])),
            0: (int(r[3].replace(",", "")), float(r[4])),
            1: (int(r[5].replace(",", "")), float(r[6])),
            2: (int(r[7].replace(",", "")), float(r[8])),
            "total": int(r[9].replace(",", "")),
        }
    return out


def extract_state2_duration(html):
    """State 2 Duration per Year table.
    Returns: {year: {intervals, hours, days, pct}}
    """
    section = re.search(r"State 2 Duration per Year.*?</tbody>", html, re.DOTALL)
    if not section:
        return {}
    rows = re.findall(
        r'<tr>\s*<td>(\d{4})</td>\s*'
        r'<td>([\d,]+)</td>\s*'
        r'<td>([\d,]+)</td>\s*'
        r'<td>([\d\.]+)</td>\s*'
        r'<td class="val-imb">([\d\.]+)%</td>',
        section.group(0),
    )
    out = {}
    for year, intervals, hours, days, pct in rows:
        out[year] = {
            "intervals": int(intervals.replace(",", "")),
            "hours": int(hours.replace(",", "")),
            "days": float(days),
            "pct": float(pct),
        }
    return out


def extract_state2_spread(html):
    """Price Spread During State 2 table.
    Returns: {year: {avg, median, min, max}}
    """
    section = re.search(r"Price Spread During State 2.*?</tbody>", html, re.DOTALL)
    if not section:
        return {}
    rows = re.findall(
        r'<tr>\s*<td>(\d{4})</td>\s*'
        r'<td class="val-imb">([\d\.,]+)</td>\s*'
        r'<td>([\d\.,]+)</td>\s*'
        r'<td>([\d\.,]+)</td>\s*'
        r'<td class="val-diff-neg">([\d\.,]+)</td>',
        section.group(0),
    )
    out = {}
    for year, avg, med, mn, mx in rows:
        out[year] = {
            "avg": float(avg.replace(",", "")),
            "median": float(med.replace(",", "")),
            "min": float(mn.replace(",", "")),
            "max": float(mx.replace(",", "")),
        }
    return out


def extract_total_spread(html):
    """Total Annual Spread NL vs FR table (skips the Σ totals row).
    Returns: {year: {nl_total, nl_avg, nl_p90, fr_total, fr_avg, fr_p90}}
    """
    section = re.search(
        r"Total Annual Spread.*?Two 1 MW Assets.*?</tbody>",
        html, re.DOTALL,
    )
    if not section:
        return {}
    rows = re.findall(
        r'<tr>\s*<td>(\d{4})</td>\s*'
        r'<td class="val-diff-neg"[^>]*>([\d,]+)</td>\s*<td>([\d\.]+)</td>\s*<td>([\d\.]+)</td>\s*'
        r'<td class="val-diff-neg"[^>]*>([\d,]+)</td>\s*<td>([\d\.]+)</td>\s*<td>([\d\.]+)</td>',
        section.group(0),
    )
    out = {}
    for r in rows:
        out[r[0]] = {
            "nl_total": int(r[1].replace(",", "")),
            "nl_avg": float(r[2]),
            "nl_p90": float(r[3]),
            "fr_total": int(r[4].replace(",", "")),
            "fr_avg": float(r[5]),
            "fr_p90": float(r[6]),
        }
    return out


# ============================================================
# TEST RUNNER
# ============================================================
def extract_percentiles(html, section_id):
    """Extract a percentile table written by nl_percentiles.py ('nl-percentiles' for
    prices, 'nl-spread-percentiles' for imbalance − day-ahead).
    Returns dict: {(side, label): [p50, p75, p90, p95, p98, p99, max]}
    """
    block = re.search(rf'id="{section_id}".*?</table>', html, re.DOTALL)
    if not block:
        return {}
    out = {}
    for side, label, row in re.findall(
        r'<tr data-side="([^"]+)" data-label="([^"]+)"[^>]*>(.*?)</tr>', block.group(0), re.DOTALL,
    ):
        vals = re.findall(r'<td class="val-imb">(-?[\d,]+)</td>', row)
        vals += re.findall(r'<td>(-?[\d,]+)</td>\s*$', row)  # Max (last cell)
        out[(side, label)] = [float(v.replace(",", "")) for v in vals]
    return out


AMS = ZoneInfo("Europe/Amsterdam")


def utc_starts(rows):
    """UTC start of each imbalance row. TenneT 'Loc' times follow summer time; the
    repeated autumn hour appears twice in file order, the second time is fold=1."""
    seen, out = set(), []
    for r in rows:
        fold = 1 if r["start"] in seen else 0
        seen.add(r["start"])
        out.append(r["start"].replace(tzinfo=AMS, fold=fold).astimezone(timezone.utc).replace(tzinfo=None))
    return out


def da_exact(da_prices, dt_utc):
    """Day-ahead for a quarter-hour: 15-min price when published (Oct 2025+), else the hour's."""
    p = da_prices.get(dt_utc)
    return p if p is not None else da_prices.get(dt_utc.replace(minute=0))


def make_test(name, expected, actual, tolerance, unit=""):
    diff = abs(expected - actual)
    passed = diff <= tolerance
    return {
        "name": name,
        "expected": round(expected, 4),
        "actual": round(actual, 4),
        "diff": round(diff, 4),
        "tolerance": tolerance,
        "unit": unit,
        "passed": passed,
    }


def run_tests():
    print("Loading data...")
    da_prices = load_da_prices()
    print(f"  Loaded {len(da_prices)} day-ahead price points")

    imbalance_data = {}
    for year, (path, delim) in IMBALANCE_FILES.items():
        rows = load_imbalance(path, delim)
        imbalance_data[year] = rows
        print(f"  Loaded {len(rows)} imbalance intervals for {year}")

    print("\nReading infographic...")
    html = parse_html(INFOGRAPHIC)

    print("Extracting sample values from HTML...")
    sample_annual = extract_annual_avgs(html)
    sample_maxloss = extract_max_loss_table(html)
    sample_longest = extract_longest_negative(html)
    sample_worst_consumer = extract_worst_consumer_24h(html)
    sample_baseload_pct = extract_pct_table(html, "Producer — Baseload (1 MW 24/7): % Negative Return")
    sample_solar_pct = extract_pct_table(html, "Producer — Solar (1 MW Daylight Only): % Negative Return")
    sample_flat_100 = extract_pct_table(html, "Consumer — Flat (1 MW 24/7): % of Periods with Average Price &gt; 100")
    sample_resi_100 = extract_pct_table(html, "Consumer — Residential Profile: % of Periods with Average Price &gt; 100")
    sample_flat_150 = extract_pct_table(html, "Consumer — Flat (1 MW 24/7): % of Periods with Average Price &gt; 150")
    sample_resi_150 = extract_pct_table(html, "Consumer — Residential Profile: % of Periods with Average Price &gt; 150")
    sample_page1_pct = extract_pct_table(html, "Probability of Negative Return — Imbalance vs Day-Ahead (1 MW Baseload)")
    sample_exp_imb = extract_consumer_expensive(
        html,
        'Consumer — Most Expensive Periods Identified on <span style="color:#ff6600">Imbalance',
    )
    sample_exp_da = extract_consumer_expensive(
        html,
        'Consumer — Most Expensive Periods Identified on <span style="color:#3c3c3c">Day-Ahead',
    )

    print(f"  Found annual averages for: {sorted(sample_annual.keys())}")
    print(f"  Found max-loss entries for: {sorted(sample_maxloss.keys())}")
    print(f"  Found longest-negative entries for: {sorted(sample_longest.keys())}")
    print(f"  Found worst 24h consumer entries for: {sorted(sample_worst_consumer.keys())}")
    print(f"  Found baseload prob windows: {sorted(sample_baseload_pct.keys())}")
    print(f"  Found solar prob windows: {sorted(sample_solar_pct.keys())}")
    print(f"  Found flat>100 windows: {sorted(sample_flat_100.keys())}")
    print(f"  Found resi>100 windows: {sorted(sample_resi_100.keys())}")
    print(f"  Found flat>150 windows: {sorted(sample_flat_150.keys())}")
    print(f"  Found resi>150 windows: {sorted(sample_resi_150.keys())}")
    print(f"  Found page-1 baseload prob windows: {sorted(sample_page1_pct.keys())}")
    print(f"  Found imb-most-expensive entries: {len(sample_exp_imb)}")
    print(f"  Found DA-most-expensive entries: {len(sample_exp_da)}")

    tests = []
    print("\nRunning tests...")

    # ----- Annual averages (imbalance and day-ahead) -----
    for year, vals in sample_annual.items():
        rows = imbalance_data[year]
        imb_prices = [r["price"] for r in rows]
        da_aligned = [da_lookup(da_prices, r["start"]) or 0 for r in rows]

        actual_imb = annual_avg(imb_prices)
        actual_da = annual_avg(da_aligned)

        tests.append(make_test(
            f"{year} annual avg imbalance price",
            vals["imb"], actual_imb, 0.05, "EUR/MWh",
        ))
        tests.append(make_test(
            f"{year} annual avg day-ahead price",
            vals["da"], actual_da, 0.05, "EUR/MWh",
        ))

    # ----- Maximum single-period loss -----
    for year, vals in sample_maxloss.items():
        rows = imbalance_data[year]
        imb_prices = [r["price"] for r in rows]
        i, j, loss = find_max_loss(imb_prices)
        period_prices = imb_prices[i:j + 1]
        actual_avg_per_mwh = sum(period_prices) / len(period_prices)
        actual_total_eur = loss * MW * HOURS_PER_INTERVAL

        # DA over same window
        period_da = [da_lookup(da_prices, rows[k]["start"]) or 0 for k in range(i, j + 1)]
        actual_da_per_mwh = sum(period_da) / len(period_da)

        tests.append(make_test(
            f"{year} max loss avg EUR/MWh (imbalance)",
            vals["imb_per_mwh"], actual_avg_per_mwh, 0.05, "EUR/MWh",
        ))
        tests.append(make_test(
            f"{year} max loss total EUR (imbalance)",
            vals["imb_total"], actual_total_eur, 1, "EUR",
        ))
        tests.append(make_test(
            f"{year} max loss avg EUR/MWh (day-ahead, same period)",
            vals["da_per_mwh"], actual_da_per_mwh, 0.05, "EUR/MWh",
        ))

    # ----- Longest continuous negative return -----
    for year, vals in sample_longest.items():
        rows = imbalance_data[year]
        imb_prices = [r["price"] for r in rows]
        i, j, length = find_longest_negative(imb_prices)
        if length == 0:
            continue
        period_prices = imb_prices[i:j + 1]
        actual_avg = sum(period_prices) / len(period_prices)
        actual_total = sum(period_prices) * MW * HOURS_PER_INTERVAL
        actual_hours = length * 0.25

        tests.append(make_test(
            f"{year} longest negative streak hours",
            vals["hours"], actual_hours, 0.5, "h",
        ))
        tests.append(make_test(
            f"{year} longest negative streak avg EUR/MWh",
            vals["imb_per_mwh"], actual_avg, 0.05, "EUR/MWh",
        ))
        tests.append(make_test(
            f"{year} longest negative streak total EUR",
            vals["imb_total"], actual_total, 1, "EUR",
        ))

    # ----- Worst 24h consumer cost (uses Price Shortage) -----
    for year, vals in sample_worst_consumer.items():
        rows = imbalance_data[year]
        consumer_prices = [r["shortage"] for r in rows]
        i, total = find_max_window(consumer_prices, 96)
        actual_avg = total / 96
        actual_total = total * MW * HOURS_PER_INTERVAL
        period_da = [da_lookup(da_prices, rows[k]["start"]) or 0 for k in range(i, i + 96)]
        actual_da_avg = sum(period_da) / 96

        tests.append(make_test(
            f"{year} worst 24h consumer imbalance shortage EUR/MWh",
            vals["imb_per_mwh"], actual_avg, 0.05, "EUR/MWh",
        ))
        tests.append(make_test(
            f"{year} worst 24h consumer imbalance shortage total EUR",
            vals["imb_total"], actual_total, 1, "EUR",
        ))
        tests.append(make_test(
            f"{year} worst 24h consumer day-ahead EUR/MWh (same window)",
            vals["da_per_mwh"], actual_da_avg, 0.05, "EUR/MWh",
        ))

    # ----- Baseload probability of negative return (page 1 + page 2) -----
    window_intervals = {"24h": 96, "72h": 288, "7d": 672, "14d": 1344, "21d": 2016}

    def add_pct_tests(table, label, value_func_imb, value_func_da):
        for window_name, year_data in table.items():
            window = window_intervals[window_name]
            for year, pcts in year_data.items():
                rows = imbalance_data[year]
                actual_imb_pct = value_func_imb(rows, window)
                actual_da_pct = value_func_da(rows, window)
                tests.append(make_test(
                    f"{year} {window_name} {label} imb",
                    pcts["imb_pct"], actual_imb_pct, 0.1, "%",
                ))
                tests.append(make_test(
                    f"{year} {window_name} {label} DA",
                    pcts["da_pct"], actual_da_pct, 0.1, "%",
                ))

    def baseload_neg_imb(rows, window):
        return pct_negative_rolling([r["price"] for r in rows], window)

    def baseload_neg_da(rows, window):
        return pct_negative_rolling([da_lookup(da_prices, r["start"]) or 0 for r in rows], window)

    def solar_neg_imb(rows, window):
        return pct_negative_rolling(
            [r["price"] if is_daylight(r["start"]) else 0 for r in rows], window,
        )

    def solar_neg_da(rows, window):
        return pct_negative_rolling(
            [(da_lookup(da_prices, r["start"]) or 0) if is_daylight(r["start"]) else 0 for r in rows], window,
        )

    # Consumer perspective uses Price Shortage
    def flat_above_imb_factory(threshold):
        def f(rows, window):
            return pct_above_threshold([r["shortage"] for r in rows], window, threshold)
        return f

    def flat_above_da_factory(threshold):
        def f(rows, window):
            return pct_above_threshold([da_lookup(da_prices, r["start"]) or 0 for r in rows], window, threshold)
        return f

    def resi_above_imb_factory(threshold):
        def f(rows, window):
            weights = [residential_profile(r["hour"], r["month"]) for r in rows]
            values = [r["shortage"] * w for r, w in zip(rows, weights)]
            return pct_above_weighted(values, weights, window, threshold)
        return f

    def resi_above_da_factory(threshold):
        def f(rows, window):
            weights = [residential_profile(r["hour"], r["month"]) for r in rows]
            values = [(da_lookup(da_prices, r["start"]) or 0) * w for r, w in zip(rows, weights)]
            return pct_above_weighted(values, weights, window, threshold)
        return f

    add_pct_tests(sample_baseload_pct, "% neg baseload (page 2)", baseload_neg_imb, baseload_neg_da)
    add_pct_tests(sample_page1_pct, "% neg baseload (page 1)", baseload_neg_imb, baseload_neg_da)
    add_pct_tests(sample_solar_pct, "% neg solar", solar_neg_imb, solar_neg_da)
    add_pct_tests(sample_flat_100, "% flat >100", flat_above_imb_factory(100), flat_above_da_factory(100))
    add_pct_tests(sample_resi_100, "% resi >100", resi_above_imb_factory(100), resi_above_da_factory(100))
    add_pct_tests(sample_flat_150, "% flat >150", flat_above_imb_factory(150), flat_above_da_factory(150))
    add_pct_tests(sample_resi_150, "% resi >150", resi_above_imb_factory(150), resi_above_da_factory(150))

    # ----- Consumer most expensive periods (uses Price Shortage) -----
    window_intervals_full = {"24h": 96, "72h": 288, "7d": 672, "14d": 1344, "21d": 2016}

    # IMBALANCE-IDENTIFIED most expensive (using Price Shortage)
    for entry in sample_exp_imb:
        year = entry["year"]
        window = window_intervals_full[entry["window"]]
        rows = imbalance_data[year]
        consumer_prices = [r["shortage"] for r in rows]
        i, total = find_max_window(consumer_prices, window)
        actual_total = total * MW * HOURS_PER_INTERVAL
        actual_pmwh = total / window
        period_da = [da_lookup(da_prices, rows[k]["start"]) or 0 for k in range(i, i + window)]
        actual_da_total = sum(period_da) * MW * HOURS_PER_INTERVAL
        actual_da_pmwh = sum(period_da) / window

        tests.append(make_test(
            f"{year} {entry['window']} most expensive (shortage-based) — shortage total",
            entry["primary_total"], actual_total, 1, "EUR",
        ))
        tests.append(make_test(
            f"{year} {entry['window']} most expensive (shortage-based) — shortage EUR/MWh",
            entry["primary_pmwh"], actual_pmwh, 0.7, "EUR/MWh",
        ))
        tests.append(make_test(
            f"{year} {entry['window']} most expensive (shortage-based) — DA same window total",
            entry["secondary_total"], actual_da_total, 1, "EUR",
        ))
        tests.append(make_test(
            f"{year} {entry['window']} most expensive (shortage-based) — DA same window EUR/MWh",
            entry["secondary_pmwh"], actual_da_pmwh, 0.7, "EUR/MWh",
        ))

    # DAY-AHEAD-IDENTIFIED most expensive (imbalance same window uses Price Shortage)
    for entry in sample_exp_da:
        year = entry["year"]
        window = window_intervals_full[entry["window"]]
        rows = imbalance_data[year]
        da_aligned = [da_lookup(da_prices, r["start"]) or 0 for r in rows]
        i, total = find_max_window(da_aligned, window)
        actual_da_total = total * MW * HOURS_PER_INTERVAL
        actual_da_pmwh = total / window
        period_imb = [rows[k]["shortage"] for k in range(i, i + window)]
        actual_imb_total = sum(period_imb) * MW * HOURS_PER_INTERVAL
        actual_imb_pmwh = sum(period_imb) / window

        tests.append(make_test(
            f"{year} {entry['window']} most expensive (DA-based) — DA total",
            entry["primary_total"], actual_da_total, 1, "EUR",
        ))
        tests.append(make_test(
            f"{year} {entry['window']} most expensive (DA-based) — DA EUR/MWh",
            entry["primary_pmwh"], actual_da_pmwh, 0.5, "EUR/MWh",
        ))
        tests.append(make_test(
            f"{year} {entry['window']} most expensive (DA-based) — shortage same window total",
            entry["secondary_total"], actual_imb_total, 1, "EUR",
        ))
        tests.append(make_test(
            f"{year} {entry['window']} most expensive (DA-based) — shortage same window EUR/MWh",
            entry["secondary_pmwh"], actual_imb_pmwh, 0.7, "EUR/MWh",
        ))

    # ========================================================
    # PAGE 5 — Portfolio Benefits / Regulation State 2 (NL + FR)
    # ========================================================
    sample_state_dist = extract_state_distribution(html)
    sample_state2_dur = extract_state2_duration(html)
    sample_state2_spr = extract_state2_spread(html)
    sample_total_spread = extract_total_spread(html)
    print(f"  Found state distribution years: {sorted(sample_state_dist.keys())}")
    print(f"  Found state-2 duration years: {sorted(sample_state2_dur.keys())}")
    print(f"  Found state-2 spread years: {sorted(sample_state2_spr.keys())}")
    print(f"  Found total-spread years: {sorted(sample_total_spread.keys())}")

    # ----- Regulation state distribution -----
    for year, dist in sample_state_dist.items():
        rows = imbalance_data[year]
        counts = {-1: 0, 0: 0, 1: 0, 2: 0}
        for r in rows:
            if r["state"] in counts:
                counts[r["state"]] += 1
        total = sum(counts.values())
        for s in (-1, 0, 1, 2):
            exp_count, exp_pct = dist[s]
            tests.append(make_test(
                f"{year} reg state {s} interval count",
                exp_count, counts[s], 1, "intervals",
            ))
            tests.append(make_test(
                f"{year} reg state {s} percentage",
                exp_pct, counts[s] / total * 100, 0.05, "%",
            ))
        tests.append(make_test(
            f"{year} reg state total intervals",
            dist["total"], total, 1, "intervals",
        ))

    # ----- State 2 duration -----
    for year, dur in sample_state2_dur.items():
        rows = imbalance_data[year]
        s2 = sum(1 for r in rows if r["state"] == 2)
        tests.append(make_test(
            f"{year} State 2 intervals",
            dur["intervals"], s2, 1, "intervals",
        ))
        tests.append(make_test(
            f"{year} State 2 hours",
            dur["hours"], s2 * 0.25, 0.5, "h",
        ))
        tests.append(make_test(
            f"{year} State 2 days equivalent",
            dur["days"], s2 * 0.25 / 24, 0.05, "d",
        ))
        tests.append(make_test(
            f"{year} State 2 % of year",
            dur["pct"], s2 / len(rows) * 100, 0.05, "%",
        ))

    # ----- Spread during State 2 -----
    for year, spr in sample_state2_spr.items():
        rows = imbalance_data[year]
        spreads = [abs(r["shortage"] - r["price"]) for r in rows if r["state"] == 2]
        if not spreads:
            continue
        tests.append(make_test(
            f"{year} State 2 avg spread",
            spr["avg"], sum(spreads) / len(spreads), 0.05, "EUR/MWh",
        ))
        tests.append(make_test(
            f"{year} State 2 median spread",
            spr["median"], median(spreads), 0.05, "EUR/MWh",
        ))
        tests.append(make_test(
            f"{year} State 2 min spread",
            spr["min"], min(spreads), 0.01, "EUR/MWh",
        ))
        tests.append(make_test(
            f"{year} State 2 max spread",
            spr["max"], max(spreads), 0.05, "EUR/MWh",
        ))

    # ----- Total Annual Spread NL vs FR (two 1 MW assets, opposite sides) -----
    if sample_total_spread:
        print("\nLoading French RTE imbalance data...")
        fr_data = {}
        for year in sorted(sample_total_spread.keys()):
            fr_rows = load_fr_imbalance(year)
            fr_data[year] = fr_rows
            print(f"  Loaded {len(fr_rows)} FR intervals for {year}")

        for year, spread in sample_total_spread.items():
            # NL side: |Shortage − Surplus| × 0.25h, summed over the year
            rows = imbalance_data[year]
            nl_spreads = [abs(r["shortage"] - r["price"]) for r in rows]
            tests.append(make_test(
                f"{year} NL total annual spread",
                spread["nl_total"], sum(nl_spreads) * HOURS_PER_INTERVAL, 5, "EUR",
            ))
            tests.append(make_test(
                f"{year} NL avg spread per MWh",
                spread["nl_avg"], sum(nl_spreads) / len(nl_spreads), 0.05, "EUR/MWh",
            ))
            tests.append(make_test(
                f"{year} NL p90 spread per MWh",
                spread["nl_p90"], percentile(nl_spreads, 90), 0.05, "EUR/MWh",
            ))

            # FR side: |Négatifs − Positifs| × interval_h, summed over the year
            fr_rows = fr_data.get(year, [])
            if fr_rows:
                fr_spreads = [abs(r["negative"] - r["positive"]) for r in fr_rows]
                fr_h = fr_interval_hours(year)
                tests.append(make_test(
                    f"{year} FR total annual spread",
                    spread["fr_total"], sum(fr_spreads) * fr_h, 50, "EUR",
                ))
                tests.append(make_test(
                    f"{year} FR avg spread per MWh",
                    spread["fr_avg"], sum(fr_spreads) / len(fr_spreads), 0.05, "EUR/MWh",
                ))
                tests.append(make_test(
                    f"{year} FR p90 spread per MWh",
                    spread["fr_p90"], percentile(fr_spreads, 90), 0.1, "EUR/MWh",
                ))

    # --- NL imbalance price + imbalance − DA spread percentiles (page 1, whole-euro display) ---
    years = sorted(imbalance_data)
    rows_with_da = {}
    for y in years:
        rows_with_da[y] = [
            (r, p) for r, t in zip(imbalance_data[y], utc_starts(imbalance_data[y]))
            if (p := da_exact(da_prices, t)) is not None
        ]
    pooled = f"{years[0]}–{years[-1]}"
    for section_id, is_spread in (("nl-percentiles", False), ("nl-spread-percentiles", True)):
        table = extract_percentiles(html, section_id)
        if not table:
            tests.append(make_test(f"{section_id} table present", 1, 0, 0))
        for (side, label), shown in sorted(table.items()):
            if label not in years and label != pooled:
                continue  # YTD / rolling rows come from files outside IMBALANCE_FILES
            key = "price" if side.startswith("Surplus") else "shortage"
            ys = years if label == pooled else [label]
            if is_spread:
                values = [r[key] - p for y in ys for r, p in rows_with_da[y]]
            else:
                values = [r[key] for y in ys for r in imbalance_data[y]]
            expected = [percentile(values, p) for p in (50, 75, 90, 95, 98, 99)] + [max(values)]
            tests.append(make_test(f"{label} NL {side} percentile columns", 7, len(shown), 0))
            for name, computed, on_page in zip(("P50", "P75", "P90", "P95", "P98", "P99", "max"), expected, shown):
                tests.append(make_test(f"{label} NL {side} {name}", on_page, computed, 0.51, "EUR/MWh"))

    return tests


def write_results(tests):
    n_total = len(tests)
    n_pass = sum(1 for t in tests if t["passed"])
    n_fail = n_total - n_pass

    summary = {
        "total": n_total,
        "passed": n_pass,
        "failed": n_fail,
        "pass_rate": round(n_pass / n_total * 100, 1) if n_total else 0,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tests": tests,
    }

    js = f"window.testResults = {json.dumps(summary, indent=2)};\n"
    with open(OUTPUT_JS, "w") as f:
        f.write(js)

    print(f"\n{'='*60}")
    print(f" TEST RESULTS")
    print(f"{'='*60}")
    print(f"  Total:  {n_total}")
    print(f"  Passed: {n_pass}")
    print(f"  Failed: {n_fail}")
    print(f"  Pass rate: {summary['pass_rate']}%")
    print()

    if n_fail > 0:
        print("  Failed tests:")
        for t in tests:
            if not t["passed"]:
                print(f"    ✗ {t['name']}")
                print(f"        expected: {t['expected']} {t['unit']}")
                print(f"        actual:   {t['actual']} {t['unit']}")
                print(f"        diff:     {t['diff']} (tolerance: {t['tolerance']})")
    else:
        print("  All tests passed!")

    print(f"\nResults written to: {OUTPUT_JS}")


if __name__ == "__main__":
    tests = run_tests()
    write_results(tests)
