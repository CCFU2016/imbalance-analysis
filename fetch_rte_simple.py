#!/usr/bin/env python3
"""
Simplified RTE France data fetcher.

Usage:
    python3 fetch_rte_simple.py YOUR_CLIENT_ID YOUR_CLIENT_SECRET
"""
import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import base64
import json
import os
import sys
import time
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode

DIR = os.path.dirname(os.path.abspath(__file__))
BASE = "https://digital.iservices.rte-france.com"

def get_token(cid, csec):
    cred = base64.b64encode(f"{cid}:{csec}".encode()).decode()
    req = Request(f"{BASE}/token/oauth/", method="POST")
    req.add_header("Authorization", f"Basic {cred}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.data = b""
    try:
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read())["access_token"]
    except HTTPError as e:
        print(f"Auth failed: {e.code} — {e.read().decode()[:300]}")
        return None
    except Exception as e:
        print(f"Auth error: {e}")
        return None

def fetch(token, endpoint, start, end, fmt="text/csv"):
    params = urlencode({"start_date": start, "end_date": end})
    url = f"{BASE}/open_api/balancing_energy/v5/{endpoint}?{params}"
    req = Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", fmt)
    try:
        with urlopen(req, timeout=120) as r:
            return r.read().decode()
    except HTTPError as e:
        print(f"  Error {e.code}: {e.read().decode()[:200]}")
        return None

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 fetch_rte_simple.py CLIENT_ID CLIENT_SECRET")
        sys.exit(1)

    cid, csec = sys.argv[1], sys.argv[2]
    print("Authenticating...")
    token = get_token(cid, csec)
    if not token:
        sys.exit(1)
    print("OK\n")

    for ep in ["imbalance_data", "prices"]:
        print(f"--- {ep} ---")
        for year in range(2021, 2026):
            for month in range(1, 13):
                if datetime(year, month, 1) > datetime.now():
                    break
                m2 = month + 1
                y2 = year
                if m2 > 12:
                    m2 = 1; y2 += 1
                s = f"{year}-{month:02d}-01T00:00:00+01:00"
                e = f"{y2}-{m2:02d}-01T00:00:00+01:00"
                print(f"  {year}-{month:02d}...", end=" ", flush=True)

                data = fetch(token, ep, s, e)
                if data and len(data) > 10:
                    fn = f"FR_{ep}_{year}_{month:02d}.csv"
                    with open(os.path.join(DIR, fn), "w") as f:
                        f.write(data)
                    print(f"OK → {fn}")
                else:
                    # Try JSON
                    data = fetch(token, ep, s, e, "application/json")
                    if data:
                        fn = f"FR_{ep}_{year}_{month:02d}.json"
                        with open(os.path.join(DIR, fn), "w") as f:
                            f.write(data)
                        print(f"OK (json) → {fn}")
                    else:
                        print("FAILED")
                time.sleep(1)

            # Refresh token each year
            token = get_token(cid, csec)
            if not token:
                print("Token refresh failed"); sys.exit(1)

    print("\nDone! Files saved to:", DIR)
