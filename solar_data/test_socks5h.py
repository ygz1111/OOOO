# test_socks5h.py - Try socks5h:// for remote DNS resolution
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os
import requests
import urllib3
urllib3.disable_warnings()

API_KEY = os.environ.get("NREL_API_KEY", "").strip()
if not API_KEY:
    raise SystemExit("缺少 NREL_API_KEY 环境变量；请使用自己的密钥，不要写入源码。")

# Test 1: socks5h:// (remote DNS)
print("Test 1: socks5h:// (remote DNS through proxy)")
try:
    proxies = {
        "http": "socks5h://127.0.0.1:7897",
        "https": "socks5h://127.0.0.1:7897",
    }
    url = "https://developer.nrel.gov/api/solar/solar_resource/v1.json"
    params = {"api_key": API_KEY, "lat": 42.3601, "lon": -71.0589}
    r = requests.get(url, params=params, proxies=proxies, timeout=30, verify=False)
    print(f"  Status: {r.status_code}, Size: {len(r.text)}")
    if r.status_code == 200:
        print(f"  Response: {r.text[:300]}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# Test 2: Try with socks5:// and explicitly resolve DNS
print("\nTest 2: Resolve NREL IP via DNS-over-HTTPS, then connect via proxy")
try:
    import socket
    # Use Google DNS-over-JSON to resolve developer.nrel.gov
    dns_url = "https://dns.google/resolve?name=developer.nrel.gov&type=A"
    r = requests.get(dns_url, proxies={"https": "http://127.0.0.1:7897"}, timeout=15, verify=False)
    import json
    dns_data = r.json()
    print(f"  DNS resolution: {dns_data}")
    answers = dns_data.get("Answer", [])
    if answers:
        ip = answers[0]["data"]
        print(f"  NREL IP: {ip}")

        # Connect using IP with Host header
        url_ip = f"https://{ip}/api/solar/solar_resource/v1.json"
        headers = {"Host": "developer.nrel.gov"}
        r = requests.get(url_ip, params=params, headers=headers,
                        proxies={"https": "http://127.0.0.1:7897"},
                        timeout=30, verify=False)
        print(f"  Status: {r.status_code}, Size: {len(r.text)}")
        if r.status_code == 200:
            print(f"  Response: {r.text[:300]}")
    else:
        print("  DNS resolution failed - no answers")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# Test 3: Check if Clash has a mixed-port or different ports
print("\nTest 3: Try different proxy ports")
for port in [7890, 7891, 7892, 7893, 7897, 1080, 8080]:
    try:
        r = requests.get(
            "https://developer.nrel.gov/api/solar/solar_resource/v1.json",
            params={"api_key": API_KEY, "lat": 42.36, "lon": -71.06},
            proxies={"https": f"http://127.0.0.1:{port}"},
            timeout=5, verify=False
        )
        print(f"  Port {port}: Status {r.status_code}")
        if r.status_code == 200:
            print(f"  Response: {r.text[:200]}")
            break
    except requests.exceptions.ConnectionError:
        pass  # Port not open
    except Exception as e:
        err = str(e)[:80]
        if "SSLError" in err:
            print(f"  Port {port}: SSL Error (connected but TLS failed)")
        else:
            print(f"  Port {port}: {err}")

# Test 4: Try open-meteo solar API as alternative
print("\nTest 4: Open-Meteo Solar API (alternative data source)")
try:
    # Open-Meteo provides solar radiation data
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": 42.3601,
        "longitude": -71.0589,
        "start_date": "2023-01-01",
        "end_date": "2023-01-02",
        "hourly": "shortwave_radiation,direct_radiation,diffuse_radiation,temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,surface_pressure,cloud_cover,precipitable_water",
        "timezone": "America/New_York",
    }
    r = requests.get(url, params=params, timeout=30)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"  Keys: {list(data.keys())}")
        hourly = data.get("hourly", {})
        print(f"  Hourly variables: {list(hourly.keys())}")
        print(f"  First 3 values:")
        for key in list(hourly.keys())[:5]:
            print(f"    {key}: {hourly[key][:3]}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")
