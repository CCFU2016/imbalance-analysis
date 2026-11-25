#!/usr/bin/env python3
"""
Percentiles of Dutch imbalance (TenneT settlement) prices, and of the
imbalance − day-ahead spread.

Reads every data/tennet/settlement_prices_*.csv (TenneT export, ';' or ',' delimited),
de-duplicates ISPs across overlapping files, and computes P50/75/90/95/98/99
per calendar year for both Price Surplus (producer / feed-in side) and
Price Shortage (consumer / offtake side) — as absolute prices and as the
spread against the NL day-ahead price of the same quarter-hour (ENTSO-E
12.1.D files: hourly until 30 Sep 2025, 15-minute from 1 Oct 2025).

Writes nl_percentiles.json and regenerates both tables on page 1 of
infographic_dayahead.html (between the NL PERCENTILES markers).

Usage:
    python3 nl_percentiles.py
"""
import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
import glob
import json
import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(DIR, "nl_percentiles.json")
SETTLEMENT_GLOB = "data/tennet/settlement_prices_*.csv"
DA_GLOB = "data/entsoe/*EnergyPrices*.csv"
AMS = ZoneInfo("Europe/Amsterdam")

UPPER = [50, 75, 90, 95, 98, 99]
LOWER = [1, 2, 5, 10, 25]
MIN_DA_COVERAGE = 0.99  # spread rows need day-ahead for (almost) every ISP

# The page section between these markers is regenerated on every run
HTML = os.path.join(DIR, "infographic_dayahead.html")
MARK_START = "<!-- NL PERCENTILES START -->"
MARK_END = "<!-- NL PERCENTILES END -->"

TABLES = [
    {
        "key": "years",
        "id": "nl-percentiles",
        "title": "Imbalance Price Percentiles",
        "col": "Price",
        "sides": (("surplus", "Surplus", "producer receives"),
                  ("shortage", "Shortage", "consumer pays")),
        "intro": "How high do imbalance prices go? Each column is the price that the given share "
                 "of quarter-hours stayed at or below — P95 = the price exceeded in 5% of "
                 "quarter-hours, about 438 hours a year.",
        "note": "EUR/MWh, TenneT settlement prices over every 15-minute period of the year.",
        "footnote": "Surplus and Shortage only differ in quarter-hours where TenneT regulated "
                    "both up and down (regulation state 2).",
    },
    {
        "key": "spread",
        "id": "nl-spread-percentiles",
        "title": "Imbalance − Day-Ahead Spread Percentiles",
        "col": "Spread",
        "sides": (("surplus", "Surplus − DA", "producer"),
                  ("shortage", "Shortage − DA", "consumer")),
        "intro": "How far above day-ahead does imbalance settle? Spread = imbalance price − NL "
                 "day-ahead price for the same quarter-hour; positive = imbalance was more "
                 "expensive than day-ahead. P95 = the spread exceeded in 5% of quarter-hours.",
        "note": "EUR/MWh. Day-ahead: ENTSO-E 12.1.D NL — hourly until 30 Sep 2025, 15-minute "
                "from 1 Oct 2025 — matched to each quarter-hour in UTC (summer time included).",
    },
]


def percentile(values, p):
    """Linear-interpolation percentile (0–100). Matches numpy default."""
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def isp_utc(d, isp):
    """UTC start of ISP n on local date d (ISP 1 starts at local midnight;
    counting from there handles the 92/100-ISP DST days correctly)."""
    midnight = datetime.combine(d, time(0), tzinfo=AMS).astimezone(timezone.utc)
    return midnight.replace(tzinfo=None) + timedelta(minutes=15 * (isp - 1))


def load_all():
    """Return {(date, isp): {start, utc, surplus, shortage}} across all files.

    Keyed on (date, ISP number) rather than local start time, because the
    autumn DST day repeats 02:00–03:00 local and would otherwise collide.
    Later files win on overlap (newer exports carry corrected prices).
    """
    rows = {}
    files = sorted(glob.glob(SETTLEMENT_GLOB), key=os.path.getmtime)
    for fp in files:
        with open(fp, encoding="utf-8-sig") as f:
            header = f.readline()
            f.seek(0)
            delim = ";" if header.count(";") > header.count(",") else ","
            for row in csv.DictReader(f, delimiter=delim):
                su = row.get("Price Surplus", "").strip()
                sh = row.get("Price Shortage", "").strip()
                if not su and not sh:
                    continue
                start = datetime.strptime(row["Timeinterval Start Loc"], "%Y-%m-%dT%H:%M")
                isp = int(row["Isp"])
                rows[(start.date(), isp)] = {
                    "start": start,
                    "utc": isp_utc(start.date(), isp),
                    "surplus": float(su) if su else None,
                    "shortage": float(sh) if sh else None,
                }
    return files, rows


def load_da():
    """NL day-ahead prices keyed by UTC start: (hourly PT60M, quarter-hourly PT15M)."""
    hourly, quarter = {}, {}
    for fp in sorted(glob.glob(DA_GLOB)):
        with open(fp, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if row.get("MapCode") != "NL" or row.get("ContractType") != "Day-ahead":
                    continue
                t = datetime.strptime(row["DateTime(UTC)"], "%Y-%m-%d %H:%M:%S")
                target = quarter if row["ResolutionCode"] == "PT15M" else hourly
                target[t] = float(row["Price[Currency/MWh]"])
    return hourly, quarter


def da_for(utc, hourly, quarter):
    price = quarter.get(utc)
    return price if price is not None else hourly.get(utc.replace(minute=0))


def stats(values):
    return {
        "n": len(values),
        "mean": round(sum(values) / len(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        **{f"p{p}": round(percentile(values, p), 2) for p in UPPER},
        **{f"p{p}": round(percentile(values, p), 2) for p in LOWER},
    }


# Same look as tbody td:first-child, which rows under the rowspan cell get by default
YEAR_CELL = "text-align:left;font-weight:600;color:#6b7280"


def render_table(result, t):
    data = result[t["key"]]
    labels = list(data)
    trs = []
    for i, (side, name, who) in enumerate(t["sides"]):
        for j, label in enumerate(labels):
            s = data[label][side]
            attrs = f' data-side="{name}" data-label="{label}"'
            if i > 0 and j == 0:
                attrs += ' style="border-top:2px solid #e5e7eb"'
            lead = (f'<td rowspan="{len(labels)}">{name}<br>'
                    f'<span style="font-weight:400;color:#9ca3af">({who})</span></td>'
                    if j == 0 else "")
            cells = "".join(f'<td class="val-imb">{round(s[f"p{p}"]):,}</td>' for p in UPPER)
            trs.append(f'          <tr{attrs}>{lead}<td style="{YEAR_CELL}">{label}</td>{cells}'
                       f'<td>{round(s["max"]):,}</td></tr>')

    notes = [t["note"]]
    if any("–" in l for l in labels):
        notes.append(f"{next(l for l in labels if '–' in l)} pools those years.")
    if any("YTD" in l or "12m" in l for l in labels):
        notes.append(f"YTD = year to date; 12m = the 12 months up to {result['data_through'][:10]}.")
    if t["key"] == "spread":
        missing = result["spread_meta"]["missing_da"]
        if missing:
            notes.append(f"{missing:,} quarter-hours without a day-ahead price are left out.")
        for label in result["spread_meta"]["omitted"]:
            notes.append(f"{label} not shown: day-ahead data ends {result['spread_meta']['da_through'][:10]}.")
    if t.get("footnote"):
        notes.append(t["footnote"])
    th = "".join(f"<th>P{p}</th>" for p in UPPER)
    return f"""  <div class="section-title"><span class="dot"></span> {t["title"]}</div>
  <div class="summary-section" id="{t["id"]}">
    <div class="summary-wrap">
      <p class="pct-intro" style="font-size:12px;color:#6b7280;margin-bottom:16px;padding-right:72px">{t["intro"]}</p>
      <table>
        <thead>
          <tr><th style="width:170px">{t["col"]}</th><th style="text-align:left;width:110px">Year</th>{th}<th>Max</th></tr>
        </thead>
        <tbody>
{chr(10).join(trs)}
        </tbody>
      </table>
      <div class="pct-note" style="text-align:center;font-size:11px;color:#9ca3af;margin-top:12px">{' '.join(notes)}</div>
    </div>
  </div>"""


def write_html(result):
    with open(HTML, encoding="utf-8") as f:
        page = f.read()
    a, b = page.find(MARK_START), page.find(MARK_END)
    if a < 0 or b < a:
        print(f"Markers not found in {HTML}; page not updated")
        return
    body = "\n\n".join(render_table(result, t) for t in TABLES)
    page = page[:a + len(MARK_START)] + "\n" + body + "\n  " + page[b:]
    tmp = HTML + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(tmp, HTML)
    print(f"Updated percentile sections in {HTML}")


def print_table(title, data, sides):
    for side, name, _ in sides:
        print(f"{title} — {name} — EUR/MWh, 15-min ISPs")
        print(f"{'':>11}{'n':>8}" + "".join(f"{'P' + str(p):>9}" for p in UPPER) + f"{'max':>9}")
        for label, s in ((l, v[side]) for l, v in data.items()):
            print(f"{label:>11}{s['n']:>8}" + "".join(f"{s['p' + str(p)]:>9.0f}" for p in UPPER)
                  + f"{s['max']:>9.0f}")
        print(f"{'lower tail':>11}{'':>8}" + "".join(f"{'P' + str(p):>9}" for p in LOWER) + f"{'min':>9}")
        for label, s in ((l, v[side]) for l, v in data.items()):
            print(f"{label:>11}{'':>8}" + "".join(f"{s['p' + str(p)]:>9.0f}" for p in LOWER)
                  + f"{s['min']:>9.0f}")
        print()


def main():
    files, rows = load_all()
    hourly, quarter = load_da()
    for r in rows.values():
        r["da"] = da_for(r["utc"], hourly, quarter)

    by_year = {}
    for (d, _), r in rows.items():
        by_year.setdefault(str(d.year), []).append(r)

    last = max(r["start"] for r in rows.values())
    da_through = max([*hourly, *quarter])
    result = {
        "source_files": [os.path.basename(f) for f in files],
        "data_through": last.strftime("%Y-%m-%d %H:%M"),
        "years": {},
        "spread": {},
        "spread_meta": {"da_through": da_through.strftime("%Y-%m-%d %H:%M") + " UTC",
                        "missing_da": 0, "omitted": []},
    }
    groups = {}
    full_years = []
    for y, rs in sorted(by_year.items()):
        if len(rs) >= 365 * 96 - 4:
            full_years.append(y)
            groups[y] = rs
        else:
            groups[f"{y} YTD"] = rs
    if len(full_years) > 1:
        groups[f"{full_years[0]}–{full_years[-1]}"] = [
            r for y in full_years for r in by_year[y]
        ]
    # Rolling 12 months when the latest year is still in progress
    if str(last.year) not in full_years:
        cutoff = last.replace(year=last.year - 1)
        groups[f"12m→{last:%b %y}"] = [r for r in rows.values() if r["start"] > cutoff]

    for label, rs in groups.items():
        result["years"][label] = {
            side: stats([r[side] for r in rs if r[side] is not None])
            for side in ("surplus", "shortage")
        }
        with_da = [r for r in rs if r["da"] is not None]
        if len(with_da) < MIN_DA_COVERAGE * len(rs):
            result["spread_meta"]["omitted"].append(label)
            continue
        result["spread"][label] = {
            side: stats([r[side] - r["da"] for r in with_da if r[side] is not None])
            for side in ("surplus", "shortage")
        }
    result["spread_meta"]["missing_da"] = sum(
        1 for label in result["spread"] if "–" not in label and "12m" not in label
        for r in groups[label] if r["da"] is None
    )

    with open(OUT, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Data through {result['data_through']} (local time); "
          f"day-ahead through {result['spread_meta']['da_through']}\n")
    for t in TABLES:
        print_table(t["title"], result[t["key"]], t["sides"])
    if result["spread_meta"]["missing_da"]:
        print(f"Quarter-hours without day-ahead (left out of spread): {result['spread_meta']['missing_da']}")
    print(f"Wrote {OUT}")
    write_html(result)


if __name__ == "__main__":
    main()
