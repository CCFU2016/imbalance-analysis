#!/usr/bin/env python3
"""
Daily-average Dutch imbalance prices and imbalance − day-ahead spreads for
one year, plus tail percentiles.

For each local (Europe/Amsterdam) calendar day, averages over that day's
15-minute ISPs (equal weight per ISP; 92 on the spring DST day, 100 on the
autumn one):
  - TenneT Price Shortage (what a short BRP pays per MWh)
  - TenneT Price Surplus (what a long BRP receives per MWh)
  - NL day-ahead price (ENTSO-E 12.1.D; an hourly price counts for each of its
    four ISPs, a 15-minute price for its own ISP; see nl_percentiles.da_for)
  - spread_short = Shortage − DA (loss per MWh on a short sold at day-ahead)
  - spread_long  = Surplus − DA (minus the loss per MWh on a long bought at day-ahead)

Writes exports/nl_<year>_daily_imbalance.csv and prints percentiles over the
daily values (linear interpolation, numpy's default).

Usage:
    python3 nl_daily_export.py        # 2025
    python3 nl_daily_export.py 2026
"""
import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
import os
import sys

import numpy as np

from nl_percentiles import da_for, load_all, load_da

DIR = os.path.dirname(os.path.abspath(__file__))
HIGH = [90, 95, 97.5, 98, 99, 99.5]
LOW = [10, 5, 2.5, 2, 1, 0.5]


def fmt(p):
    return f"p{p:g}"


def tail(values, ps, extreme):
    out = {fmt(p): round(float(np.percentile(values, p)), 2) for p in ps}
    out[extreme.__name__] = round(float(extreme(values)), 2)
    return out


def mean(xs):
    return sum(xs) / len(xs)


def main():
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    _, rows = load_all()
    hourly, quarter = load_da()

    days = {}
    for (d, _), r in rows.items():
        if d.year == year:
            days.setdefault(d, []).append(r)
    if not days:
        raise SystemExit(f"No data for {year}")

    out_dir = os.path.join(DIR, "exports")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"nl_{year}_daily_imbalance.csv")

    daily = []
    missing = missing_da = 0
    for d in sorted(days):
        rs = days[d]
        sh = [r["shortage"] for r in rs if r["shortage"] is not None]
        su = [r["surplus"] for r in rs if r["surplus"] is not None]
        missing += 2 * len(rs) - len(sh) - len(su)
        da = [da_for(r["utc"], hourly, quarter) for r in rs]
        missing_da += da.count(None)
        # Spreads only for days with a day-ahead price in every ISP
        full = None not in da and len(sh) == len(su) == len(rs)
        daily.append({
            "date": d,
            "short": mean(sh),
            "long": mean(su),
            "n": len(rs),
            "da": mean(da) if full else None,
            "spread_short": mean([r["shortage"] - p for r, p in zip(rs, da)]) if full else None,
            "spread_long": mean([r["surplus"] - p for r, p in zip(rs, da)]) if full else None,
        })

    def cell(v):
        return "" if v is None else f"{v:.4f}"

    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "price_short_eur_mwh", "price_long_eur_mwh", "isp_count",
                    "price_da_eur_mwh", "spread_short_eur_mwh", "spread_long_eur_mwh"])
        for x in daily:
            w.writerow([x["date"].isoformat(), cell(x["short"]), cell(x["long"]), x["n"],
                        cell(x["da"]), cell(x["spread_short"]), cell(x["spread_long"])])

    def col(key):
        return np.array([x[key] for x in daily if x[key] is not None])

    odd = [(x["date"].isoformat(), x["n"]) for x in daily if x["n"] != 96]
    no_spread = [x["date"].isoformat() for x in daily if x["da"] is None]
    print(f"{year}: {len(daily)} days, {sum(x['n'] for x in daily)} ISPs, "
          f"{missing} missing prices, {missing_da} ISPs without day-ahead, "
          f"non-96 days: {odd}")
    if no_spread:
        print(f"Days without spread (day-ahead incomplete): {no_spread}")
    print(f"Short pays (Price Shortage), high tail: {tail(col('short'), HIGH, max)}")
    print(f"Long receives (Price Surplus), low tail: {tail(col('long'), LOW, min)}")
    print(f"Short spread (Shortage − DA), high tail: {tail(col('spread_short'), HIGH, max)}")
    print(f"Long spread (Surplus − DA), low tail: {tail(col('spread_long'), LOW, min)}")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
