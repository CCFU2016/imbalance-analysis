#!/usr/bin/env python3
"""
Fetch Dutch imbalance (settlement) prices from the TenneT API.

Writes one CSV per calendar year to data/tennet/ using TenneT's own export naming and
columns, e.g. data/tennet/settlement_prices_202512312300_202612312300_CET.csv for 2026,
so the existing analysis scripts and nl_percentiles.py pick it up. For the
current year the file holds data up to now; re-running overwrites it.

API key: free from https://developer.tennet.eu (sign up → subscribe to the
"publications" API). Looked up in this order:
  1. TENNET_API_KEY environment variable
  2. .tennet-key file next to this script
  3. prompted (and optionally saved to .tennet-key)

Usage:
    python3 fetch_tennet_nl.py            # current year to date
    python3 fetch_tennet_nl.py 2026 2027  # specific years
"""
import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import csv
import getpass
import io
import os
import sys
import time
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DIR = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(DIR, ".tennet-key")
API = "https://api.tennet.eu/publications/v1/settlement-prices"
OUT_DIR = os.path.join(DIR, "data", "tennet")


def get_key():
    key = os.environ.get("TENNET_API_KEY", "").strip()
    if key:
        return key
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE) as f:
            return f.read().strip()
    key = getpass.getpass("TenneT API key: ").strip()
    if key and input("Save to .tennet-key for next time? [y/N] ").lower() == "y":
        with open(KEY_FILE, "w") as f:
            f.write(key + "\n")
        os.chmod(KEY_FILE, 0o600)
    return key


def fetch(key, start, end):
    params = urlencode({
        "date_from": start.strftime("%d-%m-%Y %H:%M:%S"),
        "date_to": end.strftime("%d-%m-%Y %H:%M:%S"),
    })
    req = Request(f"{API}?{params}")
    req.add_header("apikey", key)
    req.add_header("Accept", "text/csv")
    for attempt in range(3):
        try:
            with urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8-sig")
        except HTTPError as e:
            body = e.read().decode()[:300]
            if e.code == 429 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise SystemExit(f"TenneT API error {e.code}: {body}")


def month_starts(year, until):
    m = datetime(year, 1, 1)
    while m < until:
        nxt = datetime(year + (m.month == 12), m.month % 12 + 1, 1)
        yield m, min(nxt, until)
        m = nxt


def fetch_year(key, year):
    now = datetime.now()
    until = min(datetime(year + 1, 1, 1), now)
    header, rows = None, {}
    for start, end in month_starts(year, until):
        print(f"  {start:%Y-%m} …", end=" ", flush=True)
        text = fetch(key, start, end)
        reader = csv.reader(io.StringIO(text))
        h = next(reader, None)
        if h is None:
            print("no data")
            continue
        header = header or h
        i_start, i_isp = h.index("Timeinterval Start Loc"), h.index("Isp")
        n = 0
        for r in reader:
            if not r:
                continue
            # (date, ISP) is unique; local start time repeats on the DST day
            rows[(r[i_start][:10], int(r[i_isp]))] = r
            n += 1
        print(f"{n} ISPs")
        time.sleep(1.1)  # stay under the API rate limit

    if not rows:
        print(f"  no data for {year}")
        return None
    out = os.path.join(
        OUT_DIR, f"settlement_prices_{year - 1}12312300_{year}12312300_CET.csv"
    )
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for k in sorted(rows):
            w.writerow(rows[k])
    last = rows[max(rows)]
    print(f"  wrote {len(rows)} ISPs through {last[header.index('Timeinterval End Loc')]} → {out}")
    return out


def main():
    years = [int(a) for a in sys.argv[1:]] or [datetime.now().year]
    key = get_key()
    if not key:
        raise SystemExit("No API key.")
    for y in years:
        print(f"Fetching {y}")
        fetch_year(key, y)


if __name__ == "__main__":
    main()
