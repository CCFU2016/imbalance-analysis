#!/usr/bin/env python3
"""
Fetch French imbalance data from the RTE Balancing Energy API.

Usage:
    python3 fetch_rte_france.py

You will be prompted for your RTE API credentials (client_id and client_secret).
These are NOT stored anywhere — they are only used for the current session.

To get credentials:
  1. Go to https://data.rte-france.com
  2. Create an account / log in
  3. Subscribe to the "Balancing Energy" API
  4. Create an application to get a client_id and client_secret

The script fetches imbalance_data and prices for 2021-2025 and saves them as CSV.
"""
import os as _os
_os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # data paths are relative to this folder
import base64
import getpass
import json
import os
import sys
import time
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://digital.services.rte-france.com"
TOKEN_URL = f"{BASE_URL}/token/oauth/"
API_BASE = f"{BASE_URL}/open_api/balancing_energy/v5"


def get_token(client_id, client_secret):
    """Get OAuth2 access token using client credentials."""
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = Request(TOKEN_URL, method="POST")
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.data = b""

    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["access_token"]
    except HTTPError as e:
        body = e.read().decode()
        print(f"Authentication failed: {e.code} {e.reason}")
        print(f"Response: {body}")
        return None
    except Exception as e:
        print(f"Authentication error: {e}")
        return None


def fetch_endpoint(token, endpoint, start_date, end_date, accept="text/csv"):
    """Fetch data from an RTE API endpoint."""
    params = urlencode({
        "start_date": start_date,
        "end_date": end_date,
    })
    url = f"{API_BASE}/{endpoint}?{params}"
    req = Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", accept)

    try:
        with urlopen(req, timeout=120) as resp:
            return resp.read().decode()
    except HTTPError as e:
        body = e.read().decode()
        print(f"  API error: {e.code} {e.reason}")
        print(f"  Response: {body[:500]}")
        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None


def fetch_endpoint_json(token, endpoint, start_date, end_date):
    """Fetch data as JSON (fallback if CSV isn't supported)."""
    return fetch_endpoint(token, endpoint, start_date, end_date, accept="application/json")


def main():
    print("=" * 60)
    print(" RTE France — Balancing Energy Data Fetcher")
    print("=" * 60)
    print()
    print("Enter your RTE API credentials.")
    print("(Get them from https://data.rte-france.com → My Applications)")
    print()

    client_id = input("Client ID: ").strip()
    client_secret = getpass.getpass("Client Secret: ").strip()

    if not client_id or not client_secret:
        print("Error: both client_id and client_secret are required.")
        sys.exit(1)

    print("\nAuthenticating...")
    token = get_token(client_id, client_secret)
    if not token:
        print("Failed to authenticate. Check your credentials.")
        sys.exit(1)
    print("Authenticated successfully.\n")

    # Define date ranges (fetch month by month to stay within API limits)
    endpoints = ["imbalance_data", "prices"]
    years = range(2021, 2026)

    for endpoint in endpoints:
        print(f"\n{'='*60}")
        print(f" Fetching: {endpoint}")
        print(f"{'='*60}")

        all_data = {}

        for year in years:
            for month in range(1, 13):
                # Start of month
                start = datetime(year, month, 1)
                # End of month (start of next month)
                if month == 12:
                    end = datetime(year + 1, 1, 1)
                else:
                    end = datetime(year, month + 1, 1)

                # Skip future months
                if start > datetime.now():
                    break

                start_str = start.strftime("%Y-%m-%dT00:00:00+01:00")
                end_str = end.strftime("%Y-%m-%dT00:00:00+01:00")

                print(f"  {year}-{month:02d}...", end=" ", flush=True)

                # Try CSV first
                data = fetch_endpoint(token, endpoint, start_str, end_str, "text/csv")

                if data and len(data) > 10:
                    filename = f"FR_{endpoint}_{year}_{month:02d}.csv"
                    filepath = os.path.join(OUTPUT_DIR, filename)
                    with open(filepath, "w") as f:
                        f.write(data)
                    lines = data.count("\n")
                    print(f"OK ({lines} lines) → {filename}")
                else:
                    # Try JSON fallback
                    data = fetch_endpoint_json(token, endpoint, start_str, end_str)
                    if data:
                        filename = f"FR_{endpoint}_{year}_{month:02d}.json"
                        filepath = os.path.join(OUTPUT_DIR, filename)
                        with open(filepath, "w") as f:
                            f.write(data)
                        print(f"OK (JSON) → {filename}")
                    else:
                        print("FAILED")

                # Rate limiting: be polite
                time.sleep(1)

            # Re-authenticate periodically (tokens expire)
            print("  Refreshing token...")
            token = get_token(client_id, client_secret)
            if not token:
                print("Token refresh failed. Stopping.")
                sys.exit(1)

    print(f"\n{'='*60}")
    print(f" Done! Files saved to: {OUTPUT_DIR}")
    print(f"{'='*60}")
    print("\nNext steps:")
    print("  1. Check the downloaded files (FR_imbalance_data_*.csv, FR_prices_*.csv)")
    print("  2. Run: python3 analyze_france.py  (will be created after data is available)")
    print("  3. The analysis will be added to the infographic automatically")


if __name__ == "__main__":
    main()
