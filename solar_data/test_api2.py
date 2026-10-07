# -*- coding: utf-8 -*-
"""Test NSRDB API with SSL workaround"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import requests
import json
import urllib3

# Disable SSL warnings for testing
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_KEY = os.environ.get("NREL_API_KEY", "").strip()
if not API_KEY:
    raise SystemExit("缺少 NREL_API_KEY 环境变量；请使用自己的密钥，不要写入源码。")
BASE_URL = "https://developer.nrel.gov/api/nsrdb/v2/solar/psm3-download.json"

params = {
    "api_key": API_KEY,
    "lat": 42.3601,
    "lon": -71.0589,
    "year": 2023,
    "interval": 60,
    "attributes": "Year,Month,Day,Hour,GHI,DNI,DHI,Temperature",
    "email": "research@example.com",
}

print("Test 1: Normal request with verify=False")
try:
    resp = requests.get(BASE_URL, params=params, timeout=60, verify=False)
    print(f"  Status: {resp.status_code}, Size: {len(resp.text)} chars")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  Keys: {list(data.keys())}")
        outputs = data.get("outputs", {})
        if isinstance(outputs, list) and len(outputs) > 0:
            first = outputs[0]
            if isinstance(first, dict):
                print(f"  Output keys: {list(first.keys())}")
                if "data" in first:
                    d = first["data"]
                    print(f"  Data rows: {len(d)}")
                    if len(d) > 0:
                        print(f"  First row: {d[0]}")
            elif isinstance(first, str):
                print(f"  Output (URL?): {first[:300]}")
        elif isinstance(outputs, dict):
            print(f"  Output dict keys: {list(outputs.keys())}")
            if "message" in outputs:
                print(f"  Message: {outputs['message']}")
    else:
        print(f"  Response: {resp.text[:500]}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

print()
print("Test 2: Using session with adapter")
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    resp = session.get(BASE_URL, params=params, timeout=60, verify=False)
    print(f"  Status: {resp.status_code}, Size: {len(resp.text)} chars")
    if resp.status_code == 200:
        data = resp.json()
        outputs = data.get("outputs", {})
        if isinstance(outputs, list) and len(outputs) > 0:
            first = outputs[0]
            if isinstance(first, dict) and "data" in first:
                d = first["data"]
                print(f"  Data rows: {len(d)}")
                if len(d) > 0:
                    print(f"  First row: {d[0]}")
            elif isinstance(first, str):
                print(f"  URL output: {first[:300]}")
        elif isinstance(outputs, dict):
            msg = outputs.get("message", "")
            print(f"  Message: {msg}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

print()
print("Test 3: Try pysolar API (alternative endpoint)")
try:
    # Try the pysolar endpoint which might have different SSL
    ALT_URL = "https://developer.nrel.gov/api/solar/solar_resource/v1.json"
    params2 = {"api_key": API_KEY, "lat": 42.3601, "lon": -71.0589}
    resp = requests.get(ALT_URL, params=params2, timeout=30, verify=False)
    print(f"  Status: {resp.status_code}")
    if resp.status_code == 200:
        print(f"  Response: {resp.text[:300]}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")
