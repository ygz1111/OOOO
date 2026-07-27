# test_proxy.py - Test NREL API through proxy
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os

# Check proxy settings
print("Proxy environment:")
for k in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"]:
    print(f"  {k}={os.environ.get(k, 'not set')}")

# Test 1: requests with explicit HTTP proxy
print("\nTest 1: requests with HTTP proxy")
import requests
proxies = {
    "http": "http://127.0.0.1:7897",
    "https": "http://127.0.0.1:7897",
}
try:
    # First test open-meteo (known working)
    r = requests.get("https://api.open-meteo.com/v1/forecast?latitude=42.36&longitude=-71.06&current=temperature_2m",
                     proxies=proxies, timeout=15, verify=False)
    print(f"  open-meteo: Status {r.status_code}")
except Exception as e:
    print(f"  open-meteo error: {e}")

# Test NREL with HTTP proxy
try:
    import urllib3
    urllib3.disable_warnings()
    url = "https://developer.nrel.gov/api/solar/solar_resource/v1.json"
    params = {"api_key": "QfH6aBgNoDFOMjxbA4NIBnk1o2NeRBO1nQO21Rb9", "lat": 42.3601, "lon": -71.0589}
    r = requests.get(url, params=params, proxies=proxies, timeout=30, verify=False)
    print(f"  NREL solar_resource: Status {r.status_code}, Size {len(r.text)} chars")
    if r.status_code == 200:
        print(f"  Response: {r.text[:300]}")
except Exception as e:
    print(f"  NREL error: {type(e).__name__}: {e}")

# Test 2: Try without ALL_PROXY (unset it)
print("\nTest 2: Unset ALL_PROXY, use only HTTPS_PROXY")
os.environ.pop("ALL_PROXY", None)
try:
    r = requests.get(url, params=params, timeout=30, verify=False)
    print(f"  NREL: Status {r.status_code}, Size {len(r.text)} chars")
    if r.status_code == 200:
        print(f"  Response: {r.text[:300]}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# Test 3: httpx with SOCKS proxy
print("\nTest 3: httpx with SOCKS proxy")
try:
    import httpx
    # Use the SOCKS5 proxy
    client = httpx.Client(
        proxy="socks5://127.0.0.1:7897",
        timeout=30,
        verify=False,
    )
    url2 = "https://developer.nrel.gov/api/solar/solar_resource/v1.json?api_key=QfH6aBgNoDFOMjxbA4NIBnk1o2NeRBO1nQO21Rb9&lat=42.3601&lon=-71.0589"
    resp = client.get(url2)
    print(f"  NREL via httpx SOCKS: Status {resp.status_code}, Size {len(resp.text)} chars")
    if resp.status_code == 200:
        print(f"  Response: {resp.text[:300]}")
    client.close()
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# Test 4: requests with SOCKS5 proxy
print("\nTest 4: requests with SOCKS5 proxy")
try:
    socks_proxies = {
        "http": "socks5://127.0.0.1:7897",
        "https": "socks5://127.0.0.1:7897",
    }
    r = requests.get(url, params=params, proxies=socks_proxies, timeout=30, verify=False)
    print(f"  NREL via requests SOCKS5: Status {r.status_code}, Size {len(r.text)} chars")
    if r.status_code == 200:
        print(f"  Response: {r.text[:300]}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")
