# -*- coding: utf-8 -*-
"""快速测试 NSRDB API 连通性"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests
import json

API_KEY = "QfH6aBgNoDFOMjxbA4NIBnk1o2NeRBO1nQO21Rb9"
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

print("Testing NSRDB API connection...")
print(f"URL: {BASE_URL}")
print(f"Params: lat=42.36, lon=-71.06, year=2023")
print()

try:
    resp = requests.get(BASE_URL, params=params, timeout=60)
    print(f"Status Code: {resp.status_code}")
    print(f"Response size: {len(resp.text)} chars")

    data = resp.json()

    # Print top-level keys
    print(f"\nTop-level keys: {list(data.keys())}")

    # Check for errors
    if "errors" in data and data["errors"]:
        print(f"Errors: {json.dumps(data['errors'], indent=2, ensure_ascii=False)[:500]}")

    # Check outputs
    outputs = data.get("outputs", {})
    print(f"Outputs type: {type(outputs).__name__}")

    if isinstance(outputs, dict):
        print(f"Output keys: {list(outputs.keys())}")
        if "message" in outputs:
            print(f"Message: {outputs['message']}")
    elif isinstance(outputs, list):
        print(f"Outputs list length: {len(outputs)}")
        if len(outputs) > 0:
            first = outputs[0]
            print(f"First output type: {type(first).__name__}")
            if isinstance(first, dict):
                print(f"First output keys: {list(first.keys())}")
                # Check for data
                if "data" in first:
                    d = first["data"]
                    print(f"Data type: {type(d).__name__}, length: {len(d) if hasattr(d, '__len__') else 'N/A'}")
                    if isinstance(d, list) and len(d) > 0:
                        print(f"First row: {d[0]}")
                        print(f"Last row: {d[-1]}")
                if "variables" in first:
                    v = first["variables"]
                    print(f"Variables: {json.dumps(v, indent=2, ensure_ascii=False)[:800]}")
            elif isinstance(first, str):
                print(f"Output is string (URL?): {first[:200]}")

    # Print full response (truncated)
    print(f"\nFull response (first 2000 chars):")
    print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])

except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
