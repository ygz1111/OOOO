# test_nrel_no_vpn.py - Test NREL API after VPN is off
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os

# Clear proxy env vars
for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(key, None)

print("Proxy env cleared:")
for k in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    print(f"  {k}={os.environ.get(k, 'not set')}")

import requests
import urllib3
urllib3.disable_warnings()

API_KEY = "QfH6aBgNoDFOMjxbA4NIBnk1o2NeRBO1nQO21Rb9"

# Test 1: DNS resolution
print("\nTest 1: DNS resolution for developer.nrel.gov")
import socket
try:
    ip = socket.gethostbyname("developer.nrel.gov")
    print(f"  Resolved IP: {ip}")
except Exception as e:
    print(f"  DNS failed: {e}")

# Test 2: NREL API direct connection (no proxy)
print("\nTest 2: NREL API direct connection (no VPN/proxy)")
try:
    url = "https://developer.nrel.gov/api/solar/solar_resource/v1.json"
    params = {"api_key": API_KEY, "lat": 42.3601, "lon": -71.0589}
    r = requests.get(url, params=params, timeout=30)
    print(f"  Status: {r.status_code}, Size: {len(r.text)} chars")
    if r.status_code == 200:
        print(f"  Response: {r.text[:300]}")
        print("  => NREL API WORKS! No VPN needed.")
    else:
        print(f"  Error response: {r.text[:300]}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# Test 3: NREL PSM3 download endpoint
print("\nTest 3: NREL PSM3 download endpoint")
try:
    psm3_url = "https://developer.nrel.gov/api/nsrdb/v2/solar/psm3-download.json"
    params3 = {
        "api_key": API_KEY,
        "lat": 42.3601,
        "lon": -71.0589,
        "year": 2023,
        "interval": 60,
        "attributes": "Year,Month,Day,Hour,GHI,DNI,DHI,Temperature",
        "email": "research@example.com",
    }
    r = requests.get(psm3_url, params=params3, timeout=60)
    print(f"  Status: {r.status_code}, Size: {len(r.text)} chars")
    if r.status_code == 200:
        import json
        data = r.json()
        print(f"  Keys: {list(data.keys())}")
        outputs = data.get("outputs", {})
        print(f"  Outputs type: {type(outputs).__name__}")
        if isinstance(outputs, list) and len(outputs) > 0:
            first = outputs[0]
            if isinstance(first, dict):
                print(f"  First output keys: {list(first.keys())}")
                if "data" in first:
                    d = first["data"]
                    print(f"  Data rows: {len(d)}")
                    if len(d) > 0:
                        print(f"  First row: {d[0]}")
                        print(f"  Last row: {d[-1]}")
            elif isinstance(first, str):
                print(f"  Output URL: {first[:300]}")
        elif isinstance(outputs, dict):
            msg = outputs.get("message", "")
            print(f"  Message: {msg}")
    else:
        print(f"  Response: {r.text[:500]}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# Test 4: Open-Meteo for Guangzhou (to confirm it works)
print("\nTest 4: Open-Meteo for Guangzhou (23.13°N, 113.26°E)")
try:
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": 23.1291,
        "longitude": 113.2644,
        "start_date": "2023-06-01",
        "end_date": "2023-06-02",
        "hourly": "shortwave_radiation,direct_normal_irradiance,diffuse_radiation,temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,surface_pressure,cloud_cover",
        "timezone": "Asia/Shanghai",
    }
    r = requests.get(url, params=params, timeout=30)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        hourly = data.get("hourly", {})
        print(f"  Variables: {list(hourly.keys())}")
        print(f"  First time: {hourly['time'][0]}")
        print(f"  GHI samples: {hourly['shortwave_radiation'][:3]}")
        print("  => Guangzhou data available via Open-Meteo!")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")
