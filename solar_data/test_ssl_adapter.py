# test_ssl_adapter.py - Custom SSL adapter for NREL
import sys
sys.stdout.reconfigure(encoding='utf-8')
import ssl
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import urllib3
urllib3.disable_warnings()


class CustomSSLAdapter(HTTPAdapter):
    """Custom SSL adapter with permissive cipher list"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        # Allow all ciphers
        ctx.set_ciphers('DEFAULT@SECLEVEL=0')
        # Try different TLS versions
        ctx.minimum_version = ssl.TLSVersion.TLSv1
        ctx.maximum_version = ssl.TLSVersion.TLSv1_3
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)


API_KEY = "QfH6aBgNoDFOMjxbA4NIBnk1o2NeRBO1nQO21Rb9"
proxies = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}

# Test 1: Custom SSL adapter
print("Test 1: Custom SSL adapter with permissive ciphers")
try:
    session = requests.Session()
    adapter = CustomSSLAdapter()
    session.mount("https://", adapter)
    url = "https://developer.nrel.gov/api/solar/solar_resource/v1.json"
    params = {"api_key": API_KEY, "lat": 42.3601, "lon": -71.0589}
    r = session.get(url, params=params, proxies=proxies, timeout=30, verify=False)
    print(f"  Status: {r.status_code}, Size: {len(r.text)}")
    if r.status_code == 200:
        print(f"  Response: {r.text[:300]}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# Test 2: Try with different user agent
print("\nTest 2: With browser User-Agent")
try:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    r = requests.get(url, params=params, proxies=proxies, timeout=30, verify=False, headers=headers)
    print(f"  Status: {r.status_code}, Size: {len(r.text)}")
    if r.status_code == 200:
        print(f"  Response: {r.text[:300]}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# Test 3: Try the ps3-download endpoint directly
print("\nTest 3: PSM3 download endpoint")
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
    r = requests.get(psm3_url, params=params3, proxies=proxies, timeout=30, verify=False,
                     headers={"User-Agent": "Mozilla/5.0"})
    print(f"  Status: {r.status_code}, Size: {len(r.text)}")
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
            elif isinstance(first, str):
                print(f"  Output URL: {first[:200]}")
    else:
        print(f"  Response: {r.text[:500]}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

# Test 4: Try using aiohttp
print("\nTest 4: aiohttp")
try:
    import asyncio
    import aiohttp

    async def fetch():
        connector = aiohttp.TCPConnector(ssl=False, force_close=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                url, params=params,
                proxy="http://127.0.0.1:7897",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                text = await resp.text()
                print(f"  Status: {resp.status}, Size: {len(text)}")
                if resp.status == 200:
                    print(f"  Response: {text[:300]}")

    asyncio.run(fetch())
except ImportError:
    print("  aiohttp not installed, installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp", "-q"])
    import asyncio, aiohttp
    async def fetch():
        connector = aiohttp.TCPConnector(ssl=False, force_close=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                url, params=params,
                proxy="http://127.0.0.1:7897",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                text = await resp.text()
                print(f"  Status: {resp.status}, Size: {len(text)}")
                if resp.status == 200:
                    print(f"  Response: {text[:300]}")
    asyncio.run(fetch())
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")
